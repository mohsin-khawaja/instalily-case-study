"""Clay integration.

Clay's model is table-oriented: you POST a row to a table webhook, Clay runs its
waterfall of enrichment providers, and the result comes back either by polling
the row or via a callback. Both halves are written below; only credentials are
missing, so `is_configured()` keeps it out of the chain until CLAY_API_KEY and
CLAY_WEBHOOK_URL are set.

To enable:
    CLAY_API_KEY=...            # Clay workspace API key
    CLAY_WEBHOOK_URL=...        # the target table's webhook endpoint
    CONTACT_PROVIDERS=clay,public_web
"""

from __future__ import annotations

import asyncio
import logging

import httpx

from ...config import get_settings
from ...models.domain import Company, Contact, SourceRef
from ...models.enums import RecordStatus
from .base import classify_seniority, sales_navigator_url

logger = logging.getLogger(__name__)

POLL_INTERVAL_S = 2.0
POLL_ATTEMPTS = 15


class ClayProvider:
    name = "clay"

    def __init__(self, api_key: str | None = None, webhook_url: str | None = None) -> None:
        settings = get_settings()
        self._api_key = api_key or settings.clay_api_key
        self._webhook_url = webhook_url or settings.clay_webhook_url

    def is_configured(self) -> bool:
        return bool(self._api_key and self._webhook_url)

    async def find_contacts(
        self, company: Company, target_titles: list[str], limit: int = 3
    ) -> list[Contact]:
        if not self.is_configured():
            logger.info("clay provider not configured; skipping")
            return []

        payload = {
            "company_name": company.name,
            "company_domain": company.domain,
            "company_website": company.website,
            "target_titles": target_titles,
            "max_results": limit,
            # Correlation id so a webhook callback can be matched to our record.
            "external_id": company.id,
        }
        headers = {"Authorization": f"Bearer {self._api_key}",
                   "Content-Type": "application/json"}
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(self._webhook_url, json=payload, headers=headers)
                response.raise_for_status()
                rows = await self._await_rows(client, response, headers)
        except httpx.HTTPError as exc:
            logger.warning("clay enrichment failed for %s: %s", company.name, exc)
            return []

        return [c for c in (self._to_contact(company, row) for row in rows[:limit]) if c]

    async def _await_rows(
        self, client: httpx.AsyncClient, submit_response: httpx.Response, headers: dict
    ) -> list[dict]:
        """Clay enrichment is asynchronous: poll the row until it resolves."""
        body = submit_response.json() if submit_response.content else {}
        rows = body.get("results") or body.get("rows")
        if rows:
            return rows
        status_url = body.get("status_url") or body.get("row_url")
        if not status_url:
            return []
        for _ in range(POLL_ATTEMPTS):
            await asyncio.sleep(POLL_INTERVAL_S)
            poll = await client.get(status_url, headers=headers)
            if poll.status_code == 200:
                data = poll.json()
                if data.get("status") in ("complete", "completed", "success"):
                    return data.get("results") or data.get("rows") or []
        logger.warning("clay enrichment timed out")
        return []

    def _to_contact(self, company: Company, row: dict) -> Contact | None:
        name = row.get("full_name") or " ".join(
            filter(None, [row.get("first_name"), row.get("last_name")])
        )
        if not name:
            return None
        title = row.get("title") or row.get("job_title")
        linkedin = row.get("linkedin_url") or row.get("linkedin_profile_url")
        source_url = linkedin or company.website or "https://clay.com/"
        return Contact(
            company_id=company.id,
            full_name=name,
            title=title,
            seniority=classify_seniority(title),
            linkedin_url=linkedin,
            sales_nav_url=sales_navigator_url(name, company.name),
            email=row.get("email"),
            provider=self.name,
            confidence=float(row.get("confidence", 0.8)),
            status=RecordStatus.COMPLETE if linkedin else RecordStatus.INCOMPLETE,
            sources=[SourceRef(url=source_url, title="Clay enrichment").model_dump(mode="json")],
        )
