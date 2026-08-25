"use client";

import type { Summary } from "@/lib/types";
import { Card } from "./primitives";

const TILES: { key: keyof Summary; label: string; hint: string }[] = [
  { key: "events", label: "Events & associations", hint: "Verified industry gatherings" },
  { key: "companies", label: "Companies sourced", hint: "After deduplication" },
  { key: "companies_enriched", label: "Enriched", hint: "Profiled from their own site" },
  { key: "qualified_leads", label: "Qualified leads", hint: "Tier A or B" },
  { key: "contacts", label: "Decision-makers", hint: "Named individuals found" },
  { key: "outreach_drafts", label: "Outreach drafts", hint: "Evidence-grounded" },
  { key: "errors", label: "Handled errors", hint: "Captured, not swallowed" },
];

export function MetricsBar({ summary }: { summary: Summary | null }) {
  return (
    <div className="space-y-2">
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 xl:grid-cols-7">
      {TILES.map((tile) => {
        const value = summary ? (summary[tile.key] as number) : null;
        const isErrors = tile.key === "errors";
        return (
          <Card key={tile.key} className="px-3 py-2.5">
            <p
              className="text-[11px] leading-tight"
              style={{ color: "var(--text-secondary)" }}
              title={tile.hint}
            >
              {tile.label}
            </p>
            <p
              className="tnum mt-1 text-2xl font-semibold"
              style={{
                color:
                  isErrors && value
                    ? "var(--status-serious)"
                    : "var(--text-primary)",
              }}
            >
              {value === null ? "—" : value}
            </p>
          </Card>
        );
      })}
      </div>
      <RunEconomics summary={summary} />
    </div>
  );
}

/** Unit economics for the last run — what a GTM team budgets against. */
function RunEconomics({ summary }: { summary: Summary | null }) {
  if (!summary || !summary.llm_calls) return null;
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
    <Card className="flex flex-wrap items-center gap-x-6 gap-y-1 px-3 py-2">
      {cells.map(([label, value]) => (
        <span key={label} className="text-xs" style={{ color: "var(--text-secondary)" }}>
          {label}{" "}
          <span className="tnum font-semibold" style={{ color: "var(--text-primary)" }}>
            {value}
          </span>
        </span>
      ))}
      <span className="text-[11px]" style={{ color: "var(--text-muted)" }}>
        estimated from token usage on the last run
      </span>
    </Card>
  );
}
