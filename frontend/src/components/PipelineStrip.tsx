"use client";

import { STAGES, type RunOut, type Summary } from "@/lib/types";
import { CheckIcon, WarnIcon } from "./Atoms";

/* Five states, because "done" and "done with handled errors" are genuinely
   different outcomes and the run is usually the latter. */
const STATE = {
  done: { color: "var(--c-good)", label: "done" },
  partial: { color: "var(--c-caution)", label: "done, with handled errors" },
  running: { color: "var(--c-score-1)", label: "running" },
  failed: { color: "var(--c-critical)", label: "failed" },
  pending: { color: "var(--c-t3)", label: "pending" },
} as const;

type StateKey = keyof typeof STATE;

export function PipelineStrip({ run, summary }: { run: RunOut | null; summary: Summary | null }) {
  return (
    <div
      style={{
        background: "var(--c-surface)",
        borderBottom: "1px solid var(--c-hairline)",
        padding: "8px 24px 7px",
        flexShrink: 0,
      }}
    >
      <ol className="flex flex-wrap items-center gap-1" style={{ margin: 0, padding: 0 }}>
        {STAGES.map((stage, i) => {
          const key = (run?.stage_states?.[stage.key] ?? "pending") as StateKey;
          const state = STATE[key] ?? STATE.pending;
          return (
            <li key={stage.key} className="flex items-center gap-1" style={{ listStyle: "none" }}>
              <span
                className="inline-flex items-center gap-1.5 rounded"
                title={`${stage.label}: ${state.label}`}
                style={{
                  padding: "3px 9px",
                  fontSize: 11.5,
                  color: key === "pending" ? "var(--c-t3)" : "var(--c-t1)",
                  background: "var(--c-raised)",
                  border: `1px solid ${
                    key === "pending"
                      ? "var(--c-hairline)"
                      : `color-mix(in srgb, ${state.color} 26%, transparent)`
                  }`,
                }}
              >
                <span style={{ color: state.color, display: "inline-flex" }}>
                  <StageIcon state={key} />
                </span>
                {stage.label}
                <span className="sr-only">{state.label}</span>
              </span>
              {i < STAGES.length - 1 && (
                <span aria-hidden style={{ color: "var(--c-t3)", fontSize: 11 }}>
                  →
                </span>
              )}
            </li>
          );
        })}
      </ol>

      {summary && (
        <div
          className="mt-1.5 flex flex-wrap items-center gap-x-4 gap-y-1"
          style={{ fontSize: 10.5, color: "var(--c-t3)" }}
        >
          <span className="inline-flex items-center gap-1.5">
            <span
              aria-hidden
              style={{
                width: 5,
                height: 5,
                borderRadius: "50%",
                background: summary.llm_enabled ? "var(--c-good)" : "var(--c-t3)",
              }}
            />
            {summary.llm_enabled ? "LLM enabled" : "LLM disabled — deterministic fallbacks"}
          </span>
          <span className="inline-flex items-center gap-1.5">
            search
            <Tag>{summary.search_provider}</Tag>
          </span>
          <span className="inline-flex items-center gap-1.5">
            contacts
            {summary.contact_providers.map((p) => (
              <Tag key={p}>{p}</Tag>
            ))}
          </span>
        </div>
      )}
    </div>
  );
}

function StageIcon({ state }: { state: StateKey }) {
  if (state === "done") return <CheckIcon />;
  if (state === "partial" || state === "failed") return <WarnIcon size={10} />;
  if (state === "running")
    return (
      <svg width="10" height="10" viewBox="0 0 12 12" fill="none" style={{ animation: "spin 1s linear infinite" }}>
        <circle cx="6" cy="6" r="4.6" stroke="currentColor" strokeWidth="1.4" strokeDasharray="16 8" />
      </svg>
    );
  return <span style={{ width: 10, height: 10, display: "inline-block" }} />;
}

function Tag({ children }: { children: React.ReactNode }) {
  return (
    <span
      className="rounded"
      style={{
        padding: "0 5px",
        background: "var(--c-raised)",
        border: "1px solid var(--c-hairline)",
        color: "var(--c-t2)",
        fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
        fontSize: 10,
      }}
    >
      {children}
    </span>
  );
}
