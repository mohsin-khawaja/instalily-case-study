"""Contact provider interface.

Contact data is the part of this pipeline a real deployment would buy rather than
scrape, so it sits behind one narrow interface. `PublicWebContactProvider` is the
working default; `ClayProvider` and `SalesNavigatorProvider` are complete except
for credentials. Switching is `CONTACT_PROVIDERS=clay,public_web` in the env --
no caller changes, because the chain resolves through `is_configured()`.
"""

from __future__ import annotations

import re
from typing import Protocol, runtime_checkable

from ...models.domain import Company, Contact
from ...models.enums import Seniority
from ...scoring import icp


@runtime_checkable
class ContactProvider(Protocol):
    name: str

    def is_configured(self) -> bool:
        """False when credentials are missing. The chain skips, it does not raise."""
        ...

    async def find_contacts(
        self, company: Company, target_titles: list[str], limit: int = 3
    ) -> list[Contact]: ...


def classify_seniority(title: str | None) -> Seniority:
    """Match on word boundaries, and rank VP above C-level.

    Substring matching gets this wrong twice: "director" contains "cto", and
    "Vice President" contains "President". Both mislabel real target titles.
    """
    text = (title or "").lower()
    if not text:
        return Seniority.OTHER
    if _matches(text, icp.SENIORITY_PATTERNS["vp"]):
        return Seniority.VP
    for level in ("c_level", "director", "manager"):
        if _matches(text, icp.SENIORITY_PATTERNS[level]):
            return Seniority(level)
    return Seniority.OTHER


def _matches(text: str, patterns: list[str]) -> bool:
    return any(re.search(rf"\b{re.escape(p)}\b", text) for p in patterns)


def title_relevance(title: str | None, target_titles: list[str]) -> float:
    """Crude but transparent: share of target-title words present in the title."""
    text = (title or "").lower()
    if not text:
        return 0.0
    best = 0.0
    for target in target_titles:
        words = [w for w in target.lower().split() if len(w) > 2]
        if not words:
            continue
        hits = sum(1 for w in words if w in text)
        best = max(best, hits / len(words))
    return round(best, 2)


def sales_navigator_url(full_name: str, company_name: str) -> str:
    """Deep link into a Sales Navigator lead search.

    Sales Navigator has no public 'resolve a person by name' endpoint, so until a
    partner API is wired this is the honest artefact: a one-click, pre-filtered
    search a rep can act on, rather than a fabricated profile URL.
    """
    from urllib.parse import quote_plus

    query = quote_plus(f"{full_name} {company_name}")
    return f"https://www.linkedin.com/sales/search/people?query={query}"
