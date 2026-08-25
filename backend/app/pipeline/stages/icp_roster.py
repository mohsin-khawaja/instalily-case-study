"""Channel 3 of company sourcing: a verified roster of known ICP participants.

Why this exists. The two automated channels each have a real-world failure mode:
exhibitor directories for the flagship shows (ISA Sign Expo, PRINTING United) are
JavaScript front-ends over an API that refuses server-side clients, and the
keyless search provider has thin recall on category leaders. Neither reliably
surfaces the companies a Tedlar rep would name first.

So the roster below is an *input*, not an answer: names and public URLs only. The
pipeline still fetches every site, extracts every fact, scores, and drafts from
what it actually reads -- a roster entry that cannot be fetched is recorded as an
error and scores nothing. Nothing here asserts revenue, products or fit.

This is the one hand-curated step in the pipeline and it is deliberately the
cheapest one to replace: point `SEARCH_PROVIDER` at Serper or Tavily and the
search channel covers the same ground automatically.
"""

from __future__ import annotations

from ...models.domain import Company, SourceRef
from ...models.enums import StageName

STAGE = StageName.EXTRACT_COMPANIES

# name, homepage. Public, first-party URLs only.
ICP_ROSTER: list[tuple[str, str]] = [
    ("Avery Dennison Graphics Solutions", "https://graphics.averydennison.com/"),
    ("ORAFOL Europe", "https://www.orafol.com/"),
    ("Arlon Graphics", "https://www.arlon.com/"),
    ("Drytac", "https://www.drytac.com/"),
    ("HEXIS Graphics", "https://www.hexis-graphics.com/"),
    ("General Formulations", "https://www.generalformulations.com/"),
    ("Mactac", "https://www.mactac.com/"),
    ("Briteline", "https://www.briteline.com/"),
    ("LINTEC Corporation", "https://www.lintec-global.com/"),
    ("R Tape", "https://www.rtape.com/"),
    ("Metamark", "https://www.metamark.co.uk/"),
    ("Spandex", "https://www.spandex.com/"),
    ("Grimco", "https://www.grimco.com/"),
    ("Fellers", "https://www.fellers.com/"),
    ("Serge Ferrari", "https://www.sergeferrari.com/"),
    ("Continental Grafix", "https://www.continentalgrafix.com/"),
    ("Ultraflex Systems", "https://www.ultraflexx.com/"),
    ("Nekoosa", "https://www.nekoosa.com/"),
    ("Fedrigoni", "https://www.fedrigoni.com/"),
    ("KPMF", "https://www.kpmf.com/"),
    ("3M Commercial Graphics", "https://www.3m.com/"),
]

ROSTER_NOTE = (
    "Seeded from public knowledge of the graphics & signage supply chain; "
    "every fact about this company was fetched from its own site."
)


def roster_candidates() -> list[dict]:
    """Emit the same loose candidate shape the scrape and search channels produce."""
    return [
        {
            "name": name,
            "website": url,
            "event_ids": [],
            "sources": [SourceRef(url=url, title=f"{name} (roster seed)",
                                  snippet=ROSTER_NOTE).model_dump(mode="json")],
        }
        for name, url in ICP_ROSTER
    ]


__all__ = ["ICP_ROSTER", "ROSTER_NOTE", "Company", "roster_candidates"]
