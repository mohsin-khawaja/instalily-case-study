"""Contact provider chain assembly."""

from __future__ import annotations

import logging

from ...config import get_settings
from ...services.http import Fetcher
from ...services.search.base import SearchProvider
from .apollo import ApolloProvider
from .base import ContactProvider, classify_seniority, sales_navigator_url, title_relevance
from .clay import ClayProvider
from .mock import MockContactProvider
from .public_web import PublicWebContactProvider
from .sales_navigator import SalesNavigatorProvider

logger = logging.getLogger(__name__)

__all__ = [
    "ApolloProvider",
    "ClayProvider",
    "ContactProvider",
    "MockContactProvider",
    "PublicWebContactProvider",
    "SalesNavigatorProvider",
    "build_contact_chain",
    "classify_seniority",
    "sales_navigator_url",
    "title_relevance",
]


def build_contact_chain(
    fetcher: Fetcher,
    search: SearchProvider | None = None,
    names: list[str] | None = None,
) -> list[ContactProvider]:
    """Resolve CONTACT_PROVIDERS into configured providers, in order."""
    names = names or get_settings().contact_provider_chain
    chain: list[ContactProvider] = []
    for name in names:
        if name == "public_web":
            provider: ContactProvider = PublicWebContactProvider(fetcher, search)
        elif name == "apollo":
            provider = ApolloProvider()
        elif name == "clay":
            provider = ClayProvider()
        elif name == "sales_navigator":
            provider = SalesNavigatorProvider()
        elif name == "mock":
            provider = MockContactProvider()
        else:
            logger.warning("unknown contact provider %r, skipping", name)
            continue
        if provider.is_configured():
            chain.append(provider)
        else:
            logger.info("contact provider %r not configured, skipping", name)
    return chain
