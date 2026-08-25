"""LinkedIn Sales Navigator integration.

Sales Navigator is not an open API. Production access is one of:

1. **Sales Navigator Application Platform (SNAP)** -- partner programme; the
   `/v2/salesApiLeadSearch` and `/v2/salesApiProfiles` endpoints support the
   title/company/seniority filters this pipeline needs. Requires an approved
   LinkedIn partner application and a 3-legged OAuth token with the
   `r_sales_nav_display` / `r_sales_nav_search` scopes.
2. **A licensed data reseller** (Clay, Apollo, Cognism, ...) that holds its own
   LinkedIn agreement -- see `clay.py`.

Scraping Sales Navigator would violate LinkedIn's User Agreement, so this
provider does exactly one thing without credentials: builds the deep search link
in `base.sales_navigator_url` that a licensed rep can click. With a SNAP token in
`SALES_NAV_TOKEN`, `_search_leads` below is the real call shape.

To enable:
    SALES_NAV_TOKEN=...                       # 3-legged OAuth access token
    CONTACT_PROVIDERS=sales_navigator,public_web
"""

from __future__ import annotations

import logging

import httpx

from ...config import get_settings
from ...models.domain import Company, Contact, SourceRef
from .base import classify_seniority, sales_navigator_url

logger = logging.getLogger(__name__)

LEAD_SEARCH_URL = "https://api.linkedin.com/v2/salesApiLeadSearch"
API_VERSION = "202409"


class SalesNavigatorProvider:
    name = "sales_navigator"

    def __init__(self, token: str | None = None) -> None:
        self._token = token or get_settings().sales_nav_token

    def is_configured(self) -> bool:
        return bool(self._token)

    async def find_contacts(
        self, company: Company, target_titles: list[str], limit: int = 3
    ) -> list[Contact]:
        if not self.is_configured():
            logger.info("sales navigator not configured; skipping")
            return []
        try:
            elements = await self._search_leads(company, target_titles, limit)
        except httpx.HTTPError as exc:
            logger.warning("sales navigator search failed for %s: %s", company.name, exc)
            return []
        return [c for c in (self._to_contact(company, e) for e in elements) if c][:limit]

    async def _search_leads(
        self, company: Company, target_titles: list[str], limit: int
    ) -> list[dict]:
        params = {
            "q": "searchQuery",
            "start": 0,
            "count": limit,
            # SNAP encodes facets as (key:List(value)) tuples.
            "searchQuery": (
                f"(filters:List("
                f"(type:CURRENT_COMPANY,values:List((text:{company.name}))),"
                f"(type:TITLE,values:List({','.join(f'(text:{t})' for t in target_titles[:5])}))"
                f"))"
            ),
        }
        headers = {
            "Authorization": f"Bearer {self._token}",
            "X-Restli-Protocol-Version": "2.0.0",
            "LinkedIn-Version": API_VERSION,
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(LEAD_SEARCH_URL, params=params, headers=headers)
            response.raise_for_status()
            return response.json().get("elements", [])

    def _to_contact(self, company: Company, element: dict) -> Contact | None:
        name = " ".join(filter(None, [element.get("firstName"), element.get("lastName")]))
        if not name:
            return None
        title = element.get("currentPositions", [{}])[0].get("title") or element.get("title")
        profile = element.get("profileUrl") or element.get("navigationUrl")
        return Contact(
            company_id=company.id,
            full_name=name,
            title=title,
            seniority=classify_seniority(title),
            linkedin_url=profile,
            sales_nav_url=profile or sales_navigator_url(name, company.name),
            provider=self.name,
            confidence=0.9,  # first-party LinkedIn data
            sources=[
                SourceRef(url=profile or "https://www.linkedin.com/sales/",
                          title="LinkedIn Sales Navigator").model_dump(mode="json")
            ],
        )
