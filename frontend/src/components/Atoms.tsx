"use client";

import type { CSSProperties, ReactNode } from "react";
import type { Tier } from "@/lib/types";

/* ── Tier badge ───────────────────────────────────────────────────────────
   Colour never carries meaning alone: every badge pairs a letter with a word,
   so the tier survives greyscale, colour-vision deficiency and a projector. */

const TIER: Record<Tier, { letter: string; label: string; color: string }> = {
  A: { letter: "A", label: "Priority", color: "var(--c-good)" },
  B: { letter: "B", label: "Qualified", color: "var(--c-score-1)" },
  C: { letter: "C", label: "Watch", color: "var(--c-warning)" },
  disqualified: { letter: "—", label: "Out of ICP", color: "var(--c-t3)" },
};

export function TierBadge({ tier }: { tier: Tier }) {
  const t = TIER[tier] ?? TIER.disqualified;
  return (
    <span
      className="inline-flex items-center gap-1.5 whitespace-nowrap rounded"
      style={{
        padding: "2px 8px 2px 6px",
        fontSize: 11,
        fontWeight: 500,
        color: t.color,
        background: mix(t.color, 0.1),
        border: `1px solid ${mix(t.color, 0.22)}`,
      }}
    >
      <span
        aria-hidden
        style={{ width: 5, height: 5, borderRadius: "50%", background: t.color, flexShrink: 0 }}
      />
      {t.letter} · {t.label}
    </span>
  );
}

/** A colour at low opacity, for tinted chip backgrounds. */
function mix(color: string, alpha: number) {
  return `color-mix(in srgb, ${color} ${Math.round(alpha * 100)}%, transparent)`;
}

/* ── Score ────────────────────────────────────────────────────────────────── */

export function ScoreCell({ value }: { value: number }) {
  return (
    <span className="tabular" style={{ whiteSpace: "nowrap" }}>
      <span style={{ fontSize: 13, fontWeight: 600, color: "var(--c-score-1)" }}>
        {value.toFixed(0)}
      </span>
      <span style={{ fontSize: 11, color: "var(--c-t3)" }}>/100</span>
    </span>
  );
}

/** Four discrete bars rather than a percentage bar: confidence is a coarse
 *  judgement and a continuous bar would imply precision it does not have. */
export function ConfidenceMeter({ value }: { value: number }) {
  const filled = Math.round(value * 4);
  return (
    <span
      className="inline-flex items-center gap-1.5"
      title={`Confidence ${(value * 100).toFixed(0)}%`}
    >
      <span className="flex items-end gap-[2px]" aria-hidden>
        {[0, 1, 2, 3].map((i) => (
          <span
            key={i}
            style={{
              width: 3,
              height: 7 + i * 2,
              borderRadius: 1,
              background: i < filled ? "var(--c-good)" : "var(--c-track)",
            }}
          />
        ))}
      </span>
      <span className="tabular" style={{ fontSize: 11, color: "var(--c-t2)" }}>
        {(value * 100).toFixed(0)}%
      </span>
    </span>
  );
}

/* ── Chips ────────────────────────────────────────────────────────────────── */

type ChipTone = "neutral" | "caution" | "good" | "critical" | "info";

const TONE: Record<ChipTone, string> = {
  neutral: "var(--c-t2)",
  caution: "var(--c-caution)",
  good: "var(--c-good)",
  critical: "var(--c-critical)",
  info: "var(--c-score-1)",
};

export function Chip({
  children,
  tone = "neutral",
  title,
  mono,
  style,
}: {
  children: ReactNode;
  tone?: ChipTone;
  title?: string;
  mono?: boolean;
  style?: CSSProperties;
}) {
  const color = TONE[tone];
  return (
    <span
      title={title}
      className="inline-flex items-center gap-1 whitespace-nowrap rounded"
      style={{
        padding: "1px 6px",
        fontSize: 10.5,
        color: tone === "neutral" ? "var(--c-t2)" : color,
        background: tone === "neutral" ? "var(--c-raised)" : mix(color, 0.1),
        border: `1px solid ${tone === "neutral" ? "var(--c-hairline)" : mix(color, 0.22)}`,
        fontFamily: mono ? "ui-monospace, SFMono-Regular, Menlo, monospace" : undefined,
        ...style,
      }}
    >
      {children}
    </span>
  );
}

/** A caution chip always carries its icon, so the state is never colour-only. */
export function CautionChip({ children, title }: { children: ReactNode; title?: string }) {
  return (
    <Chip tone="caution" title={title}>
      <WarnIcon />
      {children}
    </Chip>
  );
}

export function WarnIcon({ size = 9 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 10 10" fill="none" aria-hidden>
      <path
        d="M5 1.2 9.2 8.6H0.8L5 1.2Z"
        stroke="currentColor"
        strokeWidth="1.1"
        strokeLinejoin="round"
      />
      <path d="M5 4.1v1.8" stroke="currentColor" strokeWidth="1.1" strokeLinecap="round" />
      <circle cx="5" cy="7.1" r="0.5" fill="currentColor" />
    </svg>
  );
}

export function CheckIcon({ size = 10 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 12 12" fill="none" aria-hidden>
      <circle cx="6" cy="6" r="5" stroke="currentColor" strokeWidth="1.3" />
      <path
        d="M3.8 6.2 5.3 7.7 8.2 4.5"
        stroke="currentColor"
        strokeWidth="1.3"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

export function ExternalIcon({ size = 9 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 10 10" fill="none" aria-hidden>
      <path
        d="M3.5 1.5h5v5M8.5 1.5 4 6M6.5 8.5h-5v-5"
        stroke="currentColor"
        strokeWidth="1.1"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

/* ── Buttons ──────────────────────────────────────────────────────────────── */

export function Button({
  children,
  onClick,
  disabled,
  variant = "secondary",
  title,
}: {
  children: ReactNode;
  onClick?: () => void;
  disabled?: boolean;
  variant?: "primary" | "secondary" | "ghost";
  title?: string;
}) {
  const primary = variant === "primary";
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      title={title}
      className="inline-flex items-center gap-1.5 rounded transition-opacity disabled:opacity-45"
      style={{
        padding: "5px 12px",
        fontSize: 12,
        fontWeight: primary ? 600 : 500,
        borderRadius: 5,
        cursor: disabled ? "default" : "pointer",
        border: variant === "ghost" ? "1px solid transparent" : "1px solid var(--c-hairline)",
        background: primary ? "var(--c-invert-bg)" : "var(--c-raised)",
        color: primary ? "var(--c-invert-fg)" : "var(--c-t1)",
      }}
    >
      {children}
    </button>
  );
}

/* ── Layout helpers ───────────────────────────────────────────────────────── */

export function SectionLabel({ children }: { children: ReactNode }) {
  return (
    <div
      style={{
        fontSize: 10,
        fontWeight: 600,
        letterSpacing: 0.6,
        textTransform: "uppercase",
        color: "var(--c-t3)",
        marginBottom: 8,
      }}
    >
      {children}
    </div>
  );
}

export function Empty({ title, hint }: { title: string; hint?: string }) {
  return (
    <div style={{ padding: "64px 24px", textAlign: "center" }}>
      <p style={{ fontSize: 13, fontWeight: 500, margin: 0 }}>{title}</p>
      {hint && (
        <p
          style={{
            fontSize: 11.5,
            color: "var(--c-t3)",
            margin: "6px auto 0",
            maxWidth: 420,
            lineHeight: 1.6,
          }}
        >
          {hint}
        </p>
      )}
    </div>
  );
}

export function Skeleton({ rows = 8 }: { rows?: number }) {
  return (
    <div style={{ padding: 16 }}>
      {Array.from({ length: rows }).map((_, i) => (
        <div
          key={i}
          style={{
            height: 34,
            marginBottom: 6,
            borderRadius: 4,
            background: "var(--c-raised)",
            animation: "pulse 1.4s ease-in-out infinite",
            animationDelay: `${i * 60}ms`,
          }}
        />
      ))}
    </div>
  );
}

export function SourceLink({ href, children }: { href: string; children?: ReactNode }) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
      className="inline-flex items-baseline gap-1 hover:underline"
      style={{
        fontSize: 11,
        color: "var(--c-score-1)",
        wordBreak: "break-all",
        textUnderlineOffset: 2,
      }}
    >
      {children ?? href}
      <ExternalIcon />
    </a>
  );
}
