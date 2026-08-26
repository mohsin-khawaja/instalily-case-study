"""Response caching for keyed search providers.

The keyless provider already runs through `Fetcher`, so its results land in the
same content-addressed cache as every other page. Serper and Tavily are POST
APIs with their own clients, which meant they bypassed the cache entirely —
and a "cached" run silently re-searched live, discovered companies whose sites
were never fetched, and filled the error log with cache misses.

Caching them here restores the property the whole snapshot depends on: a cached
run replays the run that produced it, exactly. It also stops repeat runs from
spending search credits on questions already answered.
"""

from __future__ import annotations

import json
import logging
from urllib.parse import quote_plus

from ..cache import ResponseCache
from ..http import Fetcher

logger = logging.getLogger(__name__)


def cache_key(provider: str, query: str, limit: int) -> str:
    """A synthetic URL. The cache is URL-keyed, and this makes the entry legible."""
    return f"https://{provider}.cached/search?q={quote_plus(query)}&num={limit}"


class SearchCache:
    """Read-through cache around a provider's raw JSON payload."""

    def __init__(self, provider: str, fetcher: Fetcher | None) -> None:
        self.provider = provider
        self._fetcher = fetcher

    @property
    def live(self) -> bool:
        # Without a fetcher we have no run mode, so behave like a live run.
        return self._fetcher.live if self._fetcher else True

    @property
    def _cache(self) -> ResponseCache | None:
        return self._fetcher.cache if self._fetcher else None

    def get(self, query: str, limit: int) -> dict | None:
        cache = self._cache
        if cache is None:
            return None
        entry = cache.get(cache_key(self.provider, query, limit))
        if entry is None or entry.error:
            return None
        try:
            return json.loads(entry.text)
        except ValueError:
            return None

    def put(self, query: str, limit: int, payload: str) -> None:
        cache = self._cache
        if cache is None:
            return
        cache.put(cache_key(self.provider, query, limit), 200, payload)
