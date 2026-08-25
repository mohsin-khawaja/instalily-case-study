"""Pipeline orchestration.

Deterministic, sequential, and resumable: stages run in a fixed order, each one
commits its own results, and a `PipelineRun` row tracks per-stage state so the
dashboard can poll progress and so a crash leaves behind a readable record of how
far the run got.

Scaling path: every stage already isolates per-record work behind
`RunContext.attempt`. Replacing the in-process loop with a task queue means
enqueuing those same coroutines -- no stage code changes.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from datetime import UTC, datetime

from sqlmodel import Session, select

from ..config import get_settings
from ..db import get_engine, init_db
from ..models.domain import Company, Contact, Event, Qualification
from ..models.enums import STAGE_ORDER, PipelineMode, RunStatus, StageName
from ..models.errors import PipelineRun
from ..services.http import Fetcher
from ..services.llm import LLMClient
from ..services.search import build_search_provider
from .context import RunContext
from .stages import discover_events as discover
from .stages import (
    draft_outreach,
    enrich_companies,
    extract_companies,
    find_contacts,
    qualify,
)

logger = logging.getLogger(__name__)


def _checkpoint_wal(engine) -> None:
    """Fold the write-ahead log back into the database file.

    In WAL mode a finished run leaves most of its data in `leads.db-wal`. That
    sidecar is not committed, so without this the repo would carry a database
    file that is technically valid and completely empty.
    """
    if not engine.url.drivername.startswith("sqlite"):
        return
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("PRAGMA wal_checkpoint(TRUNCATE)")
    except Exception as exc:  # noqa: BLE001 -- a failed checkpoint must not fail the run
        logger.warning("wal checkpoint failed: %s", exc)


class PipelineRunner:
    def __init__(
        self,
        *,
        mode: PipelineMode = PipelineMode.CACHED,
        limit: int | None = None,
        stages: list[StageName] | None = None,
        engine=None,
        run_id: str | None = None,
    ) -> None:
        self.mode = mode
        self.limit = limit
        self.stages = stages or list(STAGE_ORDER)
        self.engine = engine or get_engine()
        # When the API has already created the row the dashboard is polling, run
        # into that row -- otherwise progress updates land on a different record
        # and the UI sits at "pending" until the run ends.
        self.run_id = run_id

    async def run(self) -> PipelineRun:
        init_db(self.engine)
        with Session(self.engine) as session:
            run_row = session.get(PipelineRun, self.run_id) if self.run_id else None
            if run_row is None:
                run_row = PipelineRun(id=self.run_id) if self.run_id else PipelineRun()
            run_row.mode = self.mode
            run_row.status = RunStatus.RUNNING
            run_row.stage_states = {s.value: "pending" for s in self.stages}
            session.add(run_row)
            session.commit()
            session.refresh(run_row)

            async with Fetcher(live=self.mode is PipelineMode.LIVE) as fetcher:
                ctx = RunContext(
                    run_id=run_row.id,
                    mode=self.mode,
                    session=session,
                    fetcher=fetcher,
                    search=build_search_provider(fetcher),
                    llm=LLMClient(),
                    limit=self.limit,
                )
                await self._execute(ctx, run_row)

            run_row.counts = {**ctx.counts, **ctx.llm.usage.as_dict()}
            run_row.error_count = len(ctx.errors)
            run_row.finished_at = datetime.now(UTC)
            run_row.status = RunStatus.PARTIAL if ctx.errors else RunStatus.COMPLETED
            run_row.current_stage = None
            session.add(run_row)
            session.commit()
            session.refresh(run_row)

        _checkpoint_wal(self.engine)
        return run_row

    async def _execute(self, ctx: RunContext, run_row: PipelineRun) -> None:
        events: list[Event] = []
        companies: list[Company] = []
        qualifications: list[Qualification] = []
        contacts: list[Contact] = []

        for stage in self.stages:
            self._mark(ctx, run_row, stage, "running")
            errors_before = len(ctx.errors)
            try:
                if stage is StageName.DISCOVER_EVENTS:
                    events = await discover.run(ctx)
                elif stage is StageName.EXTRACT_COMPANIES:
                    events = events or ctx.session.exec(select(Event)).all()
                    companies = await extract_companies.run(ctx, list(events))
                elif stage is StageName.ENRICH_COMPANIES:
                    companies = companies or list(ctx.session.exec(select(Company)).all())
                    companies = await enrich_companies.run(ctx, companies)
                elif stage is StageName.QUALIFY:
                    companies = companies or list(ctx.session.exec(select(Company)).all())
                    qualifications = await qualify.run(ctx, companies)
                elif stage is StageName.FIND_CONTACTS:
                    qualifications = qualifications or list(
                        ctx.session.exec(select(Qualification)).all()
                    )
                    contacts = await find_contacts.run(ctx, qualifications)
                elif stage is StageName.DRAFT_OUTREACH:
                    contacts = contacts or list(ctx.session.exec(select(Contact)).all())
                    await draft_outreach.run(ctx, contacts)
            except Exception as exc:  # noqa: BLE001 -- a stage blowing up must not lose prior work
                ctx.record_error(stage, exc, entity_type="stage", entity_ref=stage.value)
                ctx.session.commit()
                self._mark(ctx, run_row, stage, "failed")
                continue

            had_new_errors = len(ctx.errors) > errors_before
            self._mark(ctx, run_row, stage, "partial" if had_new_errors else "done")

    def _mark(self, ctx: RunContext, run_row: PipelineRun, stage: StageName, state: str) -> None:
        states = dict(run_row.stage_states)
        states[stage.value] = state
        run_row.stage_states = states
        run_row.current_stage = stage if state == "running" else run_row.current_stage
        run_row.counts = {**ctx.counts, **ctx.llm.usage.as_dict()}
        run_row.error_count = len(ctx.errors)
        ctx.session.add(run_row)
        ctx.session.commit()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_stages(raw: str | None) -> list[StageName] | None:
    if not raw:
        return None
    if "-" in raw and raw.replace("-", "").isdigit():
        start, end = (int(p) for p in raw.split("-", 1))
        return STAGE_ORDER[start - 1 : end]
    return [StageName(name.strip()) for name in raw.split(",") if name.strip()]


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Tedlar lead pipeline.")
    parser.add_argument("--mode", choices=[m.value for m in PipelineMode], default=None)
    parser.add_argument("--live", action="store_true", help="shorthand for --mode live")
    parser.add_argument("--limit", type=int, default=None, help="cap companies enriched")
    parser.add_argument("--stages", default=None, help='e.g. "1-3" or "qualify,find_contacts"')
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)-7s %(name)s: %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)

    mode = PipelineMode(args.mode or ("live" if args.live else get_settings().pipeline_mode))
    runner = PipelineRunner(mode=mode, limit=args.limit, stages=_parse_stages(args.stages))
    run_row = asyncio.run(runner.run())

    print(f"\nrun {run_row.id}  mode={run_row.mode.value}  status={run_row.status.value}")
    for stage, state in run_row.stage_states.items():
        print(f"  {stage:<20} {state}")
    print("\ncounts:")
    for key, value in sorted(run_row.counts.items()):
        print(f"  {key:<24} {value}")
    print(f"\nerrors: {run_row.error_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
