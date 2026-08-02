"""Persist snapshots as JSON + CSV."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

import pandas as pd

from ..models.opportunity import Opportunity, SourceHealth
from ..sources.registry import project_root


def data_dir() -> Path:
    d = project_root() / "data"
    d.mkdir(parents=True, exist_ok=True)
    return d


# Every fetch wrote three timestamped files that were never cleaned up; on the
# Render free tier that fills the ephemeral disk. Keep a short history only.
KEEP_SNAPSHOTS = 10


def prune_snapshots(keep: int = KEEP_SNAPSHOTS) -> List[Path]:
    """Delete all but the newest `keep` timestamped snapshots. Returns removals."""
    base = data_dir()
    removed: List[Path] = []
    for pattern in ("opportunities_*.json", "opportunities_*.csv", "health_*.json"):
        files = sorted(base.glob(pattern), key=lambda p: p.name, reverse=True)
        for stale in files[keep:]:
            try:
                stale.unlink()
                removed.append(stale)
            except OSError:
                # A snapshot we cannot delete is not worth failing the run over.
                pass
    return removed


def save_snapshot(
    opportunities: List[Opportunity],
    health: List[SourceHealth],
    *,
    tag: Optional[str] = None,
    keep: int = KEEP_SNAPSHOTS,
) -> Tuple[Path, Path, Path]:
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    label = f"{ts}_{tag}" if tag else ts
    base = data_dir()

    rows = [o.to_row() for o in opportunities]
    full = {
        "fetched_at": datetime.utcnow().isoformat() + "Z",
        "count": len(opportunities),
        "health": [h.model_dump() for h in health],
        "opportunities": [o.model_dump(mode="json") for o in opportunities],
    }

    json_path = base / f"opportunities_{label}.json"
    csv_path = base / f"opportunities_{label}.csv"
    latest_json = base / "latest.json"
    latest_csv = base / "latest.csv"
    health_path = base / f"health_{label}.json"

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(full, f, indent=2, default=str)
    with open(latest_json, "w", encoding="utf-8") as f:
        json.dump(full, f, indent=2, default=str)
    with open(health_path, "w", encoding="utf-8") as f:
        json.dump([h.model_dump() for h in health], f, indent=2, default=str)

    df = pd.DataFrame(rows)
    if not df.empty:
        # sort: open first, soonest due first
        df["_due_sort"] = pd.to_datetime(df["due_date"], errors="coerce")
        status_rank = {"open": 0, "upcoming": 1, "catalog": 2, "closed": 3, "cancelled": 4}
        df["_status_rank"] = df["status"].map(lambda s: status_rank.get(s, 9))
        df = df.sort_values(["_status_rank", "_due_sort", "county", "agency"], na_position="last")
        df = df.drop(columns=["_due_sort", "_status_rank"])
    df.to_csv(csv_path, index=False)
    df.to_csv(latest_csv, index=False)

    prune_snapshots(keep)

    # Mirror into the database (best-effort) so a CLI fetch feeds the web app
    # and the snapshot survives ephemeral-disk restarts.
    try:
        from ..db import store as db_store

        db_store.bootstrap()
        db_store.save_snapshot(opportunities, health)
    except Exception:  # noqa: BLE001 — files remain the CLI's source of truth
        pass
    return json_path, csv_path, latest_json


def load_latest() -> Tuple[List[Opportunity], List[SourceHealth]]:
    path = data_dir() / "latest.json"
    if not path.exists():
        return [], []
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    opps = [Opportunity.model_validate(o) for o in data.get("opportunities") or []]
    health = [SourceHealth.model_validate(h) for h in data.get("health") or []]
    return opps, health
