"""Emit docs/results.json from the current database.

The deck and write-up quote run numbers; generating them keeps those figures
from drifting away from what the pipeline actually produced.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from sqlmodel import Session, func, select

from app.db import get_engine
from app.models.domain import Company, Contact, Event, OutreachDraft, Qualification
from app.models.enums import Tier
from app.models.errors import StageError

OUT = Path(__file__).resolve().parent.parent / "docs" / "results.json"


def _count(session: Session, model) -> int:
    return session.exec(select(func.count()).select_from(model)).one()


def main() -> None:
    with Session(get_engine()) as session:
        data = {
            "events": _count(session, Event),
            "companies": _count(session, Company),
            "companies_enriched": session.exec(
                select(func.count()).select_from(Company).where(Company.enriched == True)  # noqa: E712
            ).one(),
            "qualified_leads": session.exec(
                select(func.count()).select_from(Qualification).where(
                    Qualification.tier.in_([Tier.A, Tier.B])
                )
            ).one(),
            "contacts": _count(session, Contact),
            "outreach_drafts": _count(session, OutreachDraft),
            "errors": _count(session, StageError),
        }
    # Unit economics from the last run, for the deck and the write-up.
    with Session(get_engine()) as session:
        from app.models.errors import PipelineRun

        last = session.exec(
            select(PipelineRun).order_by(PipelineRun.started_at.desc())
        ).first()
        counts = (last.counts or {}) if last else {}
        data["llm_calls"] = int(counts.get("llm_calls", 0) or 0)
        data["llm_estimated_usd"] = float(counts.get("llm_estimated_usd", 0.0) or 0.0)
        qualified = data["qualified_leads"]
        data["cost_per_qualified_lead"] = (
            round(data["llm_estimated_usd"] / qualified, 4)
            if qualified and data["llm_estimated_usd"]
            else None
        )

    tests = subprocess.run(
        ["uv", "run", "pytest", "-q", "--collect-only"],
        capture_output=True, text=True, cwd=Path(__file__).resolve().parent,
    ).stdout
    collected = [ln for ln in tests.splitlines() if "test" in ln and "collected" in ln]
    data["tests"] = int(collected[0].split()[0]) if collected else None

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, indent=2) + "\n")
    print(json.dumps(data, indent=2))


if __name__ == "__main__":
    main()
