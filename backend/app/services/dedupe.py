"""Company deduplication.

Exhibitor directories repeat the same firm under "Avery Dennison",
"Avery Dennison Corp." and "averydennison.com" -- collapsing those is pure string
work, so it stays deterministic and fully testable.

Order of authority: registrable domain > normalised legal name + fuzzy ratio.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from urllib.parse import urlparse

NAME_FUZZY_THRESHOLD = 0.90

# Multi-part public suffixes we must not truncate to a bare "co.uk".
_MULTI_PART_SUFFIXES = {
    "co.uk", "org.uk", "ac.uk", "gov.uk", "com.au", "net.au", "org.au",
    "co.nz", "co.jp", "co.kr", "com.br", "com.mx", "com.cn", "co.za",
    "com.tr", "co.in", "com.sg",
}

_LEGAL_SUFFIXES = [
    "incorporated", "corporation", "limited", "holdings", "group", "company",
    "inc", "llc", "ltd", "plc", "corp", "co", "gmbh", "ag", "bv", "nv",
    "sa", "srl", "spa", "ab", "as", "oy", "kk", "pty", "pte", "sarl", "kg",
]
_COMMON_SUBDOMAINS = {"www", "web", "en", "us", "www2", "shop", "info", "graphics"}


def canonical_domain(value: str | None) -> str | None:
    """Reduce a URL or hostname to its registrable domain. None if unusable."""
    if not value:
        return None
    raw = value.strip().lower()
    if not raw:
        return None
    if "://" not in raw:
        raw = "http://" + raw
    host = urlparse(raw).hostname or ""
    host = host.rstrip(".")
    if not host or "." not in host:
        return None

    parts = host.split(".")
    while len(parts) > 2 and parts[0] in _COMMON_SUBDOMAINS:
        parts = parts[1:]

    if len(parts) > 2:
        tail2 = ".".join(parts[-2:])
        keep = 3 if tail2 in _MULTI_PART_SUFFIXES else 2
        parts = parts[-keep:]
    return ".".join(parts)


def normalize_name(name: str | None) -> str:
    """Lowercase, strip punctuation and legal suffixes -> comparison key."""
    if not name:
        return ""
    text = name.lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    tokens = [t for t in text.split() if t]
    while tokens and tokens[-1] in _LEGAL_SUFFIXES:
        tokens.pop()
    return " ".join(tokens)


def name_similarity(a: str | None, b: str | None) -> float:
    na, nb = normalize_name(a), normalize_name(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    return SequenceMatcher(None, na, nb).ratio()


def dedupe_key(name: str | None, website: str | None) -> str:
    """Stable grouping key: domain when we have one, else the normalised name."""
    domain = canonical_domain(website)
    return f"domain:{domain}" if domain else f"name:{normalize_name(name)}"


def merge_records(primary: dict, incoming: dict) -> dict:
    """Field-wise merge: keep what we already have, fill the holes, union lists."""
    merged = dict(primary)
    for key, value in incoming.items():
        if value in (None, "", [], {}):
            continue
        current = merged.get(key)
        if isinstance(current, list) and isinstance(value, list):
            seen: list = []
            for item in [*current, *value]:
                if item not in seen:
                    seen.append(item)
            merged[key] = seen
        elif current in (None, "", [], {}):
            merged[key] = value
    return merged


def dedupe_companies(records: list[dict]) -> list[dict]:
    """Collapse a list of `{name, website, ...}` dicts.

    Two passes: exact key match, then fuzzy name match against already-kept
    records that have no domain of their own to disagree with.
    """
    kept: dict[str, dict] = {}
    for record in records:
        key = dedupe_key(record.get("name"), record.get("website"))
        if key in kept:
            kept[key] = merge_records(kept[key], record)
            continue

        match_key = None
        if key.startswith("name:"):
            for existing_key, existing in kept.items():
                similarity = name_similarity(record.get("name"), existing.get("name"))
                if similarity >= NAME_FUZZY_THRESHOLD:
                    match_key = existing_key
                    break
        if match_key:
            kept[match_key] = merge_records(kept[match_key], record)
        else:
            kept[key] = dict(record)
    return list(kept.values())
