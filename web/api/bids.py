"""Bid workflow mutations — the JSON replacements for the old ?act= links."""

from __future__ import annotations

from datetime import date
from typing import Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.db import store as db
from web.services.serialize import opp_out

router = APIRouter()


def _bid_or_404(opportunity_id: str):
    opp = db.get_opportunity(opportunity_id)
    if opp is None:
        raise HTTPException(status_code=404, detail="unknown opportunity")
    return opp


def _out(opportunity_id: str) -> dict:
    opp = _bid_or_404(opportunity_id)
    return opp_out(opp, db.workflow_state(), db.summarized_ids())


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
    summary = db.latest_summary(opportunity_id)
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
