"use client";

import type { StageErrorOut } from "@/lib/types";
import { Chip, Empty, Skeleton } from "./Atoms";

/* Neutral and informative on purpose. These are failures the pipeline caught and
   recorded; a surface that looks like a crash report would misrepresent them. */
export function ErrorsTab({ errors, loading }: { errors: StageErrorOut[]; loading: boolean }) {
  if (loading) return <Skeleton rows={6} />;
  if (!errors.length) {
    return (
      <Empty
        title="No errors on the last run"
        hint="Every stage completed without a handled failure."
      />
    );
  }

  return (
    <div style={{ overflow: "auto" }}>
      <p
        style={{
          fontSize: 11,
          color: "var(--c-t3)",
          padding: "10px 16px 0",
          margin: 0,
        }}
      >
        Handled failures from the most recent run. Each one degraded a single record; the run
        continued.
      </p>
      <table style={{ width: "100%", minWidth: 860, borderCollapse: "collapse", marginTop: 8 }}>
        <thead>
          <tr>
            {["Stage", "Entity", "Type", "Message", "Retryable"].map((c) => (
              <th
                key={c}
                style={{
                  textAlign: "left",
                  padding: "7px 16px",
                  fontSize: 10,
                  fontWeight: 600,
                  letterSpacing: 0.6,
                  textTransform: "uppercase",
                  color: "var(--c-t3)",
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
          {errors.map((error) => (
            <tr key={error.id} style={{ borderBottom: "1px solid var(--c-hairline)" }}>
              <td style={{ padding: "9px 16px", fontSize: 12, whiteSpace: "nowrap" }}>
                {error.stage.replace(/_/g, " ")}
              </td>
              <td style={{ padding: "9px 16px", maxWidth: 260 }}>
                <div
                  style={{
                    fontSize: 11.5,
                    color: "var(--c-t2)",
                    fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
                    wordBreak: "break-all",
                  }}
                >
                  {error.entity_ref ?? "—"}
                </div>
                <div style={{ fontSize: 10, color: "var(--c-t3)" }}>{error.entity_type}</div>
              </td>
              <td style={{ padding: "9px 16px", whiteSpace: "nowrap" }}>
                <Chip tone="caution">{error.error_type}</Chip>
              </td>
              <td
                style={{
                  padding: "9px 16px",
                  fontSize: 11.5,
                  color: "var(--c-t2)",
                  lineHeight: 1.5,
                }}
              >
                {error.message}
              </td>
              <td style={{ padding: "9px 16px", fontSize: 11.5, color: "var(--c-t2)" }}>
                {error.retryable ? "yes" : "no"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
