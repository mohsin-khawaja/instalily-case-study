import type {
  AgentOut,
  EventOut,
  Lead,
  OutreachOut,
  ProspectReport,
  RunOut,
  StageErrorOut,
  Summary,
} from "./types";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

/**
 * Static demo mode. The public deployment ships the dashboard without its
 * FastAPI backend, so reads resolve from a snapshot under /public/data and
 * writes are refused outright. Faking a successful save would make the demo
 * lie about what it persisted, which is the one thing this project does not do.
 */
const STATIC = process.env.NEXT_PUBLIC_STATIC_DATA === "1";

export class ApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
  }
}

const READ_ONLY =
  "Read-only demo: this deployment has no backend. Clone the repo and run the " +
  "API locally to edit drafts or start a run.";

async function staticJson<T>(file: string): Promise<T> {
  const response = await fetch(`/data/${file}`, { cache: "force-cache" });
  if (!response.ok) throw new ApiError(`Missing snapshot: ${file}`, response.status);
  return (await response.json()) as T;
}

function matchesFilters(lead: Lead, params: URLSearchParams): boolean {
  const tiers = params.getAll("tier");
  if (tiers.length && !tiers.includes(lead.tier)) return false;
  if (lead.score_total < Number(params.get("min_score") ?? 0)) return false;

  const eventId = params.get("event_id");
  if (eventId && !lead.events.some((e) => e.id === eventId)) return false;

  const industry = params.get("industry");
  if (industry && !(lead.industry ?? "").toLowerCase().includes(industry.toLowerCase())) {
    return false;
  }

  const hasContact = params.get("has_contact");
  if (hasContact !== null && Boolean(lead.contacts.length) !== (hasContact === "true")) {
    return false;
  }

  const needle = (params.get("q") ?? "").toLowerCase().trim();
  if (needle) {
    const haystack = [
      lead.company_name,
      lead.industry ?? "",
      lead.description ?? "",
      lead.sub_industries.join(" "),
      lead.products.join(" "),
    ]
      .join(" ")
      .toLowerCase();
    if (!haystack.includes(needle)) return false;
  }
  return true;
}

async function staticRequest<T>(path: string, init?: RequestInit): Promise<T> {
  if ((init?.method ?? "GET").toUpperCase() !== "GET") {
    throw new ApiError(READ_ONLY, 405);
  }
  const url = new URL(path, "http://local");
  const route = url.pathname;
  const params = url.searchParams;

  if (route === "/api/summary") return staticJson<T>("summary.json");
  if (route === "/api/events") return staticJson<T>("events.json");
  if (route === "/api/agents") return staticJson<T>("agents.json");
  if (route === "/api/errors") return staticJson<T>("errors.json");
  if (route === "/api/runs") return staticJson<T>("runs.json");

  if (route.startsWith("/api/runs/")) {
    const id = route.slice("/api/runs/".length);
    const runs = await staticJson<RunOut[]>("runs.json");
    const found = runs.find((r) => r.id === id);
    if (!found) throw new ApiError(`No such run: ${id}`, 404);
    return found as T;
  }

  if (route === "/api/leads") {
    const leads = await staticJson<Lead[]>("leads.json");
    const limit = Number(params.get("limit") ?? 250);
    return leads.filter((l) => matchesFilters(l, params)).slice(0, limit) as T;
  }

  const reportMatch = route.match(/^\/api\/leads\/([^/]+)\/report$/);
  if (reportMatch) return staticJson<T>(`reports/${reportMatch[1]}.json`);

  const leadMatch = route.match(/^\/api\/leads\/([^/]+)$/);
  if (leadMatch) {
    const leads = await staticJson<Lead[]>("leads.json");
    const found = leads.find((l) => l.company_id === leadMatch[1]);
    if (!found) throw new ApiError(`No such lead: ${leadMatch[1]}`, 404);
    return found as T;
  }

  throw new ApiError(`${route} is not available in the static demo.`, 404);
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  if (STATIC) return staticRequest<T>(path, init);
  let response: Response;
  try {
    response = await fetch(`${BASE}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
      cache: "no-store",
    });
  } catch {
    throw new ApiError(`Cannot reach the API at ${BASE}. Is uvicorn running?`, 0);
  }
  if (!response.ok) {
    const detail = await response.text().catch(() => "");
    throw new ApiError(detail || `${response.status} ${response.statusText}`, response.status);
  }
  return (await response.json()) as T;
}

export interface LeadFilters {
  tier?: string[];
  event_id?: string;
  min_score?: number;
  q?: string;
  has_contact?: boolean;
}

export const api = {
  summary: () => request<Summary>("/api/summary"),
  events: () => request<EventOut[]>("/api/events"),
  agents: () => request<AgentOut[]>("/api/agents"),
  // Defaults to the latest run, matching the summary tile. "all" for history.
  errors: (runId?: string) =>
    request<StageErrorOut[]>(
      `/api/errors?limit=200${runId ? `&run_id=${encodeURIComponent(runId)}` : ""}`,
    ),
  runs: () => request<RunOut[]>("/api/runs?limit=10"),
  run: (id: string) => request<RunOut>(`/api/runs/${id}`),

  leads: (filters: LeadFilters = {}) => {
    const params = new URLSearchParams();
    filters.tier?.forEach((t) => params.append("tier", t));
    if (filters.event_id) params.set("event_id", filters.event_id);
    if (filters.min_score) params.set("min_score", String(filters.min_score));
    if (filters.q) params.set("q", filters.q);
    if (filters.has_contact !== undefined) params.set("has_contact", String(filters.has_contact));
    const qs = params.toString();
    return request<Lead[]>(`/api/leads${qs ? `?${qs}` : ""}`);
  },

  /** Absolute URL so the browser downloads straight from the API origin. */
  leadsCsvUrl: (filters: LeadFilters = {}) => {
    if (STATIC) return "/data/leads.csv";
    const params = new URLSearchParams();
    filters.tier?.forEach((t) => params.append("tier", t));
    if (filters.min_score) params.set("min_score", String(filters.min_score));
    const qs = params.toString();
    return `${BASE}/api/leads.csv${qs ? `?${qs}` : ""}`;
  },

  /** Zip of .eml drafts — drag into Gmail; MailSuite tracks them once sent. */
  outreachZipUrl: (filters: { tier?: string[]; approved_only?: boolean } = {}) => {
    if (STATIC) return "/data/outreach.zip";
    const params = new URLSearchParams();
    filters.tier?.forEach((t) => params.append("tier", t));
    if (filters.approved_only) params.set("approved_only", "true");
    const qs = params.toString();
    return `${BASE}/api/outreach.zip${qs ? `?${qs}` : ""}`;
  },

  /** Pre-call dossier. Deterministic and free unless `enhance` is set. */
  report: (companyId: string, enhance = false) =>
    request<ProspectReport>(
      `/api/leads/${companyId}/report${enhance ? "?enhance=true" : ""}`,
    ),

  startRun: (mode: string, limit?: number) =>
    request<RunOut>("/api/pipeline/run", {
      method: "POST",
      body: JSON.stringify({ mode, limit }),
    }),

  patchOutreach: (id: string, patch: { edited_body?: string; approved?: boolean }) =>
    request<OutreachOut>(`/api/outreach/${id}`, {
      method: "PATCH",
      body: JSON.stringify(patch),
    }),
};
