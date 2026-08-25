# Tedlar Lead Agent — working notes

Lead generation and outreach for DuPont Tedlar, Graphics & Signage. Built as a
case study for InstaLILY. `README.md` is the full picture; this file is the set of
decisions worth knowing before changing anything.

## The one design rule

**Deterministic orchestration; the LLM only does fuzzy work.** Scoring, dedup,
retries, persistence, filtering and provider selection are plain Python. The model
reads messy pages and writes prose over facts the pipeline already verified. If a
change moves a decision from code into a prompt, it is going the wrong way.

## Non-negotiables

- **Every claim carries the URL it came from.** Not the company's homepage by
  default — the URL the fact was actually read from. A revenue figure from an
  aggregator cites the aggregator and is labelled a third-party estimate.
- **Unknown stays unknown.** Missing revenue costs confidence; it never earns a
  guessed band. The extraction prompt is null-preferring and forbidden from
  inferring.
- **Placeholder data must be unmistakable.** Mock contacts render at 0.0
  confidence with a `mock` badge; template outreach is labelled `template`.
  Never remove those labels to make a demo look better.
- **Failures are data.** Per-record work goes through `ctx.attempt` / `ctx.guard`
  in `app/pipeline/context.py`; expected failures become `StageError` rows and the
  run continues. A crash is a bug, not an outcome.
- **Do not defeat anti-bot measures.** MapYourShow (ISA Sign Expo, PRINTING United)
  blocks server-side clients *and* headless browsers. That is recorded as a miss.
  Fingerprint evasion is out of scope — use a licensed data source instead.

## Layout

```
backend/app/
  pipeline/runner.py      orchestrator; stages in pipeline/stages/
  pipeline/context.py     RunContext + the error-isolation primitive
  scoring/icp.py          the ICP as data — vocab, weights, bands, target titles
  scoring/score.py        pure mechanism; never edit weights here
  services/               http+cache, extract, dedupe, search/, llm/
  integrations/contacts/  ContactProvider chain (public_web, apollo, clay, …)
  api/                    FastAPI routes + response schemas
  preflight.py            verify configured providers with one real call each
frontend/src/             Next.js dashboard; tokens in app/globals.css
```

Retargeting the pipeline at a different business unit should be an edit to
`scoring/icp.py` and the query templates, not to the stages.

## Conventions

- Python 3.11+, uv, ruff (line length 100), pytest. Type hints throughout.
- Comments explain *why*, especially where a naive implementation is wrong —
  those comments usually record a real bug that was hit.
- New provider? Implement the Protocol, register it in the package `__init__`,
  gate it on `is_configured()`. No caller changes.

## Tests

- **The suite is hermetic.** `tests/conftest.py` blanks every credential env var,
  so no test can read a real `.env` or spend API credits. Keep it that way.
- No network. HTTP goes through `httpx.MockTransport`; the LLM through a stub.
- 128 tests run in well under a second. If a test needs a real sleep or a real
  request, it is testing the wrong thing.

## Commands

```bash
cd backend && uv sync                          # dev tooling included (dependency group)
uv run python -m app.preflight                 # check the configured providers
uv run python -m app.pipeline.runner           # cached replay, seconds
uv run python -m app.pipeline.runner --live    # real fetch, ~6 min
uv run pytest -q && uv run ruff check .
uv run uvicorn app.main:app --port 8000        # API
cd frontend && npm run dev                     # dashboard on :3000
```

Do not run the CLI and the API server against the database at the same time —
SQLite allows one writer, and the loser blocks until `busy_timeout`.

## Docs are generated

`docs/results.json` comes from `backend/results_snapshot.py`; the deck
(`build_deck.js`) and the write-up read from it. Re-run the snapshot after a
pipeline run rather than hand-editing numbers into the documents.
