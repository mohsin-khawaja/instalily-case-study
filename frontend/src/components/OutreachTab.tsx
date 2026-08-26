"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import type { Lead, OutreachOut } from "@/lib/types";
import { Button, Chip, Empty, Skeleton, SourceLink, TierBadge } from "./Atoms";

/* Every draft in one place, in tier order, each one click from an addressed
   Gmail compose window. Sending from Gmail is what lets MailSuite track opens
   and forwards — there is no API to push a draft into MailSuite itself. */
export function OutreachTab({
  leads,
  loading,
  onOutreachChange,
}: {
  leads: Lead[];
  loading: boolean;
  onOutreachChange: (draft: OutreachOut) => void;
}) {
  const rows = leads
    .flatMap((lead) => lead.outreach.map((draft) => ({ lead, draft })))
    .sort((a, b) => b.lead.score_total - a.lead.score_total);

  const approved = rows.filter((r) => r.draft.approved).length;

  if (loading) return <Skeleton rows={5} />;
  if (!rows.length) {
    return (
      <Empty
        title="No outreach drafts yet"
        hint="Drafts are written only for tier A/B leads that have both a contact and evidence to ground the opening."
      />
    );
  }

  return (
    <div style={{ padding: 16 }}>
      <div
        className="mb-3 flex flex-wrap items-center gap-3"
        style={{ fontSize: 11.5, color: "var(--c-t3)" }}
      >
        <span>
          <span className="tabular" style={{ color: "var(--c-t1)", fontWeight: 600 }}>
            {rows.length}
          </span>{" "}
          drafts ·{" "}
          <span className="tabular" style={{ color: "var(--c-good)", fontWeight: 600 }}>
            {approved}
          </span>{" "}
          approved
        </span>
        <a
          href={api.outreachZipUrl()}
          style={{
            padding: "4px 10px",
            borderRadius: 5,
            border: "1px solid var(--c-hairline)",
            background: "var(--c-raised)",
            color: "var(--c-t1)",
            textDecoration: "none",
            fontSize: 11.5,
          }}
        >
          Download all as .eml
        </a>
        <a
          href={api.outreachZipUrl({ approved_only: true })}
          style={{
            padding: "4px 10px",
            borderRadius: 5,
            border: "1px solid var(--c-hairline)",
            background: "var(--c-raised)",
            color: "var(--c-t1)",
            textDecoration: "none",
            fontSize: 11.5,
          }}
        >
          Approved only
        </a>
        <span style={{ fontStyle: "italic" }}>
          Drag a .eml into Gmail, or use Open in Gmail. MailSuite tracks opens and forwards once
          you send.
        </span>
      </div>

      {rows.map(({ lead, draft }) => (
        <DraftCard
          key={draft.id}
          lead={lead}
          draft={draft}
          onOutreachChange={onOutreachChange}
        />
      ))}
    </div>
  );
}

function DraftCard({
  lead,
  draft,
  onOutreachChange,
}: {
  lead: Lead;
  draft: OutreachOut;
  onOutreachChange: (draft: OutreachOut) => void;
}) {
  const contact = lead.contacts.find((c) => c.id === draft.contact_id);
  const [body, setBody] = useState(draft.edited_body ?? draft.body);
  const [saving, setSaving] = useState(false);
  const [copied, setCopied] = useState(false);
  const dirty = body !== (draft.edited_body ?? draft.body);
  const placeholder = contact?.provider === "mock";

  async function save(approved?: boolean) {
    setSaving(true);
    try {
      onOutreachChange(
        await api.patchOutreach(draft.id, {
          edited_body: dirty ? body : undefined,
          approved,
        }),
      );
    } finally {
      setSaving(false);
    }
  }

  return (
    <div
      style={{
        border: "1px solid var(--c-hairline)",
        borderRadius: 7,
        background: "var(--c-surface)",
        padding: 12,
        marginBottom: 10,
      }}
    >
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <span style={{ fontSize: 12.5, fontWeight: 600 }}>{lead.company_name}</span>
        <TierBadge tier={lead.tier} />
        {contact && (
          <span style={{ fontSize: 11, color: "var(--c-t2)" }}>
            → {contact.full_name}
            {contact.title ? `, ${contact.title}` : ""}
          </span>
        )}
        {placeholder && (
          <Chip tone="caution" title="Placeholder contact — not a real person, so no send link">
            mock contact
          </Chip>
        )}
        <span className="ml-auto flex items-center gap-1.5">
          {draft.approved && <Chip tone="good">approved</Chip>}
          <Chip tone={draft.generator === "llm" ? "info" : "caution"}>
            {draft.generator === "llm" ? "LLM" : "template"}
          </Chip>
        </span>
      </div>

      <p style={{ fontSize: 12.5, fontWeight: 600, margin: "0 0 6px" }}>{draft.subject}</p>

      <textarea
        value={body}
        onChange={(e) => setBody(e.target.value)}
        rows={7}
        style={{
          width: "100%",
          resize: "vertical",
          borderRadius: 5,
          border: "1px solid var(--c-hairline)",
          background: "var(--c-page)",
          color: "var(--c-t1)",
          padding: 9,
          fontSize: 12,
          lineHeight: 1.6,
          fontFamily: "inherit",
          outline: "none",
        }}
      />

      {draft.hook_source_url && (
        <p style={{ fontSize: 10.5, color: "var(--c-t3)", margin: "6px 0 0" }}>
          Hook: {draft.hook_fact} <SourceLink href={draft.hook_source_url}>source</SourceLink>
        </p>
      )}

      <div className="mt-3 flex flex-wrap items-center gap-2">
        {draft.gmail_url ? (
          <a
            href={draft.gmail_url}
            target="_blank"
            rel="noreferrer"
            style={{
              padding: "5px 12px",
              borderRadius: 5,
              background: "var(--c-invert-bg)",
              color: "var(--c-invert-fg)",
              fontSize: 12,
              fontWeight: 600,
              textDecoration: "none",
            }}
          >
            Open in Gmail
          </a>
        ) : (
          <span style={{ fontSize: 11, color: "var(--c-caution)" }}>
            No send link — recipient is placeholder data
          </span>
        )}
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
      </div>
    </div>
  );
}
