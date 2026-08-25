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


@pytest.mark.parametrize(
    "host",
    ["www.ebay.com", "amazon.co.uk", "www.alibaba.com", "uk.indeed.com",
     "www.zoominfo.com", "shop.walmart.com"],
)
def test_marketplaces_and_directories_are_not_prospects(host):
    """Better search recall surfaces these for any product query; none is a lead."""
    from app.pipeline.stages.extract_companies import _LINK_BLOCKLIST

    assert any(bad in host for bad in _LINK_BLOCKLIST), host


@pytest.mark.parametrize(
    "host",
    ["graphics.averydennison.com", "www.drytac.com", "orafol.com", "briteline.com"],
)
def test_real_prospects_are_not_blocked(host):
    from app.pipeline.stages.extract_companies import _LINK_BLOCKLIST

    assert not any(bad in host for bad in _LINK_BLOCKLIST), host
