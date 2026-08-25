"""Polite, cached, retrying async fetcher.

Concurrency is bounded globally and serialised per host, so a 60-company
enrichment pass never looks like an attack. Retries cover the transient
failures (429/5xx/timeouts) and skip the permanent ones (404/403).
"""

from __future__ import annotations

import asyncio
import logging
import time
from urllib.parse import urlparse

import httpx

from ..config import get_settings
from .cache import CachedResponse, ResponseCache

logger = logging.getLogger(__name__)

RETRYABLE_STATUS = {408, 425, 429, 500, 502, 503, 504}
MAX_ATTEMPTS = 3


class FetchError(RuntimeError):
    """Raised when a URL could not be retrieved after retries."""

    def __init__(self, url: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(f"{url}: {message}")
        self.url = url
        self.retryable = retryable


class Fetcher:
    """One instance per pipeline run. Use as an async context manager."""

    def __init__(
        self,
        *,
        live: bool = False,
        cache: ResponseCache | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        settings = get_settings()
        self.live = live
        self.cache = cache or ResponseCache()
        self._client = client
        self._owns_client = client is None
        self._semaphore = asyncio.Semaphore(settings.http_concurrency)
        self._host_locks: dict[str, asyncio.Lock] = {}
        self._host_last_hit: dict[str, float] = {}
        self._delay = settings.http_per_host_delay_s
        self._timeout = settings.http_timeout_s
        self._headers = {
            "User-Agent": settings.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
        }

    async def __aenter__(self) -> Fetcher:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self._timeout, follow_redirects=True, headers=self._headers
            )
        return self

    async def __aexit__(self, *_exc) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    def _host_lock(self, url: str) -> tuple[str, asyncio.Lock]:
        host = urlparse(url).hostname or "unknown"
        if host not in self._host_locks:
            self._host_locks[host] = asyncio.Lock()
        return host, self._host_locks[host]

    async def _throttle(self, host: str) -> None:
        last = self._host_last_hit.get(host)
        if last is not None:
            wait = self._delay - (time.monotonic() - last)
            if wait > 0:
                await asyncio.sleep(wait)
        self._host_last_hit[host] = time.monotonic()

    async def fetch(self, url: str, *, force_live: bool = False) -> CachedResponse:
        """Return the page for `url`.

        Cache is authoritative unless the run is live. In live mode we still fall
        back to a stale cache entry rather than fail the whole record.
        """
        use_live = self.live or force_live
        cached = self.cache.get(url)
        if cached is not None and not use_live:
            if cached.error:
                # Replay the original failure rather than reporting a cache miss.
                raise FetchError(url, cached.error, retryable=False)
            return cached
        if not use_live and cached is None:
            raise FetchError(url, "not in cache and run is in cached mode", retryable=False)

        try:
            response = await self._fetch_live(url)
        except FetchError as exc:
            if cached is not None and not cached.error:
                logger.warning("live fetch failed for %s, serving stale cache", url)
                return cached
            self.cache.put_failure(url, _status_from(exc), str(exc).split(": ", 1)[-1])
            raise
        return self.cache.put(url, response.status_code, response.text)

    async def _fetch_live(self, url: str) -> httpx.Response:
        if self._client is None:
            raise FetchError(url, "fetcher used outside its async context")
        host, lock = self._host_lock(url)
        last_error = "unknown error"

        for attempt in range(1, MAX_ATTEMPTS + 1):
            async with self._semaphore, lock:
                await self._throttle(host)
                try:
                    response = await self._client.get(url)
                except (httpx.TimeoutException, httpx.TransportError) as exc:
                    last_error = f"{type(exc).__name__}: {exc}"
                else:
                    if response.status_code < 400:
                        return response
                    if response.status_code not in RETRYABLE_STATUS:
                        raise FetchError(
                            url, f"HTTP {response.status_code}", retryable=False
                        )
                    last_error = f"HTTP {response.status_code}"
                    retry_after = _retry_after_seconds(response)
                    if retry_after is not None:
                        await asyncio.sleep(min(retry_after, 30.0))

            if attempt < MAX_ATTEMPTS:
                await asyncio.sleep(min(2.0**attempt, 8.0))

        raise FetchError(url, f"giving up after {MAX_ATTEMPTS} attempts ({last_error})",
                         retryable=True)


def _status_from(exc: FetchError) -> int:
    """Best-effort HTTP status out of the error text; 0 for transport failures."""
    message = str(exc)
    marker = "HTTP "
    if marker in message:
        digits = message.split(marker, 1)[1][:3]
        if digits.isdigit():
            return int(digits)
    return 0


def _retry_after_seconds(response: httpx.Response) -> float | None:
    raw = response.headers.get("retry-after")
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None
