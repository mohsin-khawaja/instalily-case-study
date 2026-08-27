"use client";

import type { AgentOut } from "@/lib/types";
import { Chip, Empty, Skeleton } from "./Atoms";

const STATE_TONE: Record<string, "good" | "caution" | "info" | "critical" | "neutral"> = {
  done: "good",
  partial: "caution",
  running: "info",
  failed: "critical",
  pending: "neutral",
};

/* The pipeline as a team of specialists rather than a black box: what each one
   owns, where it hands off to the model, how it degrades, and what it actually
   produced on the last run. */
export function AgentsTab({ agents, loading }: { agents: AgentOut[]; loading: boolean }) {
  if (loading) return <Skeleton rows={6} />;
  if (!agents.length) return <Empty title="No agents reported" />;

  return (
    <div style={{ padding: 16 }}>
      <p style={{ fontSize: 11.5, color: "var(--c-t2)", margin: "0 0 12px", maxWidth: 760, lineHeight: 1.6 }}>
        Six specialists run in sequence. Each decides <em>what to do next</em> in code and
        delegates to the model only where judgement over messy language is genuinely needed —
        which is what makes the output reproducible rather than merely plausible.
      </p>

      {agents.map((agent, i) => (
        <div
          key={agent.stage}
          style={{
            border: "1px solid var(--c-hairline)",
            borderRadius: 7,
            background: "var(--c-surface)",
            padding: 13,
            marginBottom: 10,
          }}
        >
          <div className="flex flex-wrap items-center gap-2">
            <span
              aria-hidden
              className="tabular"
              style={{
                width: 20,
                height: 20,
                borderRadius: 5,
                background: "var(--c-raised)",
                border: "1px solid var(--c-hairline)",
                fontSize: 10,
                fontWeight: 700,
                color: "var(--c-t3)",
                display: "inline-flex",
                alignItems: "center",
                justifyContent: "center",
              }}
            >
              {i + 1}
            </span>
            <span style={{ fontSize: 13, fontWeight: 700 }}>{agent.name}</span>
            <Chip tone={STATE_TONE[agent.state] ?? "neutral"}>{agent.state}</Chip>
            {agent.handled_errors > 0 && (
              <Chip tone="caution" title="Failures this agent caught and recorded, without stopping the run">
                {agent.handled_errors} handled
              </Chip>
            )}
            <span className="ml-auto flex flex-wrap gap-1.5">
              {Object.entries(agent.results).map(([k, v]) => (
                <Chip key={k} mono title={k}>
                  {k.replace(/_/g, " ")} {v}
                </Chip>
              ))}
            </span>
          </div>

          <p style={{ fontSize: 12, lineHeight: 1.6, color: "var(--c-t1)", margin: "8px 0 0" }}>
            {agent.mission}
          </p>

          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))",
              gap: 12,
              marginTop: 10,
            }}
          >
            <Block label="Decides for itself">
              <ul style={{ margin: 0, paddingLeft: 15 }}>
                {agent.decides.map((d) => (
                  <li key={d} style={{ marginBottom: 2 }}>
                    {d}
                  </li>
                ))}
              </ul>
            </Block>

            <Block label={agent.delegates_to_llm ? "Delegates to the model" : "No model involved"}>
              {agent.delegates_to_llm ?? "Every decision in this stage is deterministic code."}
            </Block>

            <Block label="When a tool fails">{agent.degrades_to}</Block>
            <Block label="Guardrail">{agent.guardrail}</Block>
          </div>
        </div>
      ))}
    </div>
  );
}

function Block({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <p
        style={{
          fontSize: 9.5,
          fontWeight: 600,
          letterSpacing: 0.5,
          textTransform: "uppercase",
          color: "var(--c-t3)",
          margin: "0 0 3px",
        }}
      >
        {label}
      </p>
      <div style={{ fontSize: 11.5, lineHeight: 1.55, color: "var(--c-t2)" }}>{children}</div>
    </div>
  );
}
