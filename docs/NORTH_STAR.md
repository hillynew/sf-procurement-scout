# North Star

## The one job

Show a Florida business owner every public procurement opportunity in the state — what is
open, what closes soon, what was awarded and for how much — with the real bid documents
one click away.

## What I must be able to do for it to be worth using

1. **See every open solicitation statewide** and filter/sort by agency, county, category,
   type, close date, and value — without wondering whether a whole tier of government is
   missing.
2. **Open the actual packet fast** — every document and addendum, one click, and an honest
   flag when a packet could not be fetched.
3. **See awards**: who won, when, and for how much — linked back to the solicitation, and
   surfaced while the 72-hour protest window is still open.
4. **Trust the pipeline**: a broken scraper must look broken, a quiet portal must look
   quiet, and a missing field must look missing.
5. **Never miss a deadline** that matters: close dates, question deadlines, pre-bids,
   protest clocks.

## Current coverage — what is actually pulled today

615 sources configured → 539 effective: **313 live** + 226 catalog pointers (no data,
just "register here"). All live adapters are genuinely wired and tested (1,017 offline
tests pass); the honest caveats are in the notes column.

| Source / platform | Entries | Tier(s) covered | State |
|---|---:|---|---|
| MyFloridaMarketPlace (VIP) | 1 | State: all agencies, 12 universities, colleges, 5 WMDs | Working. Detail + documents + award notices with protest clock. |
| OpenGov Procurement API | 91 | Counties, cities, school districts, authorities | Working. Detail + S3 documents. Reads ~6 of ~147 detail fields. |
| CivicPlus bid boards | 99 | Mostly municipal + some counties/districts | Working. Detail + documents. Award/estimated-value labels on the page are discarded. |
| VendorLink | 66 | Mixed incl. 7 statewide co-ops | Working, list-only (detail is behind login). No docs/contacts/description. |
| Bonfire / Euna | 32 | Counties (Broward, Hillsborough), cities, FAU, districts | Working, list-only. Also pulls the contract register (vendor + dates, no amounts). Never sets posted_date. |
| Jaggaer (state universities) | 5 | FSU, FAU, FIU live; **UF + USF configured but per the code's own probe are empty tenants — permanent zero rows** | Drift between config and findings. Award tab read, no protest clock. |
| Ionwave | 4 | Cities, Lee County, Pasco Schools | Working under a 3-request budget (Cloudflare). Award + protest clock. Contract list deliberately unread. |
| Workday Strategic Sourcing | 3 | UNF, St. Johns County, Hillsborough CC | Working (GraphQL). Commodity codes → keywords. No docs/contacts. |
| FDOT advertisements | 2 | State DOT: professional services + design-build, incl. 124 planned ads | Working. One of only two sources populating budget. Work-type codes dropped. |
| FACTS contract register | 1 | State: every executed contract, 31 agencies | Working (weekly CLI/maintenance job, not the fetch). **The only source with award amounts** (82% of rows) + vendor + method. Reads ~10 of 52 CSV columns. |
| SAM.gov | 1 | Federal (FL place of performance) | Inert without a free API key. NAICS + attachment links (`resourceLinks`) fetched but dropped. |
| Miami-Dade INFORMS | 1 | County (PeopleSoft) | **Fragile**: heuristic table pick, status hardcoded "open", can fail silently — the one adapter with no degraded-detection. |
| Miami-Dade ISD construction + future | 2 | County | Working. Detail + documents. |
| MDC College | 1 | College | Working, but "open" is inferred from a 150-day recency window, not observed. |
| Palm Beach Schools construction | 1 | School district (construction only) | Working. Publishes budgets — captured. |
| West Palm Beach | 1 | City | Behind Akamai WAF; degrades to a DemandStar pointer when blocked. |
| Coral Gables notice links | 1 | City | Working, minimal: the notice PDF is the URL but never parsed, so no dates/docs. |
| Email alerts (IMAP) | 1 | CivicPlus "Notify Me" cities | Inert unless a mailbox is configured. Stamps every mail `broward`/"Email subscriptions" regardless of sender. |
| Catalog pointers | 226 | All tiers | Public Purchase 228 raw entries + BidNet 55 = **94% of the recorded gap**. No data flows. |

## Coverage gaps vs. the statewide target

- **Award amounts and winning vendors are structurally homeless.** `Opportunity` has no
  awarded-vendor / award-amount / award-date field. Five adapters emit `status="award"`
  rows, none can say who won or for what. FACTS covers *state* contract values only; local
  awards (county/city/school) are captured nowhere. This is the biggest gap against the
  stated job.
- **No agency-tier field.** State/county/municipal/school/special-district cannot be
  stored or filtered; it is inferred ad hoc from names.
- **Public Purchase (228 agencies) and BidNet Direct (55)** have no adapter — the two
  largest recorded holes. BidNet's terms are unreadable by their own robots rules
  (documented decision not to scrape); Public Purchase needs vendor registration + the
  planned bid mailbox.
- **~2,088 special districts** are essentially uncovered (1,095 are CDDs run by a handful
  of management firms); **15 rural counties** have no source at all; 593 agencies from the
  fingerprint sweep remain `unknown`.
- **Detail/document depth is thin**: only 5 of 20 adapters fetch detail pages, only 4
  produce documents, commodity/NAICS codes are dropped almost everywhere, and `budget`
  arrives from just 2 sources plus prose-mining.
- DemandStar is deliberately excluded (their terms prohibit scraping — recorded decision,
  reaffirmed after a bad merge). Paid options exist (VendorLink statewide $175/yr, Euna
  Pro $50/yr) but nothing is bought today.

## Every stored field, and where it is shown

**Opportunity** (list = All bids rows/cards; Drawer = slide-in; WR = Workroom):

| Field(s) | Shown |
|---|---|
| title, agency, county, status, due_date/days_until_due | Everywhere (list, Drawer, WR, Pipeline, Dashboard) |
| offer_type | TypeTag in list/Drawer/WR — renders *nothing* when `unknown` |
| budget_amount | ValueTag everywhere; Pipeline totals; filters |
| budget (raw string) | WR "Commercial terms" only |
| external_id | WR header, Drawer "Reference", search |
| posted_date | Drawer only |
| description, scope | Card preview, WR scope section, search |
| brief / ai_summary | Drawer paragraph / WR AI card |
| requirements + checks | WR checklist, Drawer chips, Pipeline unmet count |
| documents | WR + Drawer link lists only |
| pre_bid_meeting, questions_due, project_location, duration_days, liquidated_damages, licenses | WR + Drawer facts |
| contact, contact_email | WR contact card, Drawer fact |
| contact_phone, bid_opening | WR only |
| prior_cycles / last_cycle_closed | "rebid" badge in list; Drawer fact |
| detail_score | Meter in list rows + Drawer |
| tracked, stage, decision, archived, notes, result | Pipeline/WR workflow surfaces |
| **Never shown anywhere**: source_id, source_name, department, **solicitation_type (ITB/RFP/…)**, keywords, **protest_deadline** (email digest only), submittal_info, detail_fetched, package_parsed, personalized, raw, per-bid fetched_at, categories (filter input only, never rendered), tracked_on, result.decided_on | — |

**Other tables**: `contracts` (incumbent vendor, end date, FACTS amounts — **no screen**;
email digest + CLI only) · `bid_history` (feeds the rebid badge) · `watchlists`,
`notifications`, `settings` (their screens) · `ai_summaries` / `deep_dives` /
`research_threads` (Workroom) · `contractors` / `contractor_matches` (Network screen) ·
`fetch_runs` (Sources health + Dashboard trend) · `pdf_cache` (internal).

Award-status rows exist in the data but are **effectively invisible**: no UI style, the
default status filter excludes them, and the protest clock renders only in email.

## Things that do not serve the core job (or serve it and are unreachable)

- **Contractor network + AI market scout** (`/network`, `src/ai/contractors.py`) —
  finds subcontractors to broker work to. A different job than finding work to chase.
- **AI research threads** (web-search Q&A per bid) — useful, but adjacent.
- **`src/scoring.py` go/no-go meters** — dead code; built, tested, never wired to any UI.
- **Serving `raw` on every list payload** — pure wire weight, never read by the client.
- Inverse problem: the **contract register** (the only leading indicator in the build) and
  **day-31 records-request leads** serve the job directly but exist only as email
  sections — no screen shows them.

## Open questions before Phase 2

1. **Contractor network**: keep, or park it? It is the largest feature not aimed at the
   core job (I would leave it working but spend nothing on it).
2. **Paid coverage**: prior research recommends VendorLink statewide ($175/yr) and Euna
   Pro ($50/yr). May Phase 2 rank paid options as candidates, or is $0 a hard constraint?
3. **The bid mailbox** (unlocks Public Purchase's 228 agencies): needs you to register the
   business on portals and own a mailbox/domain — manual steps only you can do. Worth
   planning around?
4. **AI features** (briefs, deep dive, research): keep as-is on your API key, correct?
