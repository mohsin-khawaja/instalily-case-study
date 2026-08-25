"""Stage 5 -- qualification.

The number comes from `scoring.score_company`. The LLM's only job is to explain
it, and it may only cite evidence the scorer already produced: `_verify_rationale`
strips any sentence containing an unsupported numeric claim and flags the record.
Without an API key the stage still works -- it renders a deterministic rationale
from the same breakdown.
"""

from __future__ import annotations

import logging
import re

from pydantic import BaseModel, Field
from sqlmodel import select

from ...models.domain import Company, Event, Evidence, Qualification, utcnow
from ...models.enums import RecordStatus, StageName, Tier
from ...scoring.score import ScoredLead, score_company
from ...services.llm.prompts import RATIONALE_SYSTEM, rationale_prompt
from ..context import RunContext

logger = logging.getLogger(__name__)

STAGE = StageName.QUALIFY

_NUMERIC_CLAIM = re.compile(r"(\$\s?[\d,.]+\s*(?:billion|million|bn|m\b|b\b)|\b\d{3,}\b)",
                            re.IGNORECASE)


class RationaleOut(BaseModel):
    rationale: str = Field(description="3-5 sentences of plain prose")
    cited_source_urls: list[str] = Field(
        default_factory=list, description="URLs from the supplied evidence that you used"
    )


async def run(ctx: RunContext, companies: list[Company]) -> list[Qualification]:
    events = {e.id: e for e in ctx.session.exec(select(Event)).all()}
    existing = {
        q.company_id: q for q in ctx.session.exec(select(Qualification)).all()
    }

    out: list[Qualification] = []
    for company in companies:
        scored = score_company(company, events)
        qualification = existing.get(company.id) or Qualification(company_id=company.id)
        _apply_score(qualification, scored)

        rationale, flags = await _build_rationale(ctx, company, scored, events)
        qualification.rationale = rationale
        qualification.flags = sorted(set(qualification.flags) | set(flags))
        qualification.rationale_source = "llm" if ctx.llm.enabled and "llm_failed" not in flags \
            else "deterministic"
        qualification.status = (
            RecordStatus.COMPLETE if qualification.confidence >= 0.5 else RecordStatus.INCOMPLETE
        )
        qualification.updated_at = utcnow()
        ctx.session.add(qualification)
        out.append(qualification)

    ctx.session.commit()
    ctx.bump("qualifications", len(out))
    ctx.bump("qualified_leads", sum(1 for q in out if q.tier in (Tier.A, Tier.B)))
    return out


def _apply_score(qualification: Qualification, scored: ScoredLead) -> None:
    qualification.score = scored.breakdown.as_dict()
    qualification.score_total = scored.breakdown.total
    qualification.tier = scored.tier
    qualification.confidence = scored.confidence
    qualification.evidence = [e.model_dump(mode="json") for e in scored.evidence]
    qualification.flags = list(scored.flags)


async def _build_rationale(
    ctx: RunContext, company: Company, scored: ScoredLead, events: dict[str, Event]
) -> tuple[str, list[str]]:
    deterministic = _deterministic_rationale(company, scored, events)
    if not ctx.llm.enabled or not scored.evidence:
        return deterministic, []

    allowed = {e.source_url for e in scored.evidence}
    result = await ctx.attempt(
        STAGE,
        lambda: ctx.llm.structured(
            RationaleOut,
            prompt=rationale_prompt(
                company_name=company.name,
                facts=_facts_block(company),
                score_summary=_score_summary(scored),
                evidence_block=_evidence_block(scored.evidence),
                events=", ".join(
                    events[e].name for e in (company.event_ids or []) if e in events
                ),
            ),
            system=RATIONALE_SYSTEM,
            model=ctx.llm.model_reasoning,
        ),
        entity_type="company_rationale",
        entity_ref=company.name,
        default=None,
    )
    if result is None:
        return deterministic, ["llm_failed"]

    cleaned, flags = _verify_rationale(result, allowed, company)
    return (cleaned or deterministic), flags


def _verify_rationale(
    result: RationaleOut, allowed_urls: set[str], company: Company
) -> tuple[str, list[str]]:
    """Drop sentences making numeric claims we cannot back; flag invented citations."""
    flags: list[str] = []
    if any(url not in allowed_urls for url in result.cited_source_urls):
        flags.append("cited_unknown_source")

    known_numbers = {
        str(int(company.revenue_est_usd)) if company.revenue_est_usd else "",
        str(company.employee_count_est) if company.employee_count_est else "",
        company.revenue_band or "",
        company.employee_band or "",
    }
    kept: list[str] = []
    for sentence in re.split(r"(?<=[.!?])\s+", result.rationale.strip()):
        claims = _NUMERIC_CLAIM.findall(sentence)
        if claims and not any(
            any(known and known.replace(",", "") in claim.replace(",", "").replace("$", "")
                for known in known_numbers if known)
            or (company.revenue_band and company.revenue_band.lower() in sentence.lower())
            or (company.employee_band and company.employee_band in sentence)
            for claim in claims
        ):
            flags.append("unsupported_claim_removed")
            continue
        kept.append(sentence)
    return " ".join(kept).strip(), flags


def _deterministic_rationale(
    company: Company, scored: ScoredLead, events: dict[str, Event]
) -> str:
    b = scored.breakdown
    bits = [
        f"{company.name} scores {b.total:.0f}/100 (tier {scored.tier.value}) against the "
        f"Tedlar Graphics & Signage ICP."
    ]
    if b.industry_fit:
        bits.append(
            f"Industry fit {b.industry_fit:.0f}/30 from its stated positioning in "
            f"{company.industry or 'the graphics category'}."
        )
    if b.product_fit:
        bits.append(f"Product overlap {b.product_fit:.0f}/25 on Tedlar application areas.")
    if b.size:
        band = company.revenue_band or company.employee_band or "an identified size band"
        bits.append(f"Size {b.size:.0f}/15 ({band}).")
    linked = [events[e].name for e in (company.event_ids or []) if e in events]
    if linked:
        bits.append(f"Engaged via {', '.join(linked[:3])}.")
    if scored.pain_themes:
        bits.append(
            f"Already markets on {', '.join(scored.pain_themes)} -- the durability "
            "problems Tedlar films address."
        )
    if scored.flags:
        bits.append(f"Gaps in the record: {', '.join(scored.flags)}.")
    return " ".join(bits)


def _facts_block(company: Company) -> str:
    rows = [
        f"- website: {company.website or 'unknown'}",
        f"- industry: {company.industry or 'unknown'}",
        f"- sub-industries: {', '.join(company.sub_industries) or 'unknown'}",
        f"- products: {', '.join(company.products) or 'unknown'}",
        f"- HQ: {company.hq_location or 'unknown'}",
        f"- revenue: {company.revenue_band or 'unknown'}",
        f"- headcount: {company.employee_band or 'unknown'}",
        f"- description: {company.description or 'unknown'}",
    ]
    return "\n".join(rows)


def _score_summary(scored: ScoredLead) -> str:
    b = scored.breakdown
    return (
        f"industry_fit {b.industry_fit}/30, product_fit {b.product_fit}/25, "
        f"size {b.size}/15, event_engagement {b.event_engagement}/15, "
        f"pain_alignment {b.pain_alignment}/15, total {b.total}/100, "
        f"tier {scored.tier.value}, confidence {scored.confidence}"
    )


def _evidence_block(evidence: list[Evidence]) -> str:
    return "\n".join(f"- {e.claim} -> {e.source_url}" for e in evidence) or "none"
