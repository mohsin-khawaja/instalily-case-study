"""API response shapes. Kept separate from the tables so the dashboard contract
is explicit and the join work happens once, in one place."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from ..models.enums import RunStatus, Tier


class SummaryOut(BaseModel):
    events: int
    companies: int
    companies_enriched: int
    qualified_leads: int
    contacts: int
    outreach_drafts: int
    errors: int
    last_run_at: datetime | None = None
    last_run_id: str | None = None
    last_run_mode: str | None = None
    llm_calls: int = 0
    llm_estimated_usd: float = 0.0
    cost_per_qualified_lead: float | None = None
    llm_enabled: bool = False
    search_provider: str = "duckduckgo"
    contact_providers: list[str] = []


class EventOut(BaseModel):
    id: str
    slug: str
    name: str
    url: str
    event_type: str
    organizer: str | None = None
    city: str | None = None
    country: str | None = None
    tier1: bool = False
    relevance_note: str | None = None
    status: str
    company_count: int = 0
    sources: list[dict] = []


class ContactOut(BaseModel):
    id: str
    full_name: str
    title: str | None = None
    seniority: str
    linkedin_url: str | None = None
    sales_nav_url: str | None = None
    email: str | None = None
    provider: str
    confidence: float
    sources: list[dict] = []


class OutreachOut(BaseModel):
    id: str
    contact_id: str
    subject: str
    body: str
    edited_body: str | None = None
    hook_fact: str | None = None
    hook_source_url: str | None = None
    tedlar_value_prop: str | None = None
    approved: bool
    generator: str


class LeadOut(BaseModel):
    """One row of the dashboard table: company + score + best contact + draft."""

    company_id: str
    company_name: str
    website: str | None = None
    domain: str | None = None
    industry: str | None = None
    sub_industries: list[str] = []
    products: list[str] = []
    description: str | None = None
    hq_location: str | None = None
    revenue_band: str | None = None
    revenue_est_usd: float | None = None
    employee_band: str | None = None
    employee_count_est: int | None = None
    enriched: bool = False
    status: str

    score_total: float = 0.0
    score: dict = {}
    tier: Tier = Tier.DISQUALIFIED
    confidence: float = 0.0
    rationale: str | None = None
    rationale_source: str = "deterministic"
    evidence: list[dict] = []
    flags: list[str] = []

    events: list[EventOut] = []
    contacts: list[ContactOut] = []
    outreach: list[OutreachOut] = []
    sources: list[dict] = []


class StageErrorOut(BaseModel):
    id: str
    run_id: str
    stage: str
    entity_type: str
    entity_ref: str | None = None
    error_type: str
    message: str
    retryable: bool
    created_at: datetime


class RunOut(BaseModel):
    id: str
    mode: str
    status: RunStatus
    current_stage: str | None = None
    stage_states: dict = {}
    counts: dict = {}
    error_count: int = 0
    started_at: datetime
    finished_at: datetime | None = None


class RunRequest(BaseModel):
    mode: str = "cached"
    limit: int | None = None
    stages: str | None = None


class OutreachPatch(BaseModel):
    edited_body: str | None = None
    approved: bool | None = None
