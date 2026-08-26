"""Lookalike modelling: find companies that resemble accounts you already won.

The scorer answers "does this match the ICP we wrote down". This answers a
different and often better question: "does this look like the deals that
actually closed" — which is how a GTM team refines an ICP it only half knows.

Implemented as TF-IDF cosine over the text the pipeline already collected. No
new dependency, no model download, no API call, and — the reason it is worth
preferring here — it is **explainable**: every similarity comes with the shared
terms that produced it, so a rep sees *why* two companies resemble each other
rather than being handed a number.

Reference accounts come from two places:
* `icp.REFERENCE_ACCOUNTS` — seeded known-good fits, starting with the account
  the brief itself names as the archetype;
* any company the team has marked as won.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass

from ..models.domain import Company
from . import icp

TOKEN = re.compile(r"[a-z][a-z0-9\-]{2,}")

# Words that appear on every manufacturer's site and carry no signal about fit.
STOPWORDS = frozenset({
    # fmt: off
    "about", "address", "all", "and", "are", "been", "can",
    "careers", "click", "company", "contact", "cookies", "copyright", "corp",
    "customer", "customers", "email", "events", "find", "for", "from",
    "has", "have", "help", "here", "home", "inc", "industries",
    "industry", "it's", "its", "leadership", "learn", "llc", "ltd",
    "management", "more", "news", "our", "page", "phone", "please",
    "policy", "privacy", "product", "products", "read", "reserved", "rights",
    "search", "service", "services", "site", "solution", "solutions", "support",
    "team", "terms", "that", "the", "their", "they", "this",
    "us", "view", "we", "web", "will", "with", "you",
    "your",
    # fmt: on
})

# Language and region words are navigation chrome on every multinational's site.
# Without these, two European manufacturers "match" on "english / france / europe"
# rather than on anything about their business.
NAV_STOPWORDS = frozenset({
    # fmt: off
    "english", "deutsch", "espanol", "espa", "francais", "italiano", "portugues",
    "america", "americas", "european", "europe", "france", "germany", "italy",
    "spain", "canada", "mexico", "china", "japan", "asia", "pacific", "global",
    "worldwide", "international", "region", "regional", "country", "language",
    "select", "menu", "navigation", "skip", "content", "close", "open", "toggle",
    "cookie", "consent", "accept", "settings", "login", "register", "account",
    "cart", "checkout", "subscribe", "newsletter", "follow", "share", "download",
    # fmt: on
})

# Terms that actually say something about Tedlar fit count for much more than
# whatever else happens to be on the page.
ICP_TERM_WEIGHT = 5

MIN_SHARED_TERMS = 2
MAX_TEXT = 8_000


@dataclass(slots=True)
class Lookalike:
    company_id: str
    company_name: str
    similarity: float
    shared_terms: list[str]
    reference_name: str

    def as_dict(self) -> dict:
        return {
            "company_id": self.company_id,
            "company_name": self.company_name,
            "similarity": round(self.similarity, 3),
            "shared_terms": self.shared_terms,
            "reference_name": self.reference_name,
        }


def _icp_vocabulary() -> frozenset[str]:
    """Every word appearing in the ICP definition, as single tokens."""
    phrases = [
        *icp.INDUSTRY_TIER1,
        *icp.INDUSTRY_TIER2,
        *icp.APPLICATION_KEYWORDS,
        *(p for phrases in icp.PAIN_KEYWORDS.values() for p in phrases),
    ]
    return frozenset(w for phrase in phrases for w in TOKEN.findall(phrase.lower()))


_ICP_WORDS = _icp_vocabulary()


def _tokens(company: Company) -> Counter[str]:
    """Weighted bag of words, biased toward what makes a company a Tedlar fit.

    Raw site text alone makes two multinationals look alike because they share a
    language switcher. Structured fields and ICP vocabulary are what actually
    distinguish a wrap-film converter from a label printer.
    """
    parts = [
        (company.industry or "") * 3,
        " ".join(company.sub_industries or []) * 3,
        " ".join(company.products or []) * 3,
        (company.description or "") * 2,
        (company.site_text or "")[:MAX_TEXT],
    ]
    words = TOKEN.findall(" ".join(parts).lower())
    counts: Counter[str] = Counter()
    for word in words:
        if word in STOPWORDS or word in NAV_STOPWORDS:
            continue
        counts[word] += ICP_TERM_WEIGHT if word in _ICP_WORDS else 1
    return counts


def _tfidf(corpus: dict[str, Counter[str]]) -> dict[str, dict[str, float]]:
    """Standard TF-IDF. Rare terms carry the signal; ubiquitous ones are damped."""
    n = len(corpus) or 1
    doc_freq: Counter[str] = Counter()
    for counts in corpus.values():
        doc_freq.update(counts.keys())

    vectors: dict[str, dict[str, float]] = {}
    for key, counts in corpus.items():
        total = sum(counts.values()) or 1
        # Smoothed IDF (the scikit-learn form). Plain log(n / df) goes negative
        # once a term appears in most of the corpus, which on a small corpus
        # zeroes out exactly the shared terms that indicate similarity — three
        # documents sharing a term would score log(3/4) < 0. The +1 keeps every
        # weight positive while still damping ubiquitous words.
        vector = {
            term: (count / total) * (math.log((1 + n) / (1 + doc_freq[term])) + 1.0)
            for term, count in counts.items()
        }
        norm = math.sqrt(sum(v * v for v in vector.values())) or 1.0
        vectors[key] = {t: v / norm for t, v in vector.items()}
    return vectors


def _cosine(a: dict[str, float], b: dict[str, float]) -> tuple[float, list[str]]:
    """Cosine plus the terms that contributed most — the explainable part."""
    shared = set(a) & set(b)
    if not shared:
        return 0.0, []
    contributions = {t: a[t] * b[t] for t in shared}
    score = sum(contributions.values())
    top = sorted(contributions, key=lambda t: contributions[t], reverse=True)[:6]
    return score, top


def rank_lookalikes(
    companies: list[Company],
    reference_ids: set[str],
    limit: int = 5,
    min_similarity: float = 0.05,
) -> dict[str, list[Lookalike]]:
    """For each non-reference company, the reference accounts it most resembles.

    Returns `{company_id: [Lookalike, ...]}`. A company with no meaningful
    overlap simply gets an empty list rather than a weak match — a lookalike
    nobody believes is worse than none.
    """
    if not reference_ids or len(companies) < 2:
        return {}

    by_id = {c.id: c for c in companies}
    corpus = {c.id: _tokens(c) for c in companies}
    vectors = _tfidf(corpus)

    references = [rid for rid in reference_ids if rid in vectors]
    if not references:
        return {}

    out: dict[str, list[Lookalike]] = {}
    for company_id, vector in vectors.items():
        if company_id in reference_ids:
            continue
        matches: list[Lookalike] = []
        for rid in references:
            score, shared = _cosine(vector, vectors[rid])
            if score < min_similarity or len(shared) < MIN_SHARED_TERMS:
                continue
            matches.append(
                Lookalike(
                    company_id=rid,
                    company_name=by_id[rid].name,
                    similarity=score,
                    shared_terms=shared,
                    reference_name=by_id[rid].name,
                )
            )
        if matches:
            matches.sort(key=lambda m: m.similarity, reverse=True)
            out[company_id] = matches[:limit]
    return out


def similar_to(
    company_id: str, companies: list[Company], limit: int = 5, min_similarity: float = 0.05
) -> list[Lookalike]:
    """Nearest neighbours of one company across the whole corpus.

    Used from a won account to ask "find me more like this".
    """
    by_id = {c.id: c for c in companies}
    if company_id not in by_id or len(companies) < 2:
        return []
    vectors = _tfidf({c.id: _tokens(c) for c in companies})
    target = vectors[company_id]

    out: list[Lookalike] = []
    for other_id, vector in vectors.items():
        if other_id == company_id:
            continue
        score, shared = _cosine(target, vector)
        if score < min_similarity or len(shared) < MIN_SHARED_TERMS:
            continue
        out.append(
            Lookalike(
                company_id=other_id,
                company_name=by_id[other_id].name,
                similarity=score,
                shared_terms=shared,
                reference_name=by_id[company_id].name,
            )
        )
    out.sort(key=lambda m: m.similarity, reverse=True)
    return out[:limit]
