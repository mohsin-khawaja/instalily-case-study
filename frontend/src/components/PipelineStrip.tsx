"use client";

import { STAGES, type RunOut } from "@/lib/types";

const STATE_COLOR: Record<string, string> = {
  done: "var(--status-good)",
  partial: "var(--status-warning)",
  running: "var(--series-1)",
  failed: "var(--status-critical)",
  pending: "var(--text-muted)",
};

const STATE_LABEL: Record<string, string> = {
  done: "done",
  partial: "done, with errors",
  running: "running",
  failed: "failed",
  pending: "pending",
};

export function PipelineStrip({ run }: { run: RunOut | null }) {
  return (
    <div className="scroll-x">
      <ol className="flex min-w-max items-center gap-1">
        {STAGES.map((stage, index) => {
          const state = run?.stage_states?.[stage.key] ?? "pending";
          const color = STATE_COLOR[state] ?? STATE_COLOR.pending;
          return (
            <li key={stage.key} className="flex items-center gap-1">
              <span
                className="inline-flex items-center gap-1.5 rounded-md border px-2 py-1 text-xs"
                style={{ borderColor: "var(--border)" }}
                title={`${stage.label}: ${STATE_LABEL[state] ?? state}`}
              >
                <span
                  aria-hidden
                  className={`h-1.5 w-1.5 rounded-full ${state === "running" ? "animate-pulse" : ""}`}
                  style={{ background: color }}
                />
                <span style={{ color: "var(--text-secondary)" }}>{stage.label}</span>
                <span className="sr-only">{STATE_LABEL[state] ?? state}</span>
              </span>
              {index < STAGES.length - 1 && (
                <span aria-hidden style={{ color: "var(--text-muted)" }}>
                  ›
                </span>
              )}
            </li>
          );
        })}
      </ol>
    </div>
  );
}
