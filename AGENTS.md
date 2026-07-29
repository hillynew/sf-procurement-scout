# AGENTS.md

Instructions for an AI agent asked to deploy, redeploy, or operate this app on
**Render**. If you're a coding agent (Claude Code, Cursor, Copilot, Codex,
Devin, etc.) handed a task like "deploy this" or "why is the Render service
unhealthy," this file is for you.

## Project at a glance

- A Streamlit dashboard (`web/app.py`) and a Typer CLI (`run.py`) over one
  Python codebase — no separate backend, no database.
- State is files, not a DB: snapshots in `data/latest.json` / `data/latest.csv`,
  a recurrence archive in `data/history.json`, and a PDF text cache in
  `data/pdf_cache/`. All of it is **ephemeral on Render's free tier** — see
  "Keeping data fresh" below before assuming something is broken.
- Source config lives in `config/sources.yaml`; adapters live in
  `src/sources/`. Nothing here needs to change to deploy or operate the app.

## Deploying (Blueprint — the supported path)

1. Confirm `render.yaml` is present and its `buildCommand` / `startCommand` /
   `healthCheckPath` haven't been locally edited away from what's committed.
2. Render Dashboard → **New** → **Blueprint** → connect this repo → **Apply**.
   Render provisions one web service straight from `render.yaml`:
   - Build: `pip install -r requirements.txt`
   - Start: `streamlit run web/app.py --server.port $PORT --server.address 0.0.0.0 --server.headless true`
   - Health check: `/_stcore/health`
3. First boot shows an **empty dashboard** — "No opportunities loaded." That is
   the correct first-run state, not a failed deploy. Open the service URL and
   click **Fetch live data**, or see "Keeping data fresh" for a headless way
   to do this.

Manual (non-Blueprint) setup and its equivalent settings are in
[`README.md`](README.md#deploy-on-render) if Blueprint isn't available.

## Environment variables

Already declared in `render.yaml` — no action needed on a normal deploy:

| Variable | Value |
|---|---|
| `PYTHON_VERSION` | `3.11.11` |
| `STREAMLIT_BROWSER_GATHER_USAGE_STATS` | `false` |
| `STREAMLIT_SERVER_HEADLESS` | `true` |

Optional — three integrations are inert until these are set, and the app is
fully supported with none of them set (sources report `empty`/`inactive`, not
`error`). They're declared in `render.yaml` with `sync: false`, which means
Render will prompt for a value in its dashboard **without ever storing it in
git**. Set real values only in Render's **Environment** tab for the service —
never in a committed file:

| Variable | Enables | Notes |
|---|---|---|
| `SF_SCOUT_IMAP_HOST` / `_USER` / `_PASSWORD` | Email bid alerts | Use an app-specific password; the mailbox is opened read-only |
| `SF_SCOUT_IMAP_FOLDER` / `_DAYS` | (tuning, optional) | Default `INBOX` / `30` days lookback |
| `SF_SCOUT_BONFIRE_COOKIE` (or `_<HOST>` variant, e.g. `_BROWARD`) | Authenticated Bonfire session (invited/followed opportunities) | A browser session cookie — it expires; `run.py auth-status` shows what's configured, never the value |

Full details: [`README.md`](README.md#bid-alerts-by-email) and
[`README.md`](README.md#authenticated-bonfire-sessions).

## Keeping data fresh (the ephemeral-disk gotcha)

Render's free-tier disk does **not** persist across deploys or restarts —
`data/latest.json`, `data/history.json`, and `data/pdf_cache/` are all wiped.
Two ways to repopulate:

- **Manual**: open the app, click **Fetch live data**.
- **Automated** (recommended for anything beyond a demo): add a second
  service of `type: cron` to `render.yaml`. This is *not* auto-applied here —
  add it yourself if you want scheduled refreshes, since it provisions
  additional compute:

  ```yaml
    - type: cron
      name: sf-procurement-scout-fetch
      runtime: python
      schedule: "0 */4 * * *"   # every 4 hours
      buildCommand: pip install -r requirements.txt
      startCommand: python run.py fetch --no-briefs

    - type: cron
      name: sf-procurement-scout-history
      runtime: python
      schedule: "0 3 * * 0"     # weekly, Sunday 03:00 UTC
      buildCommand: pip install -r requirements.txt
      startCommand: python run.py history
  ```

  Both write into `data/`, which the cron service and the web service do
  **not** share on the free tier (separate ephemeral disks) — a cron job
  alone won't populate the web dashboard. Use a paid plan with a
  [persistent disk](https://render.com/docs/disks) mounted at `/opt/render/project/src/data`
  and shared appropriately, or keep the manual **Fetch live data** button as
  the source of truth, if you're not ready to take on that complexity.

## Verifying a deploy

```bash
curl -sS https://<service>.onrender.com/_stcore/health
# expect: ok
```

A dashboard that loads but says "No opportunities loaded" is healthy — that's
the pre-fetch state, not an error.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Build fails on `lxml` | rare on Render's prebuilt Python images | check the build log for a missing system library; this project has no non-Python dependencies otherwise |
| Service marked unhealthy | `--server.address` isn't `0.0.0.0`, or `$PORT` isn't wired through | `render.yaml`'s `startCommand` already does both correctly — check for local edits before anything else |
| ~30–60s cold start | Render free-tier sleep after idle | expected, not a bug |
| Email alerts always show `inactive` | `SF_SCOUT_IMAP_*` unset in Render's Environment tab | set them there; a local `.env` is never deployed |
| No `invited`/`personalized` Bonfire listings | `SF_SCOUT_BONFIRE_COOKIE` unset or the session expired | re-extract from a signed-in browser tab, update the value in Environment; run `python run.py auth-status` to confirm it's picked up |
| Need to check a diagnostic without a full fetch | — | `python run.py check-mailbox`, `python run.py auth-status`, `python run.py health` all exist for this; run via Render's **Shell** tab |

## What not to do

- Never commit a real IMAP password or Bonfire cookie to `render.yaml` or any
  tracked file — both are `sync: false` in `render.yaml` specifically so
  Render prompts for them without the value ever reaching git.
- Don't change `--server.address` away from `0.0.0.0` or drop the
  `healthCheckPath` — Render requires binding all interfaces, and the health
  check is how Render knows the service is alive.
- Don't treat an empty dashboard or a `data/` wipe after restart as a bug —
  both are expected on the free tier; see "Keeping data fresh."
- Don't add the cron services above without understanding they run on
  separate ephemeral disks from the web service (see the note under
  "Automated") — they will not, by themselves, keep the dashboard populated
  on the free tier.
