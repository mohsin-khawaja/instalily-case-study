"use client";

import type { Summary } from "@/lib/types";
import { WarnIcon } from "./Atoms";

/* One continuous band of figures divided by hairlines rather than seven boxed
   cards: the numbers are a single reading, not seven unrelated ones. */
const TILES: {
  key: keyof Summary;
  label: string;
  hint: string;
  tone?: "good" | "caution";
}[] = [
  { key: "events", label: "Events & associations", hint: "Verified industry gatherings" },
  { key: "companies", label: "Companies sourced", hint: "After deduplication" },
  { key: "companies_enriched", label: "Enriched", hint: "Profiled from their own site" },
  { key: "qualified_leads", label: "Qualified leads", hint: "Tier A or B", tone: "good" },
  { key: "contacts", label: "Decision-makers", hint: "Named individuals found" },
  { key: "outreach_drafts", label: "Outreach drafts", hint: "Evidence-grounded" },
  {
    key: "errors",
    label: "Handled errors",
    hint: "Captured on the last run, not swallowed",
    tone: "caution",
  },
];

export function MetricTiles({ summary }: { summary: Summary | null }) {
  return (
    <div
      className="flex flex-wrap"
      style={{
        background: "var(--c-surface)",
        borderBottom: "1px solid var(--c-hairline)",
        flexShrink: 0,
      }}
    >
      {TILES.map((tile, i) => {
        const value = summary ? (summary[tile.key] as number) : null;
        const emphasised = tile.tone && value ? tile.tone : null;
        const color =
          emphasised === "good"
            ? "var(--c-good)"
            : emphasised === "caution"
              ? "var(--c-caution)"
              : "var(--c-t1)";
        return (
          <div
            key={tile.key}
            title={tile.hint}
            style={{
              flex: "1 1 0",
              minWidth: 132,
              padding: "10px 16px 11px",
              borderLeft: i === 0 ? "none" : "1px solid var(--c-hairline)",
            }}
          >
            <div
              className="flex items-baseline gap-1.5"
              style={{ fontSize: 24, fontWeight: 600, color, lineHeight: 1.15 }}
            >
              {tile.tone === "caution" && value ? (
                <span style={{ display: "inline-flex", alignSelf: "center" }}>
                  <WarnIcon size={11} />
                </span>
              ) : null}
              {value === null ? "—" : value}
            </div>
            <div style={{ fontSize: 10.5, color: "var(--c-t3)", marginTop: 1 }}>{tile.label}</div>
          </div>
        );
      })}
    </div>
  );
}

/** Unit economics for the last run — the number a GTM team budgets against. */
export function RunEconomicsBar({ summary }: { summary: Summary | null }) {
  if (!summary?.llm_calls) return null;
  const cells: [string, string][] = [
    ["LLM calls", String(summary.llm_calls)],
    ["Run cost", `$${summary.llm_estimated_usd.toFixed(4)}`],
    [
      "Cost per qualified lead",
      summary.cost_per_qualified_lead != null
        ? `$${summary.cost_per_qualified_lead.toFixed(4)}`
        : "—",
    ],
  ];
  return (
    <div
      className="flex flex-wrap items-center gap-x-5 gap-y-1"
      style={{
        background: "var(--c-page)",
        borderBottom: "1px solid var(--c-hairline)",
        padding: "6px 24px",
        flexShrink: 0,
      }}
    >
      {cells.map(([label, value]) => (
        <span key={label} style={{ fontSize: 11, color: "var(--c-t3)" }}>
          {label}{" "}
          <span className="tabular" style={{ color: "var(--c-t1)", fontWeight: 600 }}>
            {value}
          </span>
        </span>
      ))}
      <span style={{ fontSize: 10.5, color: "var(--c-t3)", fontStyle: "italic" }}>
        estimated from token usage on the last run
      </span>
    </div>
  );
}
