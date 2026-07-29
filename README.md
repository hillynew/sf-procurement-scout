# SF Procurement Scout

Live aggregator for government procurement opportunities across **Miami-Dade**, **Broward**, and **Palm Beach** counties.

**GitHub:** [hillynew/sf-procurement-scout](https://github.com/hillynew/sf-procurement-scout)

## Features

| | |
|--|--|
| **A. Capture** | Live titles, refs, due dates, and links from public county/city portals |
| **B. Organize** | County, agency, solicitation type, goods/services/construction, topic categories |
| **C. Deal briefs** | One-paragraph summary with urgency and link for scanning |
| **D. Dedupe** | One record per solicitation, even when portals overlap or repeat announcements |
| **E. Detail** | Scope of work, pricing, bid requirements, documents and contacts, read from each bid's own page |
| **F. Source health** | Every portal reports `ok` / `no listings` / `degraded` / `error` so silent breakage is visible |

Sources are fetched concurrently, so a full refresh takes a few seconds rather
than a minute.

## What is captured per opportunity

List pages carry little more than a title and a date, so a second pass reads
each open bid's own page. That is where the fields a contractor actually
decides on live:

| Field | Source |
|-------|--------|
| **Scope of work** | Full narrative from the detail page — often several thousand words |
| **Estimated value** | Dollar figures qualified by "not to exceed", "budget of", "estimated at"; a bare figure is only used above $25k so a plan fee is never mistaken for the contract |
| **Requirements to bid** | Bid/performance/payment bonds, insurance, licensing, prequalification, mandatory pre-bid meetings and site visits, E-Verify, SBE/MBE/DBE goals, local preference, prevailing wage, and more |
| **Documents** | Every bid package file, with addenda tagged separately so changes stand out |
| **Key dates** | Bid deadline, question deadline, pre-bid meeting, publication date |
| **Contacts** | Buyer name, email and phone |
| **Submittal information** | Where and how a response must be delivered |

Each record carries a **detail score** (0–100) summarising how much is known,
shown as a meter in the UI so a fully-specified bid is visibly more actionable
than a bare listing.

The detail pass is bounded — it runs only for `open` and `upcoming` listings,
soonest-due first, capped at 150 requests per refresh. Portals that expose no
detail page (or block it) still get requirements and pricing mined from the
blurb they do publish. Disable it with `run_fetch(with_details=False)`.

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

### Option A — Blueprint (recommended)

1. Push this repo to GitHub (already at `hillynew/sf-procurement-scout`).
2. Open [Render Dashboard](https://dashboard.render.com/) → **New** → **Blueprint**.
3. Connect the `sf-procurement-scout` repo.
4. Render reads `render.yaml` and creates the web service.
5. After deploy, open the service URL and click **Fetch live data now**.

### Option B — Manual Web Service

1. **New** → **Web Service** → connect `hillynew/sf-procurement-scout`.
2. Settings:

| Setting | Value |
|---------|--------|
| Runtime | Python 3 |
| Build command | `pip install -r requirements.txt` |
| Start command | `streamlit run web/app.py --server.port $PORT --server.address 0.0.0.0 --server.headless true` |
| Health check path | `/_stcore/health` |

3. Env vars (optional):

```
PYTHON_VERSION=3.11.11
STREAMLIT_BROWSER_GATHER_USAGE_STATS=false
```

### Notes for free tier

- Service sleeps after idle; first request may take ~30–60s to wake.
- Disk is ephemeral — re-click **Fetch live data now** after restarts.
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
python run.py list-sources

# Web UI
python run.py dashboard
# or: streamlit run web/app.py
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
render.yaml             # Render Blueprint
Procfile                # alternate start command
runtime.txt             # Python version hint
.streamlit/config.toml  # Streamlit production config
config/sources.yaml     # portal registry
src/models/             # Opportunity + SourceHealth models
src/sources/            # per-portal adapters
src/classify.py         # categories + offer type
src/requirements.py     # bid terms, pricing and deadlines from scope prose
src/dates.py            # shared date parsing (Eastern wall clock)
src/http_util.py        # session, retries, blocked-portal detection
src/summarize.py        # deal briefs
src/pipeline/           # concurrent fetch, dedupe, store
src/cli.py              # Typer CLI
web/app.py              # Streamlit UI (Render entrypoint)
tests/                  # offline test suite + portal fixtures
data/                   # latest.json / latest.csv snapshots (last 10 kept)
```

## Always verify on the official portal

Due dates, addenda, and bid packages can change. Confirm on the agency site before submitting.
