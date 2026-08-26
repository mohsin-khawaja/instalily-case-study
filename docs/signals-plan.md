<!-- Roadmap: designed, not built. See README 'Where this sits in the GTM stack'. -->

# Buying Signals — design plan

## Context

The tool answers *"is this a good fit?"* well: a transparent 0–100 score across
five components, every claim carrying the URL it came from. It has no answer at
all to *"why now?"* — which is the question that decides whether a rep calls this
week or next quarter.

Trigger signals (a new COO, a hiring spike, a product launch) are that missing
axis. They are also the highest-risk thing to add, because a signal is a claim
about *time* and an LLM will happily assert "recently expanded" about a 2019
press release. The design below treats a date and a source URL as the price of
admission for a signal existing at all.

Three findings from reading the current code shape the plan:

1. **`Company` has no history.** Every field is overwritten each run
   (`models/domain.py`). "Headcount grew 20%" and "new VP of Product" are
   currently undetectable in principle, not just unimplemented.
2. **The pages where trigger events get announced are not crawled.**
   `SUBPAGE_KEYWORDS` in `pipeline/stages/enrich_companies.py` targets identity,
   product and durability pages — not `/news`, `/press`, `/careers`.
3. **Search has no recency control.** `services/search/serper.py` posts
   `{"q", "num"}` with no `tbs` date restriction, so "recent" is unexpressible.

### Decisions locked
- **Fit × Signal as two axes.** The 0–100 fit score stays untouched.
- **Record our own snapshots, starting immediately** — change detection works
  from the second run, so the recording has to land first.
- **Local sentence-transformer embeddings**, used to retrieve the best-matching
  sentence as evidence, not to replace keyword anchors.

---

## 1. Signal taxonomy

Ranked by value to *this* ICP × how reliably we can source it.

### Tier 1 — highest value, sourceable free

| Signal | Why it matters for Tedlar | Half-life |
|---|---|---|
| **Leadership change** in a buying role (VP/Director of Product, R&D, Innovation, Materials, Operations, COO) | New leaders re-evaluate suppliers in their first two quarters. The single strongest B2B trigger. | 120 d |
| **Product / portfolio launch** into durable, outdoor, protective or overlaminate lines | *The* Tedlar-specific trigger: new SKUs that need a protective layer, decided now. | 180 d |
| **Durability or warranty claim change** — extending a warranty, launching a "10-year outdoor" line | They have just publicly committed to the exact performance Tedlar underwrites. | 180 d |

### Tier 2 — high value, needs the careers page or history

| Signal | Why | Half-life |
|---|---|---|
| **Hiring in relevant functions** — R&D, chemist, coatings, laminating, converting, wide-format, quality | Hiring a laminating engineer is capacity expansion in Tedlar's application space. | 90 d |
| **Headcount trajectory** (from snapshots) | Growth is budget; contraction is the opposite. Needs run-over-run history. | 180 d |
| **Facility / capacity investment** — new plant, new coating or laminating line | Capital committed to converting capacity. | 270 d |

### Tier 3 — contextual

| Signal | Why | Half-life |
|---|---|---|
| **Upcoming event participation** with a date | Turns event fit into an outreach window: "see you at ISA". | to event date |
| **Certification / sustainability / PVC-reduction commitment** | Tedlar is PVF, not PVC — a stated PVC-reduction goal is a direct opening. | 270 d |
| **Funding / M&A / ownership change** | New capital and a supplier re-evaluation. | 180 d |

### Negative signals — represented, never hidden

Layoffs, plant closure, insolvency, acquisition-by-competitor. These carry
`direction = -1` and **suppress** priority. A system that can only find reasons
to call is a system nobody trusts twice.

---

## 2. Architecture: two axes, never merged

Fit stays exactly as it is. Signal is computed independently and decays:

```
signal_score = Σ over signals of  base_strength × direction × 0.5^(age_days / half_life)
               capped to 0–100, negative signals subtract
```

The pair drives a **recommended action**, which is what the dashboard sorts by:

| | Hot signal (≥40) | Warm (15–39) | Quiet (<15) |
|---|---|---|---|
| **Fit A/B** | **Act now** | Prioritise | Nurture |
| **Fit C** | Watch | Watch | Park |
| **Out of ICP** | Ignore | Ignore | Ignore |

The bottom row matters: a hiring spike at a company that does not serve Tedlar
applications is still not a lead. Signals must never promote a bad fit.

**Outreach gets a second hook type.** `draft_outreach.py` already requires the
model to return `hook_fact` + `hook_source_url` drawn from supplied evidence. A
dated signal is a *better* hook than a static fact ("I saw you appointed a new
VP of Product in March") and slots into the existing validator unchanged — the
signal's `source_url` simply joins the allowed set.

---

## 3. Data model

Two new tables in `backend/app/models/domain.py`, following the existing
SQLModel + JSON-column pattern.

```python
Signal:
    id, company_id, signal_type (enum), direction (+1 / -1)
    headline            # one line, extracted not invented
    detail              # supporting sentence, quoted from the source
    source_url, source_title
    event_date          # when it HAPPENED — the load-bearing field
    date_confidence     # exact | approximate | unknown
    observed_at         # when WE saw it
    base_strength       # from the catalog, before decay
    semantic_score      # similarity to the type's reference phrasings
    provider            # site_crawl | search | snapshot_diff | clay | ...
    status, created_at

CompanySnapshot:
    id, company_id, captured_at
    employee_count_est, employee_band
    revenue_est_usd, revenue_band
    leadership          # JSON: [{name, title, source_url}]
    product_count
    site_text_hash      # cheap "did anything change at all?" check
```

`CompanySnapshot` is written **every run**, unconditionally. It is the only
thing that makes change detection possible later, and it costs one row per
company per run.

---

## 4. Sourcing

| Source | Signals it yields | Cost |
|---|---|---|
| **Site crawl** — add `news`, `press`, `newsroom`, `blog`, `careers`, `jobs`, `leadership`, `sustainability` to `SUBPAGE_KEYWORDS` | leadership change, product launch, warranty change, hiring, facility, certification | free, uses existing `Fetcher` + cache |
| **Date-restricted search** — add `tbs=qdr:m6` to `services/search/serper.py` | anything announced off-site: trade press, local business journals | already paying for Serper |
| **Snapshot diffing** | headcount trajectory, leadership change we were never told about | free, from run 2 |
| **Event dates** — already on `Event.start_date` | upcoming-show window | free |
| **Paid feeds** (Proxycurl / Clay / PredictLeads) behind a `SignalProvider` Protocol | person-level job changes, job-posting feeds | deferred; stubbed like `ClayProvider` |

The `SignalProvider` Protocol mirrors `ContactProvider` exactly
(`integrations/contacts/base.py`) — `is_configured()` gating, chain resolved
from env, unconfigured providers skipped. That pattern is already proven here.

---

## 5. Semantic layer

`backend/app/scoring/semantic.py`, wrapping a local
`sentence-transformers` model (`all-MiniLM-L6-v2`, ~90MB, no API, no key).

Three uses, in value order:

1. **Pain-point alignment.** Today it is substring matching, so "resists
   yellowing outdoors for seven years" scores zero against "UV resistant" —
   which is why that component reads zero on 62 of 94 records. Embed the
   company's text by sentence, score against reference phrasings per theme,
   and **take the best-matching sentence as the `Evidence.quote`**. This makes
   provenance *better*, not weaker: instead of a keyword hit we cite the actual
   sentence.
2. **Signal classification.** Candidate news items are ranked by similarity to
   each signal type's reference phrasings; only the plausible ones go to the
   LLM for date extraction. Keeps LLM cost proportional to real candidates.
3. **Industry fit paraphrase**, as a secondary contributor behind keyword hits.

**Keyword hits stay the anchor.** An embedding cannot produce a quotable claim
on its own, and the whole system's credibility rests on quotable claims. Where
semantic and keyword disagree, the record is flagged rather than silently
resolved.

Graceful degradation: if the model is unavailable, `semantic.py` returns
neutral scores and the pipeline runs exactly as it does today — same contract
as `LLMUnavailable`.

---

## 6. Anti-hallucination rules for signals

This is the part most likely to go wrong, so the rules are hard:

- **No date + no source URL ⇒ no signal.** Not stored, not scored, not shown.
- **Dates are extracted, never inferred.** The LLM reads a date off the page or
  returns null. `date_confidence=unknown` halves strength.
- **Nothing older than 18 months scores**, whatever the half-life says.
- **The LLM classifies and extracts; it never invents.** Same structured-output
  + validator path as `ExtractedProfile` in `enrich_companies.py`.
- **Signals never touch the fit score.**
- **Negative signals are first-class** and visibly subtract.
- A signal whose `source_url` is not among the pages we actually fetched is
  rejected — the same guard `draft_outreach.validate()` already applies.

---

## 7. API and dashboard

**API** (`app/api/routes.py`, `schemas.py`):
- `LeadOut` gains `signals: list[SignalOut]`, `signal_score`, `signal_band`,
  `recommended_action`
- `GET /api/signals?since=&type=&direction=` for a chronological feed
- `/api/leads` gains `min_signal` and `action` filters
- `leads.csv` gains signal columns, with `event_date` and `source_url`

**Dashboard** (`frontend/src/components/`):
- New **Signal** column beside Score, showing band + count, with the same
  colour-plus-word treatment as `TierBadge` in `Atoms.tsx`
- **"Why now"** section at the top of `LeadDrawer.tsx` — dated signals,
  newest first, each with its source link and an explicit age ("47 days ago")
- Priority-matrix filter chips (Act now / Prioritise / Nurture / Watch)
- A **Signals** tab: the feed across all companies, newest first

---

## 8. Implementation phases

**Phase 0 — start recording (do first, ~1h).** `CompanySnapshot` model, written
every run from `enrich_companies.run`. Add the news/press/careers/leadership
keywords to `SUBPAGE_KEYWORDS`. *Nothing detects anything yet — but every run
from now on builds the history that Phase 4 needs.*

**Phase 1 — signals from the site crawl (~3h).** `Signal` model, `SignalType`
enum, `scoring/signals.py` catalog with base strengths and half-lives, new
`pipeline/stages/detect_signals.py` running after `qualify`. LLM extraction of
headline + date from the news/careers pages already fetched. Decay scoring.

**Phase 2 — recency-scoped search (~2h).** `tbs` support in the Serper and
Tavily providers (cache key must include it — see `services/search/cache.py`),
off-site signal queries per company.

**Phase 3 — semantic layer (~3h).** `scoring/semantic.py`, pain-point rescoring
with retrieved sentences as evidence, semantic pre-filter for signal candidates.

**Phase 4 — snapshot diffing (~2h).** Compare the latest two snapshots per
company: headcount deltas beyond a threshold, leadership additions and
departures. Works from the second run onward.

**Phase 5 — API + dashboard (~3h).** Everything in §7.

**Phase 6 — provider stubs (~1h).** `SignalProvider` Protocol plus credential-
gated Proxycurl/Clay/PredictLeads stubs, documented like `clay.py` is.

Total ≈ 15h. Phases 0–1 alone deliver a working "why now" column.

---

## 9. Verification

1. `cd backend && uv run pytest -q` — new tests must cover: decay maths at
   known ages, an undated signal being rejected, a signal older than 18 months
   scoring zero, negative signals subtracting, snapshot diffing producing a
   headcount-change signal from two fixtures, and semantic scoring degrading to
   neutral when the model is absent.
2. `uv run ruff check .`
3. `uv run python -m app.pipeline.runner --mode cached` twice in a row — the
   second run must produce snapshot-diff signals the first could not.
4. Spot-check three signals by hand: open the `source_url`, confirm the event
   actually happened and the extracted date matches the page. **A signal that
   cannot be confirmed this way is a bug, not a near-miss.**
5. Drive the dashboard: Signal column sorts, "Why now" shows ages and links,
   priority filters behave, a negative signal visibly demotes a company.
6. Confirm an outreach draft can use a dated signal as its hook and still pass
   `draft_outreach.validate()`.

## Open question for later

Signal *strengths* and *half-lives* are my judgement calls, exactly like the
75/60/40 tier thresholds. In production they would be fitted against Tedlar's
historical win data. Worth saying plainly rather than implying they are derived.
