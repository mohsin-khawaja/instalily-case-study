"""Deterministic provider for tests and for offline demos.

Returns a stable, obviously-synthetic contact so failure paths and UI states can
be exercised without a network. Every contact it emits is marked
`provider="mock"` and carries `confidence=0.0`, so mock data can never be
mistaken for a sourced lead in the dashboard or in an export.
"""

from __future__ import annotations

import hashlib

from ...models.domain import Company, Contact
from ...models.enums import RecordStatus
from .base import classify_seniority, sales_navigator_url

_FIRST = ["Alex", "Jordan", "Riley", "Morgan", "Casey", "Taylor", "Avery", "Quinn"]
_LAST = ["Reed", "Vance", "Hollis", "Marsh", "Cole", "Bryant", "Ellis", "Nolan"]


class MockContactProvider:
    name = "mock"

    def is_configured(self) -> bool:
        return True

    async def find_contacts(
        self, company: Company, target_titles: list[str], limit: int = 3
    ) -> list[Contact]:
        seed = int(hashlib.sha256(company.canonical_name.encode()).hexdigest()[:8], 16)
        title = target_titles[seed % len(target_titles)] if target_titles else "Director"
        name = f"{_FIRST[seed % len(_FIRST)]} {_LAST[(seed // 7) % len(_LAST)]}"
        return [
            Contact(
                company_id=company.id,
                full_name=name,
                title=title,
                seniority=classify_seniority(title),
                sales_nav_url=sales_navigator_url(name, company.name),
                provider=self.name,
                confidence=0.0,  # placeholder data must never look sourced
                status=RecordStatus.INCOMPLETE,
                sources=[],
            )
        ][:limit]
