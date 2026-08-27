"use client";

import type { EventOut } from "@/lib/types";
import { CautionChip, Chip, Empty, Skeleton, SourceLink } from "./Atoms";

/** "8–10 Apr 2026", or a single date, or nothing when undated. */
function formatDates(start?: string | null, end?: string | null): string {
  if (!start) return "";
  // These are date-only values. `new Date("2026-05-19")` parses as UTC midnight
  // and then renders in local time, which shifts the day backwards west of
  // Greenwich — the show would have read "18 May" for a 19 May opening.
  const opts: Intl.DateTimeFormatOptions = {
    day: "numeric",
    month: "short",
    year: "numeric",
    timeZone: "UTC",
  };
  const s = new Date(start);
  if (!end || end === start) return s.toLocaleDateString("en-GB", opts);
  const e = new Date(end);
  const sameMonth = s.getUTCMonth() === e.getUTCMonth() && s.getUTCFullYear() === e.getUTCFullYear();
  return sameMonth
    ? `${s.getUTCDate()}–${e.toLocaleDateString("en-GB", opts)}`
    : `${s.toLocaleDateString("en-GB", opts)} – ${e.toLocaleDateString("en-GB", opts)}`;
}

export function EventsTab({ events, loading }: { events: EventOut[]; loading: boolean }) {
  if (loading) return <Skeleton rows={5} />;
  if (!events.length) return <Empty title="No events discovered yet" />;

  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fill, minmax(320px, 1fr))",
        gap: 10,
        padding: 16,
      }}
    >
      {events.map((event) => (
        <div
          key={event.id}
          style={{
            border: "1px solid var(--c-hairline)",
            borderRadius: 7,
            padding: "11px 13px",
            background: "var(--c-surface)",
          }}
        >
          <div className="flex items-start justify-between gap-2">
            <SourceLink href={event.url}>{event.name}</SourceLink>
            {event.tier1 && (
              <Chip tone="good" title="Flagship show or body for this ICP">
                tier 1
              </Chip>
            )}
          </div>

          {formatDates(event.start_date, event.end_date) && (
            <p style={{ fontSize: 11.5, color: "var(--c-t1)", margin: "6px 0 0", fontWeight: 500 }}>
              {formatDates(event.start_date, event.end_date)}
              {event.venue ? ` · ${event.venue}` : ""}
            </p>
          )}

          <div className="mt-2 flex flex-wrap gap-1.5">
            <Chip>{event.event_type.replace(/_/g, " ")}</Chip>
            {event.city && <Chip>{event.city}</Chip>}
            {event.country && !event.city && <Chip>{event.country}</Chip>}
            <Chip tone="neutral">{event.company_count} companies</Chip>
            {event.status !== "complete" && (
              <CautionChip title="The site could not be verified on the last run">
                unverified
              </CautionChip>
            )}
          </div>

          {event.relevance_note && (
            <p
              style={{
                fontSize: 11.5,
                lineHeight: 1.55,
                color: "var(--c-t2)",
                margin: "9px 0 0",
              }}
            >
              {event.relevance_note}
            </p>
          )}
        </div>
      ))}
    </div>
  );
}
