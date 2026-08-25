# Tedlar Lead Agent

Lead generation and outreach for **DuPont Tedlar — Graphics & Signage**: find the
events and associations where Tedlar's ICP gathers, source the companies, enrich
them from their own websites, score them transparently, identify decision-makers,
and draft evidence-grounded outreach — then put the whole thing behind a dashboard
a rep can actually work from.

Built as a case study. The design bias throughout is **deterministic orchestration
with the LLM confined to fuzzy judgment**: scoring, deduplication, retries,
persistence and filtering are plain Python, and the model only reads messy pages
and writes prose over facts the pipeline already verified.

---

## Quick start

```bash
git clone <repo> && cd instalily-case-study
```

**Backend**

```bash
cd backend && uv sync && cp ../.env.example ../.env
```

Run the pipeline against the committed HTTP snapshot — no API keys required:

```bash
cd backend && uv run python -m app.pipeline.runner --mode cached
```

Serve the API:

```bash
cd backend && uv run uvicorn app.main:app --port 8000
```

**Frontend**

```bash
cd frontend && npm install && npm run dev
```

Open <http://localhost:3000>.

**Check your integrations before spending a run on them**

```bash
cd backend && uv run python -m app.preflight
```

Makes the smallest real call each configured provider offers, reports what it
found, never prints a secret, and exits non-zero if anything a run depends on is
broken. `--strict` also fails on warnings, which makes it usable as a CI smoke
test.

**Tests and lint**

```bash
cd backend && uv run pytest -q && uv run ruff check .
```

### Keys (optional, and worth it)

Everything above runs with an empty `.env`. Two keys unlock the rest:

| Variable | Effect when set |
|---|---|
| `ANTHROPIC_API_KEY` | Enrichment reads pages with Claude instead of keyword matching; qualification rationales and outreach emails are model-written instead of templated. |
| `APOLLO_API_KEY` (+ `CONTACT_PROVIDERS=apollo,public_web,mock`) | Real decision-makers with LinkedIn URLs, instead of mock placeholders. |
| `SERPER_API_KEY` (+ `SEARCH_PROVIDER=serper`) | Company discovery, website resolution, revenue lookup and LinkedIn contact search all switch to a real search index. |

With neither, every one of those paths has a deterministic fallback and the run
still completes — that is the point of the fallbacks, and the dashboard header
tells you which mode you are in.

---

## What it does

```
                        ┌──────────────────────────────────────────┐
  CLI ──┐               │            PipelineRunner                │
        ├──────────────▶│  sequential stages, per-record isolation │
  API ──┘               └──────────────────────────────────────────┘
                                          │
   1. discover_events    seed roster verified live + search expansion
   2. extract_companies  exhibitor directories ∪ ICP search ∪ ICP roster
   3. dedupe/normalise   registrable domain, then fuzzy legal-name match
   4. enrich_companies   fetch the company's own site → structured facts
   5. qualify            deterministic 0–100 score + evidence-bound rationale
   6. find_contacts      ContactProvider chain (public web → Clay → Sales Nav)
   7. draft_outreach     LLM draft, validated against the evidence set
                                          │
                     SQLite ◀─────────────┴─────────────▶ StageError log
                        │
                     FastAPI ──▶ Next.js dashboard
```

Every stage takes a typed input and returns a typed output. A record that fails
gets a `StageError` row and `status="incomplete"`; the run continues. **Partial
success is the normal outcome — a crash is a bug.**

---

## Lead scoring

A transparent 0–100 score, computed in `backend/app/scoring/score.py`, with the
ICP itself living as data in `backend/app/scoring/icp.py`.

| Component | Max | What earns it |
|---|---:|---|
| Industry fit | 30 | Tiered ICP vocabulary in the company's own positioning (tier-1: signage, graphic films, vehicle wrap; tier-2: commercial printing, outdoor advertising) |
| Application fit | 25 | Tedlar application areas in products and site copy — outdoor signage, fleet/transit graphics, architectural graphics, overlaminates |
| Company size | 15 | Revenue bands, falling back to headcount bands |
| Event engagement | 15 | Named on an exhibitor directory, or the company's own site says it exhibits |
| Pain-point alignment | 15 | Already markets on UV / weather / graffiti / chemical resistance, cleanability, graphic lifespan |

Tier A ≥ 75, B ≥ 60, C ≥ 40, below that disqualified.

**The LLM never produces the number.** It receives the finished breakdown and the
evidence list, and writes the rationale. Two guards run after it:

- every URL it cites must be one we supplied, or the record is flagged
  `cited_unknown_source`;
- any sentence making a numeric claim we cannot match to a known figure is
  removed and the record flagged `unsupported_claim_removed`.

`confidence` is the share of scoring components backed by a source URL, penalised
for a missing website, missing size data, an unenriched record, or a size figure
that came from a third-party aggregator rather than the company itself. A company with
a high score and low confidence is visibly that, in the table and in the detail
panel.

---

## Data, and where it comes from

Real, fetched, and cached. Every HTTP response the pipeline ever received is
written to `backend/data/raw/` keyed by URL hash, with a sidecar recording the
URL, status code and fetch time. A `--mode cached` run replays that snapshot, so
the demo is reproducible offline and a re-run costs nothing.

Company sourcing runs three independent channels because, in practice, each one
fails differently:

1. **Exhibitor directory scrape.** Works on plain-HTML directories. The flagship
   shows (ISA Sign Expo, PRINTING United) front their lists with a JavaScript app
   over an API that rejects server-side clients — those record a miss in the error
   log rather than pretending.
2. **ICP-shaped search.** The channel that scales: new vertical, new query
   templates. Recall depends entirely on the search provider.
3. **Verified ICP roster** (`backend/app/pipeline/stages/icp_roster.py`). Names
   and public URLs only — the pipeline still fetches every site and derives every
   fact from what it reads. This is the one hand-curated input, and it exists
   because channels 1 and 2 both under-deliver on category leaders without a paid
   search key. It is deliberately the cheapest part to delete.

---

## Contact enrichment

`ContactProvider` is a `Protocol` with two methods: `find_contacts` and
`is_configured`. The chain is resolved from `CONTACT_PROVIDERS` and tried in
order; unconfigured providers are skipped, never crashed on.

| Provider | State |
|---|---|
| `ApolloProvider` | Working, credential-gated. **Note:** Apollo gates *people search* behind paid plans — on the free tier it returns 403 and the chain falls through to the next provider. Its *organization* endpoint is open on free, and the pipeline uses it for firmographics (revenue, headcount, HQ, industry keywords), which is what lifts the size component off zero. Real named decision-makers with LinkedIn URLs on a free tier — the fastest way to fill the "who do I actually email" gap. Set `APOLLO_API_KEY` and put `apollo` first in the chain. |
| `PublicWebContactProvider` | Working. Follows the site's own navigation to leadership pages, plus site-restricted LinkedIn search when a search provider is configured. |
| `MockContactProvider` | Deterministic fixtures for tests and offline demos. Always `confidence=0.0` and `provider="mock"` so placeholder data can never be mistaken for sourced data. |
| `ClayProvider` | Complete but credential-gated. Implements the real table-webhook → poll/callback flow. Set `CLAY_API_KEY` + `CLAY_WEBHOOK_URL`. |
| `SalesNavigatorProvider` | Complete but credential-gated. Implements the SNAP `salesApiLeadSearch` call shape. Scraping Sales Navigator would breach LinkedIn's terms, so without a partner token the provider contributes exactly one thing: a pre-filtered Sales Navigator search deep link a licensed rep can click. |

Adding Clay to a live deployment is `CONTACT_PROVIDERS=clay,public_web` plus the
two secrets. No caller changes.

---

## Outreach

Drafted only for tier A/B leads that have both a contact and at least one piece of
evidence. The model gets verified facts, their source URLs, the score breakdown,
the contact's title, and the Tedlar value-prop list — and must return the hook
fact it used plus the URL it came from.

`validate()` then rejects the draft if the hook cites a URL outside the supplied
evidence, the body runs long, the subject runs long, or the copy contains banned
filler ("hope this finds you well", "quick question", "circle back", …). A draft
that fails falls back to a deterministic template built from the same evidence,
and the dashboard labels which is which.

---

## API

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/health` | Liveness plus which providers are configured |
| `GET` | `/api/summary` | Dashboard metrics |
| `GET` | `/api/events` | Events and associations, with company counts |
| `GET` | `/api/leads` | Lead rows; filter by `tier`, `event_id`, `min_score`, `industry`, `q`, `has_contact` |
| `GET` | `/api/leads/{id}` | One lead with evidence, contacts and drafts |
| `PATCH` | `/api/outreach/{id}` | Save an edit / toggle approval |
| `GET` | `/api/errors` | The stage error log |
| `POST` | `/api/pipeline/run` | Start a run (`cached` or `live`) |
| `GET` | `/api/runs/{id}` | Poll stage progress |

Interactive docs at `/docs`.

---

## Error handling

| Failure | Behaviour |
|---|---|
| HTTP 429 / 5xx / timeout | Exponential backoff, up to 3 attempts, `Retry-After` honoured |
| HTTP 404 / 403 | Not retried — recorded as a permanent miss |
| Live fetch fails, cache has a stale copy | Serve the stale copy and log it |
| Permanent fetch failure (403/404/timeout) | Recorded *into* the cache, so a `--mode cached` replay reproduces the original error rather than reporting a cache miss |
| Malformed LLM JSON | One repair round-trip carrying the validator error, then the record degrades |
| No API key | Deterministic fallback path for every LLM and search call |
| Duplicate companies | Registrable-domain key, then normalised-name fuzzy match ≥ 0.90 |
| Hallucinated claim | Stripped from the rationale, record flagged |
| A stage raising outright | Recorded, marked `failed`, later stages still run |

All of it is visible in the dashboard's error tab — the point is that failures are
data, not silence.

---

## Measured results

A full live run with Anthropic, Serper and Apollo configured:

| | Value |
|---|---|
| Companies sourced / enriched | 98 / 91 |
| Qualified leads (tier A/B) | 6 |
| Named decision-makers, with LinkedIn URLs | 11 |
| Outreach drafts (LLM-written, evidence-validated) | 11 |
| Wall clock | 6.2 min |
| LLM calls / estimated cost | 108 / $0.59 |
| **Cost per qualified lead** | **$0.098** |

The same corpus took **29.7 minutes and 185 LLM calls** before enrichment and
qualification were parallelised and reasoning-model rationales were gated to
qualified tiers — 4.8x faster on 42% fewer calls, with identical lead output.

## Performance and unit economics

Enrichment is almost entirely network wait — four or five fetches plus an LLM call
per company, each against a different host — so it runs **bounded-concurrent**
(`PIPELINE_CONCURRENCY`, default 6) rather than one company at a time. The fetcher
keeps its own global cap and a per-host delay underneath, so parallelism happens
*across* hosts and no single site sees a burst.

LLM spend is targeted rather than uniform: **only tier A/B leads earn a
reasoning-model rationale**. On a wide run most of the corpus is disqualified, and
writing prose about a company that scored 12/100 spends Sonnet tokens on something
no rep will open — those still get a deterministic rationale from the same score
breakdown. Extraction runs on Haiku throughout.

Every run records LLM token usage and an estimated cost, and the dashboard turns
that into **cost per qualified lead** — the number a GTM team actually budgets
against. It is on `PipelineRun.counts` and `/api/summary`.

Prompt caching is deliberately *not* used: the system prompts here are a few
hundred tokens, well under the ~1024-token minimum cacheable prefix, so it would
add complexity and cache nothing.

## Scaling

- Bounded async throughout: a global concurrency semaphore plus a per-host lock
  and delay, so a 60-company enrichment pass never looks like an attack.
- Per-record isolation already exists in every stage, so moving to a task queue
  means enqueuing the same coroutines — no stage code changes.
- The ICP lives entirely in `scoring/icp.py`. Retargeting at a different Tedlar
  business unit, or a different client, is a config edit.
- `DATABASE_URL` is the only thing standing between SQLite and Postgres.

## Known limitations

- MapYourShow-backed exhibitor directories are JavaScript-gated and their API
  rejects server-side clients; a headless browser would be the fix.
- Without a paid search key, discovery recall on category leaders is thin — hence
  the roster channel.
- SQLite allows one writer. A CLI run and the API server writing at once contend
  for the lock; a 10s `busy_timeout` turns that into a visible error rather than a
  hang, and the API's own "Run lead discovery" button is the contention-free path.
  Postgres removes the constraint entirely.
- A live run is deliberately slow — a global concurrency cap plus a one-second
  per-host delay. Cached replays take seconds.
- Revenue is frequently unknown, because most private companies never publish it.
  The scorer treats that as a confidence penalty rather than guessing. Figures that
  do come from third-party aggregators are labelled as such in the evidence, and a
  name guard drops results for similarly-named but different companies (Briteline
  the graphic-films firm vs. Briteline Extrusions the plastics firm).

## Repository layout

```
backend/app/
  models/       domain + enums + run bookkeeping
  pipeline/     runner, run context, seven stages
  scoring/      icp.py (the ICP as data), score.py (the scorer)
  services/     http + cache + extract + dedupe + search + llm
  integrations/ contacts/ (public web, mock, Clay, Sales Navigator)
  api/          FastAPI routes and response schemas
backend/data/raw/   committed HTTP snapshot
backend/tests/      77 tests, no network
frontend/src/       Next.js dashboard
docs/               write-up and deck
```
