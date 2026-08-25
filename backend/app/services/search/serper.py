"""Serper.dev (Google SERP) provider. Same shape as Tavily; enable with SERPER_API_KEY."""

from __future__ import annotations

import logging

import httpx

from ...config import get_settings
from .base import SearchResult

logger = logging.getLogger(__name__)

ENDPOINT = "https://google.serper.dev/search"


class SerperProvider:
    name = "serper"

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key or get_settings().serper_api_key

    def is_configured(self) -> bool:
        return bool(self._api_key)

    async def search(self, query: str, *, limit: int = 10) -> list[SearchResult]:
        if not self.is_configured():
            logger.info("serper provider not configured; returning no results")
            return []
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                response = await client.post(
                    ENDPOINT,
                    json={"q": query, "num": limit},
                    headers={"X-API-KEY": self._api_key or ""},
                )
                response.raise_for_status()
                data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("serper search failed for %r: %s", query, exc)
            return []
        return [
            SearchResult(
                url=item.get("link", ""),
                title=item.get("title", ""),
                snippet=item.get("snippet", ""),
                provider=self.name,
            )
            for item in data.get("organic", [])
            if item.get("link")
        ]
