"""Dashboard API.

Read endpoints assemble the lead view once and serve it filtered; the single
write endpoint is outreach edit/approve, because that is the only thing a rep
changes. Pipeline runs are kicked off in a background task and polled -- adequate
for a single-operator tool, and the obvious seam if this ever needs a real queue.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlmodel import Session, func, select

from ..config import get_settings
from ..db import get_session
from ..models.domain import Company, Contact, Event, OutreachDraft, Qualification, utcnow
from ..models.enums import STAGE_ORDER, PipelineMode, RunStatus, StageName, Tier
from ..models.errors import PipelineRun, StageError
from ..pipeline.runner import PipelineRunner, _parse_stages
from .schemas import (
    ContactOut,
    EventOut,
    LeadOut,
    OutreachOut,
    OutreachPatch,
    RunOut,
    RunRequest,
    StageErrorOut,
    SummaryOut,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


@router.get("/health")
def health() -> dict:
    settings = get_settings()
    return {
        "status": "ok",
        "llm_enabled": settings.llm_enabled,
        "search_provider": settings.search_provider,
        "contact_providers": settings.contact_provider_chain,
    }


@router.get("/summary", response_model=SummaryOut)
def summary(session: Session = Depends(get_session)) -> SummaryOut:
    settings = get_settings()
    last_run = session.exec(
        select(PipelineRun).order_by(PipelineRun.started_at.desc())
    ).first()
    qualified = session.exec(
        select(func.count()).select_from(Qualification).where(
            Qualification.tier.in_([Tier.A, Tier.B])
        )
    ).one()
    # Errors are scoped to the most recent run, like every other metric here.
    # Summing them across all runs makes a clean re-run look like a worse one.
    errors = (
        session.exec(
            select(func.count()).select_from(StageError).where(
                StageError.run_id == last_run.id
            )
        ).one()
        if last_run
        else 0
    )
    counts = (last_run.counts or {}) if last_run else {}
    llm_calls = int(counts.get("llm_calls", 0) or 0)
    llm_usd = float(counts.get("llm_estimated_usd", 0.0) or 0.0)
    # The number a GTM team actually budgets against.
    cost_per_lead = round(llm_usd / qualified, 4) if (qualified and llm_usd) else None

    return SummaryOut(
        events=_count(session, Event),
        companies=_count(session, Company),
        companies_enriched=session.exec(
            select(func.count()).select_from(Company).where(Company.enriched == True)  # noqa: E712
        ).one(),
        qualified_leads=qualified,
        contacts=_count(session, Contact),
        outreach_drafts=_count(session, OutreachDraft),
        errors=errors,
        last_run_at=last_run.finished_at or last_run.started_at if last_run else None,
        last_run_id=last_run.id if last_run else None,
        last_run_mode=last_run.mode.value if last_run else None,
        llm_calls=llm_calls,
        llm_estimated_usd=round(llm_usd, 4),
        cost_per_qualified_lead=cost_per_lead,
        llm_enabled=settings.llm_enabled,
        search_provider=settings.search_provider,
        contact_providers=settings.contact_provider_chain,
    )


@router.get("/events", response_model=list[EventOut])
def list_events(session: Session = Depends(get_session)) -> list[EventOut]:
    companies = session.exec(select(Company)).all()
    counts: dict[str, int] = {}
    for company in companies:
        for event_id in company.event_ids or []:
            counts[event_id] = counts.get(event_id, 0) + 1
    events = session.exec(select(Event)).all()
    return [_event_out(e, counts.get(e.id, 0)) for e in _sorted_events(events)]


@router.get("/leads", response_model=list[LeadOut])
def list_leads(
    session: Session = Depends(get_session),
    tier: list[Tier] | None = Query(default=None),
    event_id: str | None = None,
    min_score: float = 0.0,
    industry: str | None = None,
    q: str | None = None,
    has_contact: bool | None = None,
    limit: int = 250,
) -> list[LeadOut]:
    leads = _build_leads(session)
    needle = (q or "").lower().strip()

    def keep(lead: LeadOut) -> bool:
        if tier and lead.tier not in tier:
            return False
        if lead.score_total < min_score:
            return False
        if event_id and not any(e.id == event_id for e in lead.events):
            return False
        if industry and industry.lower() not in (lead.industry or "").lower():
            return False
        if has_contact is not None and bool(lead.contacts) is not has_contact:
            return False
        if needle:
            haystack = " ".join(
                [lead.company_name, lead.industry or "", lead.description or "",
                 " ".join(lead.sub_industries), " ".join(lead.products)]
            ).lower()
            if needle not in haystack:
                return False
        return True

    return [lead for lead in leads if keep(lead)][:limit]


@router.get("/leads/{company_id}", response_model=LeadOut)
def get_lead(company_id: str, session: Session = Depends(get_session)) -> LeadOut:
    for lead in _build_leads(session):
        if lead.company_id == company_id:
            return lead
    raise HTTPException(status_code=404, detail="lead not found")


@router.patch("/outreach/{draft_id}", response_model=OutreachOut)
def patch_outreach(
    draft_id: str, patch: OutreachPatch, session: Session = Depends(get_session)
) -> OutreachOut:
    draft = session.get(OutreachDraft, draft_id)
    if draft is None:
        raise HTTPException(status_code=404, detail="draft not found")
    if patch.edited_body is not None:
        draft.edited_body = patch.edited_body
    if patch.approved is not None:
        draft.approved = patch.approved
    draft.updated_at = utcnow()
    session.add(draft)
    session.commit()
    session.refresh(draft)
    return _outreach_out(draft)


@router.get("/errors", response_model=list[StageErrorOut])
def list_errors(
    session: Session = Depends(get_session),
    run_id: str | None = None,
    stage: StageName | None = None,
    limit: int = 200,
) -> list[StageErrorOut]:
    """Defaults to the latest run. Pass `run_id=all` for the full history."""
    statement = select(StageError).order_by(StageError.created_at.desc()).limit(limit)
    if run_id is None:
        latest = session.exec(
            select(PipelineRun).order_by(PipelineRun.started_at.desc())
        ).first()
        if latest is None:
            return []
        statement = statement.where(StageError.run_id == latest.id)
    elif run_id != "all":
        statement = statement.where(StageError.run_id == run_id)
    if stage:
        statement = statement.where(StageError.stage == stage)
    return [StageErrorOut(**e.model_dump() | {"stage": e.stage.value}) for e in
            session.exec(statement).all()]


@router.get("/runs", response_model=list[RunOut])
def list_runs(session: Session = Depends(get_session), limit: int = 20) -> list[RunOut]:
    runs = session.exec(
        select(PipelineRun).order_by(PipelineRun.started_at.desc()).limit(limit)
    ).all()
    return [_run_out(r) for r in runs]


@router.get("/runs/{run_id}", response_model=RunOut)
def get_run(run_id: str, session: Session = Depends(get_session)) -> RunOut:
    run = session.get(PipelineRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    return _run_out(run)


@router.post("/pipeline/run", response_model=RunOut)
def start_run(
    request: RunRequest,
    background: BackgroundTasks,
    session: Session = Depends(get_session),
) -> RunOut:
    """Reject a second concurrent run, then start one in the background."""
    active = session.exec(
        select(PipelineRun).where(PipelineRun.status == RunStatus.RUNNING)
    ).first()
    if active is not None and _is_recent(active.started_at):
        raise HTTPException(status_code=409, detail=f"run {active.id} is already in progress")

    try:
        mode = PipelineMode(request.mode)
        _parse_stages(request.stages)  # validated here so a bad value 422s, not 500s
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    stage_list = _parse_stages(request.stages) or list(STAGE_ORDER)
    run = PipelineRun(
        mode=mode,
        status=RunStatus.RUNNING,
        stage_states={s.value: "pending" for s in stage_list},
    )
    session.add(run)
    session.commit()
    session.refresh(run)

    background.add_task(_execute_run, run.id, mode, request.limit, request.stages)
    return _run_out(run)


def _execute_run(
    run_id: str, mode: PipelineMode, limit: int | None, stages: str | None
) -> None:
    """Background entrypoint.

    The runner writes progress into the row we just handed the client, so polling
    `/api/runs/{id}` shows stages advancing rather than flipping at the end.
    """
    from ..db import get_engine, session_scope

    try:
        runner = PipelineRunner(
            mode=mode, limit=limit, stages=_parse_stages(stages), run_id=run_id
        )
        asyncio.run(runner.run())
    except Exception as exc:  # noqa: BLE001 -- a failed run must be visible, not silent
        logger.exception("pipeline run failed")
        with session_scope(get_engine()) as session:
            run = session.get(PipelineRun, run_id)
            if run is not None:
                run.status = RunStatus.FAILED
                run.finished_at = utcnow()
                run.counts = {**(run.counts or {}), "error": str(exc)[:200]}
                session.add(run)


# ---------------------------------------------------------------------------
# assembly helpers
# ---------------------------------------------------------------------------


def _build_leads(session: Session) -> list[LeadOut]:
    companies = session.exec(select(Company)).all()
    qualifications = {q.company_id: q for q in session.exec(select(Qualification)).all()}
    events = {e.id: e for e in session.exec(select(Event)).all()}

    contacts_by_company: dict[str, list[Contact]] = {}
    for contact in session.exec(select(Contact)).all():
        contacts_by_company.setdefault(contact.company_id, []).append(contact)

    drafts_by_contact: dict[str, list[OutreachDraft]] = {}
    for draft in session.exec(select(OutreachDraft)).all():
        drafts_by_contact.setdefault(draft.contact_id, []).append(draft)

    leads: list[LeadOut] = []
    for company in companies:
        qualification = qualifications.get(company.id)
        company_contacts = contacts_by_company.get(company.id, [])
        leads.append(
            LeadOut(
                company_id=company.id,
                company_name=company.name,
                website=company.website,
                domain=company.domain,
                industry=company.industry,
                sub_industries=company.sub_industries or [],
                products=company.products or [],
                description=company.description,
                hq_location=company.hq_location,
                revenue_band=company.revenue_band,
                revenue_est_usd=company.revenue_est_usd,
                employee_band=company.employee_band,
                employee_count_est=company.employee_count_est,
                enriched=company.enriched,
                status=company.status.value,
                score_total=qualification.score_total if qualification else 0.0,
                score=qualification.score if qualification else {},
                tier=qualification.tier if qualification else Tier.DISQUALIFIED,
                confidence=qualification.confidence if qualification else 0.0,
                rationale=qualification.rationale if qualification else None,
                rationale_source=(
                    qualification.rationale_source if qualification else "deterministic"
                ),
                evidence=qualification.evidence if qualification else [],
                flags=qualification.flags if qualification else [],
                events=[
                    _event_out(events[e], 0)
                    for e in (company.event_ids or [])
                    if e in events
                ],
                contacts=[_contact_out(c) for c in company_contacts],
                outreach=[
                    _outreach_out(d)
                    for c in company_contacts
                    for d in drafts_by_contact.get(c.id, [])
                ],
                sources=company.sources or [],
            )
        )
    leads.sort(key=lambda lead: (-lead.score_total, lead.company_name.lower()))
    return leads


def _sorted_events(events) -> list[Event]:
    return sorted(events, key=lambda e: (not e.tier1, e.event_type.value, e.name.lower()))


def _event_out(event: Event, company_count: int) -> EventOut:
    return EventOut(
        id=event.id,
        slug=event.slug,
        name=event.name,
        url=event.url,
        event_type=event.event_type.value,
        organizer=event.organizer,
        city=event.city,
        country=event.country,
        tier1=event.tier1,
        relevance_note=event.relevance_note,
        status=event.status.value,
        company_count=company_count,
        sources=event.sources or [],
    )


def _contact_out(contact: Contact) -> ContactOut:
    return ContactOut(
        id=contact.id,
        full_name=contact.full_name,
        title=contact.title,
        seniority=contact.seniority.value,
        linkedin_url=contact.linkedin_url,
        sales_nav_url=contact.sales_nav_url,
        email=contact.email,
        provider=contact.provider,
        confidence=contact.confidence,
        sources=contact.sources or [],
    )


def _outreach_out(draft: OutreachDraft) -> OutreachOut:
    return OutreachOut(
        id=draft.id,
        contact_id=draft.contact_id,
        subject=draft.subject,
        body=draft.body,
        edited_body=draft.edited_body,
        hook_fact=draft.hook_fact,
        hook_source_url=draft.hook_source_url,
        tedlar_value_prop=draft.tedlar_value_prop,
        approved=draft.approved,
        generator=draft.generator,
    )


def _run_out(run: PipelineRun) -> RunOut:
    return RunOut(
        id=run.id,
        mode=run.mode.value,
        status=run.status,
        current_stage=run.current_stage.value if run.current_stage else None,
        stage_states=run.stage_states or {},
        counts=run.counts or {},
        error_count=run.error_count,
        started_at=run.started_at,
        finished_at=run.finished_at,
    )


def _count(session: Session, model) -> int:
    return session.exec(select(func.count()).select_from(model)).one()


def _is_recent(started_at: datetime, max_age_s: float = 1800.0) -> bool:
    """A 'running' row older than this is a crashed run, not a live one."""
    reference = utcnow()
    if started_at.tzinfo is None:
        reference = reference.replace(tzinfo=None)
    return (reference - started_at).total_seconds() < max_age_s
