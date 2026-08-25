"""Content-addressed HTTP cache.

Every byte we ever fetched lands in `data/raw/` keyed by URL hash, alongside a
JSON sidecar recording the URL, status and fetch time. Two payoffs:

* the committed cache lets anyone replay the exact run that produced the demo
  data, offline and without an API key;
* re-running the pipeline costs nothing and hammers nobody's exhibitor list.
"""

from __future__ import annotations

import gzip
import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from ..config import RAW_CACHE_DIR


@dataclass(slots=True)
class CachedResponse:
    url: str
    status_code: int
    text: str
    fetched_at: datetime
    from_cache: bool = False
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and 200 <= self.status_code < 300


def cache_key(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:24]


class ResponseCache:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or RAW_CACHE_DIR
        self.root.mkdir(parents=True, exist_ok=True)

    def _paths(self, url: str) -> tuple[Path, Path]:
        # Bodies are gzipped: raw HTML compresses ~6x, which is the difference
        # between a committable snapshot and one nobody wants in their repo.
        key = cache_key(url)
        return self.root / f"{key}.body.gz", self.root / f"{key}.json"

    def get(self, url: str) -> CachedResponse | None:
        body_path, meta_path = self._paths(url)
        if not (body_path.exists() and meta_path.exists()):
            return None
        try:
            meta = json.loads(meta_path.read_text())
            return CachedResponse(
                url=meta["url"],
                status_code=meta["status_code"],
                text=gzip.decompress(body_path.read_bytes()).decode("utf-8", "replace"),
                fetched_at=datetime.fromisoformat(meta["fetched_at"]),
                from_cache=True,
                error=meta.get("error"),
            )
        except (OSError, ValueError, KeyError, gzip.BadGzipFile):
            # A corrupt cache entry is a cache miss, never a crash.
            return None

    def put(
        self, url: str, status_code: int, text: str, *, error: str | None = None
    ) -> CachedResponse:
        body_path, meta_path = self._paths(url)
        fetched_at = datetime.now(UTC)
        body_path.write_bytes(gzip.compress(text.encode("utf-8"), 6))
        meta: dict = {
            "url": url,
            "status_code": status_code,
            "fetched_at": fetched_at.isoformat(),
        }
        if error:
            meta["error"] = error
        meta_path.write_text(json.dumps(meta, indent=2))
        return CachedResponse(url, status_code, text, fetched_at, from_cache=False, error=error)

    def put_failure(self, url: str, status_code: int, error: str) -> None:
        """Record a permanent failure.

        Without this, a cached replay reports "not in cache" for every URL that
        failed live -- which is true but useless. Recording the failure makes
        `--mode cached` reproduce the run that produced the snapshot, error log
        included.
        """
        self.put(url, status_code, "", error=error)

    def urls(self) -> list[str]:
        out = []
        for meta_path in self.root.glob("*.json"):
            try:
                out.append(json.loads(meta_path.read_text())["url"])
            except (OSError, ValueError, KeyError):
                continue
        return out
