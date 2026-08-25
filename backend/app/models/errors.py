"""Run bookkeeping. Failures are data, not exceptions that escape."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Column, Text
from sqlalchemy.types import JSON
from sqlmodel import Field, SQLModel

from .domain import utcnow
from .enums import PipelineMode, RunStatus, StageName


def _uuid() -> str:
    return uuid.uuid4().hex


class StageError(SQLModel, table=True):
    __tablename__ = "stage_errors"

    id: str = Field(default_factory=_uuid, primary_key=True)
    run_id: str = Field(index=True)
    stage: StageName
    entity_type: str = "unknown"
    entity_ref: str | None = None  # human-readable: company name, event slug, URL
    error_type: str = "Exception"
    message: str = Field(sa_column=Column(Text))
    retryable: bool = False
    created_at: datetime = Field(default_factory=utcnow)


class PipelineRun(SQLModel, table=True):
    __tablename__ = "pipeline_runs"

    id: str = Field(default_factory=_uuid, primary_key=True)
    mode: PipelineMode = PipelineMode.CACHED
    status: RunStatus = RunStatus.RUNNING
    current_stage: StageName | None = None
    stage_states: dict = Field(default_factory=dict, sa_column=Column(JSON))
    counts: dict = Field(default_factory=dict, sa_column=Column(JSON))
    error_count: int = 0
    started_at: datetime = Field(default_factory=utcnow)
    finished_at: datetime | None = None
