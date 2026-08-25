"""Search provider interface.

Discovery needs a web index; which one is a deployment detail. The default
provider needs no key so a reviewer can clone and run. Swapping in Tavily or
Serper is an env change, not a code change.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(slots=True)
class SearchResult:
    url: str
    title: str
    snippet: str = ""
    provider: str = "unknown"


@runtime_checkable
class SearchProvider(Protocol):
    name: str

    def is_configured(self) -> bool:
        """False when required credentials are absent -- caller skips, never crashes."""
        ...

    async def search(self, query: str, *, limit: int = 10) -> list[SearchResult]: ...
