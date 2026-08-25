from __future__ import annotations

import pytest

from app.services.dedupe import (
    canonical_domain,
    dedupe_companies,
    dedupe_key,
    merge_records,
    name_similarity,
    normalize_name,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://www.averydennison.com/en/home.html", "averydennison.com"),
        ("graphics.averydennison.com", "averydennison.com"),
        ("AVERYDENNISON.COM", "averydennison.com"),
        ("http://shop.example.co.uk/path", "example.co.uk"),
        ("https://sub.deep.example.com", "example.com"),
        ("not-a-domain", None),
        ("", None),
        (None, None),
    ],
)
def test_canonical_domain(raw, expected):
    assert canonical_domain(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Avery Dennison Corporation", "avery dennison"),
        ("Avery Dennison, Inc.", "avery dennison"),
        ("ORAFOL Europe GmbH", "orafol europe"),
        ("3M Company", "3m"),
    ],
)
def test_normalize_name_strips_legal_suffixes(raw, expected):
    assert normalize_name(raw) == expected


def test_name_similarity_distinguishes_real_companies():
    assert name_similarity("Avery Dennison Inc", "Avery Dennison Corp") == 1.0
    assert name_similarity("Avery Dennison", "Arlon Graphics") < 0.9


def test_dedupe_key_prefers_domain_over_name():
    key = dedupe_key("Avery Dennison", "https://www.averydennison.com")
    assert key == "domain:averydennison.com"
    assert dedupe_key("Avery Dennison", None) == "name:avery dennison"


def test_dedupe_collapses_domain_variants_and_merges_fields():
    records = [
        {"name": "Avery Dennison", "website": "https://www.averydennison.com", "event_ids": ["e1"]},
        {
            "name": "Avery Dennison Corp.",
            "website": "https://graphics.averydennison.com/graphics",
            "event_ids": ["e2"],
            "industry": "Graphic films",
        },
        {"name": "Arlon Graphics LLC", "website": "https://arlon.com", "event_ids": ["e1"]},
    ]
    out = dedupe_companies(records)
    assert len(out) == 2
    avery = next(r for r in out if "avery" in r["name"].lower())
    assert sorted(avery["event_ids"]) == ["e1", "e2"]
    assert avery["industry"] == "Graphic films"


def test_dedupe_uses_fuzzy_name_when_no_domain():
    records = [
        {"name": "ORAFOL Europe GmbH", "website": None},
        {"name": "ORAFOL Europe", "website": None},
        {"name": "Drytac Corporation", "website": None},
    ]
    assert len(dedupe_companies(records)) == 2


def test_dedupe_does_not_merge_distinct_companies_sharing_no_domain():
    records = [{"name": "3M Commercial Graphics"}, {"name": "Hexis Graphics"}]
    assert len(dedupe_companies(records)) == 2


def test_merge_records_never_overwrites_known_values():
    primary = {"name": "Avery", "revenue_est_usd": 8_000_000_000, "products": ["vinyl"]}
    incoming = {"name": "Avery Dennison", "revenue_est_usd": 1, "products": ["overlaminate"]}
    merged = merge_records(primary, incoming)
    assert merged["revenue_est_usd"] == 8_000_000_000
    assert merged["products"] == ["vinyl", "overlaminate"]
