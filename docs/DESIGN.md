# Dashboard design notes

## Colour

Data colours come from a validated categorical palette rather than picked by eye.
The five score components use fixed categorical slots 1–5 (blue, orange, aqua,
yellow, magenta) in a stable order — a component keeps its colour regardless of
how many components happen to be non-zero, so filtering never repaints the
survivors. Slot order matters: it is chosen so that *adjacent* pairs stay
distinguishable under colour-vision deficiency, which is the arrangement these
bars actually appear in.

The total score bar is a single-hue magnitude bar, because it encodes one
continuous quantity.

Status colours (tier badges, error counts) are a separate reserved set and are
never reused as a series colour. Every status colour is paired with a letter and
a word — `A · Priority`, not a green dot — so nothing depends on hue alone.

Both light and dark are explicitly defined token sets rather than an inversion:
the dark steps are chosen against the dark surface. Tokens live in
`frontend/src/app/globals.css`; the components reference roles, never raw hex.

## Layout

- Stat tiles across the top: seven counts, one of which (handled errors) is
  deliberately given a warning colour, because a pipeline that hides its failures
  is worse than one that has none.
- A pipeline strip under the header showing the six stages and their state, so a
  run in progress is legible without opening a log.
- Filters in one row above the table.
- The table carries score, tier, confidence and contact; the detail panel carries
  the argument — breakdown, rationale, evidence with clickable sources, contacts
  and the outreach editor.

Wide content (the lead table, the error table) scrolls inside its own container;
the page body never scrolls sideways.

## Numbers

Tabular figures in table columns and score readouts so digits line up down the
column. Proportional figures for the large stat-tile numbers.

## What the UI refuses to do

- No fabricated contact data: mock-provider contacts render at 0% confidence with
  a `mock` badge.
- Template-generated outreach is labelled `template`, LLM-written is labelled
  `LLM`.
- A company with unknown revenue shows an `unknown` chip, not a guessed band.
