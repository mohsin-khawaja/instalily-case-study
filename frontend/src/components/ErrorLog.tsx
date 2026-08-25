"use client";

import type { StageErrorOut } from "@/lib/types";
import { Chip, Empty, Skeleton } from "./primitives";

export function ErrorLog({ errors, loading }: { errors: StageErrorOut[]; loading: boolean }) {
  if (loading) return <Skeleton rows={5} />;
  if (!errors.length) {
    return <Empty title="No errors recorded" hint="Every stage completed without a handled failure." />;
  }
  return (
    <div className="scroll-x">
      <table className="w-full min-w-[820px] text-sm">
        <thead>
          <tr
            className="border-b text-left text-[11px] uppercase tracking-wide"
            style={{ borderColor: "var(--border)", color: "var(--text-muted)" }}
          >
            <th className="px-3 py-2 font-medium">Stage</th>
            <th className="px-3 py-2 font-medium">Entity</th>
            <th className="px-3 py-2 font-medium">Type</th>
            <th className="px-3 py-2 font-medium">Message</th>
            <th className="px-3 py-2 font-medium">Retryable</th>
          </tr>
        </thead>
        <tbody>
          {errors.map((error) => (
            <tr key={error.id} className="border-b" style={{ borderColor: "var(--border)" }}>
              <td className="px-3 py-2 whitespace-nowrap">{error.stage.replace(/_/g, " ")}</td>
              <td className="px-3 py-2" style={{ color: "var(--text-secondary)" }}>
                <div>{error.entity_ref ?? "—"}</div>
                <div className="text-[11px]" style={{ color: "var(--text-muted)" }}>
                  {error.entity_type}
                </div>
              </td>
              <td className="px-3 py-2 whitespace-nowrap">
                <Chip tone="warning">{error.error_type}</Chip>
              </td>
              <td className="px-3 py-2" style={{ color: "var(--text-secondary)" }}>
                {error.message}
              </td>
              <td className="px-3 py-2">{error.retryable ? "yes" : "no"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
