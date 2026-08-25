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
from dataclasses import dataclass

import httpx
from pydantic import BaseModel

from ...config import get_settings
from ...models.domain import Company, Contact, SourceRef
from ...models.enums import RecordStatus
from .base import classify_seniority, sales_navigator_url, title_relevance

logger = logging.getLogger(__name__)

SEARCH_URL = "https://api.apollo.io/api/v1/mixed_people/search"
ORG_ENRICH_URL = "https://api.apollo.io/api/v1/organizations/enrich"
TIMEOUT_S = 30.0


class ApolloProvider:
    name = "apollo"

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key or get_settings().apollo_api_key
        # A plan restriction does not change mid-run. Once people search answers
        # 403 there is nothing to gain from asking again for every remaining
        # company, so the provider retires itself and the chain moves on.
        self._people_search_available = True

    def is_configured(self) -> bool:
        return bool(self._api_key) and self._people_search_available

    async def find_contacts(
        self, company: Company, target_titles: list[str], limit: int = 3
    ) -> list[Contact]:
        if not self._api_key:
            logger.info("apollo provider not configured; skipping")
            return []
        if not self._people_search_available:
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
            # 403 on this endpoint is usually the Free plan, not a bad key --
            # Apollo gates people search behind paid tiers while leaving
            # organization enrichment open. Say so, so nobody re-checks the key.
            if exc.response.status_code == 403:
                self._people_search_available = False
                logger.warning(
                    "apollo people search is not available on this plan (403). "
                    "Organization enrichment still works; contacts fall through "
                    "to the next provider in CONTACT_PROVIDERS for this run."
                )
            elif exc.response.status_code == 429:
                self._people_search_available = False
                logger.warning("apollo people search quota exhausted for this run (429)")
            else:
                logger.warning(
                    "apollo search failed for %s: HTTP %s",
                    company.name, exc.response.status_code,
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


# ---------------------------------------------------------------------------
# Organization enrichment
# ---------------------------------------------------------------------------
#
# Unlike people search, `organizations/enrich` is available on Apollo's free
# tier, and it answers the question the scorer most often cannot: how big is
# this company. Most private manufacturers never publish revenue on their own
# site, so without a firmographics source the size component scores zero across
# the board and nothing reaches tier A.


class ApolloRateLimited(RuntimeError):
    """Apollo returned 429. Free-tier quotas are tight and reset slowly."""


@dataclass
class RateLimitBreaker:
    """Stop calling a provider that has started refusing us.

    A rate-limited free tier does not recover within a run, so retrying every
    remaining company just adds a round-trip each and delays the fallback that
    would have worked. After `threshold` consecutive 429s the circuit opens and
    callers skip straight to the next source.
    """

    threshold: int = 3
    consecutive: int = 0
    opened: bool = False

    def is_open(self) -> bool:
        return self.opened

    def record_rate_limit(self) -> bool:
        """Record a 429. Returns True if this opened the circuit."""
        self.consecutive += 1
        if self.consecutive >= self.threshold and not self.opened:
            self.opened = True
            return True
        return False

    def record_success(self) -> None:
        self.consecutive = 0


class ApolloOrganization(BaseModel):
    """The subset of Apollo's organization record this pipeline uses."""

    apollo_id: str | None = None
    name: str | None = None
    revenue_usd: float | None = None
    employee_count: int | None = None
    industry: str | None = None
    keywords: list[str] = []
    description: str | None = None
    hq_location: str | None = None
    linkedin_url: str | None = None

    @property
    def source_url(self) -> str | None:
        """A citable record. Auth-gated, but real and checkable by a rep."""
        if self.apollo_id:
            return f"https://app.apollo.io/#/organizations/{self.apollo_id}"
        return self.linkedin_url


async def enrich_organization(domain: str, api_key: str | None = None) -> ApolloOrganization | None:
    """Look up firmographics for a domain. None on any failure -- never raises."""
    key = api_key or get_settings().apollo_api_key
    if not (key and domain):
        return None
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
            response = await client.get(
                ORG_ENRICH_URL, headers={"x-api-key": key}, params={"domain": domain}
            )
            response.raise_for_status()
            org = response.json().get("organization")
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 429:
            raise ApolloRateLimited(f"apollo rate limited on {domain}") from exc
        logger.info("apollo org enrich failed for %s: HTTP %s", domain, exc.response.status_code)
        return None
    except (httpx.HTTPError, ValueError) as exc:
        logger.info("apollo org enrich failed for %s: %s", domain, exc)
        return None
    if not org:
        return None

    city, country = org.get("city"), org.get("country")
    return ApolloOrganization(
        apollo_id=org.get("id"),
        name=org.get("name"),
        revenue_usd=_positive(org.get("annual_revenue")),
        employee_count=_positive(org.get("estimated_num_employees")),
        industry=org.get("industry"),
        keywords=[k for k in (org.get("keywords") or []) if isinstance(k, str)][:12],
        description=(org.get("short_description") or None),
        hq_location=", ".join(p for p in (city, country) if p) or None,
        linkedin_url=org.get("linkedin_url"),
    )


def _positive(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None
