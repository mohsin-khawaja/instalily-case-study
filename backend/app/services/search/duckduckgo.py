"""Keyless default provider: DuckDuckGo's no-JS HTML endpoint.

Good enough for "find the official site of <company>" and it keeps the clone-and-run
promise. Results flow through the same Fetcher, so they are cached and replayable.
"""

from __future__ import annotations

import logging
from urllib.parse import parse_qs, quote_plus, urlparse

from selectolax.parser import HTMLParser

from ..http import Fetcher, FetchError
from .base import SearchResult

logger = logging.getLogger(__name__)

ENDPOINT = "https://html.duckduckgo.com/html/?q={query}"


class DuckDuckGoProvider:
    name = "duckduckgo"

    def __init__(self, fetcher: Fetcher) -> None:
        self._fetcher = fetcher

    def is_configured(self) -> bool:
        return True  # no credentials required

    async def search(self, query: str, *, limit: int = 10) -> list[SearchResult]:
        url = ENDPOINT.format(query=quote_plus(query))
        try:
            response = await self._fetcher.fetch(url)
        except FetchError as exc:
            logger.warning("search failed for %r: %s", query, exc)
            return []
        return self._parse(response.text, limit)

    def _parse(self, html: str, limit: int) -> list[SearchResult]:
        results: list[SearchResult] = []
        for node in HTMLParser(html).css("div.result"):
            link = node.css_first("a.result__a")
            if link is None:
                continue
            href = _unwrap(link.attributes.get("href") or "")
            if not href:
                continue
            snippet_node = node.css_first(".result__snippet")
            results.append(
                SearchResult(
                    url=href,
                    title=link.text(strip=True),
                    snippet=snippet_node.text(strip=True) if snippet_node else "",
                    provider=self.name,
                )
            )
            if len(results) >= limit:
                break
        return results


def _unwrap(href: str) -> str:
    """DDG wraps outbound links as /l/?uddg=<encoded>. Unwrap to the real URL."""
    if href.startswith("//"):
        href = "https:" + href
    parsed = urlparse(href)
    if parsed.path.startswith("/l/"):
        target = parse_qs(parsed.query).get("uddg", [""])[0]
        if target:
            return target
    return href if href.startswith(("http://", "https://")) else ""
