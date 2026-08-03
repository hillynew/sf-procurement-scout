# AGENTS.md

Instructions for an AI agent asked to deploy, redeploy, or operate this app on
**Render**. If you're a coding agent (Claude Code, Cursor, Copilot, Codex,
Devin, etc.) handed a task like "deploy this" or "why is the Render service
unhealthy," this file is for you.

## Project at a glance

- A React SPA (`frontend/`, built by Vite) served by a FastAPI JSON API
  (`web/server.py` + routers in `web/api/`), plus a Typer CLI (`run.py`) —
  one Python codebase, one Docker image (multi-stage: node builds the
  bundle, python serves it).
- **State is a database.** `DATABASE_URL` (Render Postgres, provisioned by
  `render.yaml`) or, when unset, SQLite at `data/scout.db`. Snapshots,
  tracked bids, notes, win/loss results, watchlists, notifications,
  settings, AI-summary cache, and custom sources all live there and survive
  restarts/deploys. The old files-only model (`data/latest.json`,
  `data/user_state.json`) is gone; the CLI still writes CSV/JSON snapshots
  for convenience and mirrors them into the DB.
- Fetches run **in the background** (`POST /api/fetch`, SSE progress on
  `/api/fetch/stream`) — the UI never blocks, and a proxy timeout on a slow
  scrape is no longer possible.
- Source config lives in `config/sources.yaml`; adapters in `src/sources/`;
  user-added CivicPlus portals are stored in the DB and merged in at runtime.
  Nothing here needs to change to deploy or operate the app.

## Deploying (Blueprint — the supported path)

1. Confirm `render.yaml` is present with its `databases:` block and the web
   service's `healthCheckPath` intact.
2. Render Dashboard → **New** → **Blueprint** → connect this repo → **Apply**.
   Render provisions:
   - **scout-db** — free Postgres, wired to the service as `DATABASE_URL`
   - **sf-procurement-scout** — Docker web service; the image builds the
     frontend in a node stage, then starts
     `uvicorn web.server:app --host 0.0.0.0 --port $PORT`
   - Health check: `/healthz` (returns `{"status": "ok", "db": "ok"}`)
3. First boot shows an **empty dashboard** with a "Load sample data" offer —
   that is the correct first-run state, not a failed deploy. Click **Fetch
   live data** (or `curl -X POST …/api/fetch`) to populate it.

Manual (non-Blueprint) setup: create the Postgres instance first, then the
web service with Docker runtime and `DATABASE_URL` set from the database's
connection string. Equivalent settings are in
[`README.md`](README.md#deploy-on-render).

## Environment variables

`DATABASE_URL` comes from the Blueprint automatically. Everything else is
optional — all integrations are inert until set, and the app is fully
supported with none of them (features show honest disabled states, not
errors). They're declared in `render.yaml` with `sync: false`, which means
Render prompts for a value in its dashboard **without ever storing it in
git**. Set real values only in Render's **Environment** tab — never in a
committed file:

| Variable | Enables | Notes |
|---|---|---|
| `SF_SCOUT_ANTHROPIC_KEY` (or `ANTHROPIC_API_KEY`) | AI deal briefs via the Claude API | Default model `claude-haiku-4-5` (~1¢ per 50 bids); switchable to `claude-sonnet-5` in Settings |
| `SF_SCOUT_SAM_KEY` (or `SAM_API_KEY`) | Federal bids via SAM.gov's public API | Free key from a sam.gov account; source is scoped to Florida place-of-performance |
| `RESEND_API_KEY` | Email digests (daily or instant) | Free tier at resend.com; recipient set in Settings or `SF_SCOUT_DIGEST_TO` |
| `SF_SCOUT_DIGEST_TO` / `SF_SCOUT_DIGEST_FROM` | Digest recipient / sender | Sender defaults to Resend's onboarding address |
| `SF_SCOUT_IMAP_HOST` / `_USER` / `_PASSWORD` | Email bid alerts | App-specific password; mailbox opened read-only |
| `SF_SCOUT_IMAP_FOLDER` / `_DAYS` | (tuning, optional) | Default `INBOX` / `30` days lookback |
| `SF_SCOUT_BONFIRE_COOKIE` (or `_<HOST>` variant) | Authenticated Bonfire session | A browser cookie — it expires; `run.py auth-status` shows what's configured |

## Keeping data fresh

Data now survives restarts (Postgres), so freshness is the only concern:

- **Manual**: the **Fetch live data** button — background job with live
  per-source progress.
- **In-app scheduler**: Settings → Auto-fetch → every N hours or
  refresh-on-open. Runs only while the service is awake; on the free tier a
  sleeping service doesn't tick.
- **Around the clock** (optional): any uptime pinger hitting the service URL
  keeps it awake, or add a Render cron that runs
  `curl -X POST https://<service>.onrender.com/api/fetch` on a schedule —
  since state is in Postgres, a cron-triggered fetch **does** populate the
  dashboard now (the old separate-ephemeral-disk caveat no longer applies).

## Verifying a deploy

```bash
curl -sS https://<service>.onrender.com/healthz
# expect: {"status":"ok","db":"ok"}
curl -sS https://<service>.onrender.com/api/opportunities | head -c 200
curl -sS -X POST https://<service>.onrender.com/api/fetch   # 202 = fetch started
```

A dashboard that loads but shows the welcome/empty state is healthy — that's
the pre-fetch state, not an error.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `/healthz` shows `"db": "error"` | `DATABASE_URL` missing or the Postgres instance is still provisioning | check the Environment tab; Blueprint deploys wire it automatically |
| Frontend shows "API is running — frontend not built" | the Docker build skipped the node stage (e.g. deployed with a non-Docker runtime) | use the Docker runtime; the committed Dockerfile builds `frontend/dist` |
| Build fails in the node stage | `frontend/package-lock.json` drift | run `cd frontend && npm install` locally and commit the lockfile |
| Service marked unhealthy | port not bound to `0.0.0.0` / `$PORT` | the image CMD already handles both — check for local edits first |
| ~30–60s cold start | Render free-tier sleep after idle | expected, not a bug |
| Fetch button errors with 409 | a fetch is already running | expected — wait for it; `GET /api/fetch/status` shows progress |
| AI briefs disabled in Settings | no Anthropic key set | set `SF_SCOUT_ANTHROPIC_KEY` in the Environment tab |
| Email digest disabled | `RESEND_API_KEY` unset | set it, then enable digests in Settings |
| Key set but no mail arrives | unverified sender, or the default `onboarding@resend.dev` sending anywhere but the Resend account owner's own address | Settings → Email digest → **Send test email** (or `python run.py test-email`) reports Resend's reason; verify a domain and set `SF_SCOUT_DIGEST_FROM` |
| Diagnostics without a full fetch | — | `python run.py health`, `auth-status`, `check-mailbox`, `test-email` via Render's **Shell** tab |

## What not to do

- Never commit a real API key, IMAP password, or Bonfire cookie to
  `render.yaml` or any tracked file — they're `sync: false` specifically so
  Render prompts for them without the value reaching git.
- Don't drop the `healthCheckPath` or bind to anything but `0.0.0.0` —
  Render requires both.
- Don't delete the `databases:` block from `render.yaml` — without
  `DATABASE_URL` the service falls back to SQLite on an **ephemeral** disk
  and user data stops surviving restarts.
- Don't treat the empty first-run dashboard as a bug — fetch or load the
  sample data.
