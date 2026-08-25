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
from ...services.extract import extract_links, html_to_text
from ...services.http import Fetcher
from ...services.search.base import SearchProvider
from .base import classify_seniority, sales_navigator_url, title_relevance

logger = logging.getLogger(__name__)

TEAM_PATHS = ["/about/leadership", "/leadership", "/about/team", "/team", "/our-team",
              "/about-us/leadership", "/management", "/about/management"]
TEAM_KEYWORDS = ("leadership", "management", "our team", "executive", "who we are",
                 "meet the team", "our people", "board")

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
        assert self._search is not None
        out: list[Contact] = []
        for target in target_titles[:3]:
            if len(out) >= limit:
                break
            query = f'site:linkedin.com/in "{company.name}" "{target}"'
            try:
                results = await self._search.search(query, limit=4)
            except Exception as exc:  # noqa: BLE001
                logger.info("contact search failed for %s: %s", company.name, exc)
                continue
            for result in results:
                match = _LINKEDIN_PROFILE.search(result.url)
                if not match:
                    continue
                name, title = _split_linkedin_title(result.title)
                if not name:
                    continue
                out.append(
                    Contact(
                        company_id=company.id,
                        full_name=name,
                        title=title or target,
                        seniority=classify_seniority(title or target),
                        linkedin_url=match.group(0),
                        sales_nav_url=sales_navigator_url(name, company.name),
                        provider=self.name,
                        confidence=0.55,  # search-snippet sourced: weaker than a site page
                        sources=[
                            SourceRef(url=result.url, title=result.title,
                                      snippet=result.snippet[:300] or None).model_dump(
                                          mode="json")
                        ],
                    )
                )
                if len(out) >= limit:
                    break
        return out


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
