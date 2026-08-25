"use client";

import type { ReactNode } from "react";
import type { Tier } from "@/lib/types";

export function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return (
    <div
      className={`rounded-lg border border-hairline bg-surface ${className}`}
      style={{ borderColor: "var(--border)" }}
    >
      {children}
    </div>
  );
}

/** Tier is state, not a series: colour is paired with the letter and a word. */
const TIER_STYLE: Record<Tier, { color: string; label: string }> = {
  A: { color: "var(--status-good)", label: "Priority" },
  B: { color: "var(--series-1)", label: "Qualified" },
  C: { color: "var(--status-warning)", label: "Watch" },
  disqualified: { color: "var(--text-muted)", label: "Out of ICP" },
};

export function TierBadge({ tier, showLabel = true }: { tier: Tier; showLabel?: boolean }) {
  const { color, label } = TIER_STYLE[tier] ?? TIER_STYLE.disqualified;
  const letter = tier === "disqualified" ? "—" : tier;
  return (
    <span className="inline-flex items-center gap-1.5 whitespace-nowrap">
      <span
        aria-hidden
        className="grid h-5 w-5 place-items-center rounded text-[11px] font-bold text-white"
        style={{ background: color }}
      >
        {letter}
      </span>
      {showLabel && (
        <span className="text-xs" style={{ color: "var(--text-secondary)" }}>
          {label}
        </span>
      )}
    </span>
  );
}

/** Single-hue magnitude bar with the value direct-labelled. */
export function ScoreBar({ value, max = 100 }: { value: number; max?: number }) {
  const pct = Math.max(0, Math.min(100, (value / max) * 100));
  return (
    <div className="flex items-center gap-2">
      <div
        className="relative h-1.5 w-20 shrink-0 rounded-full"
        style={{ background: "var(--track)" }}
      >
        <div
          className="absolute inset-y-0 left-0 rounded-full"
          style={{ width: `${pct}%`, background: "var(--series-1)" }}
        />
      </div>
      <span className="tnum text-sm font-semibold">{value.toFixed(0)}</span>
    </div>
  );
}

export function ConfidenceDots({ value }: { value: number }) {
  const filled = Math.round(value * 4);
  return (
    <span className="inline-flex items-center gap-1" title={`Confidence ${(value * 100).toFixed(0)}%`}>
      <span className="flex gap-0.5" aria-hidden>
        {[0, 1, 2, 3].map((i) => (
          <span
            key={i}
            className="h-1.5 w-1.5 rounded-full"
            style={{ background: i < filled ? "var(--series-1)" : "var(--track)" }}
          />
        ))}
      </span>
      <span className="tnum text-xs" style={{ color: "var(--text-secondary)" }}>
        {(value * 100).toFixed(0)}%
      </span>
    </span>
  );
}

export function Chip({
  children,
  tone = "neutral",
  title,
}: {
  children: ReactNode;
  tone?: "neutral" | "warning" | "good";
  title?: string;
}) {
  const color =
    tone === "warning"
      ? "var(--status-serious)"
      : tone === "good"
        ? "var(--status-good)"
        : "var(--text-secondary)";
  return (
    <span
      title={title}
      className="inline-flex items-center rounded border px-1.5 py-0.5 text-[11px]"
      style={{ borderColor: "var(--border)", color }}
    >
      {children}
    </span>
  );
}

export function Button({
  children,
  onClick,
  disabled,
  variant = "secondary",
  type = "button",
}: {
  children: ReactNode;
  onClick?: () => void;
  disabled?: boolean;
  variant?: "primary" | "secondary";
  type?: "button" | "submit";
}) {
  const primary = variant === "primary";
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      className="rounded-md border px-3 py-1.5 text-sm font-medium transition-opacity disabled:opacity-40"
      style={{
        borderColor: primary ? "transparent" : "var(--border-strong)",
        background: primary ? "var(--series-1)" : "transparent",
        color: primary ? "#ffffff" : "var(--text-primary)",
      }}
    >
      {children}
    </button>
  );
}

export function Empty({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="px-4 py-14 text-center">
      <p className="text-sm font-medium">{title}</p>
      {hint && (
        <p className="mx-auto mt-1 max-w-md text-xs" style={{ color: "var(--text-secondary)" }}>
          {hint}
        </p>
      )}
    </div>
  );
}

export function Skeleton({ rows = 6 }: { rows?: number }) {
  return (
    <div className="space-y-2 p-4">
      {Array.from({ length: rows }).map((_, i) => (
        <div
          key={i}
          className="h-8 animate-pulse rounded"
          style={{ background: "var(--surface-2)" }}
        />
      ))}
    </div>
  );
}
