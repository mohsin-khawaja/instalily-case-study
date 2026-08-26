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
        # Genuinely ambiguous: "Briteline Graphics" could be a division of ours
        # or a different firm, exactly like "Briteline Extrusions". For a revenue
        # claim we reject the ambiguous case — a wrong size figure is worse than
        # a missing one, and missing only costs confidence.
        ("Briteline Graphics - Company Profile", False),
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


async def test_run_leaves_a_self_contained_database_file(tmp_path, monkeypatch):
    """WAL data must be folded back in, or the committed db file is empty."""
    from sqlmodel import create_engine

    db_path = tmp_path / "leads.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    monkeypatch.setattr("app.config.RAW_CACHE_DIR", tmp_path / "raw5")

    runner = PipelineRunner(
        mode=PipelineMode.CACHED, stages=[StageName.QUALIFY], engine=engine
    )
    await runner.run()

    wal = tmp_path / "leads.db-wal"
    assert db_path.stat().st_size > 4096  # more than an empty header page
    assert not wal.exists() or wal.stat().st_size == 0


async def test_enrichment_runs_companies_concurrently(ctx, tmp_path, monkeypatch):
    """Bounded parallelism: many companies in flight, never more than the cap."""
    import asyncio as _asyncio

    monkeypatch.setenv("PIPELINE_CONCURRENCY", "4")
    from app.config import get_settings

    get_settings.cache_clear()

    companies = [
        Company(name=f"Co {i}", canonical_name=f"co {i}", website=f"https://c{i}.test/",
                domain=f"c{i}.test")
        for i in range(12)
    ]
    for company in companies:
        ctx.session.add(company)
    ctx.session.commit()

    in_flight = 0
    peak = 0

    async def fake_enrich(_ctx, company):
        nonlocal in_flight, peak
        in_flight += 1
        peak = max(peak, in_flight)
        # A real yield point. The suite's autouse fixture replaces asyncio.sleep
        # with an instant coroutine, which never returns to the event loop, so
        # sleep(0) would not let a sibling task start.
        loop = _asyncio.get_running_loop()
        waiter = loop.create_future()
        loop.call_soon(waiter.set_result, None)
        await waiter
        in_flight -= 1
        company.enriched = True
        return company

    monkeypatch.setattr(enrich_companies, "_enrich_one", fake_enrich)
    monkeypatch.setattr(enrich_companies, "_fill_missing_size", _noop_async)
    monkeypatch.setattr(
        "app.pipeline.stages.extract_companies.link_companies_to_events", _noop_links
    )

    await enrich_companies.run(ctx, companies)
    get_settings.cache_clear()

    assert all(c.enriched for c in companies)
    assert peak > 1, "enrichment ran sequentially"
    assert peak <= 4, f"exceeded the concurrency cap: {peak}"


async def _noop_async(_ctx, _companies):
    return None


async def _noop_links(_ctx, _companies, _events):
    return 0


async def test_llm_rationales_are_only_spent_on_qualified_leads(ctx, monkeypatch, avery,
                                                                isa_expo, printing_united):
    """Reasoning-model tokens must not be spent on companies nobody will open."""
    from app.models.enums import Tier
    from app.pipeline.stages import qualify as qualify_stage

    for event in (isa_expo, printing_united):
        ctx.session.add(event)

    off_icp = Company(
        name="Northwind Staffing", canonical_name="northwind staffing",
        website="https://northwind.test/", industry="Staffing and recruiting",
        description="Recruiting and consulting services.", enriched=True,
    )
    for company in (avery, off_icp):
        ctx.session.add(company)
    ctx.session.commit()

    asked_for: list[str] = []

    class _CountingLLM:
        enabled = True
        model_reasoning = "claude-sonnet-5"
        model_extraction = "claude-haiku-4-5"

        class _Usage:
            def as_dict(self):
                return {}

        usage = _Usage()

        async def structured(self, schema_model, *, prompt, system, model=None):
            asked_for.append(prompt.split("\n")[0])
            return qualify_stage.RationaleOut(rationale="Grounded prose.", cited_source_urls=[])

    ctx.llm = _CountingLLM()
    results = await qualify_stage.run(ctx, [avery, off_icp])

    by_name = {q.company_id: q for q in results}
    assert by_name[avery.id].tier in (Tier.A, Tier.B)
    assert by_name[avery.id].rationale_source == "llm"
    assert by_name[off_icp.id].tier is Tier.DISQUALIFIED
    assert by_name[off_icp.id].rationale_source == "deterministic"
    assert by_name[off_icp.id].rationale  # still explained, just not by the LLM
    assert len(asked_for) == 1, f"LLM called {len(asked_for)} times, expected 1"


async def test_apollo_quota_exhaustion_stops_calling_and_falls_through(ctx, monkeypatch):
    """A rate-limited free tier must not cost a round-trip per remaining company."""
    from app.integrations.contacts.apollo import ApolloRateLimited
    from app.pipeline.stages import enrich_companies as stage

    monkeypatch.setenv("APOLLO_API_KEY", "k")
    from app.config import get_settings

    get_settings.cache_clear()

    attempts = {"n": 0}

    async def always_rate_limited(_domain):
        attempts["n"] += 1
        raise ApolloRateLimited("429")

    monkeypatch.setattr(
        "app.integrations.contacts.apollo.enrich_organization", always_rate_limited
    )

    companies = [
        Company(name=f"Co {i}", canonical_name=f"co {i}", domain=f"c{i}.test",
                website=f"https://c{i}.test/", enriched=True)
        for i in range(10)
    ]
    for company in companies:
        assert await stage._apply_apollo_firmographics(ctx, company) is False

    get_settings.cache_clear()
    assert ctx.apollo_breaker.is_open()
    # Three strikes, then the circuit opens and the rest are skipped outright.
    assert attempts["n"] == 3
    # The run records the exhaustion once, not ten times.
    quota_errors = [e for e in ctx.errors if "quota exhausted" in (e.entity_ref or "")]
    assert len(quota_errors) == 1


def test_csv_export_carries_provenance_and_respects_filters(session, avery, isa_expo):
    """An exported row that cannot be traced back to a URL is not worth having."""
    import csv as _csv
    import io as _io

    from fastapi.testclient import TestClient

    from app.db import get_session
    from app.main import app
    from app.models.domain import Qualification
    from app.models.enums import Tier

    session.add(isa_expo)
    avery.event_ids = [isa_expo.id]
    session.add(avery)
    session.add(
        Qualification(
            company_id=avery.id,
            score_total=82.0,
            tier=Tier.A,
            confidence=0.9,
            rationale="Strong fit.",
            rationale_source="llm",
            evidence=[{"claim": "c", "source_url": "https://graphics.averydennison.com/"}],
            flags=["size_third_party_estimate"],
        )
    )
    session.commit()

    app.dependency_overrides[get_session] = lambda: session
    try:
        client = TestClient(app)
        response = client.get("/api/leads.csv")
        assert response.status_code == 200
        assert "text/csv" in response.headers["content-type"]
        assert "attachment" in response.headers["content-disposition"]

        rows = list(_csv.DictReader(_io.StringIO(response.text)))
        assert len(rows) == 1
        row = rows[0]
        assert row["company"] == avery.name
        assert row["tier"] == "A"
        assert "graphics.averydennison.com" in row["evidence_urls"]
        # The size figure's origin travels with the number.
        assert row["size_source"] == "third_party"
        assert row["events"] == isa_expo.name

        # A filter that excludes everything yields a header and no rows.
        empty = client.get("/api/leads.csv?min_score=95")
        assert len(list(_csv.DictReader(_io.StringIO(empty.text)))) == 0
    finally:
        app.dependency_overrides.clear()


async def test_no_outreach_is_drafted_to_an_invented_person(ctx, avery):
    """A personalised email to a fabricated recipient is worse than no email."""
    from app.models.domain import Contact, OutreachDraft, Qualification
    from app.models.enums import Tier
    from app.pipeline.stages import draft_outreach

    ctx.session.add(avery)
    ctx.session.add(
        Qualification(
            company_id=avery.id,
            tier=Tier.A,
            score_total=80.0,
            evidence=[
                {
                    "claim": "Operates in Tedlar-relevant categories: signage",
                    "source_url": "https://graphics.averydennison.com/",
                }
            ],
        )
    )
    fake = Contact(company_id=avery.id, full_name="Jordan Reed", title="VP Product",
                   provider="mock", confidence=0.0)
    real = Contact(company_id=avery.id, full_name="Dana Whitfield", title="VP Product",
                   provider="public_web", confidence=0.7)
    ctx.session.add(fake)
    ctx.session.add(real)
    ctx.session.commit()

    drafts = await draft_outreach.run(ctx, [fake, real])

    recipients = {d.contact_id for d in drafts}
    assert real.id in recipients
    assert fake.id not in recipients
    assert any("placeholder contact" in (e.message or "") for e in ctx.errors)
    assert ctx.session.exec(select(OutreachDraft)).all()


def test_exports_never_carry_a_draft_for_an_invented_person(session, avery):
    """An export is a rep about to press send. Placeholder contacts must not reach it."""

    from fastapi.testclient import TestClient

    from app.db import get_session
    from app.main import app
    from app.models.domain import Contact, OutreachDraft, Qualification
    from app.models.enums import Tier

    session.add(avery)
    session.add(Qualification(company_id=avery.id, tier=Tier.A, score_total=80.0, confidence=0.9))
    mock_contact = Contact(
        company_id=avery.id, full_name="Jordan Reed", provider="mock", confidence=0.0
    )
    session.add(mock_contact)
    session.commit()
    session.add(
        OutreachDraft(
            contact_id=mock_contact.id,
            company_id=avery.id,
            subject="Should never ship",
            body="Hi Jordan,",
        )
    )
    session.commit()

    app.dependency_overrides[get_session] = lambda: session
    try:
        client = TestClient(app)
        # Nothing exportable, so the endpoint says so rather than shipping it.
        assert client.get("/api/outreach.zip").status_code == 404
        # And the UI gets no one-click send affordance for that draft.
        lead = client.get("/api/leads").json()[0]
        assert lead["outreach"][0]["gmail_url"] is None
    finally:
        app.dependency_overrides.clear()


def test_a_real_contact_does_get_a_gmail_link_and_an_export(session, avery):
    import zipfile as _zip
    from io import BytesIO

    from fastapi.testclient import TestClient

    from app.db import get_session
    from app.main import app
    from app.models.domain import Contact, OutreachDraft, Qualification
    from app.models.enums import Tier

    session.add(avery)
    session.add(Qualification(company_id=avery.id, tier=Tier.A, score_total=80.0, confidence=0.9))
    real = Contact(
        company_id=avery.id, full_name="Dana Whitfield", provider="public_web", confidence=0.7
    )
    session.add(real)
    session.commit()
    session.add(
        OutreachDraft(
            contact_id=real.id, company_id=avery.id, subject="Tedlar films", body="Hi Dana,"
        )
    )
    session.commit()

    app.dependency_overrides[get_session] = lambda: session
    try:
        client = TestClient(app)
        lead = client.get("/api/leads").json()[0]
        assert "mail.google.com" in lead["outreach"][0]["gmail_url"]

        bundle = client.get("/api/outreach.zip")
        assert bundle.status_code == 200
        names = _zip.ZipFile(BytesIO(bundle.content)).namelist()
        assert any(n.endswith(".eml") for n in names)
        assert "README.txt" in names
    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize(
    ("company_name", "result_title", "expected"),
    [
        # The brand appears even when the full stored name does not. Requiring
        # the whole name left the brief's own example account unsized.
        ("Avery Dennison Graphics Solutions", "Avery Dennison Revenue & Competitors", True),
        ("Avery Dennison Graphics Solutions", "Avery Dennison Graphics Solutions Profile", True),
        # A different company that merely shares the first word.
        ("Avery Dennison Graphics Solutions", "Avery Industries Revenue", False),
        # The earlier false positive must stay rejected.
        ("Briteline", "Briteline Extrusions, Inc. Revenue, Growth & Competitors", False),
        ("Briteline", "Briteline Revenue and Competitors", True),
    ],
)
def test_size_lookup_matches_the_brand_without_matching_a_different_company(
    company_name, result_title, expected
):
    from app.pipeline.stages.enrich_companies import _refers_to
    from app.services.search.base import SearchResult

    company = Company(name=company_name, canonical_name=company_name.lower())
    result = SearchResult(url="https://x.test/", title=result_title)
    assert _refers_to(company, result) is expected
