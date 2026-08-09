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
  tier?: string | null;
  raw_category?: string | null;
  commodity_codes?: string[];
  awarded_vendor?: string | null;
  award_amount?: number | null;
  award_date?: string | null;
  linked_ref?: string | null;
  award_linkage?: string | null;
  contract_term?: string | null;
  protest_deadline?: string | null;
  first_seen_at?: string | null;
  detail_fetched?: boolean;
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

export interface ResearchTurn {
  question: string;
  answer: string;
  citations: { url: string; title: string }[];
  searches: number;
  model: string;
  asked_at: string;
}

export interface ResearchStatus {
  state: "idle" | "running";
  turns: ResearchTurn[];
  suggested_questions: string[];
  error?: string;
}

export type MatchStatus = "suggested" | "pitched" | "interested" | "committed" | "passed";
export type ContractorStatus = "prospect" | "contacted" | "in_network" | "passed";

export interface ContractorMatch {
  contractor_id: string;
  name: string;
  location: string;
  trade: string;
  website: string;
  phone: string;
  email: string;
  gov_experience: "none" | "some" | "regular" | "unknown";
  why_fit: string;
  pitch_angle: string;
  sources: string[];
  status: MatchStatus;
  contractor_status: ContractorStatus;
}

export interface ContractorMatchesStatus {
  state: "none" | "running" | "done" | "error";
  error?: string;
  matches?: ContractorMatch[];
  market_note?: string;
  model?: string;
  searches?: number;
  created_at?: string;
}

export interface MatchedBid {
  opportunity_id: string;
  title: string;
  agency: string;
  county: string;
  due_date: string | null;
  match_status: MatchStatus;
  matched_at: string;
}

export interface Contractor {
  id: string;
  name: string;
  county: string;
  location: string;
  trade: string;
  website: string;
  phone: string;
  email: string;
  status: ContractorStatus;
  notes: string;
  profile: { gov_experience?: string; sources?: string[] };
  created_at: string;
  updated_at: string;
  matched_bids: MatchedBid[];
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
  maintenance: { enabled: boolean; contracts_days: number; platform_check_days: number };
}

/** Read-only: when the slow walks last ran, and whether one is running now. */
export interface MaintenanceStatus {
  last_contracts_refresh_on: string | null;
  last_platform_check_on: string | null;
  running: string | null;
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
  maintenance_status: MaintenanceStatus;
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

export interface ExpiringContract {
  contract_id: string;
  agency: string;
  name: string;
  vendor: string | null;
  end_date: string | null;
  days_left: number | null;
  amount: number | null;
  method: string | null;
  extendable: boolean | null;
  commodity: string | null;
  url: string | null;
}

export interface AwardsResponse {
  awards: Opportunity[];
  contracts: ExpiringContract[];
  contracts_total: number;
}

export interface QualityField {
  label: string;
  count: number;
  pct: number | null;
}

export interface QualityBlock {
  records: number;
  awards: number;
  fields: Record<string, QualityField>;
}

export interface QualityReport {
  overall: QualityBlock;
  sources: (QualityBlock & { source_id: string; source_name: string })[];
}

export interface ProtestWindow {
  opportunity_id: string;
  title: string;
  agency: string;
  county: string;
  deadline: string;
  hours_left: number;
  awarded_vendor: string | null;
  award_amount: number | null;
  url: string;
}

export interface Stats {
  protest_windows: ProtestWindow[];
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
