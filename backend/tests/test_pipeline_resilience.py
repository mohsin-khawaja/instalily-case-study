"""The load-bearing guarantee: one bad record degrades itself, never the run."""

from __future__ import annotations

import httpx
import pytest
from sqlmodel import select

from app.models.domain import Company, Event, Qualification
from app.models.enums import PipelineMode, RecordStatus, RunStatus, StageName, Tier
from app.models.errors import StageError
from app.pipeline.context import RunContext
from app.pipeline.runner import PipelineRunner, _parse_stages
from app.pipeline.stages import enrich_companies, qualify
from app.services.cache import ResponseCache
from app.services.http import Fetcher, FetchError
from app.services.llm import LLMClient
from app.services.search.base import SearchResult


class _NullSearch:
    name = "null"

    def is_configured(self) -> bool:
        return False

    async def search(self, query: str, *, limit: int = 10) -> list[SearchResult]:
        return []


@pytest.fixture
def ctx(session, tmp_path):
    return RunContext(
        run_id="run-test",
        mode=PipelineMode.CACHED,
        session=session,
        fetcher=Fetcher(cache=ResponseCache(root=tmp_path / "raw")),
        search=_NullSearch(),
        llm=LLMClient(api_key=None),
    )


def test_guard_absorbs_an_expected_failure_and_records_it(ctx):
    with ctx.guard(StageName.ENRICH_COMPANIES, entity_type="company", entity_ref="Acme"):
        raise FetchError("https://acme.test/", "HTTP 403")
    assert len(ctx.errors) == 1
    assert ctx.errors[0].error_type == "FetchError"
    assert ctx.errors[0].entity_ref == "Acme"


def test_guard_does_not_swallow_real_bugs(ctx):
    with pytest.raises(TypeError), ctx.guard(StageName.QUALIFY):
        raise TypeError("this is a programming error, not a data problem")


async def test_attempt_returns_the_default_and_keeps_going(ctx):
    async def boom():
        raise FetchError("https://x.test/", "timeout", retryable=True)

    result = await ctx.attempt(
        StageName.ENRICH_COMPANIES, boom, entity_ref="X", default=[]
    )
    assert result == []
    assert ctx.errors[0].retryable is True


async def test_one_failing_company_does_not_stop_enrichment_of_the_others(ctx, tmp_path):
    good = Company(name="Good Films", canonical_name="good films",
                   website="https://good.test/", domain="good.test")
    bad = Company(name="Dead Site", canonical_name="dead site",
                  website="https://dead.test/", domain="dead.test")
    no_site = Company(name="No Website", canonical_name="no website")
    for company in (good, bad, no_site):
        ctx.session.add(company)
    ctx.session.commit()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "good.test" and request.url.path == "/":
            return httpx.Response(
                200,
                text=(
                    "<html><body><p>We manufacture self-adhesive vinyl and overlaminate "
                    "for outdoor signage. Our films are UV resistant and weather "
                    "resistant.</p></body></html>"
                ),
            )
        return httpx.Response(500)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True)
    async with Fetcher(live=True, cache=ResponseCache(root=tmp_path / "raw2"),
                       client=client) as fetcher:
        ctx.fetcher = fetcher
        await enrich_companies.run(ctx, [good, bad, no_site])

    assert good.enriched is True
    assert bad.enriched is False
    assert no_site.status is RecordStatus.INCOMPLETE

    refs = {e.entity_ref for e in ctx.session.exec(select(StageError)).all()}
    assert {"Dead Site", "No Website"} <= refs


async def test_qualification_survives_companies_with_nothing_known(ctx):
    empty = Company(name="Mystery Co", canonical_name="mystery co")
    ctx.session.add(empty)
    ctx.session.commit()

    results = await qualify.run(ctx, [empty])

    assert len(results) == 1
    assert results[0].tier is Tier.DISQUALIFIED
    assert results[0].confidence == 0.0
    assert "no_website" in results[0].flags
    assert results[0].rationale  # a deterministic rationale is still produced


async def test_runner_marks_a_failing_stage_and_still_finishes(session, monkeypatch, tmp_path):
    """A stage that raises outright is recorded, and later stages still run."""
    engine = session.get_bind()

    async def exploding_stage(ctx):
        raise RuntimeError("directory provider is down")

    monkeypatch.setattr("app.pipeline.stages.discover_events.run", exploding_stage)
    monkeypatch.setattr("app.config.RAW_CACHE_DIR", tmp_path / "raw3")

    runner = PipelineRunner(
        mode=PipelineMode.CACHED,
        stages=[StageName.DISCOVER_EVENTS, StageName.QUALIFY],
        engine=engine,
    )
    run_row = await runner.run()

    assert run_row.stage_states["discover_events"] == "failed"
    assert run_row.stage_states["qualify"] in ("done", "partial")
    assert run_row.status is RunStatus.PARTIAL
    assert run_row.error_count >= 1
    assert run_row.finished_at is not None


def test_parse_stages_accepts_ranges_and_names():
    assert _parse_stages(None) is None
    assert _parse_stages("1-3") == [
        StageName.DISCOVER_EVENTS,
        StageName.EXTRACT_COMPANIES,
        StageName.ENRICH_COMPANIES,
    ]
    assert _parse_stages("qualify,find_contacts") == [
        StageName.QUALIFY,
        StageName.FIND_CONTACTS,
    ]
    with pytest.raises(ValueError):
        _parse_stages("not_a_stage")


def test_events_and_companies_persist_independently(session):
    event = Event(slug="s", name="Show", url="https://show.test/")
    session.add(event)
    session.commit()
    assert session.exec(select(Event)).first().slug == "s"
    assert session.exec(select(Qualification)).all() == []


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Briteline Revenue and Competitors", True),
        ("Briteline Graphics - Company Profile", True),
        # A different legal entity that merely shares a prefix.
        ("Briteline Extrusions, Inc. Revenue, Growth & Competitor Profile", False),
        ("Britelite Windows Revenue", False),
    ],
)
def test_size_lookup_rejects_similarly_named_companies(title, expected):
    from app.pipeline.stages.enrich_companies import _refers_to
    from app.services.search.base import SearchResult

    company = Company(name="Briteline", canonical_name="briteline")
    assert _refers_to(company, SearchResult(url="https://x.test/", title=title)) is expected


async def test_runner_writes_progress_into_a_preexisting_run_row(session, monkeypatch, tmp_path):
    """The API hands the client a run id before starting; progress must land there."""
    from app.models.errors import PipelineRun

    engine = session.get_bind()
    monkeypatch.setattr("app.config.RAW_CACHE_DIR", tmp_path / "raw4")

    row = PipelineRun(mode=PipelineMode.CACHED, status=RunStatus.RUNNING, stage_states={})
    session.add(row)
    session.commit()
    session.refresh(row)
    run_id = row.id

    runner = PipelineRunner(
        mode=PipelineMode.CACHED, stages=[StageName.QUALIFY], engine=engine, run_id=run_id
    )
    result = await runner.run()

    assert result.id == run_id  # same row, not a second one
    assert result.stage_states["qualify"] in ("done", "partial")
    assert len(session.exec(select(PipelineRun)).all()) == 1


def test_summary_and_error_log_scope_to_the_latest_run(session):
    """A clean re-run must not inherit the previous run's error count."""
    from fastapi.testclient import TestClient

    from app.db import get_session
    from app.main import app
    from app.models.errors import PipelineRun, StageError

    old_run = PipelineRun(mode=PipelineMode.CACHED, status=RunStatus.PARTIAL)
    session.add(old_run)
    session.commit()
    session.refresh(old_run)
    for i in range(3):
        session.add(
            StageError(
                run_id=old_run.id, stage=StageName.QUALIFY,
                error_type="ValueError", message=f"old {i}",
            )
        )
    session.commit()

    new_run = PipelineRun(mode=PipelineMode.CACHED, status=RunStatus.COMPLETED)
    session.add(new_run)
    session.commit()
    session.refresh(new_run)
    session.add(
        StageError(
            run_id=new_run.id, stage=StageName.QUALIFY,
            error_type="ValueError", message="new only",
        )
    )
    session.commit()

    app.dependency_overrides[get_session] = lambda: session
    try:
        client = TestClient(app)
        assert client.get("/api/summary").json()["errors"] == 1
        assert [e["message"] for e in client.get("/api/errors").json()] == ["new only"]
        assert len(client.get("/api/errors?run_id=all").json()) == 4
    finally:
        app.dependency_overrides.clear()
