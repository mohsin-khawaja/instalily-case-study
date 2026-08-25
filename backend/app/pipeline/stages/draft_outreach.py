"""Stage 7 -- outreach drafting.

The model gets only facts the pipeline already verified, plus the evidence URLs
those facts came from. `_validate` then enforces the contract: the hook must cite
an evidence URL we supplied, the body must stay short, and banned filler phrasing
is rejected. A draft that fails twice falls back to a template built from the
same verified facts -- a rep always gets something sendable, and it is labelled
so they know which is which.
"""

from __future__ import annotations

import logging

from pydantic import BaseModel, Field
from sqlmodel import select

from ...models.domain import Company, Contact, OutreachDraft, Qualification, utcnow
from ...models.enums import RecordStatus, StageName, Tier
from ...scoring import icp
from ...services.llm.prompts import OUTREACH_SYSTEM, outreach_prompt
from ..context import RunContext

logger = logging.getLogger(__name__)

STAGE = StageName.DRAFT_OUTREACH
MAX_BODY_WORDS = 130
MAX_SUBJECT_WORDS = 10

BANNED_PHRASES = (
    "hope this finds you well",
    "quick question",
    "circle back",
    "touch base",
    "game changer",
    "revolutionary",
    "world-class",
    "synergy",
    "reaching out to see if",
    "i wanted to reach out",
)


class OutreachOut(BaseModel):
    subject: str = Field(description="At most 8 words")
    body: str = Field(description="At most 110 words")
    hook_fact: str = Field(description="The one company-specific fact you opened with")
    hook_source_url: str = Field(description="Must be one of the supplied evidence URLs")
    tedlar_value_prop: str = Field(description="The single value proposition you used")


class OutreachRejected(ValueError):
    """The draft violated the evidence or style contract."""


async def run(ctx: RunContext, contacts: list[Contact]) -> list[OutreachDraft]:
    companies = {c.id: c for c in ctx.session.exec(select(Company)).all()}
    qualifications = {
        q.company_id: q for q in ctx.session.exec(select(Qualification)).all()
    }
    already = {
        d.contact_id for d in ctx.session.exec(select(OutreachDraft)).all()
    }

    out: list[OutreachDraft] = []
    for contact in contacts:
        if contact.id in already:
            continue
        company = companies.get(contact.company_id)
        qualification = qualifications.get(contact.company_id)
        if company is None or qualification is None:
            continue
        if qualification.tier not in (Tier.A, Tier.B):
            continue

        draft = await _draft_one(ctx, contact, company, qualification)
        if draft is None:
            continue
        ctx.session.add(draft)
        out.append(draft)

    ctx.session.commit()
    ctx.bump("outreach_drafts", len(out))
    return out


async def _draft_one(
    ctx: RunContext, contact: Contact, company: Company, qualification: Qualification
) -> OutreachDraft | None:
    evidence = [e for e in (qualification.evidence or []) if e.get("source_url")]
    if not evidence:
        ctx.record_error(
            STAGE,
            ValueError("no evidence available; refusing to draft an ungrounded email"),
            entity_type="contact",
            entity_ref=f"{contact.full_name} @ {company.name}",
        )
        return None

    allowed_urls = {e["source_url"] for e in evidence}
    value_props = _value_props_for(qualification)

    generated = None
    if ctx.llm.enabled:
        generated = await ctx.attempt(
            STAGE,
            lambda: _generate(ctx, contact, company, evidence, value_props, allowed_urls),
            entity_type="outreach",
            entity_ref=f"{contact.full_name} @ {company.name}",
            default=None,
        )

    if generated is None:
        subject, body, hook, hook_url, prop = _template_draft(
            contact, company, evidence, value_props
        )
        generator = "template_fallback"
    else:
        subject, body = generated.subject, generated.body
        hook, hook_url, prop = (
            generated.hook_fact,
            generated.hook_source_url,
            generated.tedlar_value_prop,
        )
        generator = "llm"

    return OutreachDraft(
        contact_id=contact.id,
        company_id=company.id,
        subject=subject,
        body=body,
        hook_fact=hook,
        hook_source_url=hook_url,
        tedlar_value_prop=prop,
        generator=generator,
        status=RecordStatus.COMPLETE if generator == "llm" else RecordStatus.INCOMPLETE,
        created_at=utcnow(),
        updated_at=utcnow(),
    )


async def _generate(
    ctx: RunContext,
    contact: Contact,
    company: Company,
    evidence: list[dict],
    value_props: dict[str, str],
    allowed_urls: set[str],
) -> OutreachOut:
    prompt = outreach_prompt(
        contact_name=contact.full_name,
        contact_title=contact.title or "",
        company_name=company.name,
        facts=_facts(company),
        evidence_block="\n".join(f"- {e['claim']} -> {e['source_url']}" for e in evidence),
        value_props="\n".join(f"- {k}: {v}" for k, v in value_props.items()),
    )
    result = await ctx.llm.structured(
        OutreachOut, prompt=prompt, system=OUTREACH_SYSTEM, model=ctx.llm.model_reasoning
    )
    validate(result, allowed_urls)
    return result


def validate(draft: OutreachOut, allowed_urls: set[str]) -> None:
    """Raise `OutreachRejected` unless the draft honours the evidence contract."""
    if draft.hook_source_url not in allowed_urls:
        raise OutreachRejected(
            f"hook_source_url {draft.hook_source_url!r} is not in the supplied evidence"
        )
    body_words = len(draft.body.split())
    if body_words > MAX_BODY_WORDS:
        raise OutreachRejected(f"body is {body_words} words (max {MAX_BODY_WORDS})")
    if not draft.body.strip():
        raise OutreachRejected("empty body")
    if len(draft.subject.split()) > MAX_SUBJECT_WORDS:
        raise OutreachRejected(f"subject is longer than {MAX_SUBJECT_WORDS} words")
    lowered = f"{draft.subject}\n{draft.body}".lower()
    hit = next((p for p in BANNED_PHRASES if p in lowered), None)
    if hit:
        raise OutreachRejected(f"contains banned filler phrase {hit!r}")


def _value_props_for(qualification: Qualification) -> dict[str, str]:
    """Prefer the themes the company already markets on; fall back to the full list."""
    claims = " ".join(e.get("claim", "") for e in (qualification.evidence or [])).lower()
    matched = {k: v for k, v in icp.TEDLAR_VALUE_PROPS.items() if k in claims}
    return matched or icp.TEDLAR_VALUE_PROPS


def _facts(company: Company) -> str:
    return "\n".join(
        [
            f"- industry: {company.industry or 'unknown'}",
            f"- products: {', '.join(company.products) or 'unknown'}",
            f"- size: {company.revenue_band or company.employee_band or 'unknown'}",
            f"- description: {company.description or 'unknown'}",
        ]
    )


# Claims that read as a predicate, so "<Company> <claim>" is a sentence.
# "Estimated revenue $250M-$1B" is a fact but not a predicate, so it is a last resort.
_PREDICATE_OPENERS = ("operates", "serves", "markets", "listed", "exhibits", "supplies")


def _pick_hook(evidence: list[dict]) -> dict:
    for item in evidence:
        if item.get("claim", "").lower().startswith(_PREDICATE_OPENERS):
            return item
    return evidence[0]


def _template_draft(
    contact: Contact, company: Company, evidence: list[dict], value_props: dict[str, str]
) -> tuple[str, str, str, str, str]:
    """Deterministic fallback assembled only from verified evidence."""
    top = _pick_hook(evidence)
    prop_name, prop_text = next(iter(value_props.items()))
    first_name = contact.full_name.split()[0]
    subject = f"Tedlar films for {company.name} outdoor graphics"[:80]
    claim = top["claim"]
    body = (
        f"Hi {first_name},\n\n"
        f"I saw that {company.name} {claim[0].lower() + claim[1:]}. "
        f"That is where DuPont Tedlar tends to matter: {prop_text}\n\n"
        f"If durability in the field is on your roadmap, I can send the outdoor "
        f"weathering data and a sample set — no meeting needed unless it is useful.\n\n"
        f"Would a 15-minute call in the next couple of weeks be worth your time?"
    )
    return subject, body, top["claim"], top["source_url"], prop_name
