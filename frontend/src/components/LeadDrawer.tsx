"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { SCORE_COMPONENTS, type Lead, type OutreachOut } from "@/lib/types";
import {
  Button,
  CautionChip,
  Chip,
  ConfidenceMeter,
  SectionLabel,
  SourceLink,
  TierBadge,
} from "./Atoms";

export function LeadDrawer({
  lead,
  onClose,
  onOutreachChange,
}: {
  lead: Lead;
  onClose: () => void;
  onOutreachChange: (draft: OutreachOut) => void;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <>
      <div
        onClick={onClose}
        style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.28)", zIndex: 40 }}
      />
      <aside
        aria-label={`${lead.company_name} details`}
        style={{
          position: "fixed",
          top: 0,
          right: 0,
          bottom: 0,
          width: 620,
          maxWidth: "100vw",
          zIndex: 41,
          background: "var(--c-surface)",
          borderLeft: "1px solid var(--c-hairline)",
          boxShadow: "-8px 0 32px rgba(0,0,0,0.16)",
          display: "flex",
          flexDirection: "column",
        }}
      >
        <header
          className="flex items-start justify-between gap-4"
          style={{
            padding: "14px 20px",
            borderBottom: "1px solid var(--c-hairline)",
            flexShrink: 0,
          }}
        >
          <div style={{ minWidth: 0 }}>
            <div className="flex items-center gap-2">
              <h2 style={{ fontSize: 15, fontWeight: 700, margin: 0 }}>{lead.company_name}</h2>
              <TierBadge tier={lead.tier} />
            </div>
            {lead.website && <SourceLink href={lead.website}>{lead.website}</SourceLink>}
          </div>
          <Button onClick={onClose}>Close</Button>
        </header>

        <div style={{ flex: 1, overflowY: "auto", padding: "18px 20px 32px" }}>
          {/* ── Score ─────────────────────────────────────────────────── */}
          <section style={{ marginBottom: 24 }}>
            <SectionLabel>Score breakdown</SectionLabel>
            <div className="mb-3 flex items-baseline gap-2">
              <span className="tabular" style={{ fontSize: 34, fontWeight: 600, lineHeight: 1 }}>
                {lead.score_total.toFixed(0)}
              </span>
              <span style={{ fontSize: 13, color: "var(--c-t3)" }}>/ 100</span>
              <span style={{ marginLeft: "auto" }}>
                <ConfidenceMeter value={lead.confidence} />
              </span>
            </div>

            <ul style={{ margin: 0, padding: 0, listStyle: "none" }}>
              {SCORE_COMPONENTS.map((component) => {
                const value = Number(lead.score?.[component.key] ?? 0);
                const pct = (value / component.max) * 100;
                return (
                  <li key={component.key} className="mb-1.5 flex items-center gap-3">
                    <span style={{ width: 138, fontSize: 11.5, color: "var(--c-t2)" }}>
                      {component.label}
                    </span>
                    <span
                      style={{
                        position: "relative",
                        flex: 1,
                        height: 5,
                        borderRadius: 3,
                        background: "var(--c-track)",
                      }}
                    >
                      <span
                        style={{
                          position: "absolute",
                          inset: "0 auto 0 0",
                          width: `${pct}%`,
                          borderRadius: 3,
                          background: component.color,
                        }}
                      />
                    </span>
                    <span
                      className="tabular"
                      style={{ width: 46, textAlign: "right", fontSize: 11, color: "var(--c-t2)" }}
                    >
                      {value.toFixed(0)}/{component.max}
                    </span>
                  </li>
                );
              })}
            </ul>

            {lead.flags.length > 0 && (
              <div className="mt-3 flex flex-wrap gap-1.5">
                {lead.flags.map((flag) => (
                  <CautionChip key={flag} title={FLAG_HELP[flag] ?? "Gap that lowered confidence"}>
                    {flag.replace(/_/g, " ")}
                  </CautionChip>
                ))}
              </div>
            )}
          </section>

          {/* ── Rationale ─────────────────────────────────────────────── */}
          <section style={{ marginBottom: 24 }}>
            <SectionLabel>Why this is a qualified lead</SectionLabel>
            <p style={{ fontSize: 12.5, lineHeight: 1.65, color: "var(--c-t2)", margin: 0 }}>
              {lead.rationale ?? "No rationale generated."}
            </p>
            <p style={{ fontSize: 10.5, color: "var(--c-t3)", marginTop: 6 }}>
              {lead.rationale_source === "llm"
                ? "Generated by the LLM over verified evidence."
                : "Generated deterministically from the score breakdown."}
            </p>
          </section>

          {/* ── Evidence ──────────────────────────────────────────────── */}
          <section style={{ marginBottom: 24 }}>
            <SectionLabel>Evidence ({lead.evidence.length})</SectionLabel>
            {lead.evidence.length === 0 ? (
              <Muted>No evidence captured for this company.</Muted>
            ) : (
              <ul style={{ margin: 0, padding: 0, listStyle: "none" }}>
                {lead.evidence.map((item, i) => (
                  <li
                    key={i}
                    style={{
                      border: "1px solid var(--c-hairline)",
                      borderRadius: 6,
                      padding: "9px 11px",
                      marginBottom: 6,
                      background: "var(--c-page)",
                    }}
                  >
                    <p style={{ fontSize: 12, margin: 0, lineHeight: 1.5 }}>{item.claim}</p>
                    {item.quote && (
                      <p
                        style={{
                          fontSize: 11,
                          fontStyle: "italic",
                          color: "var(--c-t3)",
                          margin: "4px 0 0",
                          lineHeight: 1.5,
                        }}
                      >
                        “{item.quote.slice(0, 220)}”
                      </p>
                    )}
                    <div style={{ marginTop: 5 }}>
                      <SourceLink href={item.source_url} />
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </section>

          {/* ── Profile ───────────────────────────────────────────────── */}
          <section style={{ marginBottom: 24 }}>
            <SectionLabel>Company profile</SectionLabel>
            <dl
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(3, minmax(0,1fr))",
                gap: "10px 14px",
                margin: 0,
              }}
            >
              <Field label="Industry" value={lead.industry} />
              <Field label="HQ" value={lead.hq_location} />
              <Field label="Revenue" value={lead.revenue_band} />
              <Field label="Headcount" value={lead.employee_band} />
              <Field label="Sub-industries" value={lead.sub_industries.join(", ")} span />
              <Field label="Products" value={lead.products.join(", ")} span />
              <Field label="Description" value={lead.description} span />
            </dl>
          </section>

          {/* ── Events ────────────────────────────────────────────────── */}
          <section style={{ marginBottom: 24 }}>
            <SectionLabel>Events &amp; associations ({lead.events.length})</SectionLabel>
            {lead.events.length === 0 ? (
              <Muted>Not matched to any exhibitor directory or member list.</Muted>
            ) : (
              <ul style={{ margin: 0, padding: 0, listStyle: "none" }}>
                {lead.events.map((event) => (
                  <li key={event.id} className="mb-1.5 flex items-center gap-2">
                    <SourceLink href={event.url}>{event.name}</SourceLink>
                    <Chip>{event.event_type.replace(/_/g, " ")}</Chip>
                  </li>
                ))}
              </ul>
            )}
          </section>

          {/* ── Contacts ──────────────────────────────────────────────── */}
          <section style={{ marginBottom: 24 }}>
            <SectionLabel>Decision-makers ({lead.contacts.length})</SectionLabel>
            {lead.contacts.length === 0 ? (
              <Muted>
                No decision-maker resolved from public sources. This is where a Clay or Sales
                Navigator provider would take over — see integrations/contacts.
              </Muted>
            ) : (
              lead.contacts.map((contact) => (
                <div
                  key={contact.id}
                  style={{
                    border: "1px solid var(--c-hairline)",
                    borderRadius: 6,
                    padding: "9px 11px",
                    marginBottom: 6,
                    background: "var(--c-page)",
                  }}
                >
                  <div className="flex items-start justify-between gap-2">
                    <div style={{ minWidth: 0 }}>
                      <div style={{ fontSize: 12.5, fontWeight: 600 }}>{contact.full_name}</div>
                      <div style={{ fontSize: 11, color: "var(--c-t2)" }}>
                        {contact.title ?? "title unknown"}
                      </div>
                    </div>
                    <div className="flex shrink-0 items-center gap-1.5">
                      <ConfidenceMeter value={contact.confidence} />
                      {/* A mock contact must never read as sourced data. */}
                      <Chip
                        tone={contact.provider === "mock" ? "caution" : "neutral"}
                        title={
                          contact.provider === "mock"
                            ? "Placeholder data from the mock provider — not a real person"
                            : "Which provider resolved this contact"
                        }
                      >
                        {contact.provider}
                      </Chip>
                    </div>
                  </div>
                  <div className="mt-2 flex flex-wrap gap-3">
                    {contact.linkedin_url && (
                      <SourceLink href={contact.linkedin_url}>LinkedIn profile</SourceLink>
                    )}
                    {contact.sales_nav_url && (
                      <SourceLink href={contact.sales_nav_url}>Sales Navigator search</SourceLink>
                    )}
                    {contact.email && (
                      <span style={{ fontSize: 11, color: "var(--c-t2)" }}>{contact.email}</span>
                    )}
                  </div>
                </div>
              ))
            )}
          </section>

          {/* ── Outreach ──────────────────────────────────────────────── */}
          <section>
            <SectionLabel>Outreach</SectionLabel>
            {lead.outreach.length === 0 ? (
              <Muted>
                No draft. Outreach is generated only for tier A/B leads that have both a contact and
                at least one piece of evidence to ground the opening.
              </Muted>
            ) : (
              lead.outreach.map((draft) => (
                <OutreachEditor key={draft.id} draft={draft} onChange={onOutreachChange} />
              ))
            )}
          </section>
        </div>
      </aside>
    </>
  );
}

const FLAG_HELP: Record<string, string> = {
  size_unknown: "No revenue or headcount could be verified",
  no_website: "No website could be resolved for this company",
  not_enriched: "The company's own site could not be read",
  size_third_party_estimate:
    "The size figure came from an aggregator rather than the company itself",
  unsupported_claim_removed:
    "A sentence making a numeric claim we could not tie to a known figure was removed from the rationale",
  cited_unknown_source: "The model cited a URL outside the supplied evidence set",
  llm_failed: "The LLM call failed; a deterministic rationale was used instead",
};

function Muted({ children }: { children: React.ReactNode }) {
  return (
    <p style={{ fontSize: 12, color: "var(--c-t3)", margin: 0, lineHeight: 1.6 }}>{children}</p>
  );
}

function Field({ label, value, span }: { label: string; value?: string | null; span?: boolean }) {
  return (
    <div style={span ? { gridColumn: "1 / -1" } : undefined}>
      <dt style={{ fontSize: 10, color: "var(--c-t3)", marginBottom: 1 }}>{label}</dt>
      <dd style={{ fontSize: 12, color: "var(--c-t2)", margin: 0, lineHeight: 1.5 }}>
        {value || "—"}
      </dd>
    </div>
  );
}

function OutreachEditor({
  draft,
  onChange,
}: {
  draft: OutreachOut;
  onChange: (draft: OutreachOut) => void;
}) {
  const [body, setBody] = useState(draft.edited_body ?? draft.body);
  const [saving, setSaving] = useState(false);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const dirty = body !== (draft.edited_body ?? draft.body);

  async function save(approved?: boolean) {
    setSaving(true);
    setError(null);
    try {
      onChange(
        await api.patchOutreach(draft.id, {
          edited_body: dirty ? body : undefined,
          approved,
        }),
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "Save failed");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div
      style={{
        border: "1px solid var(--c-hairline)",
        borderRadius: 6,
        padding: 11,
        background: "var(--c-page)",
      }}
    >
      <div className="mb-2 flex items-start justify-between gap-2">
        <p style={{ fontSize: 12.5, fontWeight: 600, margin: 0 }}>{draft.subject}</p>
        <div className="flex shrink-0 items-center gap-1.5">
          {draft.approved && (
            <Chip tone="good" title="Approved for sending">
              approved
            </Chip>
          )}
          {/* Template vs LLM must stay visible: one is written from evidence, the
              other is assembled from a fixed sentence pattern. */}
          <Chip
            tone={draft.generator === "llm" ? "info" : "caution"}
            title={
              draft.generator === "llm"
                ? "Written by the LLM and validated against the evidence set"
                : "Deterministic template — the LLM draft was unavailable or failed validation"
            }
          >
            {draft.generator === "llm" ? "LLM" : "template"}
          </Chip>
        </div>
      </div>

      <textarea
        value={body}
        onChange={(e) => setBody(e.target.value)}
        rows={9}
        style={{
          width: "100%",
          resize: "vertical",
          borderRadius: 5,
          border: "1px solid var(--c-hairline)",
          background: "var(--c-surface)",
          color: "var(--c-t1)",
          padding: 9,
          fontSize: 12,
          lineHeight: 1.6,
          fontFamily: "inherit",
          outline: "none",
        }}
      />

      {draft.hook_fact && (
        <p style={{ fontSize: 10.5, color: "var(--c-t3)", marginTop: 6, lineHeight: 1.5 }}>
          Hook: {draft.hook_fact}{" "}
          {draft.hook_source_url && <SourceLink href={draft.hook_source_url}>source</SourceLink>}
        </p>
      )}
      {draft.tedlar_value_prop && (
        <p style={{ fontSize: 10.5, color: "var(--c-t3)" }}>
          Value prop: {draft.tedlar_value_prop}
        </p>
      )}

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <Button
          onClick={() => {
            navigator.clipboard.writeText(`${draft.subject}\n\n${body}`);
            setCopied(true);
            setTimeout(() => setCopied(false), 1500);
          }}
        >
          {copied ? "Copied" : "Copy"}
        </Button>
        <Button onClick={() => save()} disabled={!dirty || saving}>
          {saving ? "Saving…" : "Save edit"}
        </Button>
        <Button variant="primary" onClick={() => save(!draft.approved)} disabled={saving}>
          {draft.approved ? "Unapprove" : "Approve"}
        </Button>
        {error && (
          <span style={{ fontSize: 11, color: "var(--c-critical)" }}>{error}</span>
        )}
      </div>
    </div>
  );
}
