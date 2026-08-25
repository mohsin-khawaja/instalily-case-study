"use client";

import type { Lead } from "@/lib/types";
import { Chip, ConfidenceDots, Empty, ScoreBar, Skeleton, TierBadge } from "./primitives";

export function LeadTable({
  leads,
  loading,
  onSelect,
  selectedId,
}: {
  leads: Lead[];
  loading: boolean;
  onSelect: (lead: Lead) => void;
  selectedId?: string;
}) {
  if (loading) return <Skeleton rows={8} />;
  if (!leads.length) {
    return (
      <Empty
        title="No leads match these filters"
        hint="Widen the score range or clear the event filter. If the table is empty everywhere, run the pipeline from the header."
      />
    );
  }

  return (
    <div className="scroll-x">
      <table className="w-full min-w-[1000px] text-sm">
        <thead>
          <tr
            className="border-b text-left text-[11px] uppercase tracking-wide"
            style={{ borderColor: "var(--border)", color: "var(--text-muted)" }}
          >
            <th className="px-3 py-2 font-medium">Company</th>
            <th className="px-3 py-2 font-medium">Industry</th>
            <th className="px-3 py-2 font-medium">Size</th>
            <th className="px-3 py-2 font-medium">Events</th>
            <th className="px-3 py-2 font-medium">Score</th>
            <th className="px-3 py-2 font-medium">Tier</th>
            <th className="px-3 py-2 font-medium">Confidence</th>
            <th className="px-3 py-2 font-medium">Contact</th>
          </tr>
        </thead>
        <tbody>
          {leads.map((lead) => {
            const contact = lead.contacts[0];
            const selected = lead.company_id === selectedId;
            return (
              <tr
                key={lead.company_id}
                onClick={() => onSelect(lead)}
                className="cursor-pointer border-b transition-colors"
                style={{
                  borderColor: "var(--border)",
                  background: selected ? "var(--surface-2)" : "transparent",
                }}
              >
                <td className="px-3 py-2.5">
                  <div className="font-medium">{lead.company_name}</div>
                  <div className="text-xs" style={{ color: "var(--text-muted)" }}>
                    {lead.domain ?? "no domain"}
                  </div>
                </td>
                <td className="px-3 py-2.5" style={{ color: "var(--text-secondary)" }}>
                  {lead.industry ?? "—"}
                </td>
                <td className="px-3 py-2.5" style={{ color: "var(--text-secondary)" }}>
                  {lead.revenue_band ?? lead.employee_band ?? (
                    <Chip tone="warning" title="No public size figure was found">
                      unknown
                    </Chip>
                  )}
                </td>
                <td className="px-3 py-2.5">
                  {lead.events.length ? (
                    <span title={lead.events.map((e) => e.name).join(", ")}>
                      {lead.events.length}
                    </span>
                  ) : (
                    <span style={{ color: "var(--text-muted)" }}>—</span>
                  )}
                </td>
                <td className="px-3 py-2.5">
                  <ScoreBar value={lead.score_total} />
                </td>
                <td className="px-3 py-2.5">
                  <TierBadge tier={lead.tier} showLabel={false} />
                </td>
                <td className="px-3 py-2.5">
                  <ConfidenceDots value={lead.confidence} />
                </td>
                <td className="px-3 py-2.5">
                  {contact ? (
                    <div>
                      <div className="font-medium">{contact.full_name}</div>
                      <div className="text-xs" style={{ color: "var(--text-muted)" }}>
                        {contact.title ?? "—"}
                      </div>
                    </div>
                  ) : (
                    <span style={{ color: "var(--text-muted)" }}>—</span>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
