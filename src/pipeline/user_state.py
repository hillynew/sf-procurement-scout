"""Persist the user's personal workflow layer on top of fetch snapshots.

The pipeline persists *what the portals say* (``data/latest.json``); this
module persists *what the user has done about it*: which bids they track or
skip, each tracked bid's pipeline stage, per-bid checklists, go/no-go
decisions and notes, saved watchlists, and sources they queued to add.
One JSON file, one user — the same files-not-a-database model as the rest
of ``data/``.
"""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import date
from pathlib import Path
from typing import Any, Dict

from .store import data_dir

STATE_FILE = "user_state.json"

STAGES = ("watching", "preparing", "submitted", "result")

# Seeded on first run so Watchlists is useful (and demonstrable) before the
# user builds their own. Filters use the same keys the chip builder emits.
DEFAULT_WATCHLISTS = [
    {
        "id": "construction-500k",
        "name": "Construction < $500k",
        "filters": {"offers": ["construction"], "max_value": 500_000,
                    "counties": ["broward", "miami-dade"]},
        "email": "on",
        "last_opened": None,
        "prev_opened": None,
    },
    {
        "id": "janitorial-facilities",
        "name": "Janitorial / facilities",
        "filters": {"keywords": ["janitorial", "custodial", "facilities",
                                 "maintenance", "porter"]},
        "email": "off",
        "last_opened": None,
        "prev_opened": None,
    },
    {
        "id": "roofing-anywhere",
        "name": "Roofing anywhere",
        "filters": {"keywords": ["roof", "re-roof", "reroof", "recoat"]},
        "email": "daily digest",
        "last_opened": None,
        "prev_opened": None,
    },
]


def _default_state() -> Dict[str, Any]:
    return {
        "tracked": {},          # opportunity_id -> ISO date it was tracked
        "skipped": {},          # opportunity_id -> ISO date it was skipped
        "stages": {},           # opportunity_id -> watching|preparing|submitted|result
        "results": {},          # opportunity_id -> outcome line, e.g. "WON · $92,400"
        "checks": {},           # opportunity_id -> {requirement index (str): bool}
        "decisions": {},        # opportunity_id -> "go" | "nogo"
        "notes": {},            # opportunity_id -> free text
        "watchlists": deepcopy(DEFAULT_WATCHLISTS),
        "selected_watchlist": DEFAULT_WATCHLISTS[0]["id"],
        "builder_chips": {},    # chip id -> bool
        "queued_sources": [],   # [{"name": ..., "url": ..., "detected": ...}]
        "last_today_visit": None,   # ISO date of the *previous* Today visit
        "today_visit_date": None,   # ISO date Today was last rendered
    }


def state_path() -> Path:
    return data_dir() / STATE_FILE


def load_user_state() -> Dict[str, Any]:
    """Read state, tolerating a missing or damaged file.

    Unknown keys are dropped and missing keys filled in, so the schema can
    grow without a migration step.
    """
    state = _default_state()
    try:
        raw = json.loads(state_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return state
    if isinstance(raw, dict):
        for key, default in state.items():
            value = raw.get(key, default)
            if isinstance(value, type(default)) or default is None:
                state[key] = value
    return state


def save_user_state(state: Dict[str, Any]) -> Path:
    path = state_path()
    path.write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Mutations — tiny helpers so the app and tests share one vocabulary.
# ---------------------------------------------------------------------------

def toggle_tracked(state: Dict[str, Any], opp_id: str, when: date | None = None) -> bool:
    """Track/untrack a bid. Returns the new tracked flag."""
    if state["tracked"].pop(opp_id, None) is not None:
        state["stages"].pop(opp_id, None)
        return False
    state["tracked"][opp_id] = (when or date.today()).isoformat()
    state["stages"].setdefault(opp_id, "watching")
    return True


def skip(state: Dict[str, Any], opp_id: str, when: date | None = None) -> None:
    state["skipped"][opp_id] = (when or date.today()).isoformat()


def undo_skips(state: Dict[str, Any]) -> None:
    state["skipped"].clear()


def toggle_check(state: Dict[str, Any], opp_id: str, index: int) -> bool:
    per_bid = state["checks"].setdefault(opp_id, {})
    per_bid[str(index)] = not per_bid.get(str(index), False)
    return per_bid[str(index)]


def set_decision(state: Dict[str, Any], opp_id: str, decision: str | None) -> None:
    if decision is None:
        state["decisions"].pop(opp_id, None)
        return
    if decision not in ("go", "nogo"):
        raise ValueError(f"unknown decision {decision!r}")
    state["decisions"][opp_id] = decision
    if decision == "go":
        state["stages"][opp_id] = "preparing"


def stage_of(state: Dict[str, Any], opp_id: str) -> str | None:
    if opp_id not in state["tracked"]:
        return None
    return state["stages"].get(opp_id, "watching")


def set_stage(state: Dict[str, Any], opp_id: str, stage: str) -> None:
    if stage not in STAGES:
        raise ValueError(f"unknown stage {stage!r}")
    if opp_id in state["tracked"]:
        state["stages"][opp_id] = stage


def move_stage(state: Dict[str, Any], opp_id: str, step: int) -> str | None:
    """Shift a tracked bid one column left (-1) or right (+1). Returns the new stage."""
    current = stage_of(state, opp_id)
    if current is None:
        return None
    idx = STAGES.index(current) + step
    if not 0 <= idx < len(STAGES):
        return current
    set_stage(state, opp_id, STAGES[idx])
    return STAGES[idx]


def set_result(state: Dict[str, Any], opp_id: str, outcome: str) -> None:
    """Record a WON/LOST (or free-text) outcome for a bid in the Result column."""
    state["results"][opp_id] = outcome


def open_watchlist(state: Dict[str, Any], wl_id: str, now_iso: str) -> None:
    """Select a watchlist, remembering the previous open for "new" badges."""
    state["selected_watchlist"] = wl_id
    for wl in state["watchlists"]:
        if wl["id"] == wl_id:
            if wl.get("last_opened"):
                wl["prev_opened"] = wl["last_opened"]
            wl["last_opened"] = now_iso
