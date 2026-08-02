# SF Procurement Scout

Live aggregator for government procurement opportunities across **Miami-Dade**, **Broward**, and **Palm Beach** counties.

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
| **Calendar** | Month grid of bids on their due dates with county dots and values; an agenda list on mobile |
| **Pipeline** | Drag-and-drop kanban (Watching → Preparing → Submitted → Result) with per-column dollar totals, a win/loss dialog that records real amounts, and an archive |
| **Workroom** | Deep read of one bid: AI deal brief, scope, requirements checklist, documents, key dates, commercial terms, go/no-go, autosaving notes |
| **Watchlists** | Real rule builder (keywords, counties, types, value range, no-bond, recurring) with live match preview, rename/delete, and genuinely-correct NEW badges |
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

Coverage is limited to agencies whose portal exposes an archive — currently the
Bonfire ones (Broward County, Town of Palm Beach, FAU, Tri-Rail), about 945
past solicitations.

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

| Source | Method |
|--------|--------|
| Broward County BPRO | Bonfire public API |
| Town of Palm Beach | Bonfire public API |
| Miami-Dade INFORMS | Public bidding events HTML |
| Miami-Dade construction / future | ISD DataTables JSON endpoints |
| City of West Palm Beach | City page / DemandStar fallback |
| Miami Dade College | Bid posting page (announcements grouped per solicitation) |
| Palm Beach Schools construction | District tables |
| Florida Atlantic University | Bonfire public API |
| Tri-Rail / SFRTA | Bonfire public API |
| City of Plantation | Bonfire public API |
| City of Coral Gables | Public-notice link list |
| **27 city bid boards + SWA** | CivicPlus Bids module (one shared adapter) |

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
config/sources.yaml     # portal registry
frontend/               # React SPA (Vite + TypeScript + Tailwind)
frontend/src/screens/   # Dashboard, AllBids, Calendar, Pipeline, Workroom, …
frontend/src/api/       # typed client + TanStack Query hooks
src/models/             # Opportunity + SourceHealth models
src/sources/            # per-portal adapters (+ DB-stored custom sources)
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
