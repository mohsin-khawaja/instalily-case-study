from __future__ import annotations

from app.models.domain import Company
from app.models.enums import Tier
from app.scoring import icp
from app.scoring.score import score_company, score_size, tier_for


def _events(*events):
    return {e.id: e for e in events}


def test_avery_fixture_scores_tier_a(avery, isa_expo, printing_united):
    result = score_company(avery, _events(isa_expo, printing_united))
    assert result.tier is Tier.A
    assert result.breakdown.total >= icp.TIER_A_MIN
    assert result.breakdown.industry_fit == icp.MAX_INDUSTRY_FIT
    assert result.breakdown.size == 15.0
    assert result.confidence >= 0.9
    assert result.flags == []
    assert all(e.source_url.startswith("http") for e in result.evidence)


def test_every_component_respects_its_ceiling(avery, isa_expo, printing_united):
    b = score_company(avery, _events(isa_expo, printing_united)).breakdown
    assert b.industry_fit <= icp.MAX_INDUSTRY_FIT
    assert b.product_fit <= icp.MAX_PRODUCT_FIT
    assert b.size <= icp.MAX_SIZE
    assert b.event_engagement <= icp.MAX_EVENT_ENGAGEMENT
    assert b.pain_alignment <= icp.MAX_PAIN_ALIGNMENT
    assert b.total <= 100.0


def test_missing_revenue_falls_back_to_headcount():
    company = Company(name="X", canonical_name="x", employee_count_est=1200)
    points, evidence, band = score_size(company)
    assert points == 12.0
    assert band == "1000-4999"
    assert evidence == []  # no URL -> no evidence, by design


def test_unknown_size_scores_zero_and_flags_confidence(avery, isa_expo):
    avery.revenue_est_usd = None
    avery.employee_count_est = None
    result = score_company(avery, _events(isa_expo))
    assert result.breakdown.size == 0.0
    assert "size_unknown" in result.flags
    assert result.confidence < 1.0


def test_no_website_and_no_enrichment_degrade_confidence(avery):
    avery.website = None
    avery.sources = []
    avery.enriched = False
    result = score_company(avery, {})
    assert {"no_website", "not_enriched"} <= set(result.flags)
    assert result.confidence < 0.5


def test_off_icp_company_is_disqualified():
    company = Company(
        name="Northwind Staffing",
        canonical_name="northwind staffing",
        website="https://example.com",
        industry="Staffing and recruiting",
        description="We provide consulting services and recruiting for enterprises.",
        enriched=True,
    )
    result = score_company(company, {})
    assert result.tier is Tier.DISQUALIFIED
    assert result.breakdown.total < icp.TIER_C_MIN


def test_event_engagement_rewards_multiple_shows(avery, isa_expo, printing_united):
    one = score_company(avery, _events(isa_expo)).breakdown.event_engagement
    two = score_company(avery, _events(isa_expo, printing_united)).breakdown.event_engagement
    assert two > one


def test_pain_alignment_requires_real_durability_language(avery, isa_expo):
    avery.site_text = "We print things."
    result = score_company(avery, _events(isa_expo))
    assert result.breakdown.pain_alignment == 0.0


def test_tier_boundaries_are_inclusive():
    assert tier_for(icp.TIER_A_MIN) is Tier.A
    assert tier_for(icp.TIER_A_MIN - 0.1) is Tier.B
    assert tier_for(icp.TIER_B_MIN) is Tier.B
    assert tier_for(icp.TIER_C_MIN - 0.1) is Tier.DISQUALIFIED


def test_size_evidence_cites_where_the_figure_actually_came_from():
    """Size often comes from a search snippet, not the company's own site."""
    company = Company(
        name="Acme Films",
        canonical_name="acme films",
        website="https://acme.test/",
        revenue_est_usd=120_000_000,
        size_source_url="https://directory.example.com/acme-profile",
    )
    _points, evidence, _band = score_size(company)
    assert evidence[0].source_url == "https://directory.example.com/acme-profile"


def test_size_evidence_falls_back_to_the_website_when_read_from_the_site():
    company = Company(
        name="Acme Films",
        canonical_name="acme films",
        website="https://acme.test/",
        employee_count_est=600,
    )
    _points, evidence, band = score_size(company)
    assert evidence[0].source_url == "https://acme.test/"
    assert band == "250-999"


def test_third_party_size_estimate_is_labelled_and_costs_confidence(avery, isa_expo):
    avery.size_source_url = "https://growjo.com/company/Avery"
    avery.size_source_kind = "third_party"
    result = score_company(avery, {isa_expo.id: isa_expo})
    size_claims = [e.claim for e in result.evidence if "revenue" in e.claim.lower()]
    assert any("third-party estimate" in claim for claim in size_claims)
    assert "size_third_party_estimate" in result.flags
    assert result.confidence < 1.0
