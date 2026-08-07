"""Has an agency moved? Compare today's fingerprint with the recorded one.

This is the smallest piece of the build and one of the most load-bearing,
because of a failure mode that has now bitten the project five times: **a live
page returning zero rows reads as a quiet agency, not a migrated one.** The
adapter works, the fetch succeeds, health is green, and the agency has simply
stopped putting its bids there. Nothing in a fetch can tell the difference.

Deerfield Beach (DemandStar -> Ionwave), UNF (Jaggaer -> Workday), St. Johns
County and its Anastasia Sanitary District (DemandStar -> Workday) were all
found this way rather than by a fetch noticing anything was wrong.

So the check is separate from the fetch and asks a different question: not
"what is posted", but "is this still the platform we think it is". The baseline
is `data/registry/fingerprints.jsonl` as committed — a move is a disagreement
between what the repo believes and what the agency's own website says today.

Only entities already placed on a platform are rechecked. An agency that was
never identified cannot have migrated away from anything, and re-reading 635
unknowns to learn they are still unknown is 1,270 requests for no answer.

`scripts/fingerprint_agencies.py --recheck` runs this from a terminal;
`web/services/maintenance.py` runs it on a monthly cadence and turns each move
into a notification. Both call `recheck` — the comparison lives here so the two
cannot drift apart.
"""

from __future__ import annotations

import csv
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from .fingerprint import Fingerprint, fingerprint_agency

ROSTER = Path("data/registry/fl_agencies.csv")
FINGERPRINTS = Path("data/registry/fingerprints.jsonl")

#: Concurrency is about sockets, not politeness — `netpolicy` holds the
#: per-host limit, and these are a few hundred different hosts.
WORKERS = 12


@dataclass
class Move:
    """One agency whose platform no longer matches the recorded one."""

    entity_id: str
    name: str
    was: str
    now: str
    portal_url: Optional[str] = None
    confidence: str = "none"
    note: str = ""

    def describe(self) -> str:
        return f"{self.name}: {self.was} -> {self.now}"


@dataclass
class Result:
    checked: int = 0
    unchanged: int = 0
    #: Known platform -> a different known platform. These need source config.
    moved: List[Move] = field(default_factory=list)
    #: Known platform -> unknown. Usually a slow site or a WAF, not a move,
    #: which is why it is kept apart from `moved` rather than counted with it.
    lost: List[Move] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"{self.checked} rechecked · {self.unchanged} unchanged · "
            f"{len(self.moved)} moved · {len(self.lost)} no longer readable"
        )


def recorded(path: Path = FINGERPRINTS) -> Dict[str, Dict]:
    """entity_id -> its last recorded fingerprint, latest line winning.

    Latest wins because the file is append-only: a recheck writes a new line
    rather than editing the old one, so the history of a migration stays
    readable in the file itself.
    """
    out: Dict[str, Dict] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except Exception:  # noqa: BLE001 — a torn last line is not fatal
            continue
        if row.get("entity_id"):
            out[row["entity_id"]] = row
    return out


def identified(baseline: Dict[str, Dict]) -> set:
    """The entities worth rechecking: those we believe we have placed."""
    return {
        entity
        for entity, row in baseline.items()
        if row.get("platform") and row["platform"] != "unknown"
    }


def roster_rows(entity_ids: set, path: Path = ROSTER) -> List[Dict]:
    """Roster records for those entities, in roster order, websites only."""
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as fh:
        return [
            row
            for row in csv.DictReader(fh)
            if row.get("entity_id") in entity_ids and (row.get("website") or "").strip()
        ]


def compare(baseline: Dict[str, Dict], results: Sequence[Fingerprint]) -> Result:
    """Sort fresh fingerprints into moved, no-longer-readable, and unchanged."""
    out = Result(checked=len(results))
    for fp in results:
        was = (baseline.get(fp.entity_id) or {}).get("platform", "unknown")
        if was == fp.platform:
            out.unchanged += 1
            continue
        move = Move(
            entity_id=fp.entity_id, name=fp.name, was=was, now=fp.platform,
            portal_url=fp.portal_url, confidence=fp.confidence, note=fp.note,
        )
        (out.lost if fp.platform == "unknown" else out.moved).append(move)
    return out


def recheck(
    *,
    baseline: Optional[Dict[str, Dict]] = None,
    roster: Optional[List[Dict]] = None,
    workers: int = WORKERS,
    limit: int = 0,
    on_result=None,
) -> Result:
    """Re-fingerprint every identified agency and report what changed.

    Blocking and network-bound — a few hundred sites at two fetches each. Call
    it from a thread, never from an event loop.

    `on_result` is handed each fresh `Fingerprint` as it lands, so a caller that
    wants to append to the JSONL can do so without this function knowing where
    the file is.
    """
    baseline = recorded() if baseline is None else baseline
    rows = roster_rows(identified(baseline)) if roster is None else roster
    if limit:
        rows = rows[:limit]
    if not rows:
        return Result()

    results: List[Fingerprint] = []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = {
            pool.submit(fingerprint_agency, r["entity_id"], r["name"], r["website"]): r
            for r in rows
        }
        for future in as_completed(futures):
            try:
                fp = future.result()
            except Exception:  # noqa: BLE001 — one bad site is a row, not a stop
                continue
            results.append(fp)
            if on_result is not None:
                on_result(fp)
    return compare(baseline, results)
