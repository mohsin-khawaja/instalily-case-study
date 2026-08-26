"""Tavily provider.

Not wired to a live account for the case study -- `is_configured()` gates it, so
setting SEARCH_PROVIDER=tavily plus TAVILY_API_KEY is the only step to enable it.
The request/response mapping below is the real Tavily /search contract.
"""

from __future__ import annotations

import logging

import httpx

from ...config import get_settings
from ..http import Fetcher
from .base import SearchResult
from .cache import SearchCache

logger = logging.getLogger(__name__)

ENDPOINT = "https://api.tavily.com/search"


class TavilyProvider:
    name = "tavily"

    def __init__(self, api_key: str | None = None, fetcher: Fetcher | None = None) -> None:
        self._cache = SearchCache(self.name, fetcher)
        self._api_key = api_key or get_settings().tavily_api_key

    def is_configured(self) -> bool:
        return bool(self._api_key)

    async def search(self, query: str, *, limit: int = 10) -> list[SearchResult]:
        if not self.is_configured():
            logger.info("tavily provider not configured; returning no results")
            return []

        cached = self._cache.get(query, limit)
        if cached is not None and not self._cache.live:
            return self._parse(cached)
        payload = {
            "api_key": self._api_key,
            "query": query,
            "max_results": limit,
            "search_depth": "basic",
        }
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                response = await client.post(ENDPOINT, json=payload)
                response.raise_for_status()
                data = response.json()
                self._cache.put(query, limit, response.text)
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("tavily search failed for %r: %s", query, exc)
            return self._parse(cached) if cached is not None else []
        return self._parse(data)

    def _parse(self, data: dict) -> list[SearchResult]:
        return [
            SearchResult(
                url=item.get("url", ""),
                title=item.get("title", ""),
                snippet=item.get("content", ""),
                provider=self.name,
            )
            for item in data.get("results", [])
            if item.get("url")
        ]
