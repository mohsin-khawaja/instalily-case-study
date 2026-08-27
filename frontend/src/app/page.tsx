"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ApiError, api } from "@/lib/api";
import type {
  AgentOut,
  EventOut,
  Lead,
  OutreachOut,
  RunOut,
  StageErrorOut,
  Summary,
  Tier,
} from "@/lib/types";
import { Button, WarnIcon } from "@/components/Atoms";
import { ErrorsTab } from "@/components/ErrorsTab";
import { EventsTab } from "@/components/EventsTab";
import { LeadDrawer } from "@/components/LeadDrawer";
import { LeadTable } from "@/components/LeadTable";
import { OutreachTab } from "@/components/OutreachTab";
import { MetricTiles, RunEconomicsBar } from "@/components/MetricTiles";
import { AgentsTab } from "@/components/AgentsTab";
import { PipelineStrip } from "@/components/PipelineStrip";

type Tab = "leads" | "outreach" | "events" | "agents" | "errors";

const TIER_FILTERS: { value: Tier; label: string; color: string }[] = [
  { value: "A", label: "A · Priority", color: "var(--c-good)" },
  { value: "B", label: "B · Qualified", color: "var(--c-score-1)" },
  { value: "C", label: "C · Watch", color: "var(--c-warning)" },
  { value: "disqualified", label: "Out of ICP", color: "var(--c-t3)" },
];

export default function Dashboard() {
  const [dark, setDark] = useState(
    () => typeof document !== "undefined" && document.documentElement.classList.contains("dark"),
  );
  const [summary, setSummary] = useState<Summary | null>(null);
  const [leads, setLeads] = useState<Lead[]>([]);
  const [events, setEvents] = useState<EventOut[]>([]);
  const [agents, setAgents] = useState<AgentOut[]>([]);
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

  /* The bootstrap script in layout.tsx has already resolved the theme onto
     <html> before paint, so we read it rather than deciding it again here. */
  function toggleTheme() {
    setDark((d) => {
      const next = !d;
      window.localStorage.setItem("tedlar-theme", next ? "dark" : "light");
      document.documentElement.classList.toggle("dark", next);
      return next;
    });
  }

  const load = useCallback(async (isStale: () => boolean = () => false) => {
    try {
      const [s, l, e, err, runs, ag] = await Promise.all([
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
        api.agents(),
      ]);
      // A slower earlier request must not overwrite a newer one's results.
      if (isStale()) return;
      setSummary(s);
      setLeads(l);
      setEvents(e);
      setErrors(err);
      setRun(runs[0] ?? null);
      setAgents(ag);
      setApiError(null);
    } catch (e) {
      if (isStale()) return;
      setApiError(e instanceof ApiError ? e.message : "Unexpected error loading data");
    } finally {
      if (!isStale()) setLoading(false);
    }
  }, [tiers, eventId, minScore, query]);

  useEffect(() => {
    let cancelled = false;
    // The rule guards against cascading renders from a synchronous setState.
    // Every write in `load` happens after an await, in a later task, and the
    // cancelled flag stops a stale response from landing at all.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load(() => cancelled);
    return () => {
      cancelled = true;
    };
  }, [load]);

  /* Poll only while a run is active, then refresh once it settles. */
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
        /* a dropped poll retries on the next tick */
      }
    }, 2000);
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [run?.status, run?.id, load]);

  const selected = useMemo(
    () => leads.find((lead) => lead.company_id === selectedId),
    [leads, selectedId],
  );

  const running = run?.status === "running";
  const filtersActive = Boolean(tiers.length || eventId || minScore || query);

  async function startRun() {
    setStarting(true);
    try {
      setRun(await api.startRun(mode));
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

  return (
    <div
      className={dark ? "dark" : ""}
      style={{
        height: "100vh",
        display: "flex",
        flexDirection: "column",
        background: "var(--c-page)",
        color: "var(--c-t1)",
        overflow: "hidden",
      }}
    >
      {apiError && (
        <div
          className="flex items-center gap-2"
          style={{
            background: "var(--c-critical)",
            color: "#fff",
            padding: "7px 24px",
            fontSize: 12,
            fontWeight: 500,
            flexShrink: 0,
          }}
        >
          <WarnIcon size={12} />
          {apiError}
          <button
            onClick={() => void load()}
            style={{
              marginLeft: "auto",
              background: "transparent",
              border: "1px solid rgba(255,255,255,.5)",
              borderRadius: 4,
              color: "#fff",
              cursor: "pointer",
              fontSize: 11,
              padding: "2px 8px",
            }}
          >
            Retry
          </button>
        </div>
      )}

      {/* ── Header ─────────────────────────────────────────────────────── */}
      <header
        className="flex items-center gap-4"
        style={{
          background: "var(--c-surface)",
          borderBottom: "1px solid var(--c-hairline)",
          padding: "0 24px",
          height: 52,
          flexShrink: 0,
        }}
      >
        <div className="flex items-center gap-2.5">
          <div
            className="flex items-center justify-center"
            style={{
              width: 26,
              height: 26,
              borderRadius: 6,
              background: "var(--c-invert-bg)",
              flexShrink: 0,
            }}
          >
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
              <circle cx="7" cy="7" r="5.4" stroke="var(--c-invert-fg)" strokeWidth="1.4" />
              <path
                d="M4 7h6M7 4v6"
                stroke="var(--c-invert-fg)"
                strokeWidth="1.4"
                strokeLinecap="round"
              />
            </svg>
          </div>
          <div>
            <div style={{ fontSize: 13.5, fontWeight: 700, lineHeight: 1.2 }}>
              Tedlar Lead Agent
            </div>
            <div style={{ fontSize: 10, color: "var(--c-t3)", lineHeight: 1.2 }}>
              DuPont Tedlar — Graphics &amp; Signage
            </div>
          </div>
        </div>

        <div style={{ flex: 1 }} />

        <label
          className="flex items-center gap-1.5"
          style={{ fontSize: 11.5, color: "var(--c-t2)" }}
        >
          Mode
          <select
            value={mode}
            onChange={(e) => setMode(e.target.value)}
            title="Cached replays the committed snapshot; live re-fetches every source."
            style={{
              padding: "4px 8px",
              fontSize: 11.5,
              borderRadius: 5,
              background: "var(--c-raised)",
              border: "1px solid var(--c-hairline)",
              color: "var(--c-t1)",
              cursor: "pointer",
              outline: "none",
            }}
          >
            <option value="cached">Cached run</option>
            <option value="live">Live run</option>
          </select>
        </label>

        <Button variant="primary" onClick={startRun} disabled={starting || running}>
          {running ? (
            <>
              <svg
                width="12"
                height="12"
                viewBox="0 0 12 12"
                fill="none"
                style={{ animation: "spin 1s linear infinite" }}
              >
                <circle
                  cx="6"
                  cy="6"
                  r="4.5"
                  stroke="currentColor"
                  strokeWidth="1.5"
                  strokeDasharray="18 8"
                />
              </svg>
              Running…
            </>
          ) : starting ? (
            "Starting…"
          ) : (
            "Run lead discovery"
          )}
        </Button>

        <button
          onClick={toggleTheme}
          title={dark ? "Switch to light mode" : "Switch to dark mode"}
          className="flex items-center justify-center"
          style={{
            width: 30,
            height: 30,
            borderRadius: 6,
            border: "1px solid var(--c-hairline)",
            background: "var(--c-raised)",
            color: "var(--c-t2)",
            cursor: "pointer",
          }}
        >
          {dark ? (
            <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
              <circle cx="8" cy="8" r="3.4" stroke="currentColor" strokeWidth="1.4" />
              <path
                d="M8 1v2M8 13v2M1 8h2M13 8h2M3.05 3.05l1.41 1.41M11.54 11.54l1.41 1.41M11.54 4.46l1.41-1.41M3.05 12.95l1.41-1.41"
                stroke="currentColor"
                strokeWidth="1.4"
                strokeLinecap="round"
              />
            </svg>
          ) : (
            <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
              <path
                d="M13 8.5A5.5 5.5 0 0 1 7.5 3C5 3 3 5 3 7.5A5.5 5.5 0 0 0 8.5 13C11 13 13 11 13 8.5Z"
                stroke="currentColor"
                strokeWidth="1.4"
              />
            </svg>
          )}
        </button>
      </header>

      <PipelineStrip run={run} summary={summary} />
      <MetricTiles summary={summary} />
      <RunEconomicsBar summary={summary} />

      {/* ── Tabs ───────────────────────────────────────────────────────── */}
      <div
        className="flex items-end"
        style={{
          background: "var(--c-surface)",
          borderBottom: "1px solid var(--c-hairline)",
          padding: "0 16px",
          flexShrink: 0,
        }}
      >
        {(
          [
            { id: "leads", label: "Leads", count: leads.length, warn: false },
            {
              id: "outreach",
              label: "Outreach",
              count: leads.reduce((n, l) => n + l.outreach.length, 0),
              warn: false,
            },
            { id: "events", label: "Events", count: events.length, warn: false },
            { id: "agents", label: "Agents", count: agents.length, warn: false },
            { id: "errors", label: "Errors", count: errors.length, warn: true },
          ] as const
        ).map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className="flex items-center gap-1.5"
            style={{
              padding: "9px 14px 8px",
              fontSize: 12,
              fontWeight: tab === t.id ? 600 : 400,
              color: tab === t.id ? "var(--c-t1)" : "var(--c-t3)",
              background: "transparent",
              border: "none",
              borderBottom: `2px solid ${tab === t.id ? "var(--c-t1)" : "transparent"}`,
              marginBottom: -1,
              cursor: "pointer",
            }}
          >
            {t.label}
            <span
              className="tabular"
              style={{
                padding: "1px 6px",
                borderRadius: 10,
                fontSize: 10,
                fontWeight: 600,
                color: t.warn && t.count ? "var(--c-caution)" : "var(--c-t3)",
                background:
                  t.warn && t.count
                    ? "color-mix(in srgb, var(--c-caution) 12%, transparent)"
                    : "var(--c-raised)",
                border: `1px solid ${
                  t.warn && t.count
                    ? "color-mix(in srgb, var(--c-caution) 25%, transparent)"
                    : "var(--c-hairline)"
                }`,
              }}
            >
              {t.count}
            </span>
          </button>
        ))}
      </div>

      {/* ── Content ────────────────────────────────────────────────────── */}
      <div style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column" }}>
        {tab === "leads" && (
          <>
            <div
              className="flex flex-wrap items-center gap-2"
              style={{
                padding: "8px 16px",
                borderBottom: "1px solid var(--c-hairline)",
                background: "var(--c-surface)",
                flexShrink: 0,
              }}
            >
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search company, domain, industry, product…"
                style={{
                  flex: "1 1 220px",
                  minWidth: 200,
                  padding: "5px 10px",
                  fontSize: 12,
                  borderRadius: 5,
                  border: "1px solid var(--c-hairline)",
                  background: "var(--c-raised)",
                  color: "var(--c-t1)",
                  outline: "none",
                }}
              />
              <select
                value={eventId}
                onChange={(e) => setEventId(e.target.value)}
                style={{
                  padding: "5px 8px",
                  fontSize: 11.5,
                  borderRadius: 5,
                  border: "1px solid var(--c-hairline)",
                  background: "var(--c-raised)",
                  color: "var(--c-t1)",
                  cursor: "pointer",
                  outline: "none",
                  maxWidth: 230,
                }}
              >
                <option value="">All events</option>
                {events.map((event) => (
                  <option key={event.id} value={event.id}>
                    {event.name}
                  </option>
                ))}
              </select>

              <label
                className="flex items-center gap-2"
                style={{ fontSize: 11.5, color: "var(--c-t2)" }}
              >
                Min score
                <input
                  type="range"
                  min={0}
                  max={100}
                  step={5}
                  value={minScore}
                  onChange={(e) => setMinScore(Number(e.target.value))}
                  style={{ width: 84 }}
                />
                <span className="tabular" style={{ width: 22, color: "var(--c-t1)" }}>
                  {minScore || "off"}
                </span>
              </label>

              <a
                href={api.leadsCsvUrl({
                  tier: tiers.length ? tiers : undefined,
                  min_score: minScore || undefined,
                })}
                title="Export the current tier and score filters as CSV"
                style={{
                  padding: "4px 10px",
                  fontSize: 11.5,
                  borderRadius: 5,
                  border: "1px solid var(--c-hairline)",
                  background: "var(--c-raised)",
                  color: "var(--c-t1)",
                  textDecoration: "none",
                  whiteSpace: "nowrap",
                }}
              >
                Export CSV
              </a>

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
                      style={{
                        padding: "3px 9px",
                        fontSize: 11,
                        borderRadius: 5,
                        cursor: "pointer",
                        color: active ? filter.color : "var(--c-t2)",
                        background: active
                          ? `color-mix(in srgb, ${filter.color} 12%, transparent)`
                          : "var(--c-raised)",
                        border: `1px solid ${
                          active
                            ? `color-mix(in srgb, ${filter.color} 30%, transparent)`
                            : "var(--c-hairline)"
                        }`,
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
              filtersActive={filtersActive}
              onSelect={(lead) => setSelectedId(lead.company_id)}
            />
          </>
        )}

        {tab === "outreach" && (
          <div style={{ flex: 1, overflowY: "auto" }}>
            <OutreachTab
              leads={leads}
              loading={loading}
              onOutreachChange={applyOutreach}
            />
          </div>
        )}
        {tab === "events" && (
          <div style={{ flex: 1, overflowY: "auto" }}>
            <EventsTab events={events} loading={loading} />
          </div>
        )}
        {tab === "agents" && (
          <div style={{ flex: 1, overflowY: "auto" }}>
            <AgentsTab agents={agents} loading={loading} />
          </div>
        )}
        {tab === "errors" && (
          <div style={{ flex: 1, overflowY: "auto" }}>
            <ErrorsTab errors={errors} loading={loading} />
          </div>
        )}
      </div>

      {selected && (
        <LeadDrawer
          lead={selected}
          onClose={() => setSelectedId(undefined)}
          onOutreachChange={applyOutreach}
        />
      )}
    </div>
  );
}
