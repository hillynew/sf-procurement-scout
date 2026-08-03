"""SF Procurement Scout — FastAPI JSON API + SPA host.

The React app (built into ``frontend/dist``) is served for every non-API
path so history-mode routing survives a refresh; everything under ``/api``
is JSON. State lives in the database (Postgres on Render, SQLite locally),
so restarts lose nothing.

Run: uvicorn web.server:app --host 0.0.0.0 --port 8000
Dev: run the Vite dev server (frontend/) against this API on :8000.
"""

from __future__ import annotations

import asyncio
import sys
from contextlib import asynccontextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse

from src.db import store as db
from web.api import bids, fetch, misc, opportunities, sources, watchlists

DIST = ROOT / "frontend" / "dist"

NO_BUILD_PAGE = """<!doctype html><meta charset="utf-8">
<title>SF Procurement Scout</title>
<body style="font-family:system-ui;max-width:560px;margin:80px auto;color:#1B2437">
<h1 style="font-size:20px">API is running — frontend not built</h1>
<p>The React bundle is missing. Either:</p>
<ul>
<li>run <code>cd frontend && npm install && npm run build</code>, or</li>
<li>use the Vite dev server: <code>cd frontend && npm run dev</code></li>
</ul>
<p>The JSON API lives under <a href="/docs">/api</a>.</p></body>"""


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.bootstrap()
    # Briefs cached under an older prompt version have a different shape —
    # drop them so the UI regenerates instead of rendering something stale.
    from src.ai.summarizer import PROMPT_VERSION

    db.prune_summaries(PROMPT_VERSION)
    from web.services import scheduler

    task = asyncio.create_task(scheduler.loop())
    try:
        yield
    finally:
        task.cancel()


def create_app() -> FastAPI:
    app = FastAPI(title="SF Procurement Scout", lifespan=lifespan,
                  docs_url="/docs", redoc_url=None)

    @app.get("/healthz")
    def healthz():
        try:
            db.latest_run()
            db_ok = True
        except Exception:  # noqa: BLE001
            db_ok = False
        return {"status": "ok", "db": "ok" if db_ok else "error"}

    for router in (opportunities.router, bids.router, watchlists.router,
                   sources.router, fetch.router, misc.router):
        app.include_router(router, prefix="/api")

    # --- SPA hosting (after the API so /api always wins) --------------------

    if (DIST / "index.html").exists():
        from fastapi.staticfiles import StaticFiles

        app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith(("api/", "api")) and (path == "api" or path.startswith("api/")):
            raise HTTPException(status_code=404, detail="unknown API route")
        index = DIST / "index.html"
        if not index.exists():
            return HTMLResponse(NO_BUILD_PAGE, status_code=200)
        # Static files at the dist root (favicon, manifest) are served as-is;
        # every app route falls through to index.html for history-mode routing.
        candidate = (DIST / path).resolve()
        if path and candidate.is_file() and str(candidate).startswith(str(DIST.resolve())):
            return FileResponse(candidate)
        return FileResponse(index)

    return app


app = create_app()
