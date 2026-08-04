"""Contractor network — per-bid AI matching plus the growing directory.

Two surfaces share this router: ``/bids/{id}/contractors`` runs and serves
the AI match set for one bid (same background-job shape as the deep dive),
and ``/contractors`` is the network itself — every firm ever matched, with
its relationship status and the bids it was matched to, joined in Python.
"""

from __future__ import annotations

import asyncio
from typing import Dict, List, Optional, Set

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.db import store as db
from web.api.bids import _bid_or_404, ensure_detail

router = APIRouter()

# Matching runs web searches for up to a minute, so it runs as a background
# task and the UI polls — the same in-memory bookkeeping as the deep dive.
_match_running: Set[str] = set()
_match_errors: Dict[str, str] = {}


def _no_key_503() -> HTTPException:
    return HTTPException(
        status_code=503,
        detail={"reason": "no_api_key",
                "message": "Set SF_SCOUT_ANTHROPIC_KEY to enable contractor matching."},
    )


def _match_worker(opportunity_id: str, opp, model, force: bool) -> None:
    from src.ai.contractors import run_match

    try:
        ensure_detail(opp)
        run_match(opp, model=model, force=force)
    except Exception as exc:  # noqa: BLE001 — reported through GET, not logs
        _match_errors[opportunity_id] = str(exc)
    finally:
        _match_running.discard(opportunity_id)


@router.post("/bids/{opportunity_id}/contractors", status_code=202)
async def start_match(opportunity_id: str, force: bool = False):
    from src.ai import summarizer

    opp = _bid_or_404(opportunity_id)
    if not summarizer.enabled():
        raise _no_key_503()
    if opportunity_id in _match_running:
        raise HTTPException(status_code=409, detail="matching already running")

    settings = db.get_settings()
    _match_running.add(opportunity_id)
    _match_errors.pop(opportunity_id, None)
    asyncio.get_running_loop().create_task(
        asyncio.to_thread(_match_worker, opportunity_id, opp,
                          settings["ai"].get("model"), force)
    )
    return {"state": "running"}


def _with_relationship(envelope: dict) -> dict:
    """Fold each matched firm's network status into the match entries."""
    directory = {c["id"]: c for c in db.list_contractors()}
    matches = []
    for m in envelope.get("matches", []):
        firm = directory.get(m.get("contractor_id"))
        matches.append(m | {
            "contractor_status": firm["status"] if firm else "prospect",
        })
    return envelope | {"matches": matches}


@router.get("/bids/{opportunity_id}/contractors")
def get_matches(opportunity_id: str):
    from src.ai.contractors import MATCH_PROMPT_VERSION

    _bid_or_404(opportunity_id)
    if opportunity_id in _match_running:
        return {"state": "running"}
    envelope = db.get_contractor_matches(opportunity_id, MATCH_PROMPT_VERSION)
    error = _match_errors.get(opportunity_id)
    if error:
        # Keep any older successful match set visible under the error banner.
        return {"state": "error", "error": error} \
            | (_with_relationship(envelope) if envelope else {})
    if envelope is None:
        return {"state": "none"}
    return {"state": "done"} | _with_relationship(envelope)


class MatchStatusBody(BaseModel):
    status: str  # suggested | pitched | interested | committed | passed


@router.put("/bids/{opportunity_id}/contractors/{contractor_id}")
def set_match_status(opportunity_id: str, contractor_id: str, body: MatchStatusBody):
    from src.ai.contractors import MATCH_PROMPT_VERSION

    _bid_or_404(opportunity_id)
    try:
        updated = db.set_match_status(opportunity_id, contractor_id, body.status)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if updated is None:
        raise HTTPException(status_code=404, detail="unknown match")
    envelope = db.get_contractor_matches(opportunity_id, MATCH_PROMPT_VERSION)
    return {"state": "done"} | _with_relationship(envelope or {"matches": []})


# ---------------------------------------------------------------------------
# The network
# ---------------------------------------------------------------------------


@router.get("/contractors")
def list_network():
    """Every firm in the network, with the bids each was matched to."""
    contractors = db.list_contractors()
    match_sets = db.list_match_sets()
    opps = {o.opportunity_id: o for o in db.load_opportunities()}

    matched: Dict[str, List[dict]] = {}
    for oid, ms in match_sets.items():
        opp = opps.get(oid)
        for m in ms["matches"]:
            cid = m.get("contractor_id")
            if not cid:
                continue
            matched.setdefault(cid, []).append({
                "opportunity_id": oid,
                "title": opp.title if opp else "(bid no longer listed)",
                "agency": opp.agency if opp else "",
                "county": opp.county if opp else "",
                "due_date": opp.due_date.isoformat() if opp and opp.due_date else None,
                "match_status": m.get("status", "suggested"),
                "matched_at": ms["created_at"],
            })

    out = []
    for c in contractors:
        bids = sorted(matched.get(c["id"], []),
                      key=lambda b: b["matched_at"], reverse=True)
        out.append(c | {"matched_bids": bids})
    return {"count": len(out), "contractors": out}


class ContractorPatch(BaseModel):
    status: Optional[str] = None
    notes: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    website: Optional[str] = None
    trade: Optional[str] = None


@router.put("/contractors/{contractor_id}")
def update_contractor(contractor_id: str, body: ContractorPatch):
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    try:
        updated = db.update_contractor(contractor_id, **fields)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if updated is None:
        raise HTTPException(status_code=404, detail="unknown contractor")
    return updated


@router.delete("/contractors/{contractor_id}", status_code=204)
def delete_contractor(contractor_id: str):
    if not db.delete_contractor(contractor_id):
        raise HTTPException(status_code=404, detail="unknown contractor")
