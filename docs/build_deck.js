// Builds docs/Tedlar-Lead-Agent.pptx.
//   npm install pptxgenjs && node build_deck.js
const fs = require("fs");
const pptxgen = require("pptxgenjs");

// Run figures come from the database via `uv run python results_snapshot.py`,
// so the deck cannot quote numbers the pipeline never produced.
const R = fs.existsSync("results.json")
  ? JSON.parse(fs.readFileSync("results.json", "utf8"))
  : { companies: 0, companies_enriched: 0, events: 0, tests: 0, qualified_leads: 0 };

const INK = "0B1F26";      // near-black slate
const DEEP = "0B3C49";     // deep teal — dominant
const TEAL = "1C7293";     // supporting
const AMBER = "E8A33D";    // accent
const PAPER = "FFFFFF";
const MIST = "EEF3F5";     // light card tint
const MUTED = "5C7480";

const H = "Cambria";
const B = "Calibri";

const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE";                    // 13.3 x 7.5
pres.author = "Mohsin Khawaja";
pres.title = "Tedlar Lead Agent";

const W = 13.3, HT = 7.5, M = 0.7;

function darkSlide() {
  const s = pres.addSlide();
  s.background = { color: DEEP };
  return s;
}
function lightSlide(title, kicker) {
  const s = pres.addSlide();
  s.background = { color: PAPER };
  if (kicker) {
    s.addText(kicker.toUpperCase(), {
      x: M, y: 0.42, w: 8, h: 0.28, fontFace: B, fontSize: 11, bold: true,
      color: AMBER, charSpacing: 2, margin: 0,
    });
  }
  s.addText(title, {
    x: M, y: 0.72, w: W - M * 2, h: 0.75, fontFace: H, fontSize: 34, bold: true,
    color: INK, margin: 0,
  });
  return s;
}
// Repeated motif: a numbered disc.
function disc(s, n, x, y, size = 0.44, fill = TEAL, fg = "FFFFFF") {
  s.addShape(pres.ShapeType.ellipse, { x, y, w: size, h: size, fill: { color: fill } });
  s.addText(String(n), {
    x, y, w: size, h: size, align: "center", valign: "middle",
    fontFace: B, fontSize: 13, bold: true, color: fg, margin: 0,
  });
}
function card(s, x, y, w, h, fill = MIST) {
  s.addShape(pres.ShapeType.roundRect, {
    x, y, w, h, rectRadius: 0.08, fill: { color: fill },
  });
}

/* 1 — Title -------------------------------------------------------------- */
{
  const s = darkSlide();
  s.addText("Tedlar Lead Agent", {
    x: M, y: 2.25, w: 10.5, h: 1.0, fontFace: H, fontSize: 54, bold: true,
    color: PAPER, margin: 0,
  });
  s.addText("Lead generation and outreach for DuPont Tedlar — Graphics & Signage", {
    x: M, y: 3.35, w: 10.0, h: 0.5, fontFace: B, fontSize: 19, color: "CFE0E7", margin: 0,
  });
  s.addText("A deterministic pipeline with the LLM kept to what it is actually better at.", {
    x: M, y: 3.95, w: 10.0, h: 0.4, fontFace: B, fontSize: 14, italic: true,
    color: AMBER, margin: 0,
  });
  const stats = [
    ["7", "pipeline stages"],
    [String(R.companies), "companies sourced"],
    [String(R.tests), "tests, no network"],
  ];
  stats.forEach(([n, label], i) => {
    const x = M + i * 3.1;
    s.addText(n, { x, y: 5.1, w: 2.8, h: 0.75, fontFace: H, fontSize: 44, bold: true, color: AMBER, margin: 0 });
    s.addText(label, { x, y: 5.85, w: 2.8, h: 0.35, fontFace: B, fontSize: 12, color: "CFE0E7", margin: 0 });
  });
  s.addNotes("Case study for InstaLILY. The thesis: this problem is mostly deterministic engineering, and treating it that way is what makes the output defensible to a sales team.");
}

/* 2 — The choice --------------------------------------------------------- */
{
  const s = lightSlide("The brief invites an agent swarm. I built the opposite.", "Approach");
  const rows = [
    ["Reproducibility", "The same inputs give the same score every run. A sales manager can argue with the number, because the number is a formula."],
    ["Debuggability", "When a lead looks wrong, the breakdown names which of five components produced the points, and the URL behind each. No “the agent decided” step to shrug at."],
    ["Cost", "Two LLM calls per qualified lead — one to read the site, one to write — instead of one per reasoning hop."],
  ];
  rows.forEach(([head, body], i) => {
    const y = 1.85 + i * 1.55;
    card(s, M, y, W - M * 2, 1.3);
    disc(s, i + 1, M + 0.35, y + 0.42);
    s.addText(head, { x: M + 1.05, y: y + 0.22, w: 3.2, h: 0.4, fontFace: H, fontSize: 20, bold: true, color: DEEP, margin: 0 });
    s.addText(body, { x: M + 4.3, y: y + 0.2, w: W - M * 2 - 4.7, h: 0.95, fontFace: B, fontSize: 13.5, color: INK, margin: 0 });
  });
  s.addText("Deterministic: scoring · dedup · retries · persistence · filtering · provider selection", {
    x: M, y: 6.62, w: W - M * 2, h: 0.35, fontFace: B, fontSize: 12, italic: true, color: MUTED, margin: 0,
  });
  s.addNotes("The LLM is confined to two jobs it genuinely beats code at: reading a messy web page, and writing prose over facts already established.");
}

/* 3 — Pipeline ----------------------------------------------------------- */
{
  const s = lightSlide("Seven stages, each isolating its own failures", "Architecture");
  const stages = [
    ["Discover events", "Seeded anchors verified live, plus search expansion"],
    ["Source companies", "Directories ∪ ICP search ∪ verified roster"],
    ["Dedupe & normalise", "Registrable domain, then fuzzy legal name"],
    ["Enrich", "Follow the company's own nav; extract structured facts"],
    ["Qualify", "Deterministic 0–100 score, evidence-bound rationale"],
    ["Find contacts", "Provider chain: public web → Clay → Sales Navigator"],
    ["Draft outreach", "Validated against the evidence set, or templated"],
  ];
  stages.forEach(([name, sub], i) => {
    const col = i % 2, row = Math.floor(i / 2);
    const x = M + col * 6.15, y = 1.8 + row * 1.05;
    if (i === 6) { // last one spans, keeps the grid from ending ragged
      card(s, M, y, W - M * 2, 0.85, "FDF3E2");
    } else {
      card(s, x, y, 5.85, 0.85);
    }
    const w = i === 6 ? W - M * 2 : 5.85;
    const bx = i === 6 ? M : x;
    disc(s, i + 1, bx + 0.25, y + 0.2, 0.44, i === 6 ? AMBER : TEAL);
    s.addText(name, { x: bx + 0.85, y: y + 0.12, w: w - 1.1, h: 0.35, fontFace: H, fontSize: 16, bold: true, color: DEEP, margin: 0 });
    s.addText(sub, { x: bx + 0.85, y: y + 0.46, w: w - 1.1, h: 0.32, fontFace: B, fontSize: 11.5, color: MUTED, margin: 0 });
  });
  s.addText("A record that fails gets a StageError row and status=\"incomplete\". The run continues — partial success is the designed outcome, a crash is a bug.", {
    x: M, y: 6.5, w: W - M * 2, h: 0.5, fontFace: B, fontSize: 13, color: INK, margin: 0,
  });
  s.addNotes("The load-bearing primitive is ctx.attempt(): expected failures become persisted rows, genuine programming errors still propagate.");
}

/* 4 — Data --------------------------------------------------------------- */
{
  const s = lightSlide("Three sourcing channels, because each fails differently", "Real data");
  const chans = [
    ["Exhibitor directories", "Works on plain HTML. The flagship shows front their lists with a JavaScript app over an API that rejects server-side clients — those record a miss in the error log.", TEAL],
    ["ICP-shaped search", "The channel that scales: retargeting is new query templates, not new code. Recall depends entirely on the search provider.", TEAL],
    ["Verified ICP roster", "Names and public URLs only. Every fact still comes from fetching the site. The one hand-curated input — and the cheapest thing in the repo to delete.", AMBER],
  ];
  chans.forEach(([head, body, color], i) => {
    const x = M + i * 4.05;
    card(s, x, 1.8, 3.8, 3.0, i === 2 ? "FDF3E2" : MIST);
    disc(s, i + 1, x + 0.3, 2.1, 0.44, color);
    s.addText(head, { x: x + 0.3, y: 2.72, w: 3.2, h: 0.6, fontFace: H, fontSize: 17, bold: true, color: DEEP, margin: 0 });
    s.addText(body, { x: x + 0.3, y: 3.32, w: 3.2, h: 1.35, fontFace: B, fontSize: 12, color: INK, margin: 0 });
  });
  card(s, M, 5.1, W - M * 2, 1.35, DEEP);
  s.addText("Provenance is structural", { x: M + 0.4, y: 5.3, w: 4.2, h: 0.4, fontFace: H, fontSize: 18, bold: true, color: AMBER, margin: 0 });
  s.addText("Every HTTP response is written to a content-addressed cache with URL, status and timestamp. --mode cached replays that snapshot offline; --mode live refreshes it. Every claim in the UI carries a clickable source URL, and every source URL was really fetched.", {
    x: M + 4.9, y: 5.28, w: W - M * 2 - 5.3, h: 1.0, fontFace: B, fontSize: 12.5, color: "DCE8EC", margin: 0,
  });
  s.addNotes("The cached snapshot is committed and gzipped — 14MB — so a reviewer reproduces the exact demo run with no keys.");
}

/* 5 — Scoring ------------------------------------------------------------ */
{
  const s = lightSlide("A score you can argue with", "Qualification");
  s.addChart(pres.ChartType.bar, [{
    name: "Weight",
    labels: ["Industry fit", "Application fit", "Company size", "Event engagement", "Pain alignment"],
    values: [30, 25, 15, 15, 15],
  }], {
    x: M, y: 1.8, w: 6.4, h: 3.4,
    barDir: "bar", chartColors: [DEEP, TEAL, "4E9CB8", "8FC2D3", AMBER],
    showValue: true, dataLabelPosition: "outEnd", dataLabelColor: INK,
    dataLabelFontFace: B, dataLabelFontSize: 12,
    catAxisLabelColor: INK, catAxisLabelFontFace: B, catAxisLabelFontSize: 12,
    valAxisLabelColor: MUTED, valAxisLabelFontFace: B, valAxisLabelFontSize: 10,
    valGridLine: { color: "E3E9EC", size: 1 }, catGridLine: { style: "none" },
    showLegend: false, valAxisMaxVal: 35,
    showTitle: true, title: "Points available, out of 100",
    titleFontFace: B, titleFontSize: 12, titleColor: MUTED,
  });
  const notes = [
    ["The LLM never produces the number.", "It receives the finished breakdown and the evidence list, and writes the rationale."],
    ["Confidence is separate from score.", "It measures how much of the score is URL-backed, penalised for a missing website or unknown size."],
    ["Unknown stays unknown.", "Most private companies never publish revenue. That costs confidence rather than earning a guessed band."],
  ];
  notes.forEach(([head, body], i) => {
    const y = 1.9 + i * 1.15;
    s.addText(head, { x: 7.5, y, w: 5.1, h: 0.32, fontFace: H, fontSize: 15, bold: true, color: DEEP, margin: 0 });
    s.addText(body, { x: 7.5, y: y + 0.34, w: 5.1, h: 0.7, fontFace: B, fontSize: 12, color: INK, margin: 0 });
  });
  s.addText("Tier A ≥ 75   ·   B ≥ 60   ·   C ≥ 40   ·   below that, out of ICP", {
    x: M, y: 5.5, w: W - M * 2, h: 0.4, fontFace: B, fontSize: 14, bold: true, color: DEEP, margin: 0,
  });
  s.addText("The ICP vocabulary, bands and thresholds all live as data in one file — retargeting at a different business unit is a config edit.", {
    x: M, y: 5.95, w: W - M * 2, h: 0.4, fontFace: B, fontSize: 12.5, italic: true, color: MUTED, margin: 0,
  });
  s.addNotes("Each scoring component that fires emits an Evidence row carrying the URL it came from.");
}

/* 6 — Guardrails --------------------------------------------------------- */
{
  const s = lightSlide("What stops it inventing things", "Guardrails");
  const guards = [
    ["Extraction", "The prompt is null-preferring and forbidden from inferring. “A global leader” is explicitly not a size statement."],
    ["Revenue regex", "A money figure only counts when a revenue word sits within 60 characters. That is what stops “a $2 billion market” becoming company turnover."],
    ["Rationale", "A cited URL outside the supplied evidence flags the record. Any sentence making a numeric claim we cannot match to a known figure is removed."],
    ["Outreach", "The model must return its hook fact and that fact's URL. If the URL is not one we supplied, the draft is rejected."],
    ["Model output", "Parsed into a Pydantic model before it can touch the database. Invalid output gets one repair round-trip, then the record degrades."],
    ["No key at all", "Every LLM and search call has a deterministic fallback. The whole pipeline runs end to end without credentials."],
  ];
  guards.forEach(([head, body], i) => {
    const col = i % 2, row = Math.floor(i / 2);
    const x = M + col * 6.15, y = 1.8 + row * 1.62;
    card(s, x, y, 5.85, 1.42);
    s.addText(head, { x: x + 0.35, y: y + 0.16, w: 5.15, h: 0.32, fontFace: H, fontSize: 16, bold: true, color: DEEP, margin: 0 });
    s.addText(body, { x: x + 0.35, y: y + 0.52, w: 5.15, h: 0.8, fontFace: B, fontSize: 12, color: INK, margin: 0 });
  });
  s.addNotes("Hallucination is treated as an engineering problem with checks, not as something you prompt away.");
}

/* 7 — Contacts ----------------------------------------------------------- */
{
  const s = lightSlide("Contact enrichment is one interface, four providers", "Integration path");
  const provs = [
    ["PublicWebContactProvider", "Working", "Follows the site's own nav to leadership pages, plus site-restricted LinkedIn search.", TEAL],
    ["MockContactProvider", "Working", "Deterministic fixtures. Always 0% confidence and a mock badge, so placeholder data can never read as sourced.", TEAL],
    ["ClayProvider", "Credential-gated", "The real table-webhook → poll/callback flow, written in full. Set CLAY_API_KEY and CLAY_WEBHOOK_URL.", AMBER],
    ["SalesNavigatorProvider", "Credential-gated", "The real SNAP salesApiLeadSearch call shape. Scraping would breach LinkedIn's terms — so without a partner token it contributes a pre-filtered deep link a licensed rep can click.", AMBER],
  ];
  provs.forEach(([name, state, body, color], i) => {
    const y = 1.78 + i * 1.16;
    card(s, M, y, W - M * 2, 1.02, i > 1 ? "FDF3E2" : MIST);
    s.addShape(pres.ShapeType.ellipse, { x: M + 0.32, y: y + 0.42, w: 0.18, h: 0.18, fill: { color } });
    s.addText(name, { x: M + 0.68, y: y + 0.14, w: 3.7, h: 0.34, fontFace: B, fontSize: 14, bold: true, color: DEEP, margin: 0 });
    s.addText(state, { x: M + 0.68, y: y + 0.5, w: 3.7, h: 0.3, fontFace: B, fontSize: 11, italic: true, color: MUTED, margin: 0 });
    s.addText(body, { x: M + 4.6, y: y + 0.16, w: W - M * 2 - 5.0, h: 0.75, fontFace: B, fontSize: 12, color: INK, margin: 0 });
  });
  s.addText("Enabling Clay in production is CONTACT_PROVIDERS=clay,public_web plus two secrets. No caller changes.", {
    x: M, y: 6.55, w: W - M * 2, h: 0.4, fontFace: B, fontSize: 13, bold: true, color: DEEP, margin: 0,
  });
  s.addNotes("is_configured() gates each provider, so an unconfigured one is skipped rather than crashed on.");
}

/* 8 — Results ------------------------------------------------------------ */
{
  const s = lightSlide("What it produces", "Results");
  const tiles = [
    [String(R.companies), "companies sourced"],
    [String(R.companies_enriched), "enriched from their own sites"],
    [String(R.events), "events & associations"],
    [String(R.tests), "tests, no network"],
  ];
  tiles.forEach(([n, label], i) => {
    const x = M + i * 3.05;
    card(s, x, 1.8, 2.85, 1.5);
    s.addText(n, { x: x + 0.25, y: 1.92, w: 2.4, h: 0.8, fontFace: H, fontSize: 40, bold: true, color: DEEP, margin: 0 });
    s.addText(label, { x: x + 0.25, y: 2.72, w: 2.4, h: 0.45, fontFace: B, fontSize: 11.5, color: MUTED, margin: 0 });
  });
  s.addText("The dashboard", { x: M, y: 3.55, w: 6, h: 0.4, fontFace: H, fontSize: 20, bold: true, color: DEEP, margin: 0 });
  const bullets = [
    "Summary metrics, live stage progress, filters by event, tier, score and free text",
    "Detail panel: score breakdown, rationale, clickable evidence, contact card with Sales Navigator link",
    "Outreach editor — copy, edit, approve — persisted through the API",
    "A dedicated error tab listing every handled failure, because a pipeline that hides its failures is worse than one that has none",
  ];
  s.addText(bullets.map((t, i) => ({ text: t, options: { bullet: true, breakLine: i !== bullets.length - 1 } })), {
    x: M, y: 4.05, w: W - M * 2, h: 1.6, fontFace: B, fontSize: 13.5, color: INK,
    paraSpaceAfter: 6, margin: 0,
  });
  card(s, M, 5.85, W - M * 2, 1.0, "FDF3E2");
  s.addText("Runs clean with no API keys at all. Two keys — Anthropic and a search provider — turn keyword fallbacks into model-read enrichment and real search recall.", {
    x: M + 0.35, y: 6.05, w: W - M * 2 - 0.7, h: 0.6, fontFace: B, fontSize: 13, color: INK, margin: 0,
  });
  s.addNotes("Numbers are from the committed cached run, reproducible with one command.");
}

/* 9 — Limits & scale ----------------------------------------------------- */
{
  const s = darkSlide();
  s.addText("LIMITS, STATED PLAINLY", {
    x: M, y: 0.65, w: 8, h: 0.3, fontFace: B, fontSize: 11, bold: true, color: AMBER, charSpacing: 2, margin: 0,
  });
  s.addText("What the constraints cost, and where this goes next", {
    x: M, y: 1.0, w: W - M * 2, h: 0.7, fontFace: H, fontSize: 32, bold: true, color: PAPER, margin: 0,
  });
  const limits = [
    "MapYourShow-backed exhibitor directories are JavaScript-gated and their API refuses server-side clients. A headless browser is the fix.",
    "Without a paid search key, recall on category leaders is thin — which is why the roster channel exists.",
    "Most private companies never publish revenue, so the size component is frequently zero.",
  ];
  s.addText("Known limits", { x: M, y: 2.2, w: 5.6, h: 0.4, fontFace: H, fontSize: 19, bold: true, color: AMBER, margin: 0 });
  s.addText(limits.map((t, i) => ({ text: t, options: { bullet: true, breakLine: i !== limits.length - 1 } })), {
    x: M, y: 2.7, w: 5.7, h: 2.4, fontFace: B, fontSize: 13, color: "DCE8EC", paraSpaceAfter: 10, margin: 0,
  });
  const scale = [
    "Bounded async: a global concurrency semaphore plus a per-host lock and delay.",
    "Per-record isolation already exists in every stage — moving to a task queue means enqueuing the same coroutines.",
    "The ICP is one file. DATABASE_URL is the only thing between SQLite and Postgres.",
  ];
  s.addText("Scaling path", { x: 7.2, y: 2.2, w: 5.4, h: 0.4, fontFace: H, fontSize: 19, bold: true, color: AMBER, margin: 0 });
  s.addText(scale.map((t, i) => ({ text: t, options: { bullet: true, breakLine: i !== scale.length - 1 } })), {
    x: 7.2, y: 2.7, w: 5.4, h: 2.4, fontFace: B, fontSize: 13, color: "DCE8EC", paraSpaceAfter: 10, margin: 0,
  });
  s.addText("Each of these is visible in the error log rather than papered over — which is the behaviour I would want from this system in production, and the reason it was built this way.", {
    x: M, y: 5.9, w: W - M * 2, h: 0.8, fontFace: B, fontSize: 14, italic: true, color: AMBER, margin: 0,
  });
  s.addNotes("Closing point: the failures are visible on purpose.");
}

pres.writeFile({ fileName: "Tedlar-Lead-Agent.pptx" }).then((f) => console.log("wrote", f));
