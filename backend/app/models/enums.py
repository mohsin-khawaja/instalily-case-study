"""Closed vocabularies used across the pipeline."""

from enum import StrEnum


class RecordStatus(StrEnum):
    """Per-record completeness. A stage failure degrades, it never deletes."""

    COMPLETE = "complete"
    INCOMPLETE = "incomplete"
    FAILED = "failed"


class EventType(StrEnum):
    TRADE_SHOW = "trade_show"
    ASSOCIATION = "association"
    CONFERENCE = "conference"


class Tier(StrEnum):
    A = "A"
    B = "B"
    C = "C"
    DISQUALIFIED = "disqualified"


class StageName(StrEnum):
    DISCOVER_EVENTS = "discover_events"
    EXTRACT_COMPANIES = "extract_companies"
    ENRICH_COMPANIES = "enrich_companies"
    QUALIFY = "qualify"
    FIND_CONTACTS = "find_contacts"
    DRAFT_OUTREACH = "draft_outreach"


STAGE_ORDER: list[StageName] = [
    StageName.DISCOVER_EVENTS,
    StageName.EXTRACT_COMPANIES,
    StageName.ENRICH_COMPANIES,
    StageName.QUALIFY,
    StageName.FIND_CONTACTS,
    StageName.DRAFT_OUTREACH,
]


class RunStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"


class PipelineMode(StrEnum):
    CACHED = "cached"
    LIVE = "live"


class Seniority(StrEnum):
    C_LEVEL = "c_level"
    VP = "vp"
    DIRECTOR = "director"
    MANAGER = "manager"
    OTHER = "other"
