from __future__ import annotations

import httpx
import pytest

from app.services.cache import ResponseCache
from app.services.http import Fetcher, FetchError


@pytest.fixture
def cache(tmp_path):
    return ResponseCache(root=tmp_path / "raw")


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True)


def test_cache_roundtrip_and_corrupt_entry_is_a_miss(cache, tmp_path):
    url = "https://example.com/a"
    assert cache.get(url) is None
    cache.put(url, 200, "<html>hi</html>")
    hit = cache.get(url)
    assert hit is not None and hit.text == "<html>hi</html>" and hit.from_cache
    assert cache.urls() == [url]

    next(iter((tmp_path / "raw").glob("*.json"))).write_text("{ not json")
    assert cache.get(url) is None


async def test_second_fetch_is_served_from_cache_without_network(cache):
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(200, text="<html>body</html>")

    async with Fetcher(live=True, cache=cache, client=_client(handler)) as fetcher:
        first = await fetcher.fetch("https://example.com/x")
        assert first.from_cache is False

    async with Fetcher(live=False, cache=cache, client=_client(handler)) as fetcher:
        second = await fetcher.fetch("https://example.com/x")

    assert second.from_cache is True
    assert second.text == first.text
    assert calls["n"] == 1


async def test_cached_mode_raises_a_typed_error_on_a_miss(cache):
    async with Fetcher(live=False, cache=cache) as fetcher:
        with pytest.raises(FetchError) as exc:
            await fetcher.fetch("https://example.com/never-seen")
    assert exc.value.retryable is False


async def test_retries_on_429_then_succeeds(cache):
    attempts = {"n": 0}

    def handler(request):
        attempts["n"] += 1
        if attempts["n"] == 1:
            return httpx.Response(429, headers={"retry-after": "0"})
        return httpx.Response(200, text="ok")

    async with Fetcher(live=True, cache=cache, client=_client(handler)) as fetcher:
        response = await fetcher.fetch("https://example.com/rate-limited")

    assert response.text == "ok"
    assert attempts["n"] == 2


async def test_404_is_not_retried(cache):
    attempts = {"n": 0}

    def handler(request):
        attempts["n"] += 1
        return httpx.Response(404)

    async with Fetcher(live=True, cache=cache, client=_client(handler)) as fetcher:
        with pytest.raises(FetchError) as exc:
            await fetcher.fetch("https://example.com/gone")

    assert attempts["n"] == 1
    assert exc.value.retryable is False


async def test_live_failure_falls_back_to_stale_cache(cache):
    cache.put("https://example.com/flaky", 200, "stale but usable")

    def handler(request):
        raise httpx.ConnectError("network down")

    async with Fetcher(live=True, cache=cache, client=_client(handler)) as fetcher:
        response = await fetcher.fetch("https://example.com/flaky")

    assert response.text == "stale but usable"


async def test_permanent_failure_is_cached_and_replayed_faithfully(cache):
    """A cached replay must reproduce the original error, not report a cache miss."""
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(403)

    async with Fetcher(live=True, cache=cache, client=_client(handler)) as fetcher:
        with pytest.raises(FetchError) as live_error:
            await fetcher.fetch("https://blocked.example/")

    async with Fetcher(live=False, cache=cache) as fetcher:
        with pytest.raises(FetchError) as replayed:
            await fetcher.fetch("https://blocked.example/")

    assert "403" in str(live_error.value)
    assert "403" in str(replayed.value)
    assert "not in cache" not in str(replayed.value)
    assert calls["n"] == 1  # the replay hit no network


async def test_a_cached_failure_does_not_shadow_a_later_success(cache):
    def failing(request):
        return httpx.Response(403)

    def working(request):
        return httpx.Response(200, text="back online")

    async with Fetcher(live=True, cache=cache, client=_client(failing)) as fetcher:
        with pytest.raises(FetchError):
            await fetcher.fetch("https://flaky.example/")

    async with Fetcher(live=True, cache=cache, client=_client(working)) as fetcher:
        response = await fetcher.fetch("https://flaky.example/")

    assert response.text == "back online"
    assert response.error is None


# --- Search provider caching ---------------------------------------------


async def test_keyed_search_is_cached_so_a_replay_is_deterministic(cache, monkeypatch):
    """A cached run must replay the same search answers, not re-query live.

    Serper and Tavily are POST APIs with their own clients, so before this they
    bypassed the cache: a "cached" run silently re-searched, discovered
    different companies, and then failed to fetch their sites from cache.
    """
    from app.services.search import serper

    calls = {"n": 0}
    payload = {
        "organic": [
            {"link": "https://drytac.com/", "title": "Drytac", "snippet": "Laminating films"}
        ]
    }

    real_client = httpx.AsyncClient

    def handler(request):
        calls["n"] += 1
        return httpx.Response(200, json=payload)

    monkeypatch.setattr(
        serper.httpx,
        "AsyncClient",
        lambda **kw: real_client(transport=httpx.MockTransport(handler)),
    )

    async with Fetcher(live=True, cache=cache) as live_fetcher:
        provider = serper.SerperProvider(api_key="k", fetcher=live_fetcher)
        first = await provider.search("graphic films", limit=5)

    async with Fetcher(live=False, cache=cache) as cached_fetcher:
        replay = serper.SerperProvider(api_key="k", fetcher=cached_fetcher)
        second = await replay.search("graphic films", limit=5)

    assert [r.url for r in first] == [r.url for r in second]
    assert calls["n"] == 1, "the replay hit the network"


async def test_a_live_search_falls_back_to_cache_when_the_api_fails(cache, monkeypatch):
    from app.services.search import serper

    real_client = httpx.AsyncClient
    state = {"fail": False}

    def handler(request):
        if state["fail"]:
            return httpx.Response(500)
        return httpx.Response(
            200, json={"organic": [{"link": "https://x.test/", "title": "X", "snippet": ""}]}
        )

    monkeypatch.setattr(
        serper.httpx,
        "AsyncClient",
        lambda **kw: real_client(transport=httpx.MockTransport(handler)),
    )

    async with Fetcher(live=True, cache=cache) as fetcher:
        provider = serper.SerperProvider(api_key="k", fetcher=fetcher)
        await provider.search("q", limit=3)
        state["fail"] = True
        recovered = await provider.search("q", limit=3)

    assert [r.url for r in recovered] == ["https://x.test/"]
