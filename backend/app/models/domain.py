"""Domain models.

SQLModel table classes double as the persistence layer and the API schema.
Nested value objects (SourceRef, Evidence, ScoreBreakdown) are plain Pydantic and
live in JSON columns -- SQLite is the MVP store and joins on those would buy
nothing.

Design rule: every field that an enrichment step can fail to produce is nullable.
A missing value degrades `status` and `confidence`; it never aborts a run.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

from pydantic import BaseModel, field_validator
from pydantic import Field as PydField
from sqlalchemy import Column, Text
from sqlalchemy.types import JSON
from sqlmodel import Field, SQLModel

from .enums import EventType, RecordStatus, Seniority, Tier


def _uuid() -> str:
    return uuid.uuid4().hex


def utcnow() -> datetime:
    return datetime.now(UTC)


# --------------------------------------------------------------------------
# Value objects (JSON-serialised)
# --------------------------------------------------------------------------


class SourceRef(BaseModel):
    """Provenance for anything we assert. No claim ships without one of these."""

    url: str
    title: str | None = None
    fetched_at: datetime = PydField(default_factory=utcnow)
    snippet: str | None = None

    @field_validator("url")
    @classmethod
    def _must_be_http(cls, v: str) -> str:
        if not v.startswith(("http://", "https://")):
            raise ValueError(f"source url must be http(s): {v!r}")
        return v


class Evidence(BaseModel):
    """A single supported claim: what we believe, and the URL that backs it."""

    claim: str
    source_url: str
    quote: str | None = None
    stage: str | None = None

    @field_validator("source_url")
    @classmethod
    def _must_be_http(cls, v: str) -> str:
        if not v.startswith(("http://", "https://")):
            raise ValueError(f"evidence source_url must be http(s): {v!r}")
        return v


class ScoreBreakdown(BaseModel):
    """Transparent 0-100 lead score. Computed in Python, never by the LLM."""

    industry_fit: float = 0.0  # max 30
    product_fit: float = 0.0  # max 25
    size: float = 0.0  # max 15
    event_engagement: float = 0.0  # max 15
    pain_alignment: float = 0.0  # max 15

    @property
    def total(self) -> float:
        return round(
            self.industry_fit
            + self.product_fit
            + self.size
            + self.event_engagement
            + self.pain_alignment,
            1,
        )

    def as_dict(self) -> dict[str, float]:
        d = self.model_dump()
        d["total"] = self.total
        return d


# --------------------------------------------------------------------------
# Tables
# --------------------------------------------------------------------------


class Event(SQLModel, table=True):
    __tablename__ = "events"

    id: str = Field(default_factory=_uuid, primary_key=True)
    slug: str = Field(index=True, unique=True)
    name: str
    url: str
    event_type: EventType = EventType.TRADE_SHOW
    organizer: str | None = None
    venue: str | None = None
    city: str | None = None
    country: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    exhibitor_list_url: str | None = None
    relevance_note: str | None = Field(default=None, sa_column=Column(Text))
    tier1: bool = False  # flagship Tedlar-ICP show, weighted higher in scoring
    status: RecordStatus = RecordStatus.COMPLETE
    sources: list[dict] = Field(default_factory=list, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class Company(SQLModel, table=True):
    __tablename__ = "companies"

    id: str = Field(default_factory=_uuid, primary_key=True)
    name: str
    canonical_name: str = Field(index=True)
    domain: str | None = Field(default=None, index=True)
    website: str | None = None
    hq_location: str | None = None
    industry: str | None = None
    sub_industries: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    description: str | None = Field(default=None, sa_column=Column(Text))
    products: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    employee_count_est: int | None = None
    employee_band: str | None = None
    revenue_est_usd: float | None = None
    revenue_band: str | None = None
    # Where the size figure actually came from. The company's own site and a
    # search snippet are different-strength sources, and the evidence must say
    # which one it was rather than defaulting to the website.
    size_source_url: str | None = None
    # "site" (the company said it) or "third_party" (an aggregator estimated it).
    size_source_kind: str | None = None
    event_ids: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    enriched: bool = False
    status: RecordStatus = RecordStatus.INCOMPLETE
    sources: list[dict] = Field(default_factory=list, sa_column=Column(JSON))
    # Raw site text kept for scoring signals + evidence quoting; capped upstream.
    site_text: str | None = Field(default=None, sa_column=Column(Text))
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class Qualification(SQLModel, table=True):
    __tablename__ = "qualifications"

    id: str = Field(default_factory=_uuid, primary_key=True)
    company_id: str = Field(index=True, foreign_key="companies.id")
    score_total: float = 0.0
    score: dict = Field(default_factory=dict, sa_column=Column(JSON))
    tier: Tier = Tier.DISQUALIFIED
    confidence: float = 0.0
    rationale: str | None = Field(default=None, sa_column=Column(Text))
    rationale_source: str = "deterministic"  # deterministic | llm
    evidence: list[dict] = Field(default_factory=list, sa_column=Column(JSON))
    flags: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    status: RecordStatus = RecordStatus.COMPLETE
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class Contact(SQLModel, table=True):
    __tablename__ = "contacts"

    id: str = Field(default_factory=_uuid, primary_key=True)
    company_id: str = Field(index=True, foreign_key="companies.id")
    full_name: str
    title: str | None = None
    seniority: Seniority = Seniority.OTHER
    linkedin_url: str | None = None
    sales_nav_url: str | None = None
    email: str | None = None
    provider: str = "unknown"
    confidence: float = 0.0
    status: RecordStatus = RecordStatus.COMPLETE
    sources: list[dict] = Field(default_factory=list, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class OutreachDraft(SQLModel, table=True):
    __tablename__ = "outreach_drafts"

    id: str = Field(default_factory=_uuid, primary_key=True)
    contact_id: str = Field(index=True, foreign_key="contacts.id")
    company_id: str = Field(index=True, foreign_key="companies.id")
    subject: str
    body: str = Field(sa_column=Column(Text))
    edited_body: str | None = Field(default=None, sa_column=Column(Text))
    hook_fact: str | None = Field(default=None, sa_column=Column(Text))
    hook_source_url: str | None = None
    tedlar_value_prop: str | None = None
    approved: bool = False
    generator: str = "llm"  # llm | template_fallback
    status: RecordStatus = RecordStatus.COMPLETE
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
