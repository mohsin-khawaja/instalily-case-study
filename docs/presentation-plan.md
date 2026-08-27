# Video presentation plan

Target: **6 minutes**. Screen recording with voiceover. The arc is
product → proof → mechanism → integrity → scale → honesty, because a reviewer
decides whether to trust the tool in the first ninety seconds and spends the
rest looking for reasons to change their mind.

---

## Before you hit record

**Set the stage:**
- Mode dropdown on **Cached run** — deterministic. A live run mid-demo can
  reshuffle the lead set under you.
- Browser at 1440×900, dashboard theme set to whichever reads better on your
  recording (light usually screenshots cleaner).
- Both servers up: `uvicorn app.main:app --port 8000` and `npm run dev`.
- Close every other tab. One browser window, one terminal.

**Have open in background tabs, ready to switch to:**
1. The dashboard (`localhost:3000`)
2. The GitHub repo
3. `docs/Tedlar-Lead-Agent-Writeup.pdf`

**Do a dry run once without recording.** The click path below has one drawer
scroll that is easy to fumble.

---

## Beat sheet

### 0:00 – 0:30 · Cold open
**On screen:** dashboard, Leads tab, top of the table.

> "DuPont Tedlar sells protective films into graphics and signage. The problem
> isn't finding companies — it's knowing which ones are worth a call and why.
> This is a working pipeline that starts from industry events, sources the
> companies at them, qualifies them against Tedlar's ICP, finds the
> decision-maker, and drafts the email. Everything on this screen came from
> real fetched web pages."

Do **not** open with architecture. Open with the working thing.

### 0:30 – 1:30 · The output
**On screen:** scroll the lead table slowly. Point at the metric tiles.

Numbers to say out loud:
- **97 companies sourced, 90 enriched, 16 qualified** — 6 tier A, 10 tier B
- **32 decision-makers, every one with a Sales Navigator link**
- **29 outreach drafts**
- **~$0.04 per qualified lead**, and say that the run cost is on screen

> "Sixty-nine of these were disqualified. That's the filter working — a tool
> that qualifies everything is just a list."

### 1:30 – 3:00 · One lead, end to end
**On screen:** click **Drytac** (top lead, 87/100, tier A).

This is the heart of the video. Four moves:

1. **Score breakdown.** "Eighty-seven out of a hundred across five weighted
   components. The number is computed in Python — the model never produces it."
2. **Expand one component.** Click *Application fit*. "It tells you which terms
   matched, where they were read, and what would raise it. That's the difference
   between a score you can act on and a number you have to trust."
3. **Evidence.** Scroll to the evidence list, click one source URL, let the real
   page load. "Every claim carries the URL it was actually read from — not the
   homepage by default."
4. **Contact and outreach.** Scroll to the decision-maker, then the draft.
   "Named person, Sales Navigator link, and an email whose opening line is
   grounded in one verified fact — with the source next to it."

Then click **Open in Gmail** so the compose window appears pre-filled.

> "That's one click to a Gmail draft. Once it's sent, MailSuite tracks opens and
> forwards — no integration needed, because it's a Gmail extension."

### 3:00 – 4:00 · How it actually works
**On screen:** the **Agents** tab.

> "Six specialists run in sequence. Each one decides what to do next in code and
> hands off to the model only where judgement over messy language is genuinely
> needed."

The line that lands:

> "**Four of the six touch no model at all.** The Qualification Agent writes the
> rationale — but over a score that's already final. That boundary is why the
> output is reproducible instead of just plausible."

Point at one agent's **Guardrail** and **When a tool fails** blocks.

### 4:00 – 4:45 · What happens when it breaks
**On screen:** the **Errors** tab.

> "Thirteen handled failures on the last run, and I'm showing you them on
> purpose. Every one degraded a single record; the run continued."

Two specifics worth naming:
- MapYourShow — the exhibitor directory behind ISA Sign Expo and PRINTING
  United — blocks server-side clients *and* headless browsers. "That's recorded
  as a miss. Beating it would mean fingerprint evasion, which isn't something I'd
  put in a sales tool."
- "The system refuses things. It won't guess a revenue band — unknown costs
  confidence instead. It won't write an email to a placeholder contact."

### 4:45 – 5:30 · Scale and cost
**On screen:** briefly the terminal or the run-economics bar.

- Bounded concurrency across hosts — **parallelising took a run from 29.7 min to
  about 6**, on 42% fewer LLM calls
- The contact chain is a **waterfall**: Apollo → public web → mock, each gated on
  `is_configured()`. "Adding Clay is one line in an env var. The provider is
  already written."
- Every HTTP response is cached, so a cached run replays the live one exactly
- ICP lives in one file — retargeting is a config edit, not a rewrite

### 5:30 – 6:00 · Close on the honest bit
> "Where it's weakest: event participation is hard to verify because the
> flagship directories are closed, so that component reads zero more often than
> I'd like. And it scores fit, not timing — the next thing I'd build is signal
> monitoring, a new VP of Product or a hiring spike, so the tool can say not just
> *who* but *why now*. That design is in the repo."

Ending on a limitation and a roadmap reads as judgement, not as an apology.

---

## Questions you will get, and the answers

**"Is this just an LLM wrapper?"**
Four of six agents make no model call. Scoring, dedup, retries, provider
selection and filtering are all deterministic. The model reads pages and writes
prose over facts already verified.

**"How do I know the data is real?"**
Click any evidence URL live. Every claim carries the page it was read from, with
a fetch timestamp. The whole HTTP snapshot is committed to the repo.

**"Why only 16 qualified out of 97?"**
Because 69 failed on evidence. Ask them whether they'd rather have 97 leads that
mean nothing.

**"Why isn't Avery Dennison tier A?"** *(the brief's own example)*
It's tier B. Its event participation couldn't be verified from public sources on
this run, so that component scored zero rather than being assumed — the same
principle that keeps revenue honest. Worth saying it scored 48 before three bugs
were found and fixed by testing against exactly this account.

**"What breaks at 10,000 companies?"**
Nothing structural. Per-record isolation already exists, so moving to a task
queue is enqueuing the same coroutines. `DATABASE_URL` is the only thing between
SQLite and Postgres. The real limit is API quota, not the pipeline.

**"Where did the weights come from?"**
My judgement, informed by the ICP. In production you'd fit them to Tedlar's
closed-won data. Say this plainly — claiming they're derived would be worse.

---

## Recording notes

- **Talk slower than feels natural.** Six minutes of content in six minutes of
  speech is too dense to follow.
- **Don't read the screen aloud.** Say what it means, not what it says.
- **One take per beat**, then stitch. Trying to nail six minutes continuously
  wastes more time than editing does.
- If a page is slow, cut it. Nobody needs to watch a fetch.
- **Do not run a live pipeline on camera.** Ten minutes and a shuffled lead set.

## Last checks before submitting

- [ ] **Open `docs/Tedlar-Lead-Agent.pptx`** — it passes validation but nobody
      has looked at the slides
- [ ] Confirm the dashboard loads clean from a fresh browser
- [ ] `git status` clean, latest pushed
- [ ] Rebuild the zip if anything changed
