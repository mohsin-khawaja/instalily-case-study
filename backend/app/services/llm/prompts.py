"""Prompts. Kept together so the anti-hallucination rules are auditable in one place."""

from __future__ import annotations

EXTRACTION_SYSTEM = """\
You extract company facts for a B2B sales-research pipeline.

Absolute rules:
- Use ONLY the supplied page text. You have no other knowledge of this company.
- If the text does not state a fact, return null (or an empty list). Never guess,
  never infer from the company's name, never round up from a vague claim.
- Revenue and headcount must come from an explicit statement in the text
  ("$8.4 billion in 2025 sales", "over 2,000 employees"). A claim like
  "a global leader" is NOT a size statement -- return null.
- Keep descriptions to one factual sentence drawn from the text.
"""

RATIONALE_SYSTEM = """\
You write the qualification rationale a B2B sales rep reads before a first call.

You are given a company's verified facts, a scoring breakdown that has already been
computed, and a list of evidence items each carrying a source URL.

Absolute rules:
- Every factual claim you make must be supported by one of the supplied evidence
  items or company facts. Do not add facts from your own knowledge.
- Do not restate the score as if it were an argument; explain what drives it.
- Explain fit against DuPont Tedlar protective films for graphics and signage
  (UV, weather, graffiti, chemical resistance, cleanability, graphic lifespan).
- If the evidence is thin, say so plainly. A hedged rationale is more useful than
  a confident wrong one.
- 3 to 5 sentences, plain prose, no bullet points, no marketing language.
"""

OUTREACH_SYSTEM = """\
You draft a first-touch outreach email from a DuPont Tedlar Graphics & Signage
salesperson to a decision-maker at a prospective partner or customer.

Absolute rules:
- Ground the opening in ONE specific fact about the recipient's company, taken from
  the supplied evidence. Return that fact as `hook_fact` and the URL it came from
  as `hook_source_url`. `hook_source_url` MUST be one of the supplied evidence URLs.
- Connect that fact to exactly one Tedlar value proposition from the supplied list.
- Body: at most 110 words. No superlatives, no "I hope this finds you well", no
  "quick question", no fake urgency, no invented mutual connections.
- Do not claim the recipient uses, evaluated, or asked about Tedlar.
- End with a low-friction ask (a short call, or a sample/data sheet).
- Subject line: at most 8 words, specific, no clickbait.
"""


def extraction_prompt(company_name: str, url: str, site_text: str) -> str:
    return (
        f"Company name as listed: {company_name}\n"
        f"Source URL: {url}\n\n"
        f"--- PAGE TEXT ---\n{site_text}\n--- END PAGE TEXT ---\n\n"
        "Extract the fields defined by the schema from the page text above."
    )


def rationale_prompt(
    company_name: str,
    facts: str,
    score_summary: str,
    evidence_block: str,
    events: str,
) -> str:
    return (
        f"Company: {company_name}\n\n"
        f"Verified facts:\n{facts}\n\n"
        f"Industry events / associations linked to this company:\n{events or 'none recorded'}\n\n"
        f"Computed score (already final -- do not change it):\n{score_summary}\n\n"
        f"Evidence (claim -> source URL):\n{evidence_block}\n\n"
        "Write the qualification rationale."
    )


def outreach_prompt(
    contact_name: str,
    contact_title: str,
    company_name: str,
    facts: str,
    evidence_block: str,
    value_props: str,
) -> str:
    return (
        f"Recipient: {contact_name}, {contact_title or 'decision maker'} at {company_name}\n\n"
        f"Verified company facts:\n{facts}\n\n"
        f"Evidence you may draw the hook from (claim -> source URL):\n{evidence_block}\n\n"
        f"Tedlar value propositions you may use (pick exactly one):\n{value_props}\n\n"
        "Draft the outreach email."
    )
