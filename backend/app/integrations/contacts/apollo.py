"""Apollo.io contact provider.

The one provider in this chain that returns real named decision-makers on a free
tier, which is why it is the recommended first paid-ish integration. It fills the
exact gap the case study's worked example describes: a named VP or Director at a
qualified account, with a LinkedIn URL the sales team can act on.

To enable:
    APOLLO_API_KEY=...
    CONTACT_PROVIDERS=apollo,public_web,mock

Apollo's people search is credit-metered, so this provider is deliberately
narrow: one request per company, filtered to the ICP's target titles and that
company's own domain. It never pages, and it never guesses -- a person with no
name is dropped rather than synthesised.
"""

from __future__ import annotations

import logging

import httpx

from ...config import get_settings
from ...models.domain import Company, Contact, SourceRef
from ...models.enums import RecordStatus
from .base import classify_seniority, sales_navigator_url, title_relevance

logger = logging.getLogger(__name__)

SEARCH_URL = "https://api.apollo.io/api/v1/mixed_people/search"
TIMEOUT_S = 30.0


class ApolloProvider:
    name = "apollo"

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key or get_settings().apollo_api_key

    def is_configured(self) -> bool:
        return bool(self._api_key)

    async def find_contacts(
        self, company: Company, target_titles: list[str], limit: int = 3
    ) -> list[Contact]:
        if not self.is_configured():
            logger.info("apollo provider not configured; skipping")
            return []
        if not company.domain:
            # Without a domain Apollo matches on company name alone, which is how
            # you end up with a VP at a different firm of the same name.
            logger.info("apollo: no domain for %s, skipping", company.name)
            return []

        payload = {
            "person_titles": target_titles[:10],
            "q_organization_domains_list": [company.domain],
            "page": 1,
            "per_page": max(limit, 5),
        }
        headers = {
            "x-api-key": self._api_key or "",
            "Content-Type": "application/json",
            "Cache-Control": "no-cache",
        }
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
                response = await client.post(SEARCH_URL, json=payload, headers=headers)
                response.raise_for_status()
                people = response.json().get("people", [])
        except httpx.HTTPStatusError as exc:
            # 401/403 = bad key, 422 = bad filter, 429 = out of credits. All are
            # worth seeing in the error log rather than silently returning none.
            logger.warning(
                "apollo search failed for %s: HTTP %s", company.name, exc.response.status_code
            )
            return []
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("apollo search failed for %s: %s", company.name, exc)
            return []

        contacts = [
            c for c in (self._to_contact(company, p) for p in people) if c is not None
        ]
        # Best title match first, so a VP Product outranks a regional sales rep
        # that slipped through the title filter.
        contacts.sort(key=lambda c: title_relevance(c.title, target_titles), reverse=True)
        return contacts[:limit]

    def _to_contact(self, company: Company, person: dict) -> Contact | None:
        name = (person.get("name") or "").strip() or " ".join(
            filter(None, [person.get("first_name"), person.get("last_name")])
        ).strip()
        if not name:
            return None

        title = person.get("title")
        linkedin = person.get("linkedin_url")
        # Apollo redacts emails until you unlock the contact; "email_not_unlocked@
        # domain.com" is a placeholder, not an address.
        email = person.get("email")
        if email and "not_unlocked" in email:
            email = None

        return Contact(
            company_id=company.id,
            full_name=name,
            title=title,
            seniority=classify_seniority(title),
            linkedin_url=linkedin,
            sales_nav_url=linkedin or sales_navigator_url(name, company.name),
            email=email,
            provider=self.name,
            # First-party-ish B2B data, but an aggregator's record all the same:
            # high enough to act on, not so high it outranks a company's own page.
            confidence=0.85 if linkedin else 0.6,
            status=RecordStatus.COMPLETE if linkedin else RecordStatus.INCOMPLETE,
            sources=[
                SourceRef(
                    url=linkedin or f"https://{company.domain}",
                    title=f"Apollo.io person record for {name}",
                ).model_dump(mode="json")
            ],
        )
