"""Stage 2 -- company sourcing, and Stage 3 -- dedupe/normalise.

Two independent channels feed the candidate pool, because in practice exactly one
of them works on any given directory:

* `_from_directories` scrapes an event's exhibitor page for outbound company
  links. Works on plain HTML directories; a JS-rendered one (MapYourShow) yields
  nothing and records the miss instead of pretending.
* `_from_search` runs ICP-shaped queries through the configured SearchProvider.
  This is the channel that scales -- new vertical, new query templates.

Both channels emit the same loose `{name, website, event_ids, sources}` dict, and
everything funnels through `dedupe_companies` before a row is written.
"""

from __future__ import annotations

import logging
from urllib.parse import urlparse

from sqlmodel import select

from ...models.domain import Company, Event, SourceRef, utcnow
from ...models.enums import RecordStatus, StageName
from ...scoring import icp
from ...services.dedupe import canonical_domain, dedupe_companies, normalize_name
from ...services.extract import external_links
from ..context import RunContext
from .icp_roster import roster_candidates

logger = logging.getLogger(__name__)

STAGE = StageName.EXTRACT_COMPANIES

# Hosts that appear on every exhibitor page and are never the exhibitor.
_LINK_BLOCKLIST = (
    # Social, platforms, event plumbing
    "facebook.", "twitter.", "x.com", "linkedin.", "instagram.", "youtube.", "tiktok.",
    "pinterest.", "reddit.", "google.", "apple.com", "microsoft.com", "adobe.com",
    "mapyourshow.com", "onpeak.com", "eventbrite.", "cvent.com",
    "safelinks.protection.outlook.com", "wikipedia.org", "share.google", "napco.com",
    "gov", "hotels.com", "marriott.com", "hilton.com",
    # Marketplaces and general retail. A better search provider surfaces these
    # for any product query; none of them is a Tedlar prospect.
    "ebay.", "amazon.", "alibaba.", "aliexpress.", "walmart.", "etsy.", "temu.",
    "wayfair.", "homedepot.", "lowes.", "target.com", "costco.", "wish.com",
    "indiamart.", "made-in-china.com", "dhgate.",
    # Directories, review sites and job boards
    "yelp.", "glassdoor.", "indeed.", "crunchbase.com", "zoominfo.com", "dnb.com",
    "bloomberg.com", "yellowpages.", "manta.com", "trustpilot.",
)
_MIN_NAME_LEN = 3
_MAX_NAME_LEN = 90

# Query templates -- {event} is substituted per event. These encode the ICP, so
# retargeting the pipeline is a config change.
COMPANY_QUERY_TEMPLATES = [
    '"{event}" exhibitor graphic films manufacturer',
    '"{event}" exhibitor vehicle wrap vinyl supplier',
    '"{event}" exhibitor wide format laminating film',
]
STANDALONE_QUERIES = [
    "self-adhesive vinyl graphic film manufacturer outdoor signage",
    "vehicle wrap film manufacturer cast vinyl overlaminate",
    "architectural graphics film manufacturer UV resistant",
    "large format print media manufacturer protective laminate",
    "overlaminate film supplier for printed signage graphics",
    "cast vinyl film manufacturer fleet and transit graphics",
    "digital print media manufacturer banner and billboard substrate",
    "graphic films division manufacturer signage materials company",
    "sign supply distributor wide format media and laminates",
    "weather resistant printable film manufacturer outdoor durability",
]


async def run(ctx: RunContext, events: list[Event]) -> list[Company]:
    # The shows themselves are not prospects: their own domains must never enter
    # the company pool, however often they turn up in ICP-shaped search results.
    ctx.event_hosts = {
        h for h in (canonical_domain(e.url) for e in events) if h
    } | {
        h for h in (canonical_domain(e.exhibitor_list_url) for e in events) if h
    }

    # Roster first: dedupe keeps the first name it sees for a domain, and a
    # curated "Avery Dennison Graphics Solutions" beats a search result's
    # domain-derived "Averydennison".
    roster = roster_candidates()
    ctx.bump("roster_candidates", len(roster))

    candidates: list[dict] = list(roster)
    candidates.extend(await _from_directories(ctx, events))
    candidates.extend(await _from_search(ctx, events))

    ctx.bump("company_candidates", len(candidates))
    deduped = dedupe_companies(candidates)
    ctx.bump("companies_after_dedupe", len(deduped))
    logger.info("company candidates: %d raw -> %d deduped", len(candidates), len(deduped))

    companies = _persist(ctx, deduped)
    ctx.session.commit()
    ctx.bump("companies", len(companies))
    return companies


# ---------------------------------------------------------------------------
# Channel 1: exhibitor directory scrape
# ---------------------------------------------------------------------------


async def _from_directories(ctx: RunContext, events: list[Event]) -> list[dict]:
    out: list[dict] = []
    for event in events:
        url = event.exhibitor_list_url
        if not url:
            continue
        response = await ctx.attempt(
            STAGE,
            lambda u=url: ctx.fetcher.fetch(u),
            entity_type="exhibitor_directory",
            entity_ref=f"{event.slug} <{url}>",
            default=None,
        )
        if response is None:
            continue

        rows = [
            {
                "name": _directory_name(text, link),
                "website": link,
                "event_ids": [event.id],
                "sources": [
                    SourceRef(url=url, title=f"{event.name} exhibitor directory",
                              fetched_at=response.fetched_at).model_dump(mode="json")
                ],
            }
            for link, text in external_links(response.text, url)
            if _plausible_exhibitor(link, text, ctx.event_hosts)
        ]
        if not rows:
            # A directory that yields nothing is a finding, not a silent no-op.
            ctx.record_error(
                STAGE,
                ValueError("directory returned no exhibitor links (likely JS-rendered)"),
                entity_type="exhibitor_directory",
                entity_ref=f"{event.slug} <{url}>",
            )
        out.extend(rows)
    ctx.bump("directory_candidates", len(out))
    return out


def _plausible_exhibitor(link: str, text: str, event_hosts: set[str]) -> bool:
    host = (urlparse(link).hostname or "").lower()
    if not host or any(bad in host for bad in _LINK_BLOCKLIST):
        return False
    if canonical_domain(host) in event_hosts:
        return False
    name = _clean_name(text)
    return _MIN_NAME_LEN <= len(name) <= _MAX_NAME_LEN


def _directory_name(anchor_text: str, link: str) -> str:
    """Exhibitor anchors are usually the company name; anything odd falls back to domain."""
    name = _clean_name(anchor_text)
    words = name.split()
    if _MIN_NAME_LEN <= len(name) <= 60 and len(words) <= 6:
        return name
    return _domain_label(urlparse(link).hostname or "") or name


def _clean_name(text: str) -> str:
    return " ".join((text or "").split())[:_MAX_NAME_LEN]


# ---------------------------------------------------------------------------
# Channel 2: ICP-shaped search
# ---------------------------------------------------------------------------


async def _from_search(ctx: RunContext, events: list[Event]) -> list[dict]:
    if not ctx.search.is_configured():
        ctx.record_error(
            STAGE,
            ValueError(f"search provider '{ctx.search.name}' is not configured; "
                       "set SERPER_API_KEY or TAVILY_API_KEY to enable search discovery"),
            entity_type="search_provider",
            entity_ref=ctx.search.name,
        )
        return []

    queries: list[tuple[str, list[str]]] = [(q, []) for q in STANDALONE_QUERIES]
    for event in events:
        if event.status is not RecordStatus.COMPLETE and not event.exhibitor_list_url:
            continue
        for template in COMPANY_QUERY_TEMPLATES:
            queries.append((template.format(event=event.name), [event.id]))

    out: list[dict] = []
    for query, event_ids in queries:
        results = await ctx.attempt(
            STAGE,
            lambda q=query: ctx.search.search(q, limit=8),
            entity_type="search_query",
            entity_ref=query,
            default=[],
        ) or []
        for result in results:
            host = (urlparse(result.url).hostname or "").lower()
            if not host or any(bad in host for bad in _LINK_BLOCKLIST):
                continue
            if canonical_domain(host) in ctx.event_hosts:
                continue
            name = _name_from_result(result.title, host)
            if not name:
                continue
            out.append(
                {
                    "name": name,
                    "website": f"https://{host}/",
                    "event_ids": list(event_ids),
                    "sources": [
                        SourceRef(url=result.url, title=result.title,
                                  snippet=result.snippet[:300] or None).model_dump(mode="json")
                    ],
                }
            )
    ctx.bump("search_candidates", len(out))
    return out


def _name_from_result(title: str, host: str) -> str:
    """Name the company after its domain, not the page title.

    Search results land on product pages ("Overlaminate Cast Vinyl | Acme"), so a
    title-derived name produces one bogus "company" per page. The registrable
    domain is the stable identity; enrichment later upgrades the display name from
    the site's own og:site_name or the extracted profile.
    """
    label = _domain_label(host)
    if label:
        return label
    head = title.split("|")[0].split(" - ")[0].split("–")[0]
    name = _clean_name(head)
    return name if _MIN_NAME_LEN <= len(name) <= _MAX_NAME_LEN else ""


def _domain_label(host: str) -> str:
    """averydennison.com -> 'Averydennison'; hexis-graphics.com -> 'Hexis Graphics'."""
    label = canonical_domain(host) or host
    label = label.removeprefix("www.").split(".")[0]
    if len(label) < _MIN_NAME_LEN:
        return ""
    return " ".join(part.capitalize() for part in label.replace("_", "-").split("-"))


# ---------------------------------------------------------------------------
# Stage 3: persist deduped records
# ---------------------------------------------------------------------------


def _persist(ctx: RunContext, records: list[dict]) -> list[Company]:
    by_domain = {
        c.domain: c for c in ctx.session.exec(select(Company)).all() if c.domain
    }
    by_name = {c.canonical_name: c for c in ctx.session.exec(select(Company)).all()}

    companies: list[Company] = []
    for record in records:
        name = record.get("name") or ""
        website = record.get("website")
        domain = canonical_domain(website)
        canonical = normalize_name(name)
        if not canonical and not domain:
            continue

        company = (by_domain.get(domain) if domain else None) or by_name.get(canonical)
        if company is None:
            company = Company(name=name, canonical_name=canonical, domain=domain,
                              website=website, status=RecordStatus.INCOMPLETE)
        else:
            company.domain = company.domain or domain
            company.website = company.website or website

        company.event_ids = _union(company.event_ids, record.get("event_ids") or [])
        company.sources = _union(company.sources, record.get("sources") or [])
        company.updated_at = utcnow()
        ctx.session.add(company)

        if domain:
            by_domain[domain] = company
        by_name[canonical] = company
        companies.append(company)

    # `companies` may hold the same object twice when two records merged.
    unique: list[Company] = []
    for company in companies:
        if company not in unique:
            unique.append(company)
    return unique


async def link_companies_to_events(
    ctx: RunContext, companies: list[Company], events: list[Event]
) -> int:
    """Establish event engagement from two independent, verifiable directions.

    1. **First-party** -- the company's own site says it exhibits ("Visit us at
       PRINTING United, booth 4231"). We already fetched that text during
       enrichment, and the company asserting it is the strongest evidence there is.
    2. **Directory** -- the event's exhibitor list names the company. Works on
       plain-HTML directories; the flagship shows front their lists with a
       JavaScript app over an API that refuses server-side clients, so those
       record a miss instead of a link.

    Cached pages make a re-run free.
    """
    from .discover_events import EVENT_ALIASES

    linked = 0
    for event in events:
        terms = _match_terms(event, EVENT_ALIASES.get(event.slug, []))
        for company in companies:
            if event.id in (company.event_ids or []):
                continue
            haystack = _company_haystack(company)
            if not haystack:
                continue
            hit = next((term for term in terms if term in haystack), None)
            if not hit:
                continue
            _attach(
                company,
                event,
                url=company.website or event.url,
                title=f"{company.name} is associated with {event.name}",
            )
            linked += 1

        linked += await _link_via_directory(ctx, companies, event)

    ctx.session.commit()
    ctx.bump("event_links", linked)
    return linked


async def _link_via_directory(ctx: RunContext, companies: list[Company], event: Event) -> int:
    url = event.exhibitor_list_url
    if not url:
        return 0
    response = await ctx.attempt(
        STAGE,
        lambda u=url: ctx.fetcher.fetch(u),
        entity_type="event_directory_match",
        entity_ref=f"{event.slug} <{url}>",
        default=None,
    )
    if response is None:
        return 0

    haystack = response.text.lower()
    linked = 0
    for company in companies:
        if event.id in (company.event_ids or []):
            continue
        if not _mentioned(company, haystack):
            continue
        _attach(company, event, url=url, title=f"{event.name} exhibitor directory")
        linked += 1
    return linked


def _attach(company: Company, event: Event, *, url: str, title: str) -> None:
    company.event_ids = [*(company.event_ids or []), event.id]
    company.sources = _union(
        company.sources,
        [SourceRef(url=url, title=title).model_dump(mode="json")],
    )


def _company_haystack(company: Company) -> str:
    """Everything first-party we hold about a company, lowercased.

    The site text is the strongest signal, but the search snippets we already
    stored as sources often carry "exhibiting at ..." lines that the homepage
    does not -- and re-reading them costs nothing.
    """
    parts = [company.site_text or ""]
    for source in company.sources or []:
        if isinstance(source, dict):
            parts.append(source.get("snippet") or "")
            parts.append(source.get("title") or "")
    return " ".join(parts).lower()


def _match_terms(event: Event, aliases: list[str]) -> list[str]:
    """Curated aliases, floored at 4 characters.

    The full event name ("FESPA Global Print Expo 2026") almost never appears
    verbatim on a supplier's page, while the alias ("fespa") reliably does. The
    aliases are hand-picked to be unambiguous in this industry, which is what
    lets the floor sit this low -- a bare "isa" is deliberately not among them.
    """
    terms = {event.name.lower(), *(a.lower() for a in aliases)}
    return [t for t in terms if len(t) >= 4]


def _mentioned(company: Company, haystack: str) -> bool:
    """Domain match is unambiguous; name match needs to be long enough to mean it."""
    if company.domain and company.domain in haystack:
        return True
    name = (company.canonical_name or "").strip()
    return len(name) >= 6 and name in haystack


def _union(current: list, incoming: list) -> list:
    out = list(current or [])
    for item in incoming:
        if item not in out:
            out.append(item)
    return out


__all__ = ["COMPANY_QUERY_TEMPLATES", "STANDALONE_QUERIES", "run", "icp"]
