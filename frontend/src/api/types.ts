export interface BidDocument {
  name: string;
  url: string;
  kind: string;
}

export interface BidResult {
  outcome: "won" | "lost";
  amount_cents: number | null;
  notes: string;
  decided_on: string;
}

export interface Opportunity {
  opportunity_id: string;
  source_id: string;
  source_name: string;
  external_id: string | null;
  title: string;
  url: string;
  county: string;
  agency: string;
  department: string | null;
  solicitation_type: string;
  offer_type: string;
  categories: string[];
  posted_date: string | null;
  due_date: string | null;
  status: string;
  description: string | null;
  brief: string | null;
  contact: string | null;
  budget: string | null;
  budget_amount: number | null;
  scope: string | null;
  requirements: string[];
  documents: BidDocument[];
  submittal_info: string | null;
  pre_bid_meeting: string | null;
  questions_due: string | null;
  contact_email: string | null;
  contact_phone: string | null;
  bid_opening: string | null;
  project_location: string | null;
  duration_days: number | null;
  liquidated_damages: string | null;
  licenses: string | null;
  prior_cycles: number;
  last_cycle_closed: string | null;
  days_until_due: number | null;
  detail_score: number;
  // user overlay
  tracked: boolean;
  stage: string | null;
  decision: string | null;
  archived: boolean;
  tracked_on: string | null;
  checks: Record<string, boolean>;
  notes: string;
  result: BidResult | null;
  has_summary: boolean;
  is_new?: boolean;
}

export interface OpportunityDetail extends Opportunity {
  ai_summary: AiSummaryEnvelope | null;
}

export interface AiBrief {
  what_the_work_is: string;
  key_dates?: { label: string; date: string; note?: string }[];
  money?: { estimated_value?: string; bonding?: string; payment_terms?: string };
  requirements: string[];
  red_flags: string[];
  fit_hint: string;
}

export interface AiSummaryEnvelope {
  summary: AiBrief;
  model: string;
  created_at: string;
}

export interface DeepDiveReport {
  overview: string;
  dollar_amounts: { label: string; amount: string; source?: string }[];
  key_dates: { label: string; date: string; note?: string }[];
  scope_items: string[];
  requirements: { category: string; item: string }[];
  evaluation: string[];
  contacts: { name: string; role?: string; email?: string; phone?: string }[];
  documents_reviewed: { name: string; gist: string }[];
  red_flags: string[];
  open_questions: string[];
  fit_assessment: string;
}

export interface DeepDiveStatus {
  state: "none" | "running" | "done" | "error";
  error?: string;
  report?: DeepDiveReport;
  model?: string;
  docs_read?: number;
  created_at?: string;
}

export interface SnapshotResponse {
  fetched_at: string | null;
  count: number;
  opportunities: Opportunity[];
}

export interface WatchlistRules {
  keywords?: string[];
  counties?: string[];
  offers?: string[];
  categories?: string[];
  min_value?: number | null;
  max_value?: number | null;
  no_bond?: boolean;
  recurring_only?: boolean;
}

export interface Watchlist {
  id: string;
  name: string;
  rules: WatchlistRules;
  email_digest: boolean;
  match_count: number;
  new_count: number;
}

export interface SourceHealth {
  source_id: string;
  name: string;
  ok: boolean;
  count: number;
  error: string | null;
  elapsed_ms: number;
  status: string;
  note: string | null;
}

export interface SourceInfo {
  id: string;
  name: string;
  county: string;
  agency: string;
  adapter: string;
  portal_url: string;
  live_fetch: boolean;
  custom: boolean;
  health: SourceHealth | null;
}

export interface SourcesResponse {
  sources: SourceInfo[];
  last_run: { finished_at: string | null; status: string | null; opp_count: number } | null;
}

export interface DetectResponse {
  detected: string;
  name: string;
  portal_url: string;
  suggested_id: string;
  supported: boolean;
  message: string;
}

export interface NotificationItem {
  id: number;
  kind: string;
  title: string;
  body: string;
  opportunity_id: string | null;
  created_at: string;
  read: boolean;
}

export interface Settings {
  auto_fetch: { mode: string; interval_minutes: number; stale_minutes: number };
  notifications: { deadline_days: number; watchlist: boolean; fetch_events: boolean };
  digest: { enabled: boolean; cadence: string; hour: number; email: string };
  ai: { model: string; auto_summarize_tracked: boolean };
}

export interface Capabilities {
  ai_available: boolean;
  email_available: boolean;
  db_backend: string;
  ai_models: string[];
}

export interface SettingsResponse {
  settings: Settings;
  capabilities: Capabilities;
}

export interface TestEmailResult {
  sent: boolean;
  error: string | null;
  recipient: string;
}

export interface FetchStatus {
  state: "idle" | "running" | "done" | "error";
  started_at?: string;
  phase?: string;
  sources?: SourceHealth[];
  done_count?: number;
  total?: number;
  count?: number;
  new_count?: number;
  new_matches?: number;
  error?: string;
}

export interface Stats {
  totals: {
    open_count: number;
    upcoming_count: number;
    open_value: number;
    due_7d: number;
    due_7d_value: number;
    tracked: number;
    won: number;
    lost: number;
    win_rate: number | null;
    revenue_cents: number;
  };
  by_county: { county: string; open: number; upcoming: number; value: number }[];
  by_type: { type: string; count: number; value: number }[];
  deadline_load: { week: string; count: number; value: number }[];
  pipeline: { stages: { stage: string; count: number; value: number }[] };
  results_by_month: { month: string; won: number; lost: number; revenue_cents: number }[];
  sources: { source_id: string; name: string; count: number; status: string; elapsed_ms: number }[];
  trend: { finished_at: string | null; count: number; new_count: number }[];
  attention: {
    opportunity_id: string;
    title: string;
    days_until_due: number;
    stage: string;
    unmet_count: number;
    budget_amount: number | null;
  }[];
}

// --- Filter vocabulary ------------------------------------------------------
// Served by /api/taxonomy rather than derived from the loaded snapshot, so a
// category with no bids today is still selectable. `count` is what keeps that
// honest in the UI: it separates "nothing open right now" from "broken filter".

export interface TaxonomyGroup {
  slug: string;
  label: string;
  blurb: string;
}

export interface TaxonomyCategory {
  slug: string;
  label: string;
  group: string;
  offer_type: string;
  detectable: boolean;
  count: number;
}

export interface TaxonomyCounty {
  slug: string;
  label: string;
  region: string;
  region_label: string;
  count: number;
}

export interface TaxonomyResponse {
  groups: TaxonomyGroup[];
  categories: TaxonomyCategory[];
  offer_types: { key: string; label: string; count: number }[];
  counties: TaxonomyCounty[];
  county_labels: Record<string, string>;
  total_open: number;
}
