"""Bid workflow mutations — the JSON replacements for the old ?act= links."""

from __future__ import annotations

import asyncio
from datetime import date
from typing import Dict, Optional, Set

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.ai.summarizer import PROMPT_VERSION
from src.db import store as db
from web.services.serialize import opp_out

router = APIRouter()

# Deep dives run for a minute or more (multiple PDF downloads + a long
# Claude call), so they run as background tasks and the UI polls. In-memory
# is fine: one process, and a lost "running" flag on restart just means the
# user re-runs.
_deep_running: Set[str] = set()
_deep_errors: Dict[str, str] = {}


def _bid_or_404(opportunity_id: str):
    opp = db.get_opportunity(opportunity_id)
    if opp is None:
        raise HTTPException(status_code=404, detail="unknown opportunity")
    return opp


def _out(opportunity_id: str) -> dict:
    opp = _bid_or_404(opportunity_id)
    return opp_out(opp, db.workflow_state(), db.summarized_ids(PROMPT_VERSION))


@router.post("/bids/{opportunity_id}/track")
def track(opportunity_id: str):
    _bid_or_404(opportunity_id)
    db.set_tracked(opportunity_id, True)
    return _out(opportunity_id)


@router.delete("/bids/{opportunity_id}/track")
def untrack(opportunity_id: str):
    db.set_tracked(opportunity_id, False)
    return _out(opportunity_id)


class StageBody(BaseModel):
    stage: str


@router.put("/bids/{opportunity_id}/stage")
def set_stage(opportunity_id: str, body: StageBody):
    try:
        updated = db.update_tracked(opportunity_id, stage=body.stage)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if updated is None:
        raise HTTPException(status_code=404, detail="bid is not tracked")
    return _out(opportunity_id)


class DecisionBody(BaseModel):
    decision: Optional[str] = None  # go | nogo | null clears


@router.put("/bids/{opportunity_id}/decision")
def set_decision(opportunity_id: str, body: DecisionBody):
    try:
        updated = db.update_tracked(opportunity_id, decision=body.decision)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if updated is None:
        raise HTTPException(status_code=404, detail="bid is not tracked")
    return _out(opportunity_id)


class ChecksBody(BaseModel):
    index: int
    checked: bool


@router.put("/bids/{opportunity_id}/checks")
def set_check(opportunity_id: str, body: ChecksBody):
    workflow = db.workflow_state().get(opportunity_id)
    if workflow is None:
        raise HTTPException(status_code=404, detail="bid is not tracked")
    checks: Dict[str, bool] = dict(workflow["checks"] or {})
    checks[str(body.index)] = body.checked
    db.update_tracked(opportunity_id, checks=checks)
    return _out(opportunity_id)


class NotesBody(BaseModel):
    text: str


@router.put("/bids/{opportunity_id}/notes")
def set_notes(opportunity_id: str, body: NotesBody):
    updated = db.update_tracked(opportunity_id, notes=body.text.strip())
    if updated is None:
        raise HTTPException(status_code=404, detail="bid is not tracked")
    return _out(opportunity_id)


class ResultBody(BaseModel):
    outcome: str  # won | lost
    amount_cents: Optional[int] = None
    notes: str = ""
    decided_on: Optional[date] = None


@router.put("/bids/{opportunity_id}/result")
def set_result(opportunity_id: str, body: ResultBody):
    try:
        db.set_result(opportunity_id, body.outcome, amount_cents=body.amount_cents,
                      notes=body.notes, decided_on=body.decided_on)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except KeyError:
        raise HTTPException(status_code=404, detail="bid is not tracked")
    return _out(opportunity_id)


@router.post("/bids/{opportunity_id}/archive")
def archive(opportunity_id: str):
    updated = db.update_tracked(opportunity_id, archived=True)
    if updated is None:
        raise HTTPException(status_code=404, detail="bid is not tracked")
    return _out(opportunity_id)


@router.delete("/bids/{opportunity_id}/archive")
def unarchive(opportunity_id: str):
    updated = db.update_tracked(opportunity_id, archived=False)
    if updated is None:
        raise HTTPException(status_code=404, detail="bid is not tracked")
    return _out(opportunity_id)


@router.get("/bids/{opportunity_id}/summary")
def get_summary(opportunity_id: str):
    summary = db.latest_summary(opportunity_id, PROMPT_VERSION)
    if summary is None:
        raise HTTPException(status_code=404, detail="no summary yet")
    return summary


@router.post("/bids/{opportunity_id}/summarize")
def summarize(opportunity_id: str, force: bool = False):
    from src.ai import summarizer

    opp = _bid_or_404(opportunity_id)
    if not summarizer.enabled():
        raise HTTPException(
            status_code=503,
            detail={"reason": "no_api_key",
                    "message": "Set SF_SCOUT_ANTHROPIC_KEY to enable AI briefs."},
        )
    settings = db.get_settings()
    try:
        result = summarizer.summarize(opp, model=settings["ai"].get("model"),
                                      force=force)
    except Exception as exc:  # noqa: BLE001 — surface API failures as 502
        raise HTTPException(status_code=502, detail=f"summarizer failed: {exc}")
    return result


def ensure_detail(opp) -> bool:
    """Fetch this bid's own page if the capped detail pass never reached it.

    Documents only exist after a detail fetch, and that pass is bounded — so on
    a statewide run plenty of bids keep `detail_fetched = False`. A deep dive on
    one of those reads the listing alone and concludes the package must be
    fetched by hand, which is wrong whenever the portal serves it freely.

    Clicking Go Deep on a specific bid is exactly the moment that one request is
    worth making. Failure is not fatal: the dive still runs on the listing, the
    same as before.
    """
    if getattr(opp, "detail_fetched", False):
        return False
    try:
        from src.sources.registry import get_adapters

        adapter = next(
            (a for a in get_adapters() if a.source_id == opp.source_id and a.supports_detail),
            None,
        )
        if adapter is None:
            return False
        adapter.fetch_detail(opp)
    except Exception:  # noqa: BLE001 — an un-enriched dive beats no dive
        return False
    if getattr(opp, "detail_fetched", False):
        db.save_opportunity(opp)  # so the bid page shows the documents too
        return True
    return False


def _deep_dive_worker(opportunity_id: str, opp, model, force: bool) -> None:
    from src.ai.deep_dive import run_deep_dive

    try:
        ensure_detail(opp)
        run_deep_dive(opp, model=model, force=force)
    except Exception as exc:  # noqa: BLE001 — reported through GET, not logs
        _deep_errors[opportunity_id] = str(exc)
    finally:
        _deep_running.discard(opportunity_id)


@router.post("/bids/{opportunity_id}/deep-dive", status_code=202)
async def start_deep_dive(opportunity_id: str, force: bool = False):
    from src.ai import summarizer

    opp = _bid_or_404(opportunity_id)
    if not summarizer.enabled():
        raise HTTPException(
            status_code=503,
            detail={"reason": "no_api_key",
                    "message": "Set SF_SCOUT_ANTHROPIC_KEY to enable Go Deep."},
        )
    if opportunity_id in _deep_running:
        raise HTTPException(status_code=409, detail="deep dive already running")

    settings = db.get_settings()
    _deep_running.add(opportunity_id)
    _deep_errors.pop(opportunity_id, None)
    asyncio.get_running_loop().create_task(
        asyncio.to_thread(_deep_dive_worker, opportunity_id, opp,
                          settings["ai"].get("model"), force)
    )
    return {"state": "running"}


@router.get("/bids/{opportunity_id}/deep-dive")
def get_deep_dive(opportunity_id: str):
    from src.ai.deep_dive import DEEP_PROMPT_VERSION

    _bid_or_404(opportunity_id)
    if opportunity_id in _deep_running:
        return {"state": "running"}
    envelope = db.get_deep_dive(opportunity_id, DEEP_PROMPT_VERSION)
    error = _deep_errors.get(opportunity_id)
    if error:
        # Keep any older successful report visible under the error banner.
        return {"state": "error", "error": error} | (envelope or {})
    if envelope is None:
        return {"state": "none"}
    return {"state": "done"} | envelope
