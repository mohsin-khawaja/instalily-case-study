"use client";

import type { Lead } from "@/lib/types";
import { CautionChip, ConfidenceMeter, Empty, ScoreCell, Skeleton, TierBadge } from "./Atoms";

const COLUMNS = [
  "Company",
  "Industry",
  "Size",
  "Events",
  "Score",
  "Tier",
  "Confidence",
  "Contact",
];

export function LeadTable({
  leads,
  loading,
  onSelect,
  selectedId,
  filtersActive,
}: {
  leads: Lead[];
  loading: boolean;
  onSelect: (lead: Lead) => void;
  selectedId?: string;
  filtersActive: boolean;
}) {
  if (loading) return <Skeleton rows={10} />;
  if (!leads.length) {
    return (
      <Empty
        title={filtersActive ? "No leads match these filters" : "No leads yet"}
        hint={
          filtersActive
            ? "Widen the score range, clear the event filter, or include lower tiers."
            : "Run lead discovery from the header. A cached run replays the committed snapshot in seconds."
        }
      />
    );
  }

  return (
    <div style={{ flex: 1, minHeight: 0, overflow: "auto" }}>
      <table style={{ width: "100%", minWidth: 1040, borderCollapse: "collapse" }}>
        <thead>
          <tr>
            {COLUMNS.map((c) => (
              <th
                key={c}
                style={{
                  position: "sticky",
                  top: 0,
                  zIndex: 1,
                  textAlign: "left",
                  padding: "7px 16px",
                  fontSize: 10,
                  fontWeight: 600,
                  letterSpacing: 0.6,
                  textTransform: "uppercase",
                  color: "var(--c-t3)",
                  background: "var(--c-page)",
                  borderBottom: "1px solid var(--c-hairline)",
                  whiteSpace: "nowrap",
                }}
              >
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {leads.map((lead) => {
            const contact = lead.contacts[0];
            const selected = lead.company_id === selectedId;
            const size = lead.revenue_band ?? lead.employee_band;
            return (
              <tr
                key={lead.company_id}
                onClick={() => onSelect(lead)}
                className={selected ? "" : "row-hover"}
                style={{
                  cursor: "pointer",
                  background: selected ? "var(--c-raised)" : "transparent",
                  borderBottom: "1px solid var(--c-hairline)",
                }}
              >
                <Cell>
                  <div style={{ fontSize: 12.5, fontWeight: 600 }}>{lead.company_name}</div>
                  <div
                    style={{
                      fontSize: 10.5,
                      color: "var(--c-t3)",
                      fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
                    }}
                  >
                    {lead.domain ?? "no domain"}
                  </div>
                </Cell>

                <Cell style={{ color: "var(--c-t2)", fontSize: 12 }}>{lead.industry ?? "—"}</Cell>

                <Cell>
                  {size ? (
                    <span className="tabular" style={{ fontSize: 12, color: "var(--c-t2)" }}>
                      {size}
                    </span>
                  ) : (
                    <CautionChip title="No public size figure was found; this costs confidence rather than being guessed">
                      unknown
                    </CautionChip>
                  )}
                </Cell>

                <Cell>
                  {lead.events.length ? (
                    <span
                      className="tabular"
                      style={{ fontSize: 12, color: "var(--c-t2)" }}
                      title={lead.events.map((e) => e.name).join(", ")}
                    >
                      {lead.events.length}
                    </span>
                  ) : (
                    <span style={{ color: "var(--c-t3)" }}>—</span>
                  )}
                </Cell>

                <Cell>
                  <ScoreCell value={lead.score_total} />
                </Cell>

                <Cell>
                  <TierBadge tier={lead.tier} />
                </Cell>

                <Cell>
                  <ConfidenceMeter value={lead.confidence} />
                </Cell>

                <Cell>
                  {contact ? (
                    <>
                      <div style={{ fontSize: 12, fontWeight: 500 }}>{contact.full_name}</div>
                      <div
                        style={{ fontSize: 10.5, color: "var(--c-t3)" }}
                        title={contact.title ?? undefined}
                      >
                        {truncate(contact.title, 34)}
                      </div>
                    </>
                  ) : (
                    <span style={{ fontSize: 11.5, color: "var(--c-t3)", fontStyle: "italic" }}>
                      no contact found
                    </span>
                  )}
                </Cell>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function Cell({
  children,
  style,
}: {
  children: React.ReactNode;
  style?: React.CSSProperties;
}) {
  return <td style={{ padding: "9px 16px", verticalAlign: "middle", ...style }}>{children}</td>;
}

function truncate(text: string | null | undefined, max: number) {
  if (!text) return "—";
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}
