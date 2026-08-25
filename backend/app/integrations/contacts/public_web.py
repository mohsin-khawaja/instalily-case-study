"""Public-web contact discovery.

Reads leadership/team pages on the company's own site and, when a search provider
is configured, site-restricted LinkedIn queries. Only returns people it actually
saw named alongside a relevant title -- if the page does not name anyone, this
provider returns nothing rather than a plausible-looking guess.
"""

from __future__ import annotations

import logging
import re
from urllib.parse import urlparse

from ...models.domain import Company, Contact, SourceRef
from ...models.enums import Seniority
from ...services.extract import extract_links, html_to_text
from ...services.http import Fetcher
from ...services.search.base import SearchProvider
from .base import classify_seniority, function_fit, sales_navigator_url, title_relevance

logger = logging.getLogger(__name__)

TEAM_PATHS = ["/about/leadership", "/leadership", "/about/team", "/team", "/our-team",
              "/about-us/leadership", "/management", "/about/management"]
TEAM_KEYWORDS = ("leadership", "management", "our team", "executive", "who we are",
                 "meet the team", "our people", "board")

# Headline words that actually appear on LinkedIn profiles, unlike full ICP titles.
SENIORITY_QUERY_TOKENS = ("Director", "Vice President", "Head of", "VP")
# Words that end the brand portion of a company name.
_NAME_TAIL_WORDS = {"graphics", "solutions", "group", "corporation", "corp", "inc",
                    "llc", "ltd", "limited", "company", "co", "gmbh", "international",
                    "north", "america", "usa", "europe", "products", "systems"}
_SENIORITY_WEIGHT = {
    Seniority.C_LEVEL: 0.5,
    Seniority.VP: 0.6,
    Seniority.DIRECTOR: 0.5,
    Seniority.MANAGER: 0.2,
    Seniority.OTHER: 0.0,
}

# "Jane Q. Smith, Vice President of Product" / "Jane Smith - Director of R&D"
_PERSON_TITLE = re.compile(
    # Name and title must sit on one line: `\s` would swallow the preceding
    # heading ("Leadership\nDana Whitfield") straight into the captured name.
    r"(?:^|[>\n])[ \t]*"
    r"([A-Z][a-z]+(?:[ \t]+[A-Z]\.)?(?:[ \t]+[A-Z][a-z\-']+){1,2})"
    r"[ \t]*[,\-–|:][ \t]*"
    r"((?:Chief|President|Senior |Sr\.? |Executive |Global |Corporate )?"
    r"(?:Vice President|VP|SVP|EVP|Director|Head)\b[^\n,;.]{0,60})",
    re.MULTILINE,
)
_LINKEDIN_PROFILE = re.compile(r"https://[a-z]{0,3}\.?linkedin\.com/in/[A-Za-z0-9\-_%]+")


class PublicWebContactProvider:
    name = "public_web"

    def __init__(self, fetcher: Fetcher, search: SearchProvider | None = None) -> None:
        self._fetcher = fetcher
        self._search = search

    def is_configured(self) -> bool:
        return True

    async def find_contacts(
        self, company: Company, target_titles: list[str], limit: int = 3
    ) -> list[Contact]:
        found = await self._from_team_pages(company, target_titles, limit)
        if len(found) < limit and self._search is not None and self._search.is_configured():
            found.extend(await self._from_search(company, target_titles, limit - len(found)))
        return _dedupe(found)[:limit]

    async def _from_team_pages(
        self, company: Company, target_titles: list[str], limit: int
    ) -> list[Contact]:
        if not company.website:
            return []
        out: list[Contact] = []
        for url in await self._team_page_urls(company):
            if len(out) >= limit:
                break
            try:
                response = await self._fetcher.fetch(url)
            except Exception:  # noqa: BLE001 -- most sites have none of these paths
                continue
            text = html_to_text(response.text)
            for name, title in _PERSON_TITLE.findall(text):
                score = title_relevance(title, target_titles)
                if score < 0.34:
                    continue
                out.append(
                    Contact(
                        company_id=company.id,
                        full_name=name.strip(),
                        title=" ".join(title.split())[:120],
                        seniority=classify_seniority(title),
                        sales_nav_url=sales_navigator_url(name, company.name),
                        provider=self.name,
                        confidence=round(min(1.0, 0.5 + score / 2), 2),
                        sources=[
                            SourceRef(url=url, title=f"{company.name} leadership page",
                                      fetched_at=response.fetched_at).model_dump(mode="json")
                        ],
                    )
                )
                if len(out) >= limit:
                    break
        return out

    async def _team_page_urls(self, company: Company) -> list[str]:
        """Follow the site's own nav to its leadership page, then guess as a fallback.

        Guessed paths miss on most real sites -- the page is at /our-story or
        /company/executive-team as often as /leadership.
        """
        base = (company.website or "").rstrip("/")
        urls: list[str] = []
        try:
            home = await self._fetcher.fetch(company.website or "")
        except Exception:  # noqa: BLE001 -- fall through to guessed paths
            return [base + path for path in TEAM_PATHS]

        host = urlparse(company.website or "").hostname or ""
        for url, anchor in extract_links(home.text, company.website or ""):
            if (urlparse(url).hostname or "") != host:
                continue
            haystack = f"{anchor} {urlparse(url).path}".lower()
            if any(word in haystack for word in TEAM_KEYWORDS):
                normalized = url.split("#")[0]
                if normalized not in urls:
                    urls.append(normalized)
        urls.extend(base + path for path in TEAM_PATHS)
        return urls[:6]

    async def _from_search(
        self, company: Company, target_titles: list[str], limit: int
    ) -> list[Contact]:
        """Find decision-makers through site-restricted LinkedIn search.

        Querying the full target title verbatim ("VP Product Development") almost
        never matches a real profile headline, so the queries use seniority words
        instead and the ICP titles are applied afterwards as a ranking signal.
        """
        assert self._search is not None
        short = _short_name(company.name)
        candidates: list[tuple[float, Contact]] = []
        seen: set[str] = set()

        for token in SENIORITY_QUERY_TOKENS:
            if len(candidates) >= limit * 3:
                break
            query = f'site:linkedin.com/in "{short}" "{token}"'
            try:
                results = await self._search.search(query, limit=6)
            except Exception as exc:  # noqa: BLE001
                logger.info("contact search failed for %s: %s", company.name, exc)
                continue

            for result in results:
                match = _LINKEDIN_PROFILE.search(result.url)
                if not match or match.group(0) in seen:
                    continue
                name, role = _split_linkedin_title(result.title)
                if not name or _is_stale_role(role):
                    continue
                if not _mentions_company(result, short, person_name=name):
                    continue

                relevance = title_relevance(role, target_titles)
                seniority = classify_seniority(role)
                fit = function_fit(role)
                if seniority is Seniority.OTHER and relevance < 0.34:
                    continue  # not a decision-maker by either measure

                seen.add(match.group(0))
                candidates.append(
                    (
                        relevance + _SENIORITY_WEIGHT.get(seniority, 0.0) + fit,
                        Contact(
                            company_id=company.id,
                            full_name=name,
                            title=role,
                            seniority=seniority,
                            linkedin_url=match.group(0),
                            sales_nav_url=sales_navigator_url(name, company.name),
                            provider=self.name,
                            # Search-snippet sourced: weaker than a company's own
                            # leadership page, strong enough for a rep to verify.
                            confidence=round(min(0.8, 0.5 + relevance / 4 + max(fit, 0) / 4), 2),
                            sources=[
                                SourceRef(
                                    url=result.url, title=result.title,
                                    snippet=result.snippet[:300] or None,
                                ).model_dump(mode="json")
                            ],
                        ),
                    )
                )

        candidates.sort(key=lambda pair: pair[0], reverse=True)
        return [contact for _score, contact in candidates[:limit]]


def _short_name(name: str) -> str:
    """"Avery Dennison Graphics Solutions" -> "Avery Dennison".

    Search engines match the brand, not the divisional long form, and a profile
    headline says "at Avery Dennison".
    """
    tokens = [t for t in re.split(r"[\s,]+", name) if t]
    trimmed: list[str] = []
    for token in tokens:
        if token.lower() in _NAME_TAIL_WORDS and trimmed:
            break
        trimmed.append(token)
        if len(trimmed) == 2:
            break
    return " ".join(trimmed) or name


# Short company names are also ordinary words and surnames — "Gregory", "Capital",
# "Fellers". Below this length a bare mention proves nothing.
_DISTINCTIVE_NAME_LEN = 8


def _mentions_company(result, short_name: str, person_name: str = "") -> bool:
    """Decide whether a profile actually belongs to this company.

    Two traps, both seen in real output:
    * the company is named after its founders, so the person's own surname
      matches ("Alan Fellers — Director, Conflicts of Interest Program");
    * the company name is a common word, so an unrelated profile mentions it in
      passing ("VP of Sales, Family Fresh Foods" ranking for "Gregory").

    So: strip the person's name first, then require an employer-shaped match
    ("at Acme", "@ Acme", "| Acme") unless the name is long enough to stand alone.
    """
    haystack = f"{result.title} {result.snippet}".lower()
    for part in person_name.lower().split():
        haystack = haystack.replace(part, " ")

    needle = short_name.lower()
    if needle not in haystack:
        return False
    if len(needle) >= _DISTINCTIVE_NAME_LEN:
        return True

    # For a short name, require it to sit where an employer is named.
    escaped = re.escape(needle)
    # "… at Fellers", "… @ Fellers", "… | Fellers", "…, Fellers"
    after_marker = re.compile(rf"(?:\bat\s+|@\s*|[|,·:]\s*|[-—]\s+){escaped}\b", re.IGNORECASE)
    # Leading position, but only when a separator or a legal suffix follows —
    # "Fellers — wrap and graphics" is an employer line; "Gregory was a mentor"
    # is prose that happens to start with a common first name.
    leading = re.compile(
        rf"^{escaped}\b\s*(?:$|[|,·:—-]|\((?:inc|llc)|\b(?:inc|llc|ltd|corp|co|usa|group|"
        rf"international|graphics|films)\b)",
        re.IGNORECASE,
    )
    fields = (
        _strip_name(result.title, person_name).strip(),
        _strip_name(result.snippet or "", person_name).strip(),
    )
    return any(after_marker.search(f) or leading.search(f) for f in fields)


def _strip_name(text: str, person_name: str) -> str:
    out = text.lower()
    for part in person_name.lower().split():
        out = out.replace(part, " ")
    return out


def _is_stale_role(role: str | None) -> bool:
    text = (role or "").lower()
    return any(word in text for word in ("retired", "former", "ex-", "seeking", "student"))


def _split_linkedin_title(title: str) -> tuple[str, str | None]:
    """'Jane Smith - Director of R&D - Acme | LinkedIn' -> ('Jane Smith', 'Director of R&D')."""
    parts = [p.strip() for p in title.replace("|", "-").split("-") if p.strip()]
    if not parts:
        return "", None
    name = parts[0]
    if not re.fullmatch(r"[A-Z][A-Za-z.'\-]+(?:\s+[A-Z][A-Za-z.'\-]+){1,3}", name):
        return "", None
    role = parts[1] if len(parts) > 1 and parts[1].lower() != "linkedin" else None
    return name, role


def _dedupe(contacts: list[Contact]) -> list[Contact]:
    seen: set[str] = set()
    out: list[Contact] = []
    for contact in contacts:
        key = contact.full_name.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(contact)
    return out
