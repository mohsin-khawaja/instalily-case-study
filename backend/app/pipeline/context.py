"""Shared state for one pipeline run, plus the error-isolation primitive.

`RunContext.guard` is the load-bearing piece: any stage can wrap per-record work
in it, and a failure becomes a persisted `StageError` on that record rather than
an exception that kills the run.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import TypeVar

from sqlmodel import Session

from ..models.enums import PipelineMode, StageName
from ..models.errors import StageError
from ..services.http import Fetcher, FetchError
from ..services.llm import LLMClient, LLMOutputError, LLMUnavailable
from ..services.search.base import SearchProvider

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Failure classes we expect and absorb. Anything else is a bug and should surface.
EXPECTED_FAILURES = (FetchError, LLMOutputError, LLMUnavailable, ValueError, KeyError)


@dataclass
class RunContext:
    run_id: str
    mode: PipelineMode
    session: Session
    fetcher: Fetcher
    search: SearchProvider
    llm: LLMClient
    limit: int | None = None
    errors: list[StageError] = field(default_factory=list)
    event_hosts: set[str] = field(default_factory=set)
    counts: dict[str, int] = field(default_factory=dict)

    @property
    def live(self) -> bool:
        return self.mode is PipelineMode.LIVE

    def bump(self, key: str, amount: int = 1) -> None:
        self.counts[key] = self.counts.get(key, 0) + amount

    def record_error(
        self,
        stage: StageName,
        exc: Exception,
        *,
        entity_type: str = "unknown",
        entity_ref: str | None = None,
    ) -> StageError:
        error = StageError(
            run_id=self.run_id,
            stage=stage,
            entity_type=entity_type,
            entity_ref=entity_ref,
            error_type=type(exc).__name__,
            message=str(exc)[:2000],
            retryable=getattr(exc, "retryable", False),
        )
        self.session.add(error)
        self.errors.append(error)
        logger.warning("[%s] %s on %s: %s", stage, type(exc).__name__, entity_ref, exc)
        return error

    @contextmanager
    def guard(
        self,
        stage: StageName,
        *,
        entity_type: str = "unknown",
        entity_ref: str | None = None,
    ):
        """Absorb an expected failure for one record; let real bugs propagate."""
        try:
            yield
        except EXPECTED_FAILURES as exc:
            self.record_error(stage, exc, entity_type=entity_type, entity_ref=entity_ref)

    async def attempt(
        self,
        stage: StageName,
        coro_factory: Callable[[], Awaitable[T]],
        *,
        entity_type: str = "unknown",
        entity_ref: str | None = None,
        default: T | None = None,
    ) -> T | None:
        """Async form of `guard` -- returns `default` when the record fails."""
        try:
            return await coro_factory()
        except EXPECTED_FAILURES as exc:
            self.record_error(stage, exc, entity_type=entity_type, entity_ref=entity_ref)
            return default
