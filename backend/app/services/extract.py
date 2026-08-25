"""HTML -> clean text / links. selectolax because it is fast and dependency-light."""

from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

from selectolax.parser import HTMLParser

_DROP_TAGS = ("script", "style", "noscript", "svg", "iframe", "nav", "footer", "form")
_WS = re.compile(r"[ \t\r\f\v]+")
_BLANKS = re.compile(r"\n{3,}")

DEFAULT_TEXT_CAP = 12_000


def html_to_text(html: str, *, cap: int = DEFAULT_TEXT_CAP) -> str:
    if not html:
        return ""
    tree = HTMLParser(html)
    for tag in _DROP_TAGS:
        for node in tree.css(tag):
            node.decompose()
    body = tree.body or tree.root
    text = body.text(separator="\n") if body else ""
    text = _WS.sub(" ", text)
    text = _BLANKS.sub("\n\n", text)
    text = "\n".join(line.strip() for line in text.splitlines() if line.strip())
    return text[:cap]


def page_title(html: str) -> str | None:
    if not html:
        return None
    node = HTMLParser(html).css_first("title")
    title = node.text(strip=True) if node else None
    return title or None


def site_name(html: str) -> str | None:
    """The company's own name for itself: og:site_name, then application-name."""
    if not html:
        return None
    tree = HTMLParser(html)
    for selector, attr in (
        ('meta[property="og:site_name"]', "content"),
        ('meta[name="application-name"]', "content"),
    ):
        node = tree.css_first(selector)
        value = (node.attributes.get(attr) or "").strip() if node else ""
        if 2 <= len(value) <= 60:
            return value
    return None


def extract_links(html: str, base_url: str) -> list[tuple[str, str]]:
    """Return (absolute_url, anchor_text) for every on-page link."""
    if not html:
        return []
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for node in HTMLParser(html).css("a[href]"):
        href = (node.attributes.get("href") or "").strip()
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        absolute = urljoin(base_url, href)
        if not absolute.startswith(("http://", "https://")) or absolute in seen:
            continue
        seen.add(absolute)
        out.append((absolute, node.text(strip=True) or ""))
    return out


def external_links(html: str, base_url: str) -> list[tuple[str, str]]:
    """Links pointing off `base_url`'s host -- how exhibitor rows reveal company sites."""
    base_host = urlparse(base_url).hostname or ""
    return [
        (url, text)
        for url, text in extract_links(html, base_url)
        if (urlparse(url).hostname or "") not in ("", base_host)
    ]
