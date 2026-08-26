"""Lookalike modelling: does it match on business substance, or on page furniture?"""

from __future__ import annotations

from app.models.domain import Company
from app.scoring.similarity import rank_lookalikes, similar_to


def _company(cid: str, name: str, industry: str, subs: list[str], text: str) -> Company:
    return Company(
        id=cid,
        name=name,
        canonical_name=name.lower(),
        domain=f"{cid}.test",
        website=f"https://{cid}.test/",
        industry=industry,
        sub_industries=subs,
        description=text[:120],
        site_text=text,
        enriched=True,
    )


WRAP_REFERENCE = _company(
    "ref",
    "Avery Dennison Graphics",
    "Graphic films",
    ["vehicle wrap", "graphic films"],
    "We manufacture cast vinyl and overlaminate for vehicle wrap and fleet graphics. "
    "Our films are UV resistant for outdoor signage. English America Europe France.",
)
WRAP_LOOKALIKE = _company(
    "wrap",
    "Transport Graphics",
    "Vehicle wrap",
    ["vehicle wrap", "fleet graphics"],
    "Fleet graphics and vehicle wrap films with overlaminate protection for outdoor "
    "durability. English America Europe France.",
)
UNRELATED = _company(
    "food",
    "Northwind Foods",
    "Food distribution",
    ["frozen foods"],
    "We distribute frozen foods and dairy to regional grocers. "
    "English America Europe France.",
)


def test_a_wrap_converter_matches_the_wrap_reference():
    out = rank_lookalikes([WRAP_REFERENCE, WRAP_LOOKALIKE, UNRELATED], {"ref"})
    assert "wrap" in out
    match = out["wrap"][0]
    assert match.reference_name == WRAP_REFERENCE.name
    assert match.similarity > 0


def test_similarity_is_driven_by_business_terms_not_page_furniture():
    """All three share 'english america europe france'. That must not be the match."""
    out = rank_lookalikes([WRAP_REFERENCE, WRAP_LOOKALIKE, UNRELATED], {"ref"})
    shared = out["wrap"][0].shared_terms
    assert any(t in shared for t in ("wrap", "fleet", "graphics", "films", "overlaminate"))
    assert not any(
        t in shared for t in ("english", "america", "europe", "france")
    ), f"matched on navigation chrome: {shared}"


def test_an_unrelated_company_scores_far_below_a_real_match():
    out = rank_lookalikes([WRAP_REFERENCE, WRAP_LOOKALIKE, UNRELATED], {"ref"})
    wrap_score = out["wrap"][0].similarity
    food_score = out["food"][0].similarity if "food" in out else 0.0
    assert wrap_score > food_score * 2


def test_reference_accounts_are_never_their_own_lookalike():
    out = rank_lookalikes([WRAP_REFERENCE, WRAP_LOOKALIKE, UNRELATED], {"ref"})
    assert "ref" not in out


def test_no_reference_accounts_yields_nothing_rather_than_noise():
    assert rank_lookalikes([WRAP_REFERENCE, WRAP_LOOKALIKE], set()) == {}


def test_similar_to_finds_neighbours_of_any_company():
    out = similar_to("wrap", [WRAP_REFERENCE, WRAP_LOOKALIKE, UNRELATED])
    assert out
    assert out[0].company_id == "ref"
    assert out[0].shared_terms


def test_similar_to_is_empty_for_an_unknown_company():
    assert similar_to("nope", [WRAP_REFERENCE, WRAP_LOOKALIKE]) == []
