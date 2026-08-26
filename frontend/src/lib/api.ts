import type {
  EventOut,
  Lead,
  OutreachOut,
  ProspectReport,
  RunOut,
  StageErrorOut,
  Summary,
} from "./types";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

export class ApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
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
    const params = new URLSearchParams();
    filters.tier?.forEach((t) => params.append("tier", t));
    if (filters.min_score) params.set("min_score", String(filters.min_score));
    const qs = params.toString();
    return `${BASE}/api/leads.csv${qs ? `?${qs}` : ""}`;
  },

  /** Zip of .eml drafts — drag into Gmail; MailSuite tracks them once sent. */
  outreachZipUrl: (filters: { tier?: string[]; approved_only?: boolean } = {}) => {
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
