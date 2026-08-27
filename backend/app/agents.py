"""The agent roster.

Each pipeline stage is a specialist agent with a narrow job, an explicit
boundary on what it may decide for itself, and a defined behaviour when its
tools are unavailable. This module is the single place that describes them, so
the dashboard, the API and the write-up all read from one definition rather
than three descriptions that drift apart.

The design point worth stating plainly: **these agents are deterministic
orchestration with the LLM confined to fuzzy sub-tasks.** An agent decides
*what to do next* in Python — which pages to fetch, which provider to try, when
to stop, what a record scores. It delegates to the model only where judgement
over messy language is genuinely needed: reading a web page, writing prose over
facts already verified. That boundary is what makes the output reproducible and
arguable rather than merely plausible.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from .models.enums import StageName


@dataclass(frozen=True)
class Agent:
    """One specialist in the chain."""

    stage: str
    name: str
    mission: str
    #: Decisions this agent makes on its own, in code.
    decides: list[str] = field(default_factory=list)
    #: Where it hands off to the model, and what it is forbidden to invent.
    delegates_to_llm: str | None = None
    #: What it does when a tool, provider or model is unavailable.
    degrades_to: str = "Records a StageError against the record and continues."
    #: The guardrail that stops it doing damage.
    guardrail: str = ""
    #: Keys in `PipelineRun.counts` this agent is responsible for.
    metrics: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return asdict(self)


AGENTS: list[Agent] = [
    Agent(
        stage=StageName.DISCOVER_EVENTS.value,
        name="Event Research Agent",
        mission=(
            "Find the trade shows, expos and industry bodies where Tedlar's ideal "
            "customers physically gather, and prove each one is real."
        ),
        decides=[
            "Which seeded institutions to verify against their live site",
            "Whether a search result is an event or a listicle about events",
            "One event per host, so a show's own site cannot flood the roster",
        ],
        delegates_to_llm=None,
        degrades_to=(
            "An unreachable event is kept and marked unverified rather than dropped — "
            "a 403 from a bot wall is not evidence the show does not exist."
        ),
        guardrail="Every event carries the URL it was verified at, plus a fetch timestamp.",
        metrics=["events"],
    ),
    Agent(
        stage=StageName.EXTRACT_COMPANIES.value,
        name="Company Sourcing Agent",
        mission=(
            "Assemble the candidate pool from three independent channels, then "
            "collapse it to one row per real company."
        ),
        decides=[
            "Which of exhibitor directories, ICP search and the verified roster to draw on",
            "Whether a link is an exhibitor or the venue's hotel partner",
            "Deduplication: registrable domain first, then fuzzy legal name at 0.90",
        ],
        delegates_to_llm=None,
        degrades_to=(
            "A JavaScript-gated directory yields nothing and the miss is recorded; the "
            "other two channels carry the run."
        ),
        guardrail=(
            "Marketplaces, job boards and the shows' own domains can never enter the "
            "company pool."
        ),
        metrics=["company_candidates", "companies_after_dedupe", "companies"],
    ),
    Agent(
        stage=StageName.ENRICH_COMPANIES.value,
        name="Enrichment Agent",
        mission=(
            "Build a factual profile of each company from its own website, plus "
            "firmographics where a provider can supply them."
        ),
        decides=[
            "Which pages to crawl — follows the site's own navigation rather than guessing paths",
            "Enrichment order: flagship accounts first, so scarce API quota reaches them",
            "Whether to trust a size figure, and whether to record it as first- or third-party",
        ],
        delegates_to_llm=(
            "Reading the crawled text into structured fields. The extraction prompt is "
            "null-preferring and forbidden from inferring: 'a global leader' is not a "
            "size statement."
        ),
        degrades_to=(
            "Falls back to keyword extraction with no model at all, and to search "
            "snippets when the firmographics provider is rate limited."
        ),
        guardrail=(
            "Unknown stays unknown. A missing revenue costs the lead confidence; it "
            "never earns a guessed band."
        ),
        metrics=["companies_enriched", "event_links"],
    ),
    Agent(
        stage=StageName.QUALIFY.value,
        name="Qualification Agent",
        mission=(
            "Score every company against the ICP and explain the number in terms a "
            "sales manager can argue with."
        ),
        decides=[
            "The entire 0-100 score, in Python — the model never produces it",
            "Confidence, computed separately from score as the share of URL-backed components",
            "Which tier, and therefore which leads are worth spending contact budget on",
        ],
        delegates_to_llm=(
            "Writing the rationale over a finished breakdown — and only for tier A/B, "
            "because prose about a company scoring 12/100 is spend nobody reads."
        ),
        degrades_to="A deterministic rationale assembled from the same breakdown.",
        guardrail=(
            "A cited URL outside the supplied evidence flags the record; any sentence "
            "making a numeric claim we cannot match to a known figure is removed."
        ),
        metrics=["qualifications", "qualified_leads"],
    ),
    Agent(
        stage=StageName.FIND_CONTACTS.value,
        name="Stakeholder Agent",
        mission=(
            "Find named decision-makers at qualified accounts, with a Sales Navigator "
            "link a rep can act on."
        ),
        decides=[
            "Provider order — the waterfall: Apollo, then public web, then mock",
            "Whether a profile actually belongs to this company or merely mentions it",
            "Ranking by function as well as seniority, so product and R&D outrank finance",
        ],
        delegates_to_llm=None,
        degrades_to=(
            "A provider that answers 403 or 429 retires itself for the rest of the run "
            "and the chain moves on."
        ),
        guardrail=(
            "Only tier A/B accounts get contact spend, and a surname matching the "
            "company name is not accepted as proof of employment."
        ),
        metrics=["contacts", "companies_with_contacts"],
    ),
    Agent(
        stage=StageName.DRAFT_OUTREACH.value,
        name="Outreach Agent",
        mission=(
            "Write a short, specific first-touch email grounded in one verified fact "
            "about the recipient's business."
        ),
        decides=[
            "Which evidence item makes the strongest hook",
            "Which Tedlar value proposition the hook connects to",
            "Whether a draft is fit to ship, or must fall back to a template",
        ],
        delegates_to_llm=(
            "Writing the email. The model must return the hook fact and the URL it "
            "came from, both drawn from the supplied evidence."
        ),
        degrades_to="A deterministic template built from the same evidence, labelled as such.",
        guardrail=(
            "A hook citing a URL we did not supply is rejected. No email is ever "
            "addressed to a placeholder contact — an invented recipient reads as real "
            "and could be sent."
        ),
        metrics=["outreach_drafts"],
    ),
]

AGENTS_BY_STAGE: dict[str, Agent] = {agent.stage: agent for agent in AGENTS}
