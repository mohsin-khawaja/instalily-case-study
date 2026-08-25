"""Stage 4 -- company enrichment from the company's own website.

Resolve a domain, pull the homepage plus a handful of high-signal subpages, and
turn the text into structured facts. The LLM does the reading; a keyword-based
fallback covers runs with no API key so the pipeline is never key-dependent.

Nothing here invents a number: the extraction schema is null-preferring and the
prompt forbids inference, so an unknown revenue stays unknown and costs the
company confidence rather than earning it a fabricated band.
"""

from __future__ import annotations

import asyncio
import logging
import re
from urllib.parse import urlparse

from pydantic import BaseModel, Field

from ...config import get_settings
from ...models.domain import Company, SourceRef, utcnow
from ...models.enums import RecordStatus, StageName
from ...scoring import icp
from ...services.dedupe import canonical_domain
from ...services.extract import extract_links, html_to_text, page_title, site_name
from ...services.llm.prompts import EXTRACTION_SYSTEM, extraction_prompt
from ..context import RunContext

logger = logging.getLogger(__name__)

STAGE = StageName.ENRICH_COMPANIES

# Fallback only. Guessed paths 404 on most real sites, so the primary route is
# following the homepage's own navigation -- that is where the durability copy
# and the company facts actually live.
SUBPAGE_PATHS = ["/about", "/about-us", "/company", "/products", "/our-company"]

# Nav words worth following, most informative first.
SUBPAGE_KEYWORDS = (
    "about", "company", "product", "solution", "material", "film",
    "technology", "quality", "who we are", "overview",
)
MAX_SUBPAGES = 3
SITE_TEXT_CAP = 14_000

# A money figure only counts as revenue when a revenue word sits beside it.
# Without the proximity requirement this happily reads "$2 billion market" or a
# customer's project value as the company's own turnover.
_REVENUE_RE = re.compile(
    r"(?:revenue|sales|turnover|annual\s+income)[^.\n]{0,60}?"
    r"\$\s?([\d,.]+)\s*(billion|million|bn|mm|b\b|m\b)"
    r"|\$\s?([\d,.]+)\s*(billion|million|bn|mm|b\b|m\b)[^.\n]{0,40}?"
    r"(?:in\s+(?:annual\s+)?(?:revenue|sales|turnover)|revenue|turnover)",
    re.IGNORECASE,
)
_EMPLOYEE_RE = re.compile(
    r"(?:over|more than|approximately|about|nearly|~)?\s*([\d,]{2,12})\+?\s+"
    r"(?:employees|people|team members|associates)",
    re.IGNORECASE,
)


class ExtractedProfile(BaseModel):
    """LLM extraction target. Every field is optional on purpose."""

    industry: str | None = Field(description="One short industry label, or null")
    sub_industries: list[str] = Field(default_factory=list)
    products: list[str] = Field(default_factory=list)
    description: str | None = Field(description="One factual sentence, or null")
    company_name: str | None = Field(
        description="The company's own name for itself as printed on the page, or null"
    )
    hq_location: str | None = Field(description="City, Country if stated, else null")
    revenue_usd: float | None = Field(
        description="Annual revenue in USD, only if explicitly stated in the text"
    )
    employee_count: int | None = Field(
        description="Headcount, only if explicitly stated in the text"
    )


async def run(ctx: RunContext, companies: list[Company]) -> list[Company]:
    targets = companies[: ctx.limit] if ctx.limit else companies

    # Enrichment is almost entirely network wait: four or five fetches plus an
    # LLM call per company, each against a different host. Running it one company
    # at a time left the fetcher's own concurrency cap idle and made a live run
    # scale linearly with the company count.
    semaphore = asyncio.Semaphore(get_settings().pipeline_concurrency)

    async def enrich_guarded(company: Company) -> None:
        async with semaphore:
            await ctx.attempt(
                STAGE,
                lambda c=company: _enrich_one(ctx, c),
                entity_type="company",
                entity_ref=company.name,
            )

    await asyncio.gather(*(enrich_guarded(company) for company in targets))
    for company in targets:
        ctx.session.add(company)
    ctx.session.commit()

    await _fill_missing_size(ctx, targets)

    from sqlmodel import select as _select

    from ...models.domain import Event as _Event
    from .extract_companies import link_companies_to_events

    events = list(ctx.session.exec(_select(_Event)).all())
    await link_companies_to_events(ctx, targets, events)

    ctx.bump("companies_enriched", sum(1 for c in targets if c.enriched))
    return targets


async def _fill_missing_size(ctx: RunContext, companies: list[Company]) -> None:
    """Second pass for revenue/headcount via search snippets.

    Company homepages almost never state their own revenue, so without this the
    size component scores zero across the board. Snippets are weaker evidence than
    a company's own page, so a number found here still has to survive the same
    plausibility bounds -- and if nothing is found, the field stays null.
    """
    semaphore = asyncio.Semaphore(get_settings().pipeline_concurrency)

    async def fill_one(company: Company) -> None:
        if company.revenue_est_usd or company.employee_count_est or not company.enriched:
            return

        # Firmographics provider first: a structured record beats parsing a
        # number out of a search snippet, and it fills industry and HQ too.
        if await _apply_apollo_firmographics(ctx, company):
            return

        if not ctx.search.is_configured():
            return
        results = await ctx.attempt(
            STAGE,
            lambda c=company: ctx.search.search(
                f"{c.name} company annual revenue number of employees", limit=4
            ),
            entity_type="company_size_lookup",
            entity_ref=company.name,
            default=[],
        ) or []
        matched = [r for r in results if _refers_to(company, r)]
        blob = " ".join(f"{r.title} {r.snippet}" for r in matched)
        if not blob:
            return
        revenue = _revenue_from_text(blob)
        headcount = _employees_from_text(blob)
        if not (revenue or headcount):
            return
        source = SourceRef(
            url=matched[0].url, title=matched[0].title,
            snippet=matched[0].snippet[:300] or None,
        ).model_dump(mode="json")
        if revenue:
            company.revenue_est_usd = revenue
            company.revenue_band = _revenue_band(revenue)
        if headcount:
            company.employee_count_est = headcount
            company.employee_band = _employee_band(headcount)
        # Cite the snippet we actually read, not the company's homepage.
        company.size_source_url = matched[0].url
        company.size_source_kind = "third_party"
        company.sources = [*(company.sources or []), source]
        ctx.session.add(company)

    async def guarded(company: Company) -> None:
        async with semaphore:
            await fill_one(company)

    await asyncio.gather(*(guarded(company) for company in companies))
    ctx.session.commit()


async def _apply_apollo_firmographics(ctx: RunContext, company: Company) -> bool:
    """Fill size (and any missing profile fields) from Apollo. True if it did."""
    from ...integrations.contacts.apollo import enrich_organization

    if not (get_settings().apollo_api_key and company.domain):
        return False

    org = await ctx.attempt(
        STAGE,
        lambda: enrich_organization(company.domain or ""),
        entity_type="company_firmographics",
        entity_ref=company.name,
        default=None,
    )
    if org is None or not (org.revenue_usd or org.employee_count):
        return False

    source_url = org.source_url or company.website
    if org.revenue_usd:
        company.revenue_est_usd = org.revenue_usd
        company.revenue_band = _revenue_band(org.revenue_usd)
    if org.employee_count:
        company.employee_count_est = int(org.employee_count)
        company.employee_band = _employee_band(int(org.employee_count))
    company.size_source_url = source_url
    company.size_source_kind = "third_party"

    # Only fill gaps -- the company's own site outranks an aggregator on anything
    # it already told us.
    company.hq_location = company.hq_location or org.hq_location
    company.description = company.description or org.description
    if org.keywords:
        existing = {s.lower() for s in (company.sub_industries or [])}
        company.sub_industries = [
            *(company.sub_industries or []),
            *[k for k in org.keywords if k.lower() not in existing],
        ][:14]

    if source_url:
        company.sources = [
            *(company.sources or []),
            SourceRef(
                url=source_url,
                title=f"Apollo.io organization record for {org.name or company.name}",
            ).model_dump(mode="json"),
        ]
    ctx.session.add(company)
    return True


async def _enrich_one(ctx: RunContext, company: Company) -> Company:
    website = company.website or await _resolve_website(ctx, company)
    if not website:
        company.status = RecordStatus.INCOMPLETE
        raise ValueError(f"no website could be resolved for {company.name!r}")

    company.website = website
    company.domain = company.domain or canonical_domain(website)

    pages, home_site_name, home_title = await _fetch_pages(ctx, website)
    if not _usable(pages):
        # Deduplication picked one URL out of several the channels found. If that
        # one is a JS shell or a redirect stub, the others are still worth trying
        # before we write the company off.
        for alternate in _alternate_urls(company, website):
            pages, home_site_name, home_title = await _fetch_pages(ctx, alternate)
            if _usable(pages):
                company.website = website = alternate
                break
    if not _usable(pages):
        company.status = RecordStatus.INCOMPLETE
        raise ValueError(f"no usable page content at {website}")

    combined = "\n\n".join(text for _, text in pages)[:SITE_TEXT_CAP]
    company.site_text = combined
    company.sources = _merge_sources(company.sources, pages)

    profile = await _extract_profile(ctx, company, website, combined)
    _apply_profile(company, profile, combined)
    _upgrade_name(company, profile, home_site_name, home_title)

    company.enriched = True
    company.status = (
        RecordStatus.COMPLETE if company.industry and company.description
        else RecordStatus.INCOMPLETE
    )
    company.updated_at = utcnow()
    return company


async def _resolve_website(ctx: RunContext, company: Company) -> str | None:
    if not ctx.search.is_configured():
        return None
    results = await ctx.search.search(f"{company.name} official website", limit=3)
    for result in results:
        domain = canonical_domain(result.url)
        if domain:
            return f"https://{domain}/"
    return None


async def _fetch_pages(
    ctx: RunContext, website: str
) -> tuple[list[tuple[str, str]], str | None, str | None]:
    """Homepage is required; subpages are best-effort and never fail the record."""
    pages: list[tuple[str, str]] = []
    home = await ctx.fetcher.fetch(website)
    pages.append((website, html_to_text(home.text)))
    home_title = page_title(home.text)
    home_site_name = site_name(home.text)

    for url in _subpage_candidates(home.text, website):
        if len(pages) > MAX_SUBPAGES:
            break
        try:
            response = await ctx.fetcher.fetch(url)
        except Exception:  # noqa: BLE001 -- subpage misses are expected and uninteresting
            continue
        text = html_to_text(response.text)
        if len(text) > 200:
            pages.append((url, text))

    if home_title:
        pages[0] = (website, f"{home_title}\n{pages[0][1]}")
    return [p for p in pages if p[1]], home_site_name, home_title


# Low on purpose: this separates "a JavaScript shell rendered nothing" from
# "a genuinely short homepage", not "thin content" from "rich content".
MIN_USABLE_TEXT = 80


def _usable(pages: list[tuple[str, str]]) -> bool:
    return sum(len(text) for _url, text in pages) >= MIN_USABLE_TEXT


def _alternate_urls(company: Company, tried: str) -> list[str]:
    """Other first-party URLs this company was seen at, root pages first."""
    tried_host = urlparse(tried).hostname or ""
    out: list[str] = []
    for source in company.sources or []:
        url = source.get("url") if isinstance(source, dict) else None
        if not url:
            continue
        parsed = urlparse(url)
        host = parsed.hostname or ""
        if not host or host == tried_host:
            continue
        root = f"{parsed.scheme}://{host}/"
        if root not in out:
            out.append(root)
    return out[:2]


def _subpage_candidates(html: str, website: str) -> list[str]:
    """Follow the site's own navigation, then fall back to guessed paths."""
    host = urlparse(website).hostname or ""
    ranked: list[tuple[int, str]] = []
    seen: set[str] = {website.rstrip("/")}

    for url, anchor in extract_links(html, website):
        parsed = urlparse(url)
        if (parsed.hostname or "") != host:
            continue
        normalized = url.split("#")[0].rstrip("/")
        if normalized in seen or normalized == website.rstrip("/"):
            continue
        haystack = f"{anchor} {parsed.path}".lower()
        rank = next(
            (i for i, word in enumerate(SUBPAGE_KEYWORDS) if word in haystack), None
        )
        if rank is None:
            continue
        seen.add(normalized)
        ranked.append((rank, normalized))

    ranked.sort(key=lambda item: item[0])
    candidates = [url for _rank, url in ranked[:MAX_SUBPAGES]]

    base = website.rstrip("/")
    candidates.extend(
        base + path for path in SUBPAGE_PATHS if base + path not in seen
    )
    return candidates[: MAX_SUBPAGES * 2]


def _merge_sources(existing: list[dict], pages: list[tuple[str, str]]) -> list[dict]:
    out = list(existing or [])
    seen = {s.get("url") for s in out if isinstance(s, dict)}
    for url, text in pages:
        if url in seen:
            continue
        seen.add(url)
        out.append(
            SourceRef(url=url, title=None, snippet=text[:300] or None).model_dump(mode="json")
        )
    return out


async def _extract_profile(
    ctx: RunContext, company: Company, url: str, site_text: str
) -> ExtractedProfile:
    if not ctx.llm.enabled:
        return _keyword_profile(site_text)
    try:
        return await ctx.llm.structured(
            ExtractedProfile,
            prompt=extraction_prompt(company.name, url, site_text[:12_000]),
            system=EXTRACTION_SYSTEM,
            model=ctx.llm.model_extraction,
        )
    except Exception as exc:  # noqa: BLE001 -- degrade to keywords, keep the record
        ctx.record_error(STAGE, exc, entity_type="company_extraction", entity_ref=company.name)
        return _keyword_profile(site_text)


def _keyword_profile(site_text: str) -> ExtractedProfile:
    """Deterministic fallback: ICP vocabulary hits become the profile."""
    hay = site_text.lower()
    subs = [term for term in icp.INDUSTRY_TIER1 + icp.INDUSTRY_TIER2 if term in hay]
    products = [term for term in icp.APPLICATION_KEYWORDS if term in hay]
    first_line = next((ln for ln in site_text.splitlines() if len(ln) > 60), None)
    return ExtractedProfile(
        industry=subs[0].title() if subs else None,
        sub_industries=subs[:6],
        products=products[:6],
        description=first_line[:300] if first_line else None,
        company_name=None,
        hq_location=None,
        revenue_usd=None,
        employee_count=None,
    )


def _apply_profile(company: Company, profile: ExtractedProfile, site_text: str) -> None:
    company.industry = profile.industry or company.industry
    company.sub_industries = profile.sub_industries or company.sub_industries
    company.products = profile.products or company.products
    company.description = profile.description or company.description
    company.hq_location = profile.hq_location or company.hq_location

    revenue = profile.revenue_usd if profile.revenue_usd else _revenue_from_text(site_text)
    if revenue:
        company.revenue_est_usd = revenue
        company.revenue_band = _revenue_band(revenue)
        company.size_source_url = company.website
        company.size_source_kind = "site"

    headcount = profile.employee_count or _employees_from_text(site_text)
    if headcount:
        company.employee_count_est = headcount
        company.employee_band = _employee_band(headcount)
        company.size_source_url = company.size_source_url or company.website
        company.size_source_kind = company.size_source_kind or "site"


def _upgrade_name(
    company: Company,
    profile: ExtractedProfile,
    meta_name: str | None,
    title: str | None = None,
) -> None:
    """Replace the provisional domain-derived name with what the company calls itself.

    Preference order: what the extractor read off the page, then og:site_name,
    then the brand segment of <title> ("Drytac | Adhesive Solutions" -> "Drytac").
    """
    if not _name_is_provisional(company):
        return  # a directory or roster already gave us a real name; don't downgrade it
    for candidate in (profile.company_name, meta_name, _brand_from_title(title)):
        text = (candidate or "").strip()
        if 2 <= len(text) <= 60 and len(text.split()) <= 6 and not _is_generic(text):
            company.name = text
            return


def _name_is_provisional(company: Company) -> bool:
    """True when the name was derived from the domain rather than supplied."""
    if not company.domain:
        return True
    label = company.domain.split(".")[0].replace("-", "").lower()
    return company.name.replace(" ", "").replace("-", "").lower() == label


# Page titles are full of section words that are not anyone's company name.
_GENERIC_NAMES = {
    "graphics", "products", "solutions", "home", "welcome", "company", "about",
    "about us", "index", "films", "materials", "services", "shop", "store",
}


def _is_generic(text: str) -> bool:
    return text.strip().lower() in _GENERIC_NAMES


# Separators must be space-delimited, or "Self-Adhesive Vinyl" splits at the hyphen.
_TITLE_SEPARATOR = re.compile(r"\s+(?:\|+|:{1,2}|\u2013|\u2014|\u00b7)\s+|\s+-\s+")
# Segments that are navigation, not identity.
_TITLE_STOPWORDS = {"home", "welcome", "index", "homepage", "official site", "en", "us"}


def _brand_from_title(title: str | None) -> str | None:
    """Titles run both ways: "Brand | Tagline" and "Tagline - Brand"."""
    if not title:
        return None
    parts = [
        part.strip()
        for part in _TITLE_SEPARATOR.split(title)
        if part.strip() and part.strip().lower() not in _TITLE_STOPWORDS
    ]
    if not parts:
        return None
    return min(parts, key=lambda part: len(part.split()))


def _refers_to(company: Company, result) -> bool:
    """Guard against confident answers about a similarly-named company.

    "Briteline" (graphic films) and "Briteline Extrusions" (plastics) are
    different businesses, and an aggregator page for one is not evidence about
    the other. Require the result to name this company and nothing longer.
    """
    from ...services.dedupe import normalize_name

    name = normalize_name(company.name)
    if len(name) < 4:
        return False
    title = normalize_name(result.title)
    if name not in title:
        return False
    # Allow a trailing descriptor ("revenue", "company profile"), not a different
    # legal entity: at most one extra token before the boilerplate.
    extra = [tok for tok in title.replace(name, "", 1).split() if tok]
    boilerplate = {"revenue", "employees", "company", "profile", "competitors",
                   "funding", "info", "overview", "size", "financials", "growth",
                   "number", "of", "and", "the", "inc", "llc", "corp", "estimated",
                   "annual", "headquarters", "linkedin", "zoominfo", "growjo"}
    return sum(1 for tok in extra if tok not in boilerplate) <= 1


def _revenue_from_text(text: str) -> float | None:
    """Regex backstop for '$8.4 billion in sales' style statements."""
    for match in _REVENUE_RE.finditer(text):
        amount_raw = match.group(1) or match.group(3)
        unit_raw = match.group(2) or match.group(4)
        if not amount_raw or not unit_raw:
            continue
        try:
            amount = float(amount_raw.replace(",", ""))
        except ValueError:
            continue
        unit = unit_raw.lower()
        scale = 1_000_000_000 if unit.startswith(("b", "bn")) else 1_000_000
        value = amount * scale
        if 1_000_000 <= value <= 500_000_000_000:
            return value
    return None


def _employees_from_text(text: str) -> int | None:
    for match in _EMPLOYEE_RE.finditer(text):
        try:
            count = int(match.group(1).replace(",", ""))
        except ValueError:
            continue
        if 5 <= count <= 1_000_000:
            return count
    return None


def _revenue_band(value: float) -> str:
    for floor, label, _pts in icp.REVENUE_BANDS:
        if value >= floor:
            return label
    return "<$50M"


def _employee_band(count: int) -> str:
    for floor, label, _pts in icp.EMPLOYEE_BANDS:
        if count >= floor:
            return label
    return "1-49"
