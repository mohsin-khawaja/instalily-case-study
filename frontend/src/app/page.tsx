"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError } from "@/lib/api";
import type {
  EventOut,
  Lead,
  OutreachOut,
  RunOut,
  StageErrorOut,
  Summary,
  Tier,
} from "@/lib/types";
import { ErrorLog } from "@/components/ErrorLog";
import { EventList } from "@/components/EventList";
import { LeadDetail } from "@/components/LeadDetail";
import { LeadTable } from "@/components/LeadTable";
import { MetricsBar } from "@/components/MetricsBar";
import { PipelineStrip } from "@/components/PipelineStrip";
import { Button, Card } from "@/components/primitives";

const TIER_FILTERS: { value: Tier; label: string }[] = [
  { value: "A", label: "A — Priority" },
  { value: "B", label: "B — Qualified" },
  { value: "C", label: "C — Watch" },
  { value: "disqualified", label: "Out of ICP" },
];

type Tab = "leads" | "events" | "errors";

export default function Dashboard() {
  const [summary, setSummary] = useState<Summary | null>(null);
  const [leads, setLeads] = useState<Lead[]>([]);
  const [events, setEvents] = useState<EventOut[]>([]);
  const [errors, setErrors] = useState<StageErrorOut[]>([]);
  const [run, setRun] = useState<RunOut | null>(null);

  const [tab, setTab] = useState<Tab>("leads");
  const [loading, setLoading] = useState(true);
  const [apiError, setApiError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | undefined>();

  const [tiers, setTiers] = useState<Tier[]>([]);
  const [eventId, setEventId] = useState("");
  const [minScore, setMinScore] = useState(0);
  const [query, setQuery] = useState("");
  const [mode, setMode] = useState("cached");
  const [starting, setStarting] = useState(false);

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const load = useCallback(async () => {
    try {
      const [s, l, e, err, runs] = await Promise.all([
        api.summary(),
        api.leads({
          tier: tiers.length ? tiers : undefined,
          event_id: eventId || undefined,
          min_score: minScore || undefined,
          q: query || undefined,
        }),
        api.events(),
        api.errors(),
        api.runs(),
      ]);
      setSummary(s);
      setLeads(l);
      setEvents(e);
      setErrors(err);
      setRun(runs[0] ?? null);
      setApiError(null);
    } catch (e) {
      setApiError(e instanceof ApiError ? e.message : "Unexpected error loading data");
    } finally {
      setLoading(false);
    }
  }, [tiers, eventId, minScore, query]);

  useEffect(() => {
    void load();
  }, [load]);

  // Poll only while a run is active, then refresh everything once it settles.
  useEffect(() => {
    if (run?.status !== "running") {
      if (pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
      return;
    }
    const id = run.id;
    pollRef.current = setInterval(async () => {
      try {
        const latest = await api.run(id);
        setRun(latest);
        if (latest.status !== "running") void load();
      } catch {
        /* transient poll failure: the next tick retries */
      }
    }, 2500);
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [run?.status, run?.id, load]);

  const selected = useMemo(
    () => leads.find((lead) => lead.company_id === selectedId),
    [leads, selectedId],
  );

  async function startRun() {
    setStarting(true);
    try {
      const started = await api.startRun(mode);
      setRun(started);
      setApiError(null);
    } catch (e) {
      setApiError(e instanceof ApiError ? e.message : "Could not start the run");
    } finally {
      setStarting(false);
    }
  }

  function applyOutreach(updated: OutreachOut) {
    setLeads((current) =>
      current.map((lead) => ({
        ...lead,
        outreach: lead.outreach.map((d) => (d.id === updated.id ? updated : d)),
      })),
    );
  }

  const running = run?.status === "running";

  return (
    <div className="min-h-screen">
      <header
        className="sticky top-0 z-30 border-b px-4 py-3 backdrop-blur"
        style={{ borderColor: "var(--border)", background: "color-mix(in srgb, var(--page) 88%, transparent)" }}
      >
        <div className="mx-auto flex max-w-[1600px] flex-wrap items-center gap-3">
          <div className="mr-auto">
            <h1 className="text-base font-semibold">Tedlar Lead Agent</h1>
            <p className="text-xs" style={{ color: "var(--text-secondary)" }}>
              DuPont Tedlar — Graphics &amp; Signage · lead discovery, qualification and outreach
            </p>
          </div>

          <select
            value={mode}
            onChange={(e) => setMode(e.target.value)}
            className="rounded-md border px-2 py-1.5 text-sm"
            style={{ borderColor: "var(--border-strong)", background: "transparent" }}
            title="Cached replays the committed HTTP snapshot; live re-fetches every source."
          >
            <option value="cached">Cached run</option>
            <option value="live">Live run</option>
          </select>
          <Button variant="primary" onClick={startRun} disabled={starting || running}>
            {running ? "Pipeline running…" : starting ? "Starting…" : "Run lead discovery"}
          </Button>
        </div>

        <div className="mx-auto mt-3 flex max-w-[1600px] flex-wrap items-center gap-3">
          <PipelineStrip run={run} />
          {summary && (
            <p className="ml-auto text-[11px]" style={{ color: "var(--text-muted)" }}>
              LLM {summary.llm_enabled ? "enabled" : "disabled (deterministic fallbacks)"} · search{" "}
              {summary.search_provider} · contacts {summary.contact_providers.join(" → ")}
            </p>
          )}
        </div>
      </header>

      <main className="mx-auto max-w-[1600px] space-y-4 px-4 py-4">
        {apiError && (
          <Card className="px-4 py-3">
            <p className="text-sm" style={{ color: "var(--status-critical)" }}>
              {apiError}
            </p>
          </Card>
        )}

        <MetricsBar summary={summary} />

        <Card>
          <div
            className="flex flex-wrap items-center gap-2 border-b px-3 py-2"
            style={{ borderColor: "var(--border)" }}
          >
            {(["leads", "events", "errors"] as Tab[]).map((t) => (
              <button
                key={t}
                onClick={() => setTab(t)}
                className="rounded px-2.5 py-1 text-sm capitalize"
                style={{
                  background: tab === t ? "var(--surface-2)" : "transparent",
                  color: tab === t ? "var(--text-primary)" : "var(--text-secondary)",
                }}
              >
                {t}
                {t === "errors" && errors.length > 0 && (
                  <span className="tnum ml-1.5 text-xs" style={{ color: "var(--status-serious)" }}>
                    {errors.length}
                  </span>
                )}
              </button>
            ))}
          </div>

          {tab === "leads" && (
            <>
              <div
                className="flex flex-wrap items-center gap-2 border-b px-3 py-2"
                style={{ borderColor: "var(--border)" }}
              >
                <input
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="Search company, industry, product…"
                  className="min-w-56 flex-1 rounded-md border px-2.5 py-1.5 text-sm"
                  style={{ borderColor: "var(--border-strong)", background: "transparent" }}
                />
                <select
                  value={eventId}
                  onChange={(e) => setEventId(e.target.value)}
                  className="rounded-md border px-2 py-1.5 text-sm"
                  style={{ borderColor: "var(--border-strong)", background: "transparent" }}
                >
                  <option value="">All events</option>
                  {events.map((event) => (
                    <option key={event.id} value={event.id}>
                      {event.name}
                    </option>
                  ))}
                </select>
                <label
                  className="flex items-center gap-2 text-xs"
                  style={{ color: "var(--text-secondary)" }}
                >
                  min score
                  <input
                    type="range"
                    min={0}
                    max={100}
                    step={5}
                    value={minScore}
                    onChange={(e) => setMinScore(Number(e.target.value))}
                  />
                  <span className="tnum w-6">{minScore}</span>
                </label>
                <div className="flex flex-wrap gap-1">
                  {TIER_FILTERS.map((filter) => {
                    const active = tiers.includes(filter.value);
                    return (
                      <button
                        key={filter.value}
                        onClick={() =>
                          setTiers((current) =>
                            active
                              ? current.filter((t) => t !== filter.value)
                              : [...current, filter.value],
                          )
                        }
                        className="rounded border px-2 py-1 text-xs"
                        style={{
                          borderColor: active ? "var(--series-1)" : "var(--border)",
                          color: active ? "var(--series-1)" : "var(--text-secondary)",
                        }}
                      >
                        {filter.label}
                      </button>
                    );
                  })}
                </div>
              </div>
              <LeadTable
                leads={leads}
                loading={loading}
                selectedId={selectedId}
                onSelect={(lead) => setSelectedId(lead.company_id)}
              />
            </>
          )}

          {tab === "events" && <EventList events={events} loading={loading} />}
          {tab === "errors" && <ErrorLog errors={errors} loading={loading} />}
        </Card>
      </main>

      {selected && (
        <LeadDetail
          lead={selected}
          onClose={() => setSelectedId(undefined)}
          onOutreachChange={applyOutreach}
        />
      )}
    </div>
  );
}
