# SF Procurement Scout

Live aggregator for government procurement opportunities across **Miami-Dade**, **Broward**, and **Palm Beach** counties.

**GitHub:** [hillynew/sf-procurement-scout](https://github.com/hillynew/sf-procurement-scout)

## Features

| | |
|--|--|
| **A. Capture** | Live titles, refs, due dates, and links from public county/city portals |
| **B. Organize** | County, agency, solicitation type, goods/services/construction, topic categories |
| **C. Deal briefs** | One-paragraph summary with urgency and link for scanning |

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
python run.py list-sources

# Web UI
python run.py dashboard
# or: streamlit run web/app.py
```

## Live sources

| Source | Method |
|--------|--------|
| Broward County BPRO | Bonfire public API |
| Town of Palm Beach | Bonfire public API |
| Miami-Dade INFORMS | Public bidding events HTML |
| Miami-Dade construction / future | ISD pages |
| City of West Palm Beach | City page / DemandStar fallback |
| Miami Dade College | Bid posting page |
| Palm Beach Schools construction | District tables |
| SWA Palm Beach County | Bid board |

**Catalog (register to bid):** City of Miami Bidnet, M-DCPS DemandStar, Broward Schools, Broward Health, Fort Lauderdale, Palm Beach County VSS, PBC Facilities.

## Project layout

```
render.yaml             # Render Blueprint
Procfile                # alternate start command
runtime.txt             # Python version hint
.streamlit/config.toml  # Streamlit production config
config/sources.yaml     # portal registry
src/models/             # Opportunity model
src/sources/            # per-portal adapters
src/classify.py         # categories + offer type
src/summarize.py        # deal briefs
src/pipeline/           # fetch + store
src/cli.py              # Typer CLI
web/app.py              # Streamlit UI (Render entrypoint)
data/                   # latest.json / latest.csv snapshots
```

## Always verify on the official portal

Due dates, addenda, and bid packages can change. Confirm on the agency site before submitting.
