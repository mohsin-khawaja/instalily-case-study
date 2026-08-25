"""Deterministic lead scoring.

Every point is traceable to a keyword hit or a numeric band, and every component
that scores emits an `Evidence` row carrying the URL it came from. The LLM is
handed this output to write prose -- it never produces the number, so the score
is reproducible and arguable in a sales review.
"""

from __future__ import annotations

import re

from ..models.domain import Company, Evidence, ScoreBreakdown
from ..models.enums import Tier
from . import icp


def _norm(text: str | None) -> str:
    return re.sub(r"\s+", " ", (text or "").lower())


def _company_haystack(company: Company) -> str:
    parts = [
        company.industry or "",
        " ".join(company.sub_industries or []),
        company.description or "",
        " ".join(company.products or []),
    ]
    return _norm(" ".join(parts))


def _primary_url(company: Company) -> str | None:
    if company.website:
        return company.website
    for src in company.sources or []:
        url = src.get("url") if isinstance(src, dict) else None
        if url:
            return url
    return None


def _hits(haystack: str, vocab: list[str]) -> list[str]:
    return [term for term in vocab if term in haystack]


# ---------------------------------------------------------------------------
# Components. Each returns (points, evidence, notes-for-confidence).
# ---------------------------------------------------------------------------


def score_industry_fit(company: Company) -> tuple[float, list[Evidence]]:
    hay = _company_haystack(company)
    url = _primary_url(company)
    if not hay.strip():
        return 0.0, []

    t1 = _hits(hay, icp.INDUSTRY_TIER1)
    t2 = _hits(hay, icp.INDUSTRY_TIER2)
    neg = _hits(hay, icp.INDUSTRY_NEGATIVE)

    # Saturating: 1 tier-1 term is already a strong signal, 3+ is conclusive.
    points = min(icp.MAX_INDUSTRY_FIT, len(t1) * 12.0 + len(t2) * 4.0)
    if neg and not t1:
        points *= 0.25

    evidence: list[Evidence] = []
    if (t1 or t2) and url:
        matched = ", ".join((t1 + t2)[:5])
        evidence.append(
            Evidence(
                claim=f"Operates in Tedlar-relevant categories: {matched}",
                source_url=url,
                stage="qualify",
            )
        )
    return round(points, 1), evidence


def score_product_fit(company: Company) -> tuple[float, list[Evidence]]:
    hay = _company_haystack(company) + " " + _norm(company.site_text)
    url = _primary_url(company)
    matches = _hits(hay, icp.APPLICATION_KEYWORDS)
    if not matches:
        return 0.0, []
    points = min(icp.MAX_PRODUCT_FIT, len(matches) * 8.0)
    evidence: list[Evidence] = []
    if url:
        evidence.append(
            Evidence(
                claim=f"Serves Tedlar application areas: {', '.join(matches[:5])}",
                source_url=url,
                quote=_first_context(hay, matches[0]),
                stage="qualify",
            )
        )
    return round(points, 1), evidence


def score_size(company: Company) -> tuple[float, list[Evidence], str | None]:
    """Revenue first, headcount as fallback, 0 + no evidence if neither is known."""
    # Size often comes from a search snippet rather than the company's own site;
    # the evidence has to point at whichever one it really was.
    url = company.size_source_url or _primary_url(company)
    qualifier = " (third-party estimate)" if company.size_source_kind == "third_party" else ""
    if company.revenue_est_usd is not None:
        for floor, label, pts in icp.REVENUE_BANDS:
            if company.revenue_est_usd >= floor:
                ev = (
                    [
                        Evidence(
                            claim=f"Estimated revenue {label}{qualifier}",
                            source_url=url,
                            stage="qualify",
                        )
                    ]
                    if url
                    else []
                )
                return pts, ev, label
    if company.employee_count_est is not None:
        for floor, label, pts in icp.EMPLOYEE_BANDS:
            if company.employee_count_est >= floor:
                ev = (
                    [
                        Evidence(
                            claim=(
                                f"Approximately {company.employee_count_est} "
                                f"employees ({label}){qualifier}"
                            ),
                            source_url=url,
                            stage="qualify",
                        )
                    ]
                    if url
                    else []
                )
                return pts, ev, label
    return 0.0, [], None


def score_event_engagement(
    company: Company, events_by_id: dict[str, object]
) -> tuple[float, list[Evidence]]:
    linked = [events_by_id[e] for e in (company.event_ids or []) if e in events_by_id]
    if not linked:
        return 0.0, []

    trade_shows = [e for e in linked if getattr(e, "event_type", None) != "association"]
    associations = [e for e in linked if getattr(e, "event_type", None) == "association"]

    points = 0.0
    if trade_shows:
        points += icp.TIER1_EVENT_POINTS
        points += icp.ADDITIONAL_EVENT_POINTS * (len(trade_shows) - 1)
    points += icp.ASSOCIATION_POINTS * len(associations)
    points = min(icp.MAX_EVENT_ENGAGEMENT, points)

    evidence = [
        Evidence(
            claim=f"Listed for {getattr(e, 'name', 'event')}",
            source_url=getattr(e, "exhibitor_list_url", None) or getattr(e, "url", ""),
            stage="qualify",
        )
        for e in linked
        if getattr(e, "exhibitor_list_url", None) or getattr(e, "url", None)
    ]
    return round(points, 1), evidence


def score_pain_alignment(company: Company) -> tuple[float, list[Evidence], list[str]]:
    hay = _company_haystack(company) + " " + _norm(company.site_text)
    url = _primary_url(company)
    matched_themes: list[str] = []
    quote: str | None = None
    for theme, phrases in icp.PAIN_KEYWORDS.items():
        hit = next((p for p in phrases if p in hay), None)
        if hit:
            matched_themes.append(theme)
            quote = quote or _first_context(hay, hit)
    if not matched_themes:
        return 0.0, [], []
    points = min(icp.MAX_PAIN_ALIGNMENT, len(matched_themes) * 5.0)
    evidence: list[Evidence] = []
    if url:
        evidence.append(
            Evidence(
                claim=f"Markets on durability themes Tedlar addresses: {', '.join(matched_themes)}",
                source_url=url,
                quote=quote,
                stage="qualify",
            )
        )
    return round(points, 1), evidence, matched_themes


def _first_context(haystack: str, needle: str, window: int = 90) -> str | None:
    idx = haystack.find(needle)
    if idx < 0:
        return None
    start = max(0, idx - window // 2)
    return haystack[start : idx + len(needle) + window // 2].strip()


# ---------------------------------------------------------------------------
# Aggregate
# ---------------------------------------------------------------------------


class ScoredLead:
    __slots__ = ("breakdown", "tier", "confidence", "evidence", "flags", "pain_themes", "size_band")

    def __init__(
        self,
        breakdown: ScoreBreakdown,
        tier: Tier,
        confidence: float,
        evidence: list[Evidence],
        flags: list[str],
        pain_themes: list[str],
        size_band: str | None,
    ) -> None:
        self.breakdown = breakdown
        self.tier = tier
        self.confidence = confidence
        self.evidence = evidence
        self.flags = flags
        self.pain_themes = pain_themes
        self.size_band = size_band


def tier_for(total: float) -> Tier:
    if total >= icp.TIER_A_MIN:
        return Tier.A
    if total >= icp.TIER_B_MIN:
        return Tier.B
    if total >= icp.TIER_C_MIN:
        return Tier.C
    return Tier.DISQUALIFIED


def score_company(company: Company, events_by_id: dict[str, object] | None = None) -> ScoredLead:
    events_by_id = events_by_id or {}

    industry, ev_industry = score_industry_fit(company)
    product, ev_product = score_product_fit(company)
    size, ev_size, size_band = score_size(company)
    engagement, ev_event = score_event_engagement(company, events_by_id)
    pain, ev_pain, pain_themes = score_pain_alignment(company)

    breakdown = ScoreBreakdown(
        industry_fit=industry,
        product_fit=product,
        size=size,
        event_engagement=engagement,
        pain_alignment=pain,
    )
    evidence = [*ev_industry, *ev_product, *ev_size, *ev_event, *ev_pain]

    # Confidence = how much of the score is URL-backed, penalised for the gaps
    # that most often mislead a rep.
    components = [
        (industry, bool(ev_industry)),
        (product, bool(ev_product)),
        (size, bool(ev_size)),
        (engagement, bool(ev_event)),
        (pain, bool(ev_pain)),
    ]
    scoring_components = [c for c in components if c[0] > 0]
    backed = sum(1 for _, has_ev in scoring_components if has_ev)
    confidence = backed / len(scoring_components) if scoring_components else 0.0

    flags: list[str] = []
    if company.revenue_est_usd is None and company.employee_count_est is None:
        flags.append("size_unknown")
        confidence -= 0.15
    if not company.website:
        flags.append("no_website")
        confidence -= 0.20
    if not company.enriched:
        flags.append("not_enriched")
        confidence -= 0.15
    if company.size_source_kind == "third_party":
        # An aggregator's estimate is real evidence, but weaker than the company
        # saying it, and name-collision risk never fully goes away.
        flags.append("size_third_party_estimate")
        confidence -= 0.10
    confidence = round(max(0.0, min(1.0, confidence)), 2)

    return ScoredLead(
        breakdown=breakdown,
        tier=tier_for(breakdown.total),
        confidence=confidence,
        evidence=evidence,
        flags=flags,
        pain_themes=pain_themes,
        size_band=size_band,
    )
