# SF Procurement Scout

Live aggregator for government procurement across **Florida** — every state
agency through MyFloridaMarketPlace, plus **305 live local sources** on eleven
platforms (OpenGov, CivicPlus, VendorLink, Bonfire, Ionwave, Vendor Registry,
FACTS, FDOT, Jaggaer, Workday, and a handful of bespoke portals), **federal bids
in Florida** via SAM.gov, and a catalog of the portals that cannot be read
without an account.

It started as a tri-county tool. The county field now takes any of Florida's 67,
and coverage grew by writing one adapter per *platform* rather than per agency:
one OpenGov adapter serves 91 agencies, one CivicPlus parser serves 89.

**GitHub:** [hillynew/sf-procurement-scout](https://github.com/hillynew/sf-procurement-scout)

## Features

| | |
|--|--|
| **A. Capture** | Live titles, refs, due dates, and links from public county/city portals |
| **B. Organize** | County, agency, solicitation type, goods/services/construction, topic categories |
| **C. AI deal briefs** | Claude reads the scope + bid-package PDF and writes a plain-English brief with red flags (optional API key; rule-based fallback) |
| **D. Dedupe** | One record per solicitation, even when portals overlap or repeat announcements |
| **E. Detail** | Scope of work, pricing, bid requirements, documents and contacts, read from each bid's own page |
| **F. Source health** | Every portal reports `ok` / `no listings` / `degraded` / `error` so silent breakage is visible |
| **G. Pipeline** | Drag-and-drop kanban from Watching to Result, with win/loss dollars and an archive |
| **H. Alerts** | In-app notification center + optional email digests for watchlist matches and deadlines |
| **I. Protest clock** | Intended-award notices carry a 72-hour protest deadline under s. 120.57(3)(b), counted excluding weekends and state holidays |
| **J. Records trigger** | Sealed bids stop being exempt 30 days after opening; day 31 turns into a ready-to-send Chapter 119 request |
| **K. Incumbents** | Executed contracts with vendor names and end dates — the earliest warning that a rebid is coming |
| **L. Discovery** | Fingerprints an agency's own website to work out which platform it runs, so the source list grows without hand-written rows |

Sources are fetched concurrently in the background with live per-source
progress — the UI never blocks on a refresh.

## What is captured per opportunity

List pages carry little more than a title and a date, so a second pass reads
each open bid's own page. That is where the fields a contractor actually
decides on live:

| Field | Source |
|-------|--------|
| **Scope of work** | Full narrative from the detail page or the bid package — often several thousand words |
| **Estimated value** | The figure the agency states in its own package; failing that, dollar amounts qualified by "not to exceed" / "budget of" in the listing prose. A bare figure is only used above $25k, so a plan fee is never mistaken for the contract |
| **Project duration** | Calendar days allowed for completion |
| **Liquidated damages** | Daily penalty for late completion |
| **Licence classes** | The primary and sub-contractor licences a bidder must hold |
| **Project location** | Site address |
| **Requirements to bid** | Bid/performance/payment bonds, insurance, licensing, prequalification, mandatory pre-bid meetings and site visits, E-Verify, SBE/MBE/DBE goals, local preference, prevailing wage, and more |
| **Documents** | Every bid package file, with addenda tagged separately so changes stand out |
| **Key dates** | Bid deadline, question deadline, pre-bid meeting, publication date |
| **Contacts** | Buyer name, email and phone |
| **Submittal information** | Where and how a response must be delivered |

Each record carries a **detail score** (0–100) summarising how much is known,
shown as a meter in the UI so a fully-specified bid is visibly more actionable
than a bare listing.

### Where each field comes from

Three passes, each cheaper to skip than the last:

1. **Listing** — title, reference, dates from the portal's index page.
2. **Detail page** — scope, documents, submittal terms and contacts.
3. **Bid package PDF** — the commercial terms that appear nowhere else:
   estimated value, bond requirements, licence classes, project duration and
   liquidated damages. Miami-Dade's RPQ packages open with a labelled
   "DETAILED BREAKDOWN" block that states all of them outright.

Both extra passes are bounded and run only for `open` and `upcoming` listings,
soonest-due first: 150 detail requests and 60 PDFs per refresh. Extracted PDF
text is cached under `data/pdf_cache/`, and a package shared by several
solicitations (common for framework contracts) is downloaded once. Portals
that expose no detail page still get requirements and pricing mined from the
blurb they do publish.

Disable either pass with `run_fetch(with_details=False)` or
`run_fetch(with_packages=False)`.

## The app

A React single-page app (Vite + TypeScript + Tailwind, `frontend/`) served by
a FastAPI JSON API (`web/server.py`, routers in `web/api/`). Fully responsive
— a sidebar on desktop, a bottom tab bar on the phone.

| Screen | What it does |
|--------|--------------|
| **Dashboard** | Stat tiles (open bids, open value, due-soon, win rate) plus charts: bids by county, value by work type, 8-week deadline load, won revenue by month, top sources |
| **All bids** | Instant search-as-you-type, county/type/status filter chips, sortable list with value and detail-score on every row |
| **Pipeline** | Drag-and-drop kanban (Watching → Preparing → Submitted → Result) with per-column dollar totals, a win/loss dialog that records real amounts, and an archive |
| **Workroom** | Deep read of one bid: AI deal brief, scope, requirements checklist, documents, key dates, commercial terms, go/no-go, autosaving notes |
| **Watchlists** | Real rule builder (keywords, counties, types, value range, no-bond, recurring) with live match preview, rename/delete, and genuinely-correct NEW badges. A county rule also keeps statewide bids that *name* that county — see below |
| **Sources** | Health KPIs and per-portal status, plus a working "add a source" flow: paste a URL, CivicPlus portals are detected, added, and test-fetched on the spot |
| **Settings** | Auto-fetch schedule, notification prefs, email digest, AI model choice, and data management (export CSV, purges, demo data) |

Clicking any bid opens a slide-in drawer with facts, requirements, documents
and actions; a bell in the top bar collects notifications (new watchlist
matches, deadlines approaching, fetch results). Everything you *do* — tracking,
checklists, decisions, notes, results, watchlists — persists in the database
(Postgres on Render, SQLite locally), so restarts lose nothing. An empty first
run offers **load sample data** (`web/sample_data.py`) to explore before the
first live fetch.

### AI deal briefs

With `SF_SCOUT_ANTHROPIC_KEY` (or `ANTHROPIC_API_KEY`) set, Scout sends each
bid's scraped fields + extracted PDF text to the Claude API and caches a
structured brief: what the work is, key dates, money terms, requirements in
plain English, red flags, and a fit hint. Tracked bids are summarized
automatically after each fetch; any other bid has a **Summarize with AI**
button. Default model is `claude-haiku-4-5` (roughly a cent per 50 bids);
switch to `claude-sonnet-5` in Settings for harder documents. No key → the
rule-based brief (`src/summarize.py`) is shown instead and nothing breaks.

## Bid history and recurrence

Knowing a contract is open today is worth less than knowing the agency rebids
it every three years and the last cycle closed in March. Bonfire publishes a
public archive of closed solicitations, so `run.py history` collects it into
`data/history.json` and every fetch matches open bids against it:

```bash
python run.py history      # refresh the archive (slow-moving; run occasionally)
python run.py fetch        # matches open bids against it automatically
```

Matching is per-agency on the significant words of a title, after stripping
boilerplate ("Request for Proposals", "Services", "City of") and years, so
"Janitorial Contract 2024" and "Janitorial Services Citywide" are recognised as
the same recurring buy while "Roof Repairs Fire Station 12" and "Roof Repairs
Water Plant" stay distinct. Matches show as `prior_cycles` and
`last_cycle_closed`, and as a 🔁 badge in the UI.

Coverage is limited to agencies whose portal exposes an archive — the Bonfire
ones (Broward County, Town of Palm Beach, FAU, Tri-Rail), about 945 past
solicitations, plus the 91 OpenGov tenants, whose public project list carries
closed and awarded projects alongside open ones.

## Bid alerts by email

No portal here offers webhooks. CivicPlus cities do offer a "Notify Me"
email/SMS subscription, so the `email_alerts` source reads a dedicated mailbox
over IMAP and turns each notice into an opportunity — the closest thing to
real-time push available.

Subscribe a mailbox at each city's `/list.aspx?Mode=Subscribe#bids`, then copy
`.env.example` and fill it in. Use an app-specific password; the mailbox is
opened **read-only** and nothing is deleted. Left unconfigured, the source
reports `inactive` and changes nothing.

Subscribing is a manual, per-city step — there is no API for it. Two CLI
commands make it tractable:

```bash
python run.py subscribe-links   # every CivicPlus city's subscribe page, as a checklist
python run.py check-mailbox     # confirms SF_SCOUT_IMAP_* actually works, no full fetch
```

## Outgoing email digests (Resend)

The mailbox above is mail coming *in*. Digests are mail going *out*: watchlist
matches and deadlines, sent through [Resend](https://resend.com) (free tier is
ample). Three environment variables, all optional:

| Variable | Meaning |
|---|---|
| `RESEND_API_KEY` | API key from resend.com — without it the whole feature stays inert and Settings says so |
| `SF_SCOUT_DIGEST_TO` | Fallback recipient; the recipient set in Settings wins |
| `SF_SCOUT_DIGEST_FROM` | Sender, e.g. `Scout <scout@yourdomain.com>`. Defaults to Resend's shared `onboarding@resend.dev`, which only delivers to the address that owns the Resend account — verify a domain to send anywhere else |

Then pick a cadence in **Settings → Email digest**: `daily` at a chosen UTC
hour, or `instant` right after any fetch that turns up new watchlist matches.

Nothing about email is worth trusting until you've seen one arrive, so both the
UI and the CLI can send one on demand through the exact code path the digest
uses:

```bash
python run.py test-email        # or: Settings → Email digest → Send test email
```

A failure reports Resend's own reason — bad key, unverified sender, missing
recipient — rather than failing silently. Scheduled digests stay fire-and-forget:
a send that fails is logged as not-sent and never breaks a fetch.

## Authenticated Bonfire sessions

Bonfire's public API only shows what is open to everyone. A signed-in vendor
account additionally sees `getMyOpportunitiesSectionData` — solicitations this
account was invited to or is following — which an anonymous scrape cannot see
at all.

If you have an account with a Bonfire agency, set the session cookie from a
signed-in browser tab and the adapter merges those in automatically, tagged
`personalized` with an `invited` category:

```bash
# .env — one account for every Bonfire agency:
SF_SCOUT_BONFIRE_COOKIE=<the whole Cookie header from a signed-in session>

# or scope one account to a single host, e.g. broward.bonfirehub.com:
SF_SCOUT_BONFIRE_COOKIE_BROWARD=<cookie>

python run.py auth-status   # shows which hosts have a session configured — never the cookie itself
```

Bonfire issues a session cookie rather than an API token, so this expires like
any browser session. When it does, the source quietly falls back to the
public list — never a fetch failure — and `auth-status` is the way to notice
and re-paste a fresh one.

The Euna Supplier Network (`vendor.bonfirehub.com`) additionally exposes a
cross-agency API covering every Bonfire tenant at once, not just the ones
configured here — but its API base is only injected into the page at deploy
time from a signed-in browser session, and could not be confirmed without one.
If you can capture it (browser dev tools, Network tab, while signed in), it
would be a natural follow-up.

## Source health

Scrapers break quietly — a portal changes its layout and the adapter returns
zero rows while still reporting success. Each fetch therefore classifies every
source:

| Status | Meaning | What to do |
|--------|---------|------------|
| `ok` | Returned live rows | Nothing |
| `no listings` | Fetched cleanly; the portal genuinely has nothing posted | Nothing |
| `degraded` | Blocked by the portal, or parsed nothing where rows were expected | Check that agency directly; the adapter may need updating |
| `error` | The request itself failed | Check connectivity, then the adapter |

`python run.py health` prints this for the last snapshot, and the dashboard
surfaces it in the left menu and the **Source health** panel.

> The City of West Palm Beach portal sits behind a WAF that blocks scrapers, so
> that source reports `degraded` and falls back to its DemandStar listing.

## Background upkeep

Health catches an adapter that breaks. It cannot catch the two ways this build
goes wrong quietly, so each has its own job on its own cadence, under
**Settings → Background upkeep**. Both are off until you switch them on, like
auto-fetch and the digest, because between them they make several hundred
requests to agency websites.

| Job | Default | What it answers |
|-----|---------|-----------------|
| Contract register | Weekly | When does the incumbent's term end? |
| Platform check | Monthly | Is this agency still on the portal we read? |

The **contract register** is the only leading indicator in the build. A rebid is
advertised weeks before it opens and scoped months before that; an incumbent's
end date is the earliest warning available. It decays invisibly — a stale
register looks exactly like a current one — so it is re-read weekly and reports
what is expiring inside 90 days.

The **platform check** exists because of a failure mode that has cost this
project five agencies: *a live page returning zero rows reads as a quiet agency,
not a migrated one.* The adapter works, the fetch succeeds, health stays green,
and the agency has simply stopped posting there. Deerfield Beach (DemandStar →
Ionwave), UNF (Jaggaer → Workday), St. Johns County and its Anastasia Sanitary
District (DemandStar → Workday) were all found this way rather than by anything
noticing they had gone silent. So once a month every identified agency's own
website is asked whether it still runs the platform the registry records, and
each disagreement becomes a notification naming where it went.

An agency that goes from a known platform to *unreadable* is reported
separately, and only when it happens in bulk — individually that is a slow site
or a bot wall, not a migration, and treating the two alike would cry wolf every
sweep.

Both run in a worker thread, one at a time, never during a fetch, and never two
in one tick — they are minutes of blocking HTTP each, and the scheduler's tick
runs on the event loop. Either can also be run by hand:

```bash
python -m src.cli contracts --refresh
python scripts/fingerprint_agencies.py --recheck
```

## Deploy on Render

> Handing this to an AI agent (Claude Code, Cursor, Copilot, etc.) to deploy
> or operate? See [`AGENTS.md`](AGENTS.md) — it has the step-by-step,
> troubleshooting table, and the exact env var names, written for that.

### Option A — Blueprint (recommended)

1. Push this repo to GitHub (already at `hillynew/sf-procurement-scout`).
2. Open [Render Dashboard](https://dashboard.render.com/) → **New** → **Blueprint**.
3. Connect the `sf-procurement-scout` repo.
4. Render reads `render.yaml` and creates the web service **plus a free
   Postgres database** wired in via `DATABASE_URL`, so tracked bids, notes,
   results, and snapshots survive restarts. The optional integration
   variables below are declared with `sync: false`, so Render's dashboard
   prompts for each one without ever storing a value in git — leave them
   blank to keep those integrations inactive.
5. After deploy, open the service URL and click **Fetch live data**.

### Option B — Manual Web Service

1. **New** → **Web Service** → connect `hillynew/sf-procurement-scout`.
2. Settings:

| Setting | Value |
|---------|--------|
| Runtime | Docker |
| Dockerfile path | `./Dockerfile` |
| Health check path | `/healthz` |

Render injects `$PORT`; the Dockerfile's start command honors it.

### Notes for free tier

- Service sleeps after idle; first request may take ~30–60s to wake.
- Data lives in Postgres, so restarts lose nothing — but a fresh fetch still
  runs in the background (with live progress) whenever you want newer bids.
- The in-app auto-fetch scheduler only ticks while the service is awake; an
  external uptime pinger (or a cron `curl -X POST …/api/fetch`) keeps data
  fresh around the clock if you need that.
- Scraping public sites takes 30–90s per full refresh.

## Local development

```bash
cd sf-procurement-scout
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# CLI
python run.py fetch
python run.py fetch --county broward -q "software"
python run.py show
python run.py health
python run.py history
python run.py auth-status
python run.py check-mailbox
python run.py test-email
python run.py subscribe-links
python run.py list-sources
python run.py import-legacy-state   # one-shot: old data/user_state.json → DB

# API + built SPA on :8000 (needs `cd frontend && npm run build` once)
uvicorn web.server:app --host 0.0.0.0 --port 8000

# Frontend dev server with hot reload (proxies /api to :8000)
cd frontend && npm install && npm run dev
```

Without `DATABASE_URL` the backend uses SQLite at `data/scout.db` — no setup.
Set `DATABASE_URL=postgres://…` to run against Postgres like production.

### Docker

```bash
docker compose up --build          # dashboard on http://localhost:8000
docker compose --profile fetch up  # + a sidecar that re-fetches every 4h
```

The `./data` volume keeps snapshots and your workflow state across container
restarts. Or without compose:

```bash
docker build -t sf-procurement-scout .
docker run -p 8000:8000 -v "$PWD/data:/app/data" sf-procurement-scout
```

### Tests

```bash
pip install -r requirements-dev.txt
pytest
```

Tests run offline against saved portal responses in `tests/fixtures/`, so they
stay fast and do not hammer public sites. When a portal changes its layout,
re-capture the fixture and update the adapter together.

## Live sources

Coverage is by platform, not by agency — that is what makes statewide
tractable. Counts are what is configured and answering today.

| Platform | Sources | How |
|---|---:|---|
| **OpenGov Procurement** | 91 | Open JSON API on `api.procurement.opengov.com`. The portal host is Cloudflare-challenged; the API host is not. Documents arrive as pre-signed S3 URLs. |
| **CivicPlus Bids** | 89 | One parser for byte-identical markup across hundreds of city bid boards |
| **VendorLink** | 66 | Florida-native ASP.NET grid, paged via ViewState postbacks. List-only: detail is behind a login |
| **Bonfire** | 32 | Public JSON API — open, past, and the contract register |
| **DemandStar** | 14 | **List only.** `api.demandstar.com/contents/agency/search?id=<guid>` — the base the app itself calls `urlNoAuth` — returns the agency's most recent 100 solicitations as open JSON. Every detail endpoint answers 401, so the row links the public bid page rather than being enriched |
| **Ionwave** | 4 | Four public lists the tenant's own login page links to, no cookie needed. Cloudflare challenges the fourth request on a session, so `fetch` costs exactly one |
| **Vendor Registry** | 5 | **Archive only.** The platform's current list reports no open solicitations for any buyer in any state; these agencies post on OpenGov, Bonfire and BidNet now. 1,098 past solicitations that back-fill recurrence for the feeds that replaced them |
| **Workday Strategic Sourcing** | 3 | UNF, St. Johns County and Hillsborough Community College, all arrived here in 2026. Apollo GraphQL behind an `X-XSRF-TOKEN` handshake; only the public-portal host is read, never the authenticated one |
| **Jaggaer** | 5 | Florida State, Florida Atlantic, FIU, and — found by the fingerprint sweep — Florida and South Florida, the two largest buyers in the state system. Four GET-addressable tabs; the row is one `<td>` of nested markup, read by the portal's own field labels |
| **FDOT advertisements** | 2 | Professional services and design-build, from the PDA REST host behind a page-minted token. Carries Notices of Planned Advertisement — 124 jobs FDOT has scheduled but not yet advertised, as `upcoming` |
| **FACTS** | 1 | **Contract register, not a bid feed.** Every executed state contract under s. 215.985(14) — 12,377 with a live end date, 10,192 expiring within a year, with dollar values and procurement method. Two POSTs: run the search, download the CSV |
| **MyFloridaMarketPlace (VIP)** | 1 | Every state agency, university, college and water management district in one adapter, with anonymous PDF downloads |
| **SAM.gov** | 1 | Federal solicitations with a Florida place of performance (free API key) |
| Bespoke portals | 8 | Miami-Dade INFORMS and construction, West Palm Beach, MDC, Palm Beach Schools, notice links, the bid mailbox |
| Catalog pointers | 223 | Portals that need an account — recorded so the gap is visible, and superseded automatically once an adapter can read the agency for real |

Two registries drive this rather than hand-editing:

- `data/registry/fl_agencies.csv` — 2,817 Florida buying entities, the universe.
- `data/registry/fl_procurement_sources.csv` — 133 verified agency → platform rows.

and four scripts turn them into config:

```bash
python scripts/discover_opengov_tenants.py     # OpenGov's own directory → config
python scripts/discover_vendorlink.py --probe  # VendorLink's agency dropdown → config
python scripts/seed_from_registry.py           # verified registry → config
python scripts/fingerprint_agencies.py         # ask each agency's site what it runs
python scripts/sources_from_fingerprints.py    # strong matches → live sources
```

Each one prints what it *skipped* and why. The gap between "verified" and
"fetched" is the number worth watching, so none of them hide it.

A source is identified by its **tenant**, not its hostname. CivicPlus and
Bonfire give each agency its own host, so for them the two are the same thing;
Jaggaer, VendorLink and BidNet put every agency in Florida behind one hostname,
and treating the host as the identity meant that once one university was
configured, every other one read as an already-configured duplicate.

### When the sweep says "unknown"

`unknown` is the sweep's most useful output — it is the queue of things worth a
human minute — but it is not one thing. Of the 635 unknowns in the first pass:

| | |
|---|---|
| 271 | the homepage linked nothing we recognised |
| 151 | we read a procurement page and it named no platform |
| 198 | we could not reach the site at all |
| 15 | robots refused |

Only the first two are fingerprinting problems, and they needed different
answers. A homepage aimed at students does not link purchasing, so procurement
**subdomains** are probed — `procurement.fsu.edu` and `bids.fiu.edu` are both
Jaggaer and both read as "no procurement link found" while this only followed
links. A procurement landing page is often only a signpost, so **one more hop**
is taken off it, which is what separates UF and USF from a dead end. And an
agency that runs no platform at all, keeping the table on its own website, is
recorded as `selfhosted` rather than filed beside the sites that timed out —
those need a page-level reader, not an adapter, and the distinction is the
difference between a queue and a shrug.

After the fingerprinter learns a new way to look, re-ask the ones it missed:

```bash
python scripts/fingerprint_agencies.py --retry-unknown
```

Re-asking all 635 identified 47 of them and lost none — 180 → 227 of the 815
entities swept. Among them: the University of Florida and the University of
South Florida, the two largest buyers in the state university system, neither
of which was reachable by following links from a homepage.

A later pass removed one signature rather than adding one. `/PublicPortal/` is
where Bonfire's API lives, and it was treated as proof of Bonfire — but
JustFOIA serves public *records request* portals at the same path, so 15
agencies linking one were recorded as Bonfire tenants. Rechecking them found
their real platforms: CivicPlus, OpenGov, PlanetBids, DemandStar. A signature a
second vendor also serves is not a signature.

The 593 that are still unknown are mostly not a fingerprinting problem: 261 are
special districts and small towns with no bid board to find, 207 are sites that
cannot be reached from here at all — a bot wall, a bad certificate, a dead host
— and 151 have a purchasing page that names no platform and lists no live work.

### Adding a city

Most South Florida municipalities run the **CivicPlus Bids module** at
`/bids.aspx`, so they all share `src/sources/civicplus.py`. Adding one is a
config entry, not a new scraper:

```yaml
  - id: my_city
    name: City of Somewhere
    county: broward
    agency: City of Somewhere
    live_fetch: true
    adapter: civicplus
    portal_url: https://www.somewhere.gov/bids.aspx
```

Optional keys: `default_categories` (tags every row from a single-purpose
board, e.g. the waste authority) and `base_url` (if relative links resolve
against a different origin).

Cities currently covered — Miami-Dade: Hialeah, North Miami, Miami Gardens,
Homestead, Aventura, Opa-locka, South Miami, Palmetto Bay, Key Biscayne,
Sweetwater. Broward: Hollywood, Pembroke Pines, Davie, Deerfield Beach,
Tamarac, Wilton Manors, Oakland Park, Hallandale Beach, Dania Beach,
Lauderdale Lakes, Parkland. Palm Beach: Boca Raton, Boynton Beach, Jupiter,
Palm Beach Gardens, Wellington, Palm Springs.

Many of these boards are empty at any given moment — they report `no listings`
rather than an error, and start producing rows the moment the city posts one,
with no code change.

Two other adapters are equally generic:

- **`bonfire`** — any agency on Bonfire/Euna. Needs only `bonfire_host`
  (e.g. `fau.bonfirehub.com`); the public opportunities API does the rest.
- **`notice_links`** — agencies that publish solicitations as a list of
  public-notice documents rather than a bid table. It pulls the reference and
  subject out of each link's text. Optional `link_selector` scopes the search
  to one part of the page.

### Agencies that procure through a parent

Some agencies do not run their own portal, so scraping them separately would
duplicate rows already collected:

| Agency | Procures through |
|--------|------------------|
| Port Everglades | Broward County BPRO |
| Broward Aviation (FLL) | Broward County BPRO |
| Miami-Dade Aviation (MDAD) | Miami-Dade ISD / INFORMS |
| Miami-Dade Water & Sewer | Miami-Dade ISD / INFORMS |

Their solicitations already appear under the parent county's source.

**Catalog (register to bid):** City of Miami Bidnet, M-DCPS DemandStar, Broward
Schools, Broward Health, Fort Lauderdale, Palm Beach County VSS, PBC Facilities,
the colleges and cities that publish only through a vendor platform (Miami
Beach, Pompano Beach, North Miami Beach, Broward College, Palm Beach State,
FIU), and the cities whose portals refuse automated clients — Coral Springs,
Miramar, Sunrise, Doral, Delray Beach and Miami Springs. Catalog entries are hidden in the
dashboard unless **Include catalog portals** is ticked.

## Project layout

```
render.yaml             # Render Blueprint (Docker web service + free Postgres)
Dockerfile              # multi-stage: node builds the SPA, python serves it
docker-compose.yml      # local: web + optional 4-hourly fetch sidecar
runtime.txt             # Python version hint
config/sources.yaml     # hand-maintained portal registry
config/sources.*.yaml   # generated companions (opengov, vendorlink, fingerprinted, …)
data/registry/          # the agency census and verified source rows the generators read
research/               # the field research the statewide expansion was built from
frontend/               # React SPA (Vite + TypeScript + Tailwind)
frontend/src/screens/   # Dashboard, AllBids, Pipeline, Workroom, …
frontend/src/api/       # typed client + TanStack Query hooks
src/models/             # Opportunity + SourceHealth models
src/sources/            # per-platform adapters (+ DB-stored custom sources)
src/netpolicy.py        # crawl policy: identity, robots.txt, per-host rate limit, fetch log
src/robots.py           # RFC 9309 robots.txt (the stdlib parser drops rules after a blank line)
src/protest.py          # the 72-hour protest clock and the day-31 records sunset
src/records.py          # which tabulations are requestable, and the Chapter 119 letter
src/contracts.py        # incumbent contracts and when they expire
src/pipeline/fingerprint.py  # work out which platform an agency runs, from its own site
src/classify.py         # categories + offer type
src/requirements.py     # bid terms, pricing and deadlines from scope prose
src/pdf_extract.py      # commercial terms from the bid package PDF
src/pipeline/history.py # closed-solicitation archive + recurrence matching
src/auth.py             # optional vendor-session credentials (env only)
src/dates.py            # shared date parsing (Eastern wall clock)
src/http_util.py        # session, retries, blocked-portal detection
src/summarize.py        # rule-based deal briefs (no-key fallback)
src/ai/summarizer.py    # Claude-powered deal briefs with caching
src/pipeline/           # concurrent fetch, dedupe, store
src/db/                 # SQLAlchemy models + store (Postgres or SQLite)
src/cli.py              # Typer CLI
web/server.py           # FastAPI app: JSON API + SPA hosting (deploy entrypoint)
web/api/                # REST routers (bids, watchlists, sources, fetch, …)
web/services/           # background fetch job, scheduler, matching, digest
web/sample_data.py      # demo snapshot for exploring the screens offline
tests/                  # offline test suite + portal fixtures
data/                   # SQLite DB (local) + CSV/JSON snapshots from the CLI
```

## Always verify on the official portal

Due dates, addenda, and bid packages can change. Confirm on the agency site before submitting.

## Counties, when the source is statewide

A growing share of the sources are statewide by nature — MyFloridaMarketPlace,
FACTS, SAM.gov, and both FDOT advertisement feeds. Their `county` is
`statewide`, which is honest: an FDOT District 4 job spans six counties and a
state term contract spans all of them.

Matched on the county field alone, a Broward watchlist silently drops every one
of them. Measured against a live sample of 307 bids, a tri-county rule kept 24
and discarded 241 — **including all 24 FDOT District 4 advertisements, which
are Broward and Palm Beach road work.** The user's own county filter was hiding
work in their own county.

So a statewide bid matches a county rule when it *names* one of those counties,
either in the keywords its adapter stamped on it (FDOT writes its district's
counties there for exactly this) or in its own text — "SR736/Davie Blvd Bridge"
resolves to Broward off the title alone, whichever district filed it. On that
sample the rule recovers 147 of the 241, and the tri-county watchlist goes from
24 matches to 72.

The remaining 94 are genuinely unlocated — a state contract performable
anywhere. They stay out unless a rule sets `include_statewide`, because four
times as much unlocated noise as located signal is not a filter.

## Planned work is kept apart

`upcoming` means an agency has said what it intends to advertise, not that it
has. FDOT publishes 124 of these at a time with projected deadlines into 2027,
and they are genuinely the earliest warning the scout gets — but they are not
biddable, and two things had to change before the digest could carry them
honestly:

- Every row carries a **PLANNED** tag, so a projected deadline never reads as a
  real one.
- They get their **own section**. Watchlist lists sort soonest-due-first, and a
  projection months out sorts last — so mixed in with open bids the planned ones
  fell off the ten-row cap every single day. Measured: 43 of 72 matches were
  planned and none of them appeared.

The subject line separates them too: *"29 new matches, 43 planned"* rather than
72 of something the reader would assume they could bid on.

## Crawl policy

Every request in the codebase goes through `src/netpolicy.py`, below the
adapters, because a guardrail an adapter can forget is not a guardrail.

- **We say who we are.** An honest User-Agent with a contact URL, overridable
  with `SF_SCOUT_CONTACT`. Checked before it was adopted: OpenGov, Bonfire,
  MFMP and CivicPlus return byte-identical responses to the honest string, so
  the browser string is a per-host exception list containing exactly one
  Akamai-fronted site.
- **We honor robots.txt**, including `Crawl-delay`, cached an hour per host.
  A missing or unreadable file means unrestricted, which is what the standard
  says and what most of Florida serves. `dms.myflorida.com` is refused
  outright — the data is on VIP, which serves no robots.txt at all.
  Parsed by `src/robots.py` against **RFC 9309**, not by
  `urllib.robotparser`, which implements the 1996 draft and ends a group at a
  blank line. A file that puts a comment banner between `User-agent: *` and its
  rules — an ordinary way to write one — reads under the stdlib as a group with
  *no rules*, so every `Disallow` in it disappears and the crawler concludes it
  may fetch anything. The log still says `present`, so nothing looks wrong.
  BidNet Direct serves exactly that shape.
- **We rate-limit per host**, one request per second unless robots asks for
  longer, held across threads. Per *host* matters: 91 OpenGov tenants and 32
  Bonfire tenants each share one server.
- **We log every fetch** — URL, time, status, and what robots said at the time
  — when `SF_SCOUT_FETCH_LOG` is set.
- **We never create an account to harvest.** Where a portal's detail pages need
  a login, the adapter reports list-only rather than pretending.
- **A bot challenge is a refusal, not backpressure.** Cloudflare's "Just a
  moment" interstitial arrives with status 429, which reads as "slow down" and
  is not: it counts requests per session, so waiting does not clear it and
  retrying spends another. `http_util` raises `SourceBlocked` for it instead of
  retrying into it. Ionwave serves it from about the fourth request, and a
  *fresh* session is let straight through — so rotating sessions would walk
  past it, and that is deliberately not done.

Three judgement calls are written down rather than hidden. Bonfire serves
`Disallow: /` across every tenant, and obeying it strictly costs 32 Florida
agencies including Broward and Hillsborough; Ionwave — same vendor, Euna —
serves the same file, for four more; Jaggaer's `bids.sciquest.com` serves it
for three state universities. All three exceptions live in one table,
`ROBOTS_OVERRIDES`, with their reasoning stated out loud, and
`SF_SCOUT_STRICT_ROBOTS=1` drops it. See `docs/statewide-coverage.md` for the
per-host policy table.

## The two clocks

Florida law puts a deadline on two events, and both are in the daily digest.

```bash
python -m src.cli contracts --refresh    # incumbent registers, own cadence
python -m src.cli contracts --days 120   # who is about to run out
```

- **72 hours.** A notice of protest is due within 72 hours of an intended
  decision posting, excluding weekends and state holidays (s. 120.57(3)(b)).
  Those notices arrive as `award` status — deliberately not `open`, so they
  never reach a board of things to bid on — and the digest leads with the ones
  whose window is still open, soonest first.
- **Day 31.** Sealed bids stop being exempt 30 days after opening when no
  award has posted (s. 119.071(1)(b)2). The digest reports what crossed that
  line today, and `src/records.py` writes the request — phrased as a copy of an
  existing record in the medium the agency keeps it in, never as a compilation,
  which is the difference between a free copy and a special service charge.
