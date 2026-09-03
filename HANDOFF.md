# Handoff — Tedlar Lead Agent

Everything below is current as of commit `2c11f55`. The project is **complete
against the brief**; what remains is presentation and final checks, not features.

## Orientation

| | |
|---|---|
| Repo | `~/Desktop/instalily-case-study` → GitHub `mohsin-khawaja/instalily-case-study` |
| Submission zip | `~/Desktop/instalily-case-study-submission.zip` (39MB, rebuild after any change) |
| Deliverables | `docs/Tedlar-Lead-Agent-Writeup.pdf` (3 pages), `docs/Tedlar-Lead-Agent.pptx` (9 slides) |
| Run-of-show | `docs/presentation-plan.md` — 6-minute video plan, beat by beat |
| Roadmap | `docs/signals-plan.md` — designed, deliberately not built |
| Deadline | Thursday 27 Aug 2026, 8:18 PM EDT |

## Running it

```bash
cd backend && uv run uvicorn app.main:app --port 8000   # API on :8000
cd frontend && npm run dev                               # dashboard on :3000
cd backend && uv run python -m app.preflight             # verify every provider
cd backend && uv run pytest -q && uv run ruff check .    # 165 tests, no network
```

**Demo on `Cached run`** — deterministic. A live run costs ~10 min and ~$0.85 and
reshuffles which companies are found.

## Shipped snapshot

97 companies · 90 enriched · **16 qualified (6 tier A, 10 tier B)** · 32 contacts
(all with Sales Navigator links) · 29 drafts (28 LLM-written) · 10 events ·
165 tests · ~$0.04 per qualified lead.

## What exists

Six-stage pipeline, one named agent per stage (`backend/app/agents.py`,
Agents tab in the dashboard). Per-component score explanations with matched
terms and source URLs. Lookalike modelling against reference accounts. On-demand
prospect research reports. Gmail compose deep-links plus `.eml` export
(MailSuite tracks once sent). CSV export with provenance columns. Clay and Sales
Navigator providers written and credential-gated.

## Open items, in priority order

1. **The `.pptx` has never been visually rendered.** No LibreOffice on this
   machine — it passes XSD validation and a geometry check, but nobody has
   looked at the slides. **Open it before submitting.** This is the only real
   risk left.
2. **Run-to-run variance.** Serper's ranking drifts, so the lead set changes
   between live runs — Avery Dennison has scored 48, 61, 73 and 76 across runs.
   Demo cached.
3. **No contact has a verified email** (0/32). Apollo gates people search on the
   free tier. The UI says so explicitly rather than guessing an address.
4. **Docs drift from data after any run.** Re-run `backend/results_snapshot.py`,
   then rebuild the deck (`docs/build_deck.js`) and the PDF.
5. Signals ("why now") and a won/deal model are designed, not built. Present as
   roadmap.

## Rules that must not be broken

Full set in `CLAUDE.md`. The load-bearing ones:

- Every claim carries the URL it was **actually read from**, not the homepage.
- **Unknown stays unknown.** Missing revenue costs confidence; it never earns a
  guessed band.
- **Placeholder data stays labelled** and never receives outreach.
- **Failures are data** — they become `StageError` rows and the run continues.
- **Do not defeat anti-bot measures.** MapYourShow blocks server-side clients
  and headless browsers; that is recorded as a miss.
- Deterministic orchestration; the LLM only does fuzzy work. If a change moves a
  decision from code into a prompt, it is going the wrong way.

## Recent history worth knowing

Several defects were found by testing against the brief's own example account
rather than by inspection — a pain vocabulary too literal to match a company
that says "warranty" but never "year warranty"; an enrichment order that spent
the firmographics quota alphabetically; a name guard that rejected the very
pages answering the question. Avery Dennison went 48 → 76 as a result, and
corpus-wide qualified leads went 6 → 16. If something looks wrong in the data,
test it against a known-good account first.
