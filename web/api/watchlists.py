"""Watchlist CRUD, rule matching, and correct NEW badges via seen-ID sets."""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.db import store as db
from web.services.matching import wl_matches
from web.services.serialize import opp_out

router = APIRouter()


class Rules(BaseModel):
    keywords: List[str] = Field(default_factory=list)
    counties: List[str] = Field(default_factory=list)
    offers: List[str] = Field(default_factory=list)
    min_value: Optional[int] = None
    max_value: Optional[int] = None
    no_bond: bool = False
    recurring_only: bool = False

    def compact(self) -> dict:
        """Only the meaningful keys — keeps rule chips readable."""
        out: dict = {}
        if self.keywords:
            out["keywords"] = [k.strip().lower() for k in self.keywords if k.strip()]
        if self.counties:
            out["counties"] = self.counties
        if self.offers:
            out["offers"] = self.offers
        if self.min_value:
            out["min_value"] = self.min_value
        if self.max_value:
            out["max_value"] = self.max_value
        if self.no_bond:
            out["no_bond"] = True
        if self.recurring_only:
            out["recurring_only"] = True
        return out


def _with_counts(wl: dict, opps) -> dict:
    matches = wl_matches(wl.get("rules") or {}, opps)
    seen = set(wl.get("seen_ids") or [])
    return {
        "id": wl["id"],
        "name": wl["name"],
        "rules": wl["rules"],
        "email_digest": wl["email_digest"],
        "match_count": len(matches),
        "new_count": sum(1 for o in matches if o.opportunity_id not in seen),
    }


@router.get("/watchlists")
def list_watchlists():
    opps = db.load_opportunities(present_only=True)
    return {"watchlists": [_with_counts(wl, opps) for wl in db.list_watchlists()]}


class WatchlistBody(BaseModel):
    name: str
    rules: Rules = Field(default_factory=Rules)
    email_digest: bool = False


@router.post("/watchlists", status_code=201)
def create_watchlist(body: WatchlistBody):
    wl = db.create_watchlist(body.name, body.rules.compact(),
                             email_digest=body.email_digest)
    return _with_counts(wl | {"seen_ids": []}, db.load_opportunities(present_only=True))


class WatchlistPatch(BaseModel):
    name: Optional[str] = None
    rules: Optional[Rules] = None
    email_digest: Optional[bool] = None


@router.put("/watchlists/{wl_id}")
def update_watchlist(wl_id: str, body: WatchlistPatch):
    fields: dict = {}
    if body.name is not None:
        fields["name"] = body.name.strip() or "Watchlist"
    if body.rules is not None:
        fields["rules"] = body.rules.compact()
    if body.email_digest is not None:
        fields["email_digest"] = body.email_digest
    updated = db.update_watchlist(wl_id, **fields)
    if updated is None:
        raise HTTPException(status_code=404, detail="unknown watchlist")
    return _with_counts(updated, db.load_opportunities(present_only=True))


@router.delete("/watchlists/{wl_id}", status_code=204)
def delete_watchlist(wl_id: str):
    if not db.delete_watchlist(wl_id):
        raise HTTPException(status_code=404, detail="unknown watchlist")


@router.get("/watchlists/{wl_id}/matches")
def watchlist_matches(wl_id: str):
    wl = next((w for w in db.list_watchlists() if w["id"] == wl_id), None)
    if wl is None:
        raise HTTPException(status_code=404, detail="unknown watchlist")
    opps = db.load_opportunities(present_only=True)
    matches = wl_matches(wl.get("rules") or {}, opps)
    seen = set(wl.get("seen_ids") or [])
    workflow = db.workflow_state()
    summarized = db.summarized_ids()
    return {
        "watchlist": _with_counts(wl, opps),
        "matches": [
            opp_out(o, workflow, summarized) | {"is_new": o.opportunity_id not in seen}
            for o in matches
        ],
    }


@router.post("/watchlists/{wl_id}/seen")
def mark_seen(wl_id: str):
    wl = next((w for w in db.list_watchlists() if w["id"] == wl_id), None)
    if wl is None:
        raise HTTPException(status_code=404, detail="unknown watchlist")
    opps = db.load_opportunities(present_only=True)
    ids = [o.opportunity_id for o in wl_matches(wl.get("rules") or {}, opps)]
    db.mark_watchlist_seen(wl_id, ids)
    return {"seen": len(ids)}
