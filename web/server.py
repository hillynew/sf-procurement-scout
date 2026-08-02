"""SF Procurement Scout web server — FastAPI + uvicorn.

One route renders the whole Scout Classic app (screens picked by ?screen=…);
action links and forms hit the same route with ?act=… and are answered with a
303 redirect to the clean view URL, so refreshes never replay an action.
User workflow state persists via src/pipeline/user_state; fetch snapshots are
cached in-process and invalidated by data/latest.json's mtime.

Run: uvicorn web.server:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import sys
import threading
import time
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

from src.pipeline import user_state as us
from src.pipeline.runner import run_fetch
from src.pipeline.store import data_dir, load_latest, save_snapshot
from src.sources.registry import load_source_config
from web.views import CHIP_DEFS, Page, SCREENS, ViewParams, href

app = FastAPI(title="SF Procurement Scout", docs_url=None, redoc_url=None)

_STYLES = Path(__file__).parent / "styles.css"

# One user, one state file — serialize mutations.
_state_lock = threading.Lock()

# Post-redirect flashes (fetch finished / detect result). In-memory is fine:
# single-user app, and losing one across a restart only loses a banner.
_flash: dict = {}


def _snapshot_mtime() -> int:
    try:
        return (data_dir() / "latest.json").stat().st_mtime_ns
    except OSError:
        return 0


@lru_cache(maxsize=2)
def _load_snapshot(mtime_ns: int):
    return load_latest()


def _snapshot_time(mtime_ns: int):
    return datetime.fromtimestamp(mtime_ns / 1e9) if mtime_ns else None


@lru_cache(maxsize=1)
def _configured_sources() -> int:
    try:
        return len(load_source_config())
    except Exception:
        return 0


def _view_url(p: ViewParams) -> str:
    return href(
        screen=p.screen,
        drawer=p.drawer,
        bid=p.bid,
        scope="1" if p.scope_open else None,
        allsrc="1" if p.all_sources else None,
        q=p.query,
        f=p.status,
    )


def _parse_params(request: Request) -> ViewParams:
    q = request.query_params
    return ViewParams(
        screen=q.get("screen", "today"),
        drawer=q.get("drawer") or None,
        bid=q.get("bid") or None,
        scope_open=q.get("scope") == "1",
        all_sources=q.get("allsrc") == "1",
        query=q.get("q", ""),
        status=q.get("f", ""),
    )


def _apply_action(act: str, request: Request, state: dict, p: ViewParams) -> None:
    q = request.query_params
    arg = q.get("id") or ""
    if act == "fetch":
        opps, health = run_fetch(include_catalog=False, open_only=False, quiet=True)
        save_snapshot(opps, health, tag="dashboard")
        _load_snapshot.cache_clear()
        _flash["fetched"] = {"count": len(health), "ts": time.time()}
    elif act == "demo":
        from web.sample_data import load_sample

        load_sample(state)
        _load_snapshot.cache_clear()
    elif act == "track" and arg:
        us.toggle_tracked(state, arg)
    elif act == "skip" and arg:
        us.skip(state, arg)
    elif act == "undoskips":
        us.undo_skips(state)
    elif act == "check" and arg:
        try:
            us.toggle_check(state, arg, int(q.get("i", "-1")))
        except ValueError:
            pass
    elif act in ("go", "nogo") and arg:
        us.set_decision(state, arg, act)
    elif act == "cleardec" and arg:
        us.set_decision(state, arg, None)
    elif act == "stage" and arg:
        to = q.get("to", "")
        if to in ("prev", "next"):
            us.move_stage(state, arg, -1 if to == "prev" else 1)
        elif to in us.STAGES:
            us.set_stage(state, arg, to)
    elif act == "result" and arg:
        outcome = q.get("val", "").upper()
        if outcome in ("WON", "LOST"):
            us.set_result(state, arg, outcome)
    elif act == "notes" and arg:
        state["notes"][arg] = q.get("notes", "").strip()
    elif act == "selwl" and q.get("wl"):
        us.open_watchlist(state, q.get("wl"), datetime.now().isoformat(timespec="seconds"))
    elif act == "chip" and arg:
        state["builder_chips"][arg] = not state["builder_chips"].get(arg, False)
    elif act == "savewl":
        chips = {k: v for k, v in state["builder_chips"].items() if v}
        labels = [label for key, label in CHIP_DEFS if key in chips]
        n = len(state["watchlists"]) + 1
        wl = {
            "id": f"wl-{n}-{'-'.join(sorted(chips)) or 'all'}",
            "name": " · ".join(labels) if labels else f"Watchlist {n}",
            "filters": {"chips": sorted(chips)},
            "email": "off",
            "last_opened": None,
            "prev_opened": None,
        }
        if not any(w["id"] == wl["id"] for w in state["watchlists"]):
            state["watchlists"].append(wl)
        state["selected_watchlist"] = wl["id"]
    elif act == "addsrc" and q.get("name"):
        name = q.get("name")
        if not any(s.get("name") == name for s in state["queued_sources"]):
            state["queued_sources"].append({"name": name, "url": "", "detected": "suggested"})
    elif act == "detect":
        url = (q.get("url") or "").strip()
        lowered = url.lower()
        if "civicplus" in lowered or "bids.aspx" in lowered:
            host = urlparse(url).netloc or url
            if not any(s.get("url") == url for s in state["queued_sources"]):
                state["queued_sources"].append(
                    {"name": host, "url": url, "detected": "civicplus"}
                )
            _flash["detect"] = {"status": "ok", "url": url, "ts": time.time()}
        else:
            _flash["detect"] = {"status": "fail", "url": url, "ts": time.time()}


def _consume_flash(p: ViewParams) -> None:
    """Show one-shot action outcomes on the first render after the redirect."""
    fetched = _flash.get("fetched")
    if fetched and time.time() - fetched["ts"] < 10:
        p.fetched_now = True
        p.fetch_count = fetched["count"]
    detect = _flash.get("detect")
    if detect and time.time() - detect["ts"] < 10 and p.screen == "sources":
        p.detect_status = detect["status"]
        p.detect_url = detect["url"]


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


@app.get("/styles.css")
def styles():
    return FileResponse(_STYLES, media_type="text/css")


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    p = _parse_params(request)
    if p.screen not in dict(SCREENS):
        p.screen = "today"
    act = request.query_params.get("act")

    with _state_lock:
        state = us.load_user_state()

        # Roll the "new since last visit" baseline once per calendar day.
        today_iso = date.today().isoformat()
        if state.get("today_visit_date") != today_iso:
            state["last_today_visit"] = state.get("today_visit_date")
            state["today_visit_date"] = today_iso
            us.save_user_state(state)

        if act:
            _apply_action(act, request, state, p)
            us.save_user_state(state)
            return RedirectResponse(_view_url(p), status_code=303)

    _consume_flash(p)
    mtime = _snapshot_mtime()
    opps, health = _load_snapshot(mtime)
    page = Page(
        opps=opps,
        health=health,
        state=state,
        p=p,
        total_sources=_configured_sources(),
        snapshot_time=_snapshot_time(mtime),
    )
    return HTMLResponse(page.render())
