export type Tier = "A" | "B" | "C" | "disqualified";

export interface SourceRef {
  url: string;
  title?: string | null;
  fetched_at?: string;
  snippet?: string | null;
}

export interface Evidence {
  claim: string;
  source_url: string;
  quote?: string | null;
  stage?: string | null;
}

export interface EventOut {
  id: string;
  slug: string;
  name: string;
  url: string;
  event_type: string;
  organizer?: string | null;
  venue?: string | null;
  city?: string | null;
  country?: string | null;
  start_date?: string | null;
  end_date?: string | null;
  tier1: boolean;
  relevance_note?: string | null;
  status: string;
  company_count: number;
  sources: SourceRef[];
}

export interface ContactOut {
  id: string;
  full_name: string;
  title?: string | null;
  seniority: string;
  linkedin_url?: string | null;
  sales_nav_url?: string | null;
  email?: string | null;
  provider: string;
  confidence: number;
  sources: SourceRef[];
}

export interface OutreachOut {
  id: string;
  contact_id: string;
  subject: string;
  body: string;
  edited_body?: string | null;
  hook_fact?: string | null;
  hook_source_url?: string | null;
  tedlar_value_prop?: string | null;
  approved: boolean;
  generator: string;
  gmail_url?: string | null;
}

export interface ScoreBreakdown {
  industry_fit: number;
  product_fit: number;
  size: number;
  event_engagement: number;
  pain_alignment: number;
  total: number;
}

export interface ComponentExplanation {
  key: string;
  label: string;
  points: number;
  max_points: number;
  weight_pct: number;
  verdict: "Strong" | "Partial" | "Weak" | "No evidence";
  reasoning: string;
  matched: string[];
  source_url?: string | null;
  to_improve?: string | null;
}

export interface Lookalike {
  company_id: string;
  company_name: string;
  similarity: number;
  shared_terms: string[];
  reference_name: string;
}

export interface Lead {
  company_id: string;
  company_name: string;
  website?: string | null;
  domain?: string | null;
  industry?: string | null;
  sub_industries: string[];
  products: string[];
  description?: string | null;
  hq_location?: string | null;
  revenue_band?: string | null;
  revenue_est_usd?: number | null;
  employee_band?: string | null;
  employee_count_est?: number | null;
  enriched: boolean;
  status: string;
  score_total: number;
  score: Partial<ScoreBreakdown>;
  tier: Tier;
  confidence: number;
  rationale?: string | null;
  rationale_source: string;
  score_explanations: ComponentExplanation[];
  score_summary?: string | null;
  lookalikes: Lookalike[];
  is_reference_account: boolean;
  evidence: Evidence[];
  flags: string[];
  events: EventOut[];
  contacts: ContactOut[];
  outreach: OutreachOut[];
  sources: SourceRef[];
}

export interface Summary {
  events: number;
  companies: number;
  companies_enriched: number;
  qualified_leads: number;
  contacts: number;
  outreach_drafts: number;
  errors: number;
  last_run_at?: string | null;
  last_run_id?: string | null;
  last_run_mode?: string | null;
  llm_calls: number;
  llm_estimated_usd: number;
  cost_per_qualified_lead?: number | null;
  llm_enabled: boolean;
  search_provider: string;
  contact_providers: string[];
}

export interface StageErrorOut {
  id: string;
  run_id: string;
  stage: string;
  entity_type: string;
  entity_ref?: string | null;
  error_type: string;
  message: string;
  retryable: boolean;
  created_at: string;
}

export interface RunOut {
  id: string;
  mode: string;
  status: "running" | "completed" | "partial" | "failed";
  current_stage?: string | null;
  stage_states: Record<string, string>;
  counts: Record<string, number | string>;
  error_count: number;
  started_at: string;
  finished_at?: string | null;
}

export const STAGES = [
  { key: "discover_events", label: "Events" },
  { key: "extract_companies", label: "Companies" },
  { key: "enrich_companies", label: "Enrichment" },
  { key: "qualify", label: "Qualification" },
  { key: "find_contacts", label: "Contacts" },
  { key: "draft_outreach", label: "Outreach" },
] as const;

export const SCORE_COMPONENTS = [
  { key: "industry_fit", label: "Industry fit", max: 30, color: "var(--series-1)" },
  { key: "product_fit", label: "Application fit", max: 25, color: "var(--series-2)" },
  { key: "size", label: "Company size", max: 15, color: "var(--series-3)" },
  { key: "event_engagement", label: "Event engagement", max: 15, color: "var(--series-4)" },
  { key: "pain_alignment", label: "Pain-point alignment", max: 15, color: "var(--series-5)" },
] as const;

export interface ReportSection {
  heading: string;
  body: string;
  sources: string[];
}

export interface ProspectReport {
  company_id: string;
  company_name: string;
  sections: ReportSection[];
  generator: "deterministic" | "llm";
  note?: string;
  briefing?: {
    positioning: string;
    tedlar_angle: string;
    talking_points: string[];
    objections: string[];
    opener: string;
  } | null;
}

export interface AgentOut {
  stage: string;
  name: string;
  mission: string;
  decides: string[];
  delegates_to_llm?: string | null;
  degrades_to: string;
  guardrail: string;
  metrics: string[];
  state: string;
  handled_errors: number;
  results: Record<string, number>;
}
