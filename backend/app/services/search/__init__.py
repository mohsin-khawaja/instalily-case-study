"""Search provider registry."""

from __future__ import annotations

from ...config import get_settings
from ..http import Fetcher
from .base import SearchProvider, SearchResult
from .duckduckgo import DuckDuckGoProvider
from .serper import SerperProvider
from .tavily import TavilyProvider

__all__ = [
    "DuckDuckGoProvider",
    "SearchProvider",
    "SearchResult",
    "SerperProvider",
    "TavilyProvider",
    "build_search_provider",
]


def build_search_provider(fetcher: Fetcher, name: str | None = None) -> SearchProvider:
    """Resolve SEARCH_PROVIDER, falling back to the keyless provider if unconfigured."""
    name = (name or get_settings().search_provider).lower()
    if name == "tavily":
        provider: SearchProvider = TavilyProvider()
    elif name == "serper":
        provider = SerperProvider()
    else:
        return DuckDuckGoProvider(fetcher)
    return provider if provider.is_configured() else DuckDuckGoProvider(fetcher)
