"use client";

import type { EventOut } from "@/lib/types";
import { Card, Chip, Empty, Skeleton } from "./primitives";

export function EventList({ events, loading }: { events: EventOut[]; loading: boolean }) {
  if (loading) return <Skeleton rows={4} />;
  if (!events.length) return <Empty title="No events discovered yet" />;

  return (
    <div className="grid gap-2 p-3 sm:grid-cols-2 xl:grid-cols-3">
      {events.map((event) => (
        <Card key={event.id} className="p-3">
          <div className="flex items-start justify-between gap-2">
            <a
              href={event.url}
              target="_blank"
              rel="noreferrer"
              className="text-sm font-medium underline underline-offset-2"
              style={{ color: "var(--series-1)" }}
            >
              {event.name}
            </a>
            {event.tier1 && <Chip tone="good" title="Flagship show for this ICP">tier 1</Chip>}
          </div>
          <div className="mt-1 flex flex-wrap gap-1.5">
            <Chip>{event.event_type.replace(/_/g, " ")}</Chip>
            {event.city && <Chip>{event.city}</Chip>}
            {event.status !== "complete" && (
              <Chip tone="warning" title="The site could not be verified on the last run">
                unverified
              </Chip>
            )}
            <Chip>{event.company_count} companies</Chip>
          </div>
          {event.relevance_note && (
            <p className="mt-2 text-xs leading-relaxed" style={{ color: "var(--text-secondary)" }}>
              {event.relevance_note}
            </p>
          )}
        </Card>
      ))}
    </div>
  );
}
