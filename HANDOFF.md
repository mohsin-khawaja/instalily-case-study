# Handoff — Tedlar Lead Agent

Continue from here in a new chat. Everything below is current as of the last commit.

## Where things are

- **Repo:** `~/Desktop/instalily-case-study` — GitHub `mohsin-khawaja/instalily-case-study`
- **Submission zip:** `~/Desktop/instalily-case-study-submission.zip`
- **Docs:** `docs/Tedlar-Lead-Agent-Writeup.pdf` (3 pages), `docs/Tedlar-Lead-Agent.pptx` (9 slides)
- **Deadline:** Thursday 27 Aug 2026, 8:18 PM EDT

## Running it

```bash
cd backend && uv run uvicorn app.main:app --port 8000     # API
cd frontend && npm run dev                                 # dashboard on :3000
cd backend && uv run python -m app.preflight               # verify providers
```

Demo on **Cached run** — deterministic. A live run costs ~10 min and ~$0.85 and
will reshuffle which companies are found.

## Current shipped snapshot

97 companies · 90 enriched · 16 qualified (6 tier A, 10 tier B) · 32 contacts ·
29 drafts · 10 events (3 dated) · 165 tests · cost/qualified lead ~$0.04

## What exists

Seven-stage pipeline presented as six named agents (`backend/app/agents.py`,
Agents tab). Per-component score explanations. Lookalike modelling against
reference accounts. On-demand prospect research reports. Gmail compose
deep-links plus .eml export (MailSuite tracks once sent). CSV export with
provenance. Clay and Sales Navigator providers written and credential-gated.

## Known gaps, in priority order

1. **The .pptx has never been visually rendered.** No LibreOffice on this
   machine — it passes XSD validation and a geometry check, but nobody has
   looked at the slides. **Open it before submitting.**
2. **Run-to-run variance.** Serper ranking drifts, so the lead set changes
   between live runs. Avery Dennison has scored 48, 61, 73 across runs. Demo
   cached.
3. **No contact has a verified email** (0/32) — Apollo gates people search on
   the free tier. The UI says so rather than guessing.
4. **Signals ("why now") is designed, not built** — `docs/signals-plan.md`.
   Deliberately deferred; presented as roadmap.
5. **No won/deal model.** Lookalikes work off seeded reference accounts, not
   closed-won records. `REFERENCE_ACCOUNT_DOMAINS` in `scoring/icp.py`.
6. Data drifts from docs whenever a run happens — re-run
   `backend/results_snapshot.py` and rebuild the deck/PDF afterwards.

## Rules that must not be broken

In `CLAUDE.md`, but the load-bearing ones: every claim carries the URL it was
actually read from; unknown stays unknown (never a guessed band); placeholder
data stays labelled and never receives outreach; failures become StageError rows
and the run continues; do not defeat anti-bot measures.
