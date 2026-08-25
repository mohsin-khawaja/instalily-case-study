"""Stage 1 -- event & association discovery.

The industry's anchor institutions are a small, slow-moving set, so the seed
roster below is a curated *starting point*, not the answer: every entry is
fetched live, its title and text confirmed, and anything unreachable is kept but
marked `incomplete` with a StageError attached rather than silently dropped.

Search expansion then adds events we did not seed, which is where this scales --
point `EVENT_SEARCH_QUERIES` at a different vertical and the roster regrows.
"""

from __future__ import annotations

import logging
from datetime import date

from sqlmodel import select

from ...models.domain import Event, SourceRef, utcnow
from ...models.enums import EventType, RecordStatus, StageName
from ...services.dedupe import canonical_domain
from ...services.extract import html_to_text, page_title
from ..context import RunContext

logger = logging.getLogger(__name__)

STAGE = StageName.DISCOVER_EVENTS

# name, slug, url, exhibitor_list_url, type, tier1, city, country, dates, note
SEED_EVENTS: list[dict] = [
    {
        "slug": "isa-sign-expo-2026",
        "aliases": ["isa sign expo", "sign expo", "international sign expo"],
        "name": "ISA Sign Expo 2026",
        "url": "https://signexpo.org/",
        "exhibitor_list_url": "https://signexpo.org/exhibitors/",
        "event_type": EventType.TRADE_SHOW,
        "tier1": True,
        "organizer": "International Sign Association",
        "city": "Las Vegas",
        "country": "USA",
        "relevance_note": (
            "North America's flagship sign, graphics and visual communications show. "
            "Sign manufacturers, wrap shops and film converters -- Tedlar's direct "
            "overlaminate buyers -- exhibit and specify here."
        ),
    },
    {
        "slug": "printing-united-expo-2026",
        "aliases": ["printing united", "printing united expo"],
        "name": "PRINTING United Expo 2026",
        "url": "https://www.printingunited.com/",
        "exhibitor_list_url": "https://pru26.mapyourshow.com/8_0/explore/exhibitor-alphalist.cfm",
        "event_type": EventType.TRADE_SHOW,
        "tier1": True,
        "organizer": "PRINTING United Alliance",
        "city": "Orlando",
        "country": "USA",
        "relevance_note": (
            "Largest US printing trade show, with a dedicated wide-format and graphics "
            "floor. Wide-format printers are the converters that laminate Tedlar films "
            "onto printed graphics."
        ),
    },
    {
        "slug": "fespa-global-print-expo-2026",
        "aliases": ["fespa", "fespa global print expo"],
        "name": "FESPA Global Print Expo 2026",
        "url": "https://www.fespa.com/",
        "exhibitor_list_url": "https://www.fespa.com/en/events/fespa-global-print-expo",
        "event_type": EventType.TRADE_SHOW,
        "tier1": True,
        "organizer": "FESPA",
        "country": "Europe",
        "relevance_note": (
            "Europe's principal speciality print and signage exhibition; the main "
            "European route to vehicle-wrap and outdoor-graphics converters."
        ),
    },
    {
        "slug": "international-sign-association",
        "aliases": ["international sign association", "isa member"],
        "name": "International Sign Association (ISA)",
        "url": "https://signs.org/",
        "exhibitor_list_url": "https://signs.org/membership/member-directory/",
        "event_type": EventType.ASSOCIATION,
        "tier1": True,
        "organizer": "ISA",
        "country": "USA",
        "relevance_note": (
            "Trade body for the sign and graphics industry. Membership is a durable "
            "signal of category commitment between show cycles."
        ),
    },
    {
        "slug": "printing-united-alliance",
        "aliases": ["printing united alliance", "sgia", "specialty graphic imaging"],
        "name": "PRINTING United Alliance",
        "url": "https://www.printing.org/",
        "exhibitor_list_url": "https://www.printing.org/membership",
        "event_type": EventType.ASSOCIATION,
        "tier1": True,
        "organizer": "PRINTING United Alliance",
        "country": "USA",
        "relevance_note": (
            "Merged SGIA/PIA body covering speciality graphics printing; its members "
            "are the converters and print service providers Tedlar sells through."
        ),
    },
    {
        "slug": "oaaa-out-of-home-advertising-association",
        "aliases": ["oaaa", "out of home advertising association"],
        "name": "Out of Home Advertising Association of America (OAAA)",
        "url": "https://oaaa.org/",
        "exhibitor_list_url": "https://oaaa.org/membership/member-directory/",
        "event_type": EventType.ASSOCIATION,
        "tier1": False,
        "organizer": "OAAA",
        "country": "USA",
        "relevance_note": (
            "Billboard and transit-advertising owners -- the end customers whose "
            "outdoor inventory suffers the UV and weather damage Tedlar prevents."
        ),
    },
]

EVENT_SEARCH_QUERIES = [
    "signage industry trade show 2026 exhibitor list",
    "wide format printing trade show 2026 Europe",
    "vehicle wrap industry conference 2026",
    "outdoor advertising association members graphics",
]

# Search hits from these hosts are directories/news, not events.
_EVENT_URL_BLOCKLIST = ("wikipedia.org", "linkedin.com", "facebook.com", "youtube.com",
                        "reddit.com", "eventbrite.com", "10times.com", "tradefest.io")

# A search hit is only an event if it names itself as one. Without this the
# expansion channel imports every "Register" and "Creative Library" page it finds.
_EVENT_TITLE_WORDS = ("expo", "show", "fair", "conference", "summit", "festival",
                      "convention", "association", "congress", "forum", "symposium")
_EVENT_TITLE_REJECT = ("register", "login", "archive", "directory", "calendar",
                       "top ", "best ", "list", "guide", "blog", "news", "highlights",
                       "attendees", "information", "home", "about",
                       # Listicles name several shows and are not themselves events.
                       "to attend", "you should", "roundup", "round-up", "must-see",
                       "upcoming", "events in", "shows in")


async def run(ctx: RunContext) -> list[Event]:
    """Upsert seeded events (verified live) then append search-discovered ones."""
    events: list[Event] = []

    for seed in SEED_EVENTS:
        event = await _upsert_seed(ctx, seed)
        if event is not None:
            events.append(event)

    events.extend(await _discover_via_search(ctx, known={e.url for e in events}))

    ctx.session.commit()
    ctx.bump("events", len(events))
    return events


EVENT_ALIASES: dict[str, list[str]] = {
    seed["slug"]: seed.get("aliases", []) for seed in SEED_EVENTS
}


async def _upsert_seed(ctx: RunContext, seed: dict) -> Event | None:
    existing = ctx.session.exec(select(Event).where(Event.slug == seed["slug"])).first()
    event = existing or Event(**{k: v for k, v in seed.items() if k in Event.model_fields})
    for key, value in seed.items():
        if key in Event.model_fields:
            setattr(event, key, value)

    # Live verification: confirm the URL still resolves and capture its title.
    verified = await ctx.attempt(
        STAGE,
        lambda: _verify(ctx, event),
        entity_type="event",
        entity_ref=event.slug,
        default=None,
    )
    if verified is None:
        # Unreachable (403 bot-wall, DNS, timeout) -- keep the event, flag the gap.
        event.status = RecordStatus.INCOMPLETE
        if not event.sources:
            event.sources = [SourceRef(url=event.url, title=event.name).model_dump(mode="json")]
    else:
        event.status = RecordStatus.COMPLETE
    event.updated_at = utcnow()
    ctx.session.add(event)
    return event


async def _verify(ctx: RunContext, event: Event) -> Event:
    response = await ctx.fetcher.fetch(event.url)
    title = page_title(response.text) or event.name
    event.sources = [
        SourceRef(
            url=event.url,
            title=title,
            fetched_at=response.fetched_at,
            snippet=html_to_text(response.text, cap=400) or None,
        ).model_dump(mode="json")
    ]
    return event


async def _discover_via_search(ctx: RunContext, known: set[str]) -> list[Event]:
    if not ctx.search.is_configured():
        logger.info("search provider unconfigured; skipping event expansion")
        return []

    found: list[Event] = []
    existing = list(ctx.session.exec(select(Event)).all())
    seen_slugs = {row.slug for row in existing}
    seen_hosts = {h for h in (canonical_domain(row.url) for row in existing) if h}
    for query in EVENT_SEARCH_QUERIES:
        results = await ctx.attempt(
            STAGE,
            lambda q=query: ctx.search.search(q, limit=6),
            entity_type="search_query",
            entity_ref=query,
            default=[],
        ) or []
        for result in results:
            if any(bad in result.url for bad in _EVENT_URL_BLOCKLIST) or result.url in known:
                continue
            if not _looks_like_event(result.title):
                continue
            # One event per host: a show's site returns many pages for one event.
            host = canonical_domain(result.url)
            if host and host in seen_hosts:
                continue
            slug = _slugify(result.title)[:80]
            if not slug or slug in seen_slugs:
                continue
            if host:
                seen_hosts.add(host)
            seen_slugs.add(slug)
            known.add(result.url)
            event = Event(
                slug=slug,
                name=result.title[:200],
                url=result.url,
                event_type=EventType.CONFERENCE,
                relevance_note=result.snippet[:500] or None,
                status=RecordStatus.INCOMPLETE,  # unverified until enrichment touches it
                sources=[
                    SourceRef(url=result.url, title=result.title,
                              snippet=result.snippet[:300] or None).model_dump(mode="json")
                ],
            )
            ctx.session.add(event)
            found.append(event)
    return found


def _looks_like_event(title: str) -> bool:
    lowered = (title or "").lower()
    if any(bad in lowered for bad in _EVENT_TITLE_REJECT):
        return False
    return any(word in lowered for word in _EVENT_TITLE_WORDS)


def _slugify(text: str) -> str:
    out = "".join(c.lower() if c.isalnum() else "-" for c in text)
    while "--" in out:
        out = out.replace("--", "-")
    return out.strip("-")


__all__ = ["SEED_EVENTS", "EVENT_SEARCH_QUERIES", "run", "date"]
