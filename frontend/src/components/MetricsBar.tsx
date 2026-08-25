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
  );
}
