"""Prospect research dossier.

A rep opening a lead gets a score and a paragraph. Before an actual call they
need the thing a good SDR would spend twenty minutes writing: what this company
does, why Tedlar is relevant to them specifically, who to talk to, what will be
objected to, and which comparable account to reference.

Two properties make this safe to ship:

* **It is generated on demand, one lead at a time.** Reports are the most
  token-hungry thing in the system, so they are never produced for the whole
  corpus during a run. A rep asks for the ones they are about to call.
* **The deterministic version always exists.** Every section is assembled from
  evidence, score explanations and lookalikes before the LLM is consulted, so
  the feature works with no credit at all — the model rewrites it into prose
  rather than inventing it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import BaseModel, Field

from ..models.domain import Company, Contact, Event, Qualification
from ..scoring import icp
from ..scoring.explain import explain_company, summarise


@dataclass
class ReportSection:
    heading: str
    body: str
    sources: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"heading": self.heading, "body": self.body, "sources": self.sources}


class ReportOut(BaseModel):
    """LLM-written narrative. Every section is constrained to supplied facts."""

    positioning: str = Field(description="What this company does, in two or three sentences")
    tedlar_angle: str = Field(description="Why Tedlar is relevant to them specifically")
    talking_points: list[str] = Field(description="3-5 concrete things to raise on a call")
    objections: list[str] = Field(description="2-3 likely objections or reasons this stalls")
    opener: str = Field(description="One sentence a rep could actually open with")


def _sources_from(evidence: list[dict]) -> list[str]:
    seen: list[str] = []
    for item in evidence or []:
        url = item.get("source_url")
        if url and url not in seen:
            seen.append(url)
    return seen


def deterministic_report(
    company: Company,
    qualification: Qualification | None,
    events: dict[str, Event],
    contacts: list[Contact],
    lookalikes: list[dict],
) -> list[ReportSection]:
    """The dossier assembled from what the pipeline already verified.

    No model involved, so this is what a reviewer sees when the API key is out
    of credit — and what the LLM version is checked against.
    """
    evidence = (qualification.evidence if qualification else []) or []
    sources = _sources_from(evidence)
    sections: list[ReportSection] = []

    # 1. What we know
    profile_bits = [
        f"Industry: {company.industry}" if company.industry else None,
        f"HQ: {company.hq_location}" if company.hq_location else None,
        f"Size: {company.revenue_band or company.employee_band}"
        if (company.revenue_band or company.employee_band)
        else "Size: not published",
        f"Products: {', '.join(company.products[:6])}" if company.products else None,
    ]
    sections.append(
        ReportSection(
            heading="Company profile",
            body=(company.description or "No description could be read from the site.")
            + "\n\n"
            + " · ".join(b for b in profile_bits if b),
            sources=[company.website] if company.website else [],
        )
    )

    # 2. Why it scored what it scored
    sections.append(
        ReportSection(
            heading="Qualification summary",
            body=summarise(company, events),
            sources=sources[:3],
        )
    )

    # 3. The Tedlar angle, derived from the pain themes actually found
    themes = [
        theme
        for theme in icp.PAIN_KEYWORDS
        if any(theme in (e.get("claim") or "").lower() for e in evidence)
    ]
    if themes:
        props = [icp.TEDLAR_VALUE_PROPS[t] for t in themes if t in icp.TEDLAR_VALUE_PROPS]
        angle = (
            f"They already market on {', '.join(themes)}, which means the durability "
            f"conversation is a product discussion rather than an education. Relevant "
            f"Tedlar positioning: " + " ".join(props)
        )
    else:
        angle = (
            "No durability claims were found in their public copy, so the opening has to "
            "establish the problem before the product. Lead with the cost of premature "
            "graphic failure rather than with film chemistry."
        )
    sections.append(ReportSection(heading="Tedlar angle", body=angle, sources=sources[:2]))

    # 4. Comparable accounts — the "who does this look like" question
    if lookalikes:
        lines = [
            f"{m['reference_name']} ({m['similarity'] * 100:.0f}% similar on "
            f"{', '.join(m['shared_terms'][:4])})"
            for m in lookalikes[:3]
        ]
        body = (
            "Closest known-good accounts: " + "; ".join(lines) + ". "
            "Reference the comparable account by name on the call — a converter is far "
            "more persuaded by what a peer does than by a spec sheet."
        )
    else:
        body = (
            "No close match to a reference account. This lead stands on its own ICP fit "
            "rather than on resemblance to a known win."
        )
    sections.append(ReportSection(heading="Comparable accounts", body=body))

    # 5. Who to talk to
    if contacts:
        lines = [
            f"{c.full_name}" + (f" — {c.title}" if c.title else "")
            + (" (placeholder data, not a real person)" if c.provider == "mock" else "")
            for c in contacts[:4]
        ]
        who = "\n".join(lines)
    else:
        who = (
            "No decision-maker resolved from public sources. Target titles for this ICP: "
            + ", ".join(icp.TARGET_TITLES[:5])
            + "."
        )
    sections.append(
        ReportSection(
            heading="Who to talk to",
            body=who,
            sources=[c.linkedin_url for c in contacts if c.linkedin_url][:3],
        )
    )

    # 6. Where the argument is weak — stated plainly
    gaps = [
        f"{part['label']}: {part['to_improve']}"
        for part in explain_company(company, events)
        if part.get("to_improve") and part.get("points", 0) == 0
    ]
    flags = (qualification.flags if qualification else []) or []
    risk_body = (
        "\n".join(f"• {g}" for g in gaps) if gaps else "• No major evidence gaps."
    )
    if flags:
        risk_body += "\n• Flags on the record: " + ", ".join(f.replace("_", " ") for f in flags)
    sections.append(ReportSection(heading="Gaps and risks", body=risk_body))

    return sections


def report_prompt(
    company: Company, sections: list[ReportSection], evidence: list[dict]
) -> str:
    facts = "\n\n".join(f"### {s.heading}\n{s.body}" for s in sections)
    evidence_block = "\n".join(
        f"- {e.get('claim')} -> {e.get('source_url')}" for e in (evidence or [])
    )
    return (
        f"Company: {company.name} ({company.website or 'no website'})\n\n"
        f"--- VERIFIED DOSSIER ---\n{facts}\n\n"
        f"--- EVIDENCE (claim -> source) ---\n{evidence_block or 'none'}\n\n"
        "Write the research briefing defined by the schema, using only the material above."
    )


RESEARCH_SYSTEM = """\
You write the pre-call research briefing a B2B seller reads before phoning a
prospect, for a DuPont Tedlar Graphics & Signage rep.

Absolute rules:
- Use ONLY the dossier and evidence supplied. You have no other knowledge of
  this company. Do not add facts, figures, customers, or news.
- Where the dossier says something is unknown, say it is unknown. A briefing
  that admits a gap is more useful than one that fills it confidently.
- Be concrete. "They serve the vehicle wrap market" beats "they are a leading
  player in graphics".
- Objections must be plausible and specific to this company's situation —
  price against incumbent laminates, existing supplier lock-in, volume too low
  for a specialty film. Not generic sales objections.
- The opener is one sentence, references one real detail from the dossier, and
  is not a question about their day.
"""
