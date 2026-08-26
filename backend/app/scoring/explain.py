"""Per-component score explanations.

A rep looking at "Application fit 16/25" cannot act on it. They need to know
*which* terms matched, *where* they were read, why the number is not higher, and
what would move it. This module answers all four for every component.

Deterministic on purpose. The explanation is derived from the same computation
that produced the points, so it cannot drift from the score, cannot hallucinate,
and costs nothing to generate. The LLM's rationale sits *above* this as a
narrative summary; this is the audit trail underneath it.

Pure function of a `Company` plus the events it links to, so the API computes it
on read — no migration, no re-run, no tokens.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

from ..models.domain import Company
from . import icp
from .score import (
    _company_haystack,
    _hits,
    _primary_url,
    score_company,
)

# How strong is this component's contribution, as a share of its ceiling?
STRONG = 0.75
MODERATE = 0.40


@dataclass
class ComponentExplanation:
    """Why one component scored what it did."""

    key: str
    label: str
    points: float
    max_points: float
    weight_pct: float
    verdict: str  # one line: "Strong", "Partial", "No evidence"
    reasoning: str  # the elaborate part
    matched: list[str] = field(default_factory=list)
    source_url: str | None = None
    to_improve: str | None = None  # what would raise it, or None if maxed

    @property
    def share(self) -> float:
        return self.points / self.max_points if self.max_points else 0.0


def _verdict(points: float, max_points: float) -> str:
    share = points / max_points if max_points else 0.0
    if share >= STRONG:
        return "Strong"
    if share >= MODERATE:
        return "Partial"
    if points > 0:
        return "Weak"
    return "No evidence"


def _listing(terms: list[str], limit: int = 6) -> str:
    shown = terms[:limit]
    extra = len(terms) - len(shown)
    text = ", ".join(f"“{t}”" for t in shown)
    return f"{text} and {extra} more" if extra > 0 else text


def explain_industry_fit(company: Company) -> ComponentExplanation:
    hay = _company_haystack(company)
    t1 = _hits(hay, icp.INDUSTRY_TIER1)
    t2 = _hits(hay, icp.INDUSTRY_TIER2)
    neg = _hits(hay, icp.INDUSTRY_NEGATIVE)
    points = min(icp.MAX_INDUSTRY_FIT, len(t1) * 12.0 + len(t2) * 4.0)
    penalised = bool(neg and not t1)
    if penalised:
        points *= 0.25

    parts: list[str] = []
    if t1:
        parts.append(
            f"{len(t1)} core category term{'s' if len(t1) != 1 else ''} — {_listing(t1)} — "
            f"worth 12 points each"
        )
    if t2:
        parts.append(
            f"{len(t2)} adjacent term{'s' if len(t2) != 1 else ''} — {_listing(t2)} — "
            f"worth 4 each"
        )
    if not parts:
        reasoning = (
            "Nothing in this company's own positioning matches the Tedlar graphics and "
            "signage vocabulary. Either it operates in a different category, or its site "
            "text was too thin to read."
        )
    else:
        reasoning = (
            f"Matched {'; '.join(parts)}. "
            + (
                f"The raw total exceeded the {icp.MAX_INDUSTRY_FIT:.0f}-point ceiling and was "
                "capped — one core term is already a strong signal, three is conclusive. "
                if len(t1) * 12.0 + len(t2) * 4.0 > icp.MAX_INDUSTRY_FIT
                else ""
            )
        )
    if penalised:
        reasoning += (
            f" Score cut to 25% because the company also reads as {_listing(neg, 3)} with no "
            "core category term to offset it."
        )

    to_improve = None
    if points < icp.MAX_INDUSTRY_FIT:
        need = max(0, 3 - len(t1))
        to_improve = (
            f"{need} more core category term{'s' if need != 1 else ''} in its positioning "
            "would reach the ceiling."
            if need
            else "Deeper enrichment of its category pages would confirm the remaining points."
        )

    return ComponentExplanation(
        key="industry_fit",
        label="Industry fit",
        points=round(points, 1),
        max_points=icp.MAX_INDUSTRY_FIT,
        weight_pct=30.0,
        verdict=_verdict(points, icp.MAX_INDUSTRY_FIT),
        reasoning=reasoning.strip(),
        matched=t1 + t2,
        source_url=_primary_url(company),
        to_improve=to_improve,
    )


def explain_product_fit(company: Company) -> ComponentExplanation:
    hay = _company_haystack(company) + " " + (company.site_text or "").lower()
    matches = _hits(hay, icp.APPLICATION_KEYWORDS)
    points = min(icp.MAX_PRODUCT_FIT, len(matches) * 8.0)

    if matches:
        reasoning = (
            f"Serves {len(matches)} Tedlar application area{'s' if len(matches) != 1 else ''} — "
            f"{_listing(matches)} — at 8 points each. These are the surfaces a protective "
            "overlaminate actually goes on, which is why this is weighted second only to "
            "industry fit."
        )
        if len(matches) * 8.0 > icp.MAX_PRODUCT_FIT:
            reasoning += f" Capped at the {icp.MAX_PRODUCT_FIT:.0f}-point ceiling."
    else:
        reasoning = (
            "No Tedlar application area appears in this company's product list or site copy. "
            "It may sit in the category without touching the specific surfaces Tedlar "
            "protects — outdoor signage, vehicle and fleet graphics, architectural graphics, "
            "billboards, overlaminates."
        )

    return ComponentExplanation(
        key="product_fit",
        label="Application fit",
        points=round(points, 1),
        max_points=icp.MAX_PRODUCT_FIT,
        weight_pct=25.0,
        verdict=_verdict(points, icp.MAX_PRODUCT_FIT),
        reasoning=reasoning,
        matched=matches,
        source_url=_primary_url(company),
        to_improve=(
            None
            if points >= icp.MAX_PRODUCT_FIT
            else f"{max(0, 4 - len(matches))} more application area(s) would reach the ceiling."
        ),
    )


def explain_size(company: Company) -> ComponentExplanation:
    third_party = company.size_source_kind == "third_party"
    url = company.size_source_url or _primary_url(company)

    if company.revenue_est_usd is not None:
        band = company.revenue_band or "unknown band"
        points = next(
            (pts for floor, _l, pts in icp.REVENUE_BANDS if company.revenue_est_usd >= floor), 0.0
        )
        basis = f"revenue of about ${company.revenue_est_usd:,.0f} places it in the {band} band"
    elif company.employee_count_est is not None:
        band = company.employee_band or "unknown band"
        points = next(
            (pts for floor, _l, pts in icp.EMPLOYEE_BANDS if company.employee_count_est >= floor),
            0.0,
        )
        basis = (
            f"no published revenue, so headcount was used instead: about "
            f"{company.employee_count_est:,} people, the {band} band"
        )
    else:
        points, basis = 0.0, None

    if basis is None:
        reasoning = (
            "Neither revenue nor headcount could be verified. Most privately held "
            "manufacturers never publish either, so this scores zero rather than being "
            "estimated — and the missing data costs the lead confidence instead."
        )
    else:
        reasoning = f"Sized because {basis}."
        if third_party:
            reasoning += (
                " This figure came from a third-party aggregator rather than the company's "
                "own site, so it is treated as weaker evidence and costs 10 points of "
                "confidence."
            )
        else:
            reasoning += " The figure was read from the company's own site."

    return ComponentExplanation(
        key="size",
        label="Company size",
        points=round(points, 1),
        max_points=icp.MAX_SIZE,
        weight_pct=15.0,
        verdict=_verdict(points, icp.MAX_SIZE),
        reasoning=reasoning,
        matched=[b for b in (company.revenue_band, company.employee_band) if b],
        source_url=url if basis else None,
        to_improve=(
            "A verified revenue figure would replace the headcount fallback."
            if company.revenue_est_usd is None and company.employee_count_est is not None
            else (
                "Any published revenue or headcount would unlock up to 15 points."
                if basis is None
                else None
            )
        ),
    )


def explain_event_engagement(
    company: Company, events_by_id: dict[str, object]
) -> ComponentExplanation:
    linked = [events_by_id[e] for e in (company.event_ids or []) if e in events_by_id]
    shows = [e for e in linked if getattr(e, "event_type", None) != "association"]
    assocs = [e for e in linked if getattr(e, "event_type", None) == "association"]
    raw = (
        icp.TIER1_EVENT_POINTS + icp.ADDITIONAL_EVENT_POINTS * (len(shows) - 1) if shows else 0.0
    ) + icp.ASSOCIATION_POINTS * len(assocs)
    points = min(icp.MAX_EVENT_ENGAGEMENT, raw)
    names = [getattr(e, "name", "") for e in linked]

    if not linked:
        reasoning = (
            "Not matched to any trade show or industry association. Note that the flagship "
            "exhibitor directories (ISA Sign Expo, PRINTING United) are behind an anti-bot "
            "wall, so an absence here is as likely to be a sourcing limit as a real one."
        )
    else:
        bits = []
        if shows:
            bits.append(
                f"{len(shows)} trade show{'s' if len(shows) != 1 else ''} "
                f"({icp.TIER1_EVENT_POINTS:.0f} for the first, "
                f"{icp.ADDITIONAL_EVENT_POINTS:.0f} for each additional)"
            )
        if assocs:
            bits.append(
                f"{len(assocs)} association membership{'s' if len(assocs) != 1 else ''} "
                f"at {icp.ASSOCIATION_POINTS:.0f} each"
            )
        reasoning = (
            f"Linked to {_listing(names, 4)} — {' and '.join(bits)}. "
            "Event presence is the clearest public evidence that a company invests in this "
            "category rather than merely touching it."
        )
        if raw > icp.MAX_EVENT_ENGAGEMENT:
            reasoning += f" Capped at {icp.MAX_EVENT_ENGAGEMENT:.0f}."

    return ComponentExplanation(
        key="event_engagement",
        label="Event engagement",
        points=round(points, 1),
        max_points=icp.MAX_EVENT_ENGAGEMENT,
        weight_pct=15.0,
        verdict=_verdict(points, icp.MAX_EVENT_ENGAGEMENT),
        reasoning=reasoning,
        matched=names,
        source_url=(
            getattr(linked[0], "exhibitor_list_url", None) or getattr(linked[0], "url", None)
            if linked
            else None
        ),
        to_improve=(
            None
            if points >= icp.MAX_EVENT_ENGAGEMENT
            else "Confirming attendance at one more show would add points."
        ),
    )


def explain_pain_alignment(company: Company) -> ComponentExplanation:
    hay = _company_haystack(company) + " " + (company.site_text or "").lower()
    themes: list[str] = []
    quotes: dict[str, str] = {}
    for theme, phrases in icp.PAIN_KEYWORDS.items():
        hit = next((p for p in phrases if p in hay), None)
        if hit:
            themes.append(theme)
            quotes[theme] = hit
    points = min(icp.MAX_PAIN_ALIGNMENT, len(themes) * 5.0)

    if themes:
        reasoning = (
            f"Already markets on {len(themes)} durability theme"
            f"{'s' if len(themes) != 1 else ''} Tedlar addresses — {_listing(themes)} — at "
            f"5 points each, matched on language such as "
            f"{_listing([quotes[t] for t in themes], 3)}. "
            "A company that already sells on durability is pre-sold on the problem, which "
            "makes the Tedlar conversation a product discussion rather than an education."
        )
    else:
        reasoning = (
            "This company's copy makes no durability claims — no UV, weathering, graffiti, "
            "chemical resistance, cleanability or lifespan language was found. Either it "
            "competes on price and speed rather than longevity, or the durability content "
            "lives on pages the crawl did not reach."
        )

    return ComponentExplanation(
        key="pain_alignment",
        label="Pain-point alignment",
        points=round(points, 1),
        max_points=icp.MAX_PAIN_ALIGNMENT,
        weight_pct=15.0,
        verdict=_verdict(points, icp.MAX_PAIN_ALIGNMENT),
        reasoning=reasoning,
        matched=themes,
        source_url=_primary_url(company),
        to_improve=(
            None
            if points >= icp.MAX_PAIN_ALIGNMENT
            else "Each additional durability theme found adds 5 points."
        ),
    )


def explain_company(
    company: Company, events_by_id: dict[str, object] | None = None
) -> list[dict]:
    """Every component explained, in scoring order. Serialisable for the API."""
    events_by_id = events_by_id or {}
    parts = [
        explain_industry_fit(company),
        explain_product_fit(company),
        explain_size(company),
        explain_event_engagement(company, events_by_id),
        explain_pain_alignment(company),
    ]
    return [asdict(p) for p in parts]


def summarise(company: Company, events_by_id: dict[str, object] | None = None) -> str:
    """One paragraph a rep can read before a call, assembled from the components.

    Deterministic, so it exists even when the LLM is unavailable — and it never
    disagrees with the numbers, because it is generated from them.
    """
    scored = score_company(company, events_by_id or {})
    parts = [
        explain_industry_fit(company),
        explain_product_fit(company),
        explain_size(company),
        explain_event_engagement(company, events_by_id or {}),
        explain_pain_alignment(company),
    ]
    carrying = [p for p in parts if p.share >= MODERATE]
    missing = [p for p in parts if p.points == 0]

    lead = (
        f"{company.name} scores {scored.breakdown.total:.0f} of 100 "
        f"(tier {scored.tier.value}) at {scored.confidence:.0%} confidence."
    )
    if carrying:
        lead += " The score is carried by " + _sentence_list(
            [f"{p.label.lower()} ({p.points:.0f}/{p.max_points:.0f})" for p in carrying]
        ) + "."
    if missing:
        lead += " Nothing was found for " + _sentence_list(
            [p.label.lower() for p in missing]
        ) + ", so those score zero rather than being estimated."
    return re.sub(r"\s+", " ", lead).strip()


def _sentence_list(items: list[str]) -> str:
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + f" and {items[-1]}"
