"""Serper.dev (Google SERP) provider. Same shape as Tavily; enable with SERPER_API_KEY."""

from __future__ import annotations

import logging

import httpx

from ...config import get_settings
from ..http import Fetcher
from .base import SearchResult
from .cache import SearchCache

logger = logging.getLogger(__name__)

ENDPOINT = "https://google.serper.dev/search"


class SerperProvider:
    name = "serper"

    def __init__(self, api_key: str | None = None, fetcher: Fetcher | None = None) -> None:
        self._cache = SearchCache(self.name, fetcher)
        self._api_key = api_key or get_settings().serper_api_key

    def is_configured(self) -> bool:
        return bool(self._api_key)

    async def search(self, query: str, *, limit: int = 10) -> list[SearchResult]:
        if not self.is_configured():
            logger.info("serper provider not configured; returning no results")
            return []

        cached = self._cache.get(query, limit)
        if cached is not None and not self._cache.live:
            return self._parse(cached)
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                response = await client.post(
                    ENDPOINT,
                    json={"q": query, "num": limit},
                    headers={"X-API-KEY": self._api_key or ""},
                )
                response.raise_for_status()
                data = response.json()
                self._cache.put(query, limit, response.text)
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("serper search failed for %r: %s", query, exc)
            return self._parse(cached) if cached is not None else []
        return self._parse(data)

    def _parse(self, data: dict) -> list[SearchResult]:
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
