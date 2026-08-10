# Sources — data fidelity, verified live

Everything below was verified against live portals on **2026-08-09** (honest UA
`sf-procurement-scout (github.com/hillynew/sf-procurement-scout)`, ≤1 req/sec/host,
~60 requests total). Where a claim comes from a real listing or a real award notice, the
verifying URL pattern is named. Nothing here is assumed from docs alone.

## 1. Target schema and the two record types

Every record should carry, when the source publishes it: issuing agency · **agency tier**
· county · solicitation number · title · full description · solicitation type · award
category (SERVICES/GOODS/CONSTRUCTION/MIXED) **plus the raw source category text** ·
NAICS/UNSPSC/NIGP codes · issue date · question deadline · pre-bid meeting · close date ·
estimated value · award status/date/vendor/**amount** · contract term/renewals ·
bond/insurance/licensing requirements · contact name/email/phone · document links (+local
copies) · source URL/method/last-verified.

**Schema gaps in the current model** (`src/models/opportunity.py`): no `tier`, no
`raw_category`, no commodity-code field, no `awarded_vendor` / `award_amount` /
`award_date`, no contract term/renewals. These must be added (additively — the DB layer
already supports `ALTER TABLE ADD COLUMN`).

**Two linked record types.** Solicitations (open/upcoming/closed/cancelled) and awards
(intended-decision notices, executed contracts, commission award approvals, bid tabs) are
different records from different feeds. Link them:
1. **By reference** where a key exists — MFMP award notices carry `linkedAdNumber`
   pointing at the originating ad (verified live, currently discarded); Legistar matter
   titles quote the bid number; FACTS has `Agency Reference Number`.
2. **By agency + title-token similarity + date** otherwise — the tokenizer in
   `src/records.py` / `src/pipeline/history.py` already does exactly this at 0.7
   containment.
Each link must record `linkage_method` (`ref` | `fuzzy`) so a bad match is traceable.

## 2. Statewide shortcuts — checked first

| Central source | Covers | Award data | Verdict |
|---|---|---|---|
| **MFMP VIP** | Every state agency, 12 universities, colleges, 5 WMDs | Agency Decision notices w/ `linkedAdNumber` + bid-tab PDF (vendor+amount in PDF only) | Already live. Fixes below recover codes, question deadline, award linkage. |
| **FACTS** | Every executed state contract, 31 agencies | **Vendor + amount + method, structured** (Total Amount; payments-to-date on detail) | Already live. 42 of 52 CSV columns still unread. State only — no locals, ever. |
| **OpenGov API** | 91 FL tenants (~14k projects) | Status signal only (`closeOutReason` free text); vendor/amount 401-gated; public planholders | Already live. Largest capture-gap fix in the plan. |
| **Legistar Web API** | County/city commission agendas: **Broward Co., Jacksonville, Miami, Ft. Lauderdale, Polk, Coral Gables live-verified**; Brevard, Clearwater, Pensacola, Ocala, Deltona by UI | **Vendor + amount + bid number in matter titles** — "MOTION TO AWARD … Crown USA, Inc. … Bid No. OPN2131620B1 … $193,500" (verified) | **The best local-award source that exists. Not yet built.** Free JSON, OData filters. Miami-Dade's instance is dead (frozen 2018) — use its govaction HTML instead. |
| **VendorLink** | 66 catalog agencies of 156 FL | n/a | **Terms prohibit scraping** (§5(H), read 2026-08-09) — adapter removed, catalog only. Do not rebuild. |
| **FDOT bidletting** | All state road construction lettings, by district | **Full bid tabs: every bidder + amount, low bid first, with county** (verified District 4) | Not built. Server-rendered HTML, no token. |
| **SAM.gov v2** | Federal in FL | `ptype=a` award notices carry a structured `award{amount, date, awardee{name, ueiSAM}}` | Adapter exists but never asks for awards, NAICS, or `resourceLinks`. Needs free key. |
| **Public Purchase** | 228 FL agencies | None (solicitation platform) | **Login wall covers even titles** (verified). Only path: free vendor registration + email alerts → bid mailbox. |
| **BidNet Direct** | 55 catalog agencies | n/a | Terms unreadable by their own robots rules — recorded decision stands. Catalog + mailbox only. |
| **DemandStar** | overlaps | n/a | Terms prohibit scraping — recorded decision stands. Do not touch. |
| **BoardDocs** (school boards) | Most FL district purchasing agendas, amounts in agenda PDFs | Present but behind CloudFront bot-filtering (403 to honest clients) | No scrape path. Ch. 119 requests / manual per district. |
| Statewide local-award aggregator | — | — | **Does not exist publicly.** Verified: LOGER/AFRs are category totals; DMS term contracts are vehicles; Right-to-Know is state payroll. |

## 3. Source by source

Format per source: **publishes** (live-verified) → **captured today** → **left on the
table** (= defects) → access → award amounts → fragility.

### MyFloridaMarketPlace VIP — state · JSON API · 1 source
- **Publishes** (list): agency + FLAIR entity code, ad number, type/typeId, title,
  open/close/publish dates, status, advertisementId. (Detail): HTML description,
  **UNSPSC `commodityCodes[]`**, `responseDate` (question/response deadline), 5 indicator
  flags (pre-solicitation conference, minority-encouraged…), `docs[]` with attachmentId,
  full `responseContact` (name/address/phone/email), **`linkedAdNumber`** on Agency
  Decisions. No budget, no county, no term/renewals, no structured requirements.
- **Captured**: title, agency, dates, type, status, scope, docs, contact trio, protest
  clock on awards.
- **Left**: UNSPSC codes; `responseDate` → questions_due; `linkedAdNumber` (the award
  linkage key!); indicator flags; detail payload not kept in `raw`.
- **Access**: open JSON, no auth. POST needs every body key + `Accept: application/json`;
  attachments need the XHR-style Accept header. Rate limiter returns HTML-with-200
  (handled).
- **Award amounts**: bid-tab PDF attached to the Agency Decision (verified: FDOT form
  with per-bidder amounts + "X INDICATES INTENDED AWARD"). Per-agency forms, sometimes
  scans → PDF parse, best-effort.
- **Fragility**: low. Fake pagination and Accept quirks already handled.

### OpenGov — county/city/school/authority · JSON API · 91 sources
- **Publishes** (detail, 148 fields): **NIGP `categories[]` (code+title)**; structured
  contacts (`contactEmail/Phone/Title/…` + `procurement*` mirror); `qaDeadline` +
  `qaResponseDeadline`; `preProposalDate/Text/Location`; estimated cost inside
  `upfrontQuestions[]` (free text); `closeOutReason` free text ("awarded" vs
  "canceled"), `awardPending` status, `closedAt`; inline `addendums[]` with **stable**
  attachment URLs; `background`/`sectionDescriptions` scope text; public
  **`/planholders`** endpoint with `isProposer` flag (the bidder pool). Not published
  anonymously: awarded vendor/amount (proposal endpoints 401), bonds/terms (PDF-only).
- **Captured**: title, ref, dates, status(open/closed only), summary/scope, contact
  (broken — see below), one questionDeadline key that doesn't exist, S3 documents.
- **Left / broken**: NIGP codes ignored (categories re-derived from title keywords!);
  `_contact()` probes keys that don't exist in the payload → detail contacts effectively
  never captured; `questions_due` never set (`questionDeadline` vs real `qaDeadline`);
  pre-bid fields ignored; estimated cost ignored; awarded-vs-cancelled collapsed;
  addenda attachments all dropped (the `/addendums` endpoint's files carry no `url`;
  the detail payload's own `addendums[]` has stable URLs — unread); planholders unknown
  to the adapter; `raw` keeps 2 of 148 fields.
- **Access**: open API host, no challenge. S3 doc URLs expire in ~20 h → fetch-now.
- **Award amounts**: not anonymously. Path: planholder/proposer pool + Legistar/agenda
  linkage, or Ch. 119 for the tab.
- **Fragility**: low; tenant list drifts (re-run discovery weekly).

### CivicPlus — municipal · HTML · 99 sources
- **Publishes** (detail, verified on an awarded Davie bid): Bid Number/Title,
  **`Category:` raw text** (sits in `BidDetail/BidDetailSpec` spans), Status incl.
  **Awarded/Cancelled**, description, publication + closing datetimes, related documents
  incl. addenda, bid-opening reports, **vendor response PDFs and "Award Recommendation /
  Intent to Award" PDFs** (verified: names the winner), optional pre-bid/contact/
  submittal/special-requirements labels. `showAllBids=on` exposes a full archive (Davie:
  1,070 rows, 725 awarded).
- **Captured**: list + detail as documented; prose-mined requirements/value/contacts.
- **Left**: raw `Category:` (adapter reads the wrong span family); awarded → flattened to
  `closed`; award-rec PDFs are already collected as documents but never parsed for the
  vendor; archive/history never fetched.
- **Access**: plain HTML. **Per-tenant divergence is the real story** (verified in one
  pass): Davie fully public; Pembroke Pines empty; Boca Raton 302s the whole board to
  CivicPlus PublicLogin; Hollywood board abandoned (city moved to BidSync — currently
  reads "healthy, no listings").
- **Award amounts**: not on the page; sometimes inside tabulation/resolution PDFs
  (unstructured). Better path for these cities: Legistar/agenda linkage.
- **Fragility**: moderate — layout stable, but tenants silently migrate or wall off.

### VendorLink — mixed · HTML (+postback detail) · 66 sources
- **Publishes** (list): agency, number, title, status (9-value vocabulary), broadcast /
  question-end / due dates, mandatory-pre-bid flag. (Detail — **public via the grid's
  `__doPostBack` → `/external/biddetails`, robots-allowed, verified anonymously**):
  explicit solicitation type ("Invitation to Bid"), department, **Project Estimate
  field**, **structured Insurance-Required / Bid-Bond / Performance-Bond flags + amount
  fields**, scope w/ term+renewals prose, pre-bid meetings table (date/location/
  mandatory), **NIGP commodity codes**, documents incl. addenda and **bid-tabulation
  PDFs**, planholders w/ timestamps, bidders table, **Anticipated Award Date**. Plus
  `/external/contracts?a=N`: contract number, title, status, **vendor**, approval/start/
  end dates, **Amount, Total Amount** (fill varies by agency).
- **Captured**: **nothing. The adapter was removed on 2026-08-09** and these 66 agencies
  are `catalog` pointers. Everything above describes what the platform publishes, not
  what this build reads, and it is kept only so the size of the gap is legible.
- **Access**: ⛔ **`PROHIBITED` in `src/terms.py`** — not `GRANDFATHERED`, which is what
  this section said while the terms were still unread. §5(H) of their Terms and
  Conditions forbids "any robot, spider, other automatic device, or manual process to
  monitor or copy" their pages, under a browse-wrap that binds on use of the site. The
  earlier check followed `/terms`, which redirects to a login; the operative document is
  linked from every page footer at `/external/termsandconditions`. robots.txt allowing
  `/external/` does not override prose terms — robots is not the test, in either
  direction. **Do not build the detail pass.** The sanctioned path is their statewide
  subscription (~$175/yr), ranked in `docs/statewide-coverage.md` §4.
- **Award amounts**: n/a here — see the Legistar and FDOT bid-tab sources instead.
- **Coverage recovered without them**: see `docs/statewide-coverage.md` §3c. Of the 66,
  11 turned out to be read live already by another adapter, and one more (New Smyrna
  Beach) was recovered by re-reading the agency's own site.

### Bonfire — mixed · JSON · 32 sources
- **Publishes**: 9 fields per project (ref, title, close **in UTC**, dept, status ids);
  past rows add **`IsPublicAward`** (224 awarded vs 37 cancelled distinguishable,
  verified on Broward's 708-row archive); contracts endpoint: name, vendor, start/end,
  status, **`IsExtendable` renewal flag** — no amounts (value key exists internally, not
  published). Detail pages Cloudflare-403; docs need vendor login.
- **Captured**: list + contracts (vendor, dates).
- **Left**: `IsPublicAward`/sub-status (awards flattened to closed); `IsExtendable`;
  **`DateClose` parsed as Eastern though it is UTC → every Bonfire due time is 4–5 h
  late** (bug, audit item).
- **Access**: 4 XHR endpoints pass anonymously; a third response class exists
  (success:1 + empty register).
- **Award amounts**: never public. Path: Legistar (Broward BCC verified) / Ch. 119.
- **Fragility**: low for the XHRs; portal generations differ.

### Jaggaer — universities · HTML · 5 sources
- **Publishes** (award tab, verified FSU): event ref/title/type/dates/contact + **Award
  Documents** — tabulation XLSX (verified: `BIDDER NAME | TOTAL PRICE`, winner
  highlighted, protest window), Intent-to-Award PDFs, shortlists, cancellations.
  Attachment URLs are per-render pre-signed S3 → must download in-session.
- **Captured**: rows incl. contact; award docs filenames into `raw`; no protest clock on
  award rows (inconsistent with ionwave/mfmp — audit item).
- **Left**: the award documents (vendor + amount inside); 20-row archive cap noted.
- **Config drift**: UF/USF configured despite the module's own probe showing empty
  tenants.
- **Award amounts**: inside award attachments; heterogeneous human-authored files → parse
  best-effort, in-session.
- **Fragility**: moderate (label-driven HTML holds; S3 links ephemeral).

### Ionwave — city/county/school · HTML · 4 sources
- **Publishes** (verified Lee County): awarded list = number/title/type/org/**award date
  only**; contracts register (1,671 rows) = number/title/org/**supplier**/type/start/end
  — **no amounts anywhere, anonymously, confirmed**.
- **Captured**: everything the lists offer, incl. protest clock. Correct.
- **Left**: contract register (deliberate — 67 pages vs 3-request Cloudflare budget).
  Organization column.
- **Award amounts**: not published. Path: agenda/Ch. 119.
- **Fragility**: the 3-request budget is the constraint; verified no challenge in 2.

### Workday Strategic Sourcing — univ/county/college · GraphQL · 3 sources
- **Publishes**: the 11 queried fields, **plus `description` and
  `attachments { nodes { fileName } }` — both confirmed valid via error-probing** (the
  attachment URL field name remains unknown; introspection off). `awardedSuppliers`,
  `buyer`, `summary` do not exist. Award = `state: AWARDED`, nothing more.
- **Captured**: all 11 queried fields incl. commodity codes → keywords.
- **Left**: `description`, attachment filenames (query-scope, cheap to add).
- **Award amounts**: not in the public schema, full stop. Path: agenda/Ch. 119.
- **Fragility**: low-moderate; query lifted from compiled bundle can drift on redeploys.

### FDOT PDA (PS + D-B) — state · token API · 2 sources
- **Publishes** (26 fields/row, 275 rows verified): ad number, short description (no long
  one), advertised + response-deadline dates, **`MajorWorkTypesText` /
  `MinorWorkTypesText` (the raw category)**, district, status incl. Planned,
  **`AdContractAmount`**, `SelectionMethodText`, **`ProjectThresholdTypeName`
  (prequalification)**, `BDI` set-aside flag, FM numbers, shortlist/final selection
  *meeting dates* (schedule, not results — no firms, no amounts, verified).
- **Captured**: number/title/dates/status/budget/district+county keywords; the rest to
  `raw` only.
- **Left**: work types never become categories; prequal/selection-method/BDI never become
  requirements.
- **Award amounts**: **not here** — construction awards live on `bidletting.fdot.gov`
  (below); CCNA selections are published nowhere machine-readable.
- **Fragility**: akey minted from an Angular page + 401-empty-body failure mode; both
  verified working.

### FDOT bidletting — state construction awards · HTML · not built
- **Publishes** (verified District 4 preliminary report): per contract — contract no,
  financial project no, **county**, **every bidder's name + bid amount, ascending** (low
  bid first). Official intent-to-award posted on the Contracts Administration notices
  page. 26 letting dates back to 2024 per district.
- **Access**: server-rendered HTML; needs the district hop + `lettingID`
  (`{district}{YY}{MM}{DD}`); no token. `Allow: /` robots.
- **Effort**: one adapter, 8 districts + statewide, modest volume.

### FACTS — state contracts · CSV export · 1 source
- **Publishes**: **52 columns** (all enumerated live): vendor(+line 2), original/total
  amounts, recurring/non-recurring budget, **UNSPSC segment code + description**,
  contract type, **execution date**, begin/original-end/**new-end**, status, **method of
  procurement + statutory authority + exemption justification text**, State Term Contract
  ID, Agency Reference Number, periodic-increase %, capital-improvement fields, CFDA/CSFA,
  comment. Detail page adds **payments-to-date by fiscal year**, budget/unfunded amounts,
  amendment history, vendor city/state/zip + minority designation, deliverables with
  per-item prices, contract PDFs (image-button postback).
- **Captured**: ~10 columns (vendor, amounts, method, dates, status).
- **Left**: commodity code/description, execution date, justification, STC ID, agency
  reference (a potential solicitation-linkage key), grants (`G`) and purchase orders
  (`P`) — the search serves three record types, only `C` is pulled.
- **Fragility**: WebForms ViewState chains; CSV quoting glitches (handled); session
  timeout interstitial exists.

### SAM.gov — federal · JSON API (free key) · 1 source
- **Publishes** (per official v2 docs): NAICS + PSC codes, `resourceLinks[]` (attachment
  URLs), full `pointOfContact[]`, `placeOfPerformance`, set-asides, and — with
  `ptype=a` — **structured `award { number, amount, date, awardee { name, ueiSAM } }`**.
- **Captured**: title/dates/dept/one email/location; NAICS parked in `raw`; no docs, no
  award notices requested.
- **Left**: NAICS/PSC → fields; `resourceLinks` → documents; contacts; `ptype=a` award
  ingestion (the cleanest structured award feed in the whole plan).
- **Fragility**: low; official API. Needs `SF_SCOUT_SAM_KEY` set.

### Bespoke local sources
- **Miami-Dade ISD** (current+future, detail): fine as-is; **Award Recommendations feed
  exists** (`Home/AwardRecommendationsList`, currently `[]`, + PDF store) — wire it and
  parse recommendation PDFs (vendor; amounts sometimes).
- **Miami-Dade INFORMS**: weakest adapter — heuristic table pick, status always "open",
  no degraded detection (audit item). Publishes nothing award-related.
- **Miami-Dade BCC awards**: Legistar instance dead; the **govaction Legislative
  Information Center** (HTML, 1996-present, File/Title/Cost) is the substitute. Not
  built.
- **MDC College**: announcement log; award recommendations + tabulations are linked PDFs
  never fetched; no due dates published.
- **Palm Beach Schools**: publishes construction budgets (captured); `location` never
  mapped to `project_location`; awards via board agendas only.
- **West Palm Beach**: Akamai-walled; awarded rows currently dropped outright.
- **Coral Gables notice links**: the notice PDF is in hand and never parsed nor recorded
  as a document — dates/contacts inside it are lost.
- **Email alerts**: stamps every mail `broward`/"Email subscriptions" — read the From
  header and map sender → city (defect).

## 4. Unreachable today, and the path

| Target | Blocker | Path |
|---|---|---|
| Public Purchase (228 agencies) | Login wall to the first byte | Free vendor registration (your manual step) → per-agency email alerts → existing IMAP adapter, fixed for attribution |
| BidNet (55) | Terms unreadable | Catalog + mailbox registration; revisit only if their terms change |
| DemandStar overlap | Terms prohibit | Agencies double-post; cover via their own portals |
| School-board awards (BoardDocs) | CloudFront bot-block | Scheduled Ch. 119 request for bid tabs per district of interest; or manual agenda pulls |
| Tampa/Orlando/St. Pete/Hillsborough/Orange/PBC awards | Not on Legistar API | Their own agenda platforms (Novus/OnBase/eScribe) — bespoke, defer; Ch. 119 fallback |
| 15 rural counties | No portal at all | s. 50.0311(6) legal-notice registration (statutory right) + standing Ch. 119 schedule |
| Special districts (~2,088) | No boards; agendas only | s. 189.069 agenda watch for the ~990 non-CDD districts, later |

## 5. Ranked: records gained per unit of effort

Effort: S = hours, M = a day or two, L = a week+. Every item is a code change except
where marked MANUAL.

| # | Work | Gain | Effort |
|---|---|---|---|
| 1 | **OpenGov capture fix** — NIGP codes, real `qaDeadline`, fixed contacts, pre-bid, estimated cost, `closeOutReason`→award/cancelled status, addenda-docs fix, keep full `raw` | 91 sources × ~150 fields; fixes 3 outright bugs | S–M |
| 2 | **MFMP capture fix** — UNSPSC codes, `responseDate`→questions_due, **`linkedAdNumber` award↔solicitation link**, indicator flags | Every state agency; the first real award linkage | S |
| 3 | **Bonfire fixes** — UTC close-time bug, `IsPublicAward`→award status, `IsExtendable` | 32 sources; 200+ award records surface immediately | S |
| 4 | **Schema additions** — tier, raw_category, commodity codes, awarded_vendor/amount/date, linkage_method, contract term | Prerequisite for everything above | S |
| 5 | **SAM.gov full capture + `ptype=a` awards** | Structured federal award amounts, docs, NAICS | S |
| 6 | **FACTS full-width capture** (commodity, execution date, justification, STC id, agency ref) | Richer state awards from data already downloaded | S |
| 7 | **Legistar award adapter** — Broward Co, Jax, Miami, Ft Laud, Polk, Coral Gables (+roster sweep) | **Local award amounts+vendors — the #1 gap — via free JSON** | M |
| 8 | ~~VendorLink detail + contracts pass~~ — **cancelled 2026-08-09**: their ToS were read and §5(H) forbids it. Replaced by *catalog recovery* (`statewide-coverage.md` §3c), which reads the agencies' own sites instead. | 11 of the 66 already covered; 1 recovered; 20 confirmed unreachable without a subscription | done |
| 9 | **CivicPlus award capture** — raw Category, awarded status, parse award-rec PDFs for vendor | 99 sources; awards for the small cities nothing else covers | M |
| 10 | **FDOT bidletting adapter** | Construction bid tabs: bidder+amount+county | M |
| 11 | **Workday query widen** (`description`, attachment filenames) | 3 sources, honest gain | S |
| 12 | **Jaggaer award-doc parse** (in-session XLSX/PDF) | University award vendors+amounts | M |
| 13 | **Miami-Dade award recs + govaction HTML** | The county Legistar can't reach | M |
| 14 | **Email-alert attribution fix** (From-header → city) | Correct county on every mailbox record | S |
| 15 | **Bid mailbox** — MANUAL: register on Public Purchase (+ 1 DemandStar free agency), then parser hardening | Up to 228 otherwise-dark agencies | M code + your registrations |
| 16 | **Ch. 119 request scheduler** for BoardDocs districts + rural counties | The tail; slow but complete | M–L |
| 17 | Special-district agenda watch | Long tail | L |

Items 1–6 are pure capture fixes on sources already fetched — they are where "leaving
data on the table" ends. Items 7–10 are the award engine. Everything past 14 needs
either your manual registrations or scheduled correspondence.
