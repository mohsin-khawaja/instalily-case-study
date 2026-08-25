"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { SCORE_COMPONENTS, type Lead, type OutreachOut } from "@/lib/types";
import { Button, Chip, ConfidenceDots, TierBadge } from "./primitives";

export function LeadDetail({
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
    <aside
      className="fixed inset-y-0 right-0 z-40 flex w-full max-w-xl flex-col border-l shadow-2xl"
      style={{ background: "var(--surface)", borderColor: "var(--border)" }}
      aria-label={`${lead.company_name} details`}
    >
      <header
        className="flex items-start justify-between gap-4 border-b px-5 py-4"
        style={{ borderColor: "var(--border)" }}
      >
        <div>
          <div className="flex items-center gap-2">
            <h2 className="text-lg font-semibold">{lead.company_name}</h2>
            <TierBadge tier={lead.tier} />
          </div>
          {lead.website && (
            <a
              href={lead.website}
              target="_blank"
              rel="noreferrer"
              className="text-xs underline underline-offset-2"
              style={{ color: "var(--series-1)" }}
            >
              {lead.website}
            </a>
          )}
        </div>
        <Button onClick={onClose}>Close</Button>
      </header>

      <div className="flex-1 space-y-6 overflow-y-auto px-5 py-5">
        <Section title="Score breakdown">
          <div className="mb-3 flex items-baseline gap-3">
            <span className="tnum text-3xl font-semibold">{lead.score_total.toFixed(0)}</span>
            <span className="text-sm" style={{ color: "var(--text-secondary)" }}>
              / 100
            </span>
            <span className="ml-auto">
              <ConfidenceDots value={lead.confidence} />
            </span>
          </div>
          <ul className="space-y-2">
            {SCORE_COMPONENTS.map((component) => {
              const value = Number(lead.score?.[component.key] ?? 0);
              const pct = (value / component.max) * 100;
              return (
                <li key={component.key} className="flex items-center gap-3">
                  <span className="w-40 shrink-0 text-xs" style={{ color: "var(--text-secondary)" }}>
                    {component.label}
                  </span>
                  <span
                    className="relative h-1.5 flex-1 rounded-full"
                    style={{ background: "var(--track)" }}
                  >
                    <span
                      className="absolute inset-y-0 left-0 rounded-full"
                      style={{ width: `${pct}%`, background: component.color }}
                    />
                  </span>
                  <span className="tnum w-14 shrink-0 text-right text-xs">
                    {value.toFixed(0)}/{component.max}
                  </span>
                </li>
              );
            })}
          </ul>
          {lead.flags.length > 0 && (
            <div className="mt-3 flex flex-wrap gap-1.5">
              {lead.flags.map((flag) => (
                <Chip key={flag} tone="warning" title="Gap that lowered confidence">
                  {flag.replace(/_/g, " ")}
                </Chip>
              ))}
            </div>
          )}
        </Section>

        <Section title="Why this is a qualified lead">
          <p className="text-sm leading-relaxed" style={{ color: "var(--text-secondary)" }}>
            {lead.rationale ?? "No rationale generated."}
          </p>
          <p className="mt-2 text-[11px]" style={{ color: "var(--text-muted)" }}>
            Generated {lead.rationale_source === "llm" ? "by the LLM over verified evidence" : "deterministically from the score breakdown"}.
          </p>
        </Section>

        <Section title={`Evidence (${lead.evidence.length})`}>
          {lead.evidence.length === 0 ? (
            <p className="text-sm" style={{ color: "var(--text-muted)" }}>
              No evidence captured for this company.
            </p>
          ) : (
            <ul className="space-y-2">
              {lead.evidence.map((item, i) => (
                <li
                  key={i}
                  className="rounded border px-3 py-2"
                  style={{ borderColor: "var(--border)" }}
                >
                  <p className="text-sm">{item.claim}</p>
                  {item.quote && (
                    <p className="mt-1 text-xs italic" style={{ color: "var(--text-muted)" }}>
                      “{item.quote.slice(0, 200)}”
                    </p>
                  )}
                  <a
                    href={item.source_url}
                    target="_blank"
                    rel="noreferrer"
                    className="mt-1 inline-block break-all text-xs underline underline-offset-2"
                    style={{ color: "var(--series-1)" }}
                  >
                    {item.source_url}
                  </a>
                </li>
              ))}
            </ul>
          )}
        </Section>

        <Section title="Company profile">
          <dl className="grid grid-cols-3 gap-x-3 gap-y-2 text-sm">
            <Field label="Industry" value={lead.industry} />
            <Field label="HQ" value={lead.hq_location} />
            <Field label="Revenue" value={lead.revenue_band} />
            <Field label="Headcount" value={lead.employee_band} />
            <Field
              label="Sub-industries"
              value={lead.sub_industries.join(", ") || null}
              span
            />
            <Field label="Products" value={lead.products.join(", ") || null} span />
            <Field label="Description" value={lead.description} span />
          </dl>
        </Section>

        <Section title={`Events & associations (${lead.events.length})`}>
          {lead.events.length === 0 ? (
            <p className="text-sm" style={{ color: "var(--text-muted)" }}>
              Not matched to any exhibitor directory or member list.
            </p>
          ) : (
            <ul className="space-y-1.5">
              {lead.events.map((event) => (
                <li key={event.id} className="text-sm">
                  <a
                    href={event.url}
                    target="_blank"
                    rel="noreferrer"
                    className="underline underline-offset-2"
                    style={{ color: "var(--series-1)" }}
                  >
                    {event.name}
                  </a>
                  <span className="ml-2 text-xs" style={{ color: "var(--text-muted)" }}>
                    {event.event_type.replace(/_/g, " ")}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </Section>

        <Section title={`Decision-makers (${lead.contacts.length})`}>
          {lead.contacts.length === 0 ? (
            <p className="text-sm" style={{ color: "var(--text-muted)" }}>
              No decision-maker resolved from public sources. This is where a Clay or
              Sales Navigator provider would take over — see integrations/contacts.
            </p>
          ) : (
            <ul className="space-y-2">
              {lead.contacts.map((contact) => (
                <li
                  key={contact.id}
                  className="rounded border px-3 py-2"
                  style={{ borderColor: "var(--border)" }}
                >
                  <div className="flex items-center justify-between gap-2">
                    <div>
                      <p className="text-sm font-medium">{contact.full_name}</p>
                      <p className="text-xs" style={{ color: "var(--text-secondary)" }}>
                        {contact.title ?? "title unknown"}
                      </p>
                    </div>
                    <Chip
                      tone={contact.provider === "mock" ? "warning" : "neutral"}
                      title="Which provider resolved this contact"
                    >
                      {contact.provider}
                    </Chip>
                  </div>
                  <div className="mt-2 flex flex-wrap gap-3 text-xs">
                    {contact.linkedin_url && (
                      <a href={contact.linkedin_url} target="_blank" rel="noreferrer"
                         className="underline underline-offset-2" style={{ color: "var(--series-1)" }}>
                        LinkedIn profile
                      </a>
                    )}
                    {contact.sales_nav_url && (
                      <a href={contact.sales_nav_url} target="_blank" rel="noreferrer"
                         className="underline underline-offset-2" style={{ color: "var(--series-1)" }}>
                        Sales Navigator search
                      </a>
                    )}
                    {contact.email && <span>{contact.email}</span>}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Section>

        <Section title="Outreach">
          {lead.outreach.length === 0 ? (
            <p className="text-sm" style={{ color: "var(--text-muted)" }}>
              No draft. Outreach is generated only for tier A/B leads that have both a
              contact and at least one piece of evidence to ground the opening.
            </p>
          ) : (
            lead.outreach.map((draft) => (
              <OutreachEditor key={draft.id} draft={draft} onChange={onOutreachChange} />
            ))
          )}
        </Section>
      </div>
    </aside>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section>
      <h3
        className="mb-2 text-[11px] font-semibold uppercase tracking-wide"
        style={{ color: "var(--text-muted)" }}
      >
        {title}
      </h3>
      {children}
    </section>
  );
}

function Field({ label, value, span }: { label: string; value?: string | null; span?: boolean }) {
  return (
    <div className={span ? "col-span-3" : ""}>
      <dt className="text-[11px]" style={{ color: "var(--text-muted)" }}>
        {label}
      </dt>
      <dd style={{ color: "var(--text-secondary)" }}>{value ?? "—"}</dd>
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
      const updated = await api.patchOutreach(draft.id, {
        edited_body: dirty ? body : undefined,
        approved,
      });
      onChange(updated);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Save failed");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="rounded border p-3" style={{ borderColor: "var(--border)" }}>
      <div className="mb-2 flex items-center justify-between gap-2">
        <p className="text-sm font-medium">{draft.subject}</p>
        <div className="flex shrink-0 items-center gap-1.5">
          {draft.approved && (
            <Chip tone="good" title="Approved for sending">
              approved
            </Chip>
          )}
          <Chip
            tone={draft.generator === "llm" ? "neutral" : "warning"}
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
        className="w-full resize-y rounded border p-2 text-sm"
        style={{
          borderColor: "var(--border)",
          background: "var(--surface-2)",
          color: "var(--text-primary)",
        }}
      />

      {draft.hook_fact && (
        <p className="mt-2 text-[11px]" style={{ color: "var(--text-muted)" }}>
          Hook: {draft.hook_fact}{" "}
          {draft.hook_source_url && (
            <a
              href={draft.hook_source_url}
              target="_blank"
              rel="noreferrer"
              className="underline underline-offset-2"
              style={{ color: "var(--series-1)" }}
            >
              source
            </a>
          )}
        </p>
      )}
      {draft.tedlar_value_prop && (
        <p className="text-[11px]" style={{ color: "var(--text-muted)" }}>
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
          <span className="text-xs" style={{ color: "var(--status-critical)" }}>
            {error}
          </span>
        )}
      </div>
    </div>
  );
}
