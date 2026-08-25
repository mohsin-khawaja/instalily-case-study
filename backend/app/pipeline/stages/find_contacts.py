"""Stage 6 -- decision-maker identification.

Only qualified leads (tier A/B) get contact work: contact data is the expensive
part of the funnel and spending it on a tier-C company is the whole reason
qualification runs first. Providers are tried in configured order and the first
one to return anything wins; a company nobody can resolve is recorded as a miss,
not dropped.
"""

from __future__ import annotations

import logging

from sqlmodel import select

from ...integrations.contacts import build_contact_chain
from ...models.domain import Company, Contact, Qualification
from ...models.enums import StageName, Tier
from ...scoring import icp
from ..context import RunContext

logger = logging.getLogger(__name__)

STAGE = StageName.FIND_CONTACTS
QUALIFIED_TIERS = (Tier.A, Tier.B)
CONTACTS_PER_COMPANY = 2


async def run(ctx: RunContext, qualifications: list[Qualification]) -> list[Contact]:
    providers = build_contact_chain(ctx.fetcher, ctx.search)
    if not providers:
        ctx.record_error(
            STAGE,
            ValueError("no contact provider is configured (see CONTACT_PROVIDERS)"),
            entity_type="contact_provider",
            entity_ref="chain",
        )
        return []
    logger.info("contact chain: %s", ", ".join(p.name for p in providers))

    qualified = [q for q in qualifications if q.tier in QUALIFIED_TIERS]
    companies = {
        c.id: c for c in ctx.session.exec(select(Company)).all()
    }
    existing_names = {
        (c.company_id, c.full_name.lower())
        for c in ctx.session.exec(select(Contact)).all()
    }

    out: list[Contact] = []
    for qualification in qualified:
        company = companies.get(qualification.company_id)
        if company is None:
            continue
        contacts = await _find_for_company(ctx, providers, company)
        if not contacts:
            ctx.record_error(
                STAGE,
                ValueError("no decision-maker could be identified from public sources"),
                entity_type="company",
                entity_ref=company.name,
            )
            continue
        for contact in contacts:
            key = (contact.company_id, contact.full_name.lower())
            if key in existing_names:
                continue
            existing_names.add(key)
            ctx.session.add(contact)
            out.append(contact)

    ctx.session.commit()
    ctx.bump("contacts", len(out))
    ctx.bump("companies_with_contacts", len({c.company_id for c in out}))
    return out


async def _find_for_company(ctx: RunContext, providers, company: Company) -> list[Contact]:
    for provider in providers:
        contacts = await ctx.attempt(
            STAGE,
            lambda p=provider: p.find_contacts(
                company, icp.TARGET_TITLES, limit=CONTACTS_PER_COMPANY
            ),
            entity_type="contact_lookup",
            entity_ref=f"{company.name} via {provider.name}",
            default=[],
        ) or []
        if contacts:
            return contacts
    return []
