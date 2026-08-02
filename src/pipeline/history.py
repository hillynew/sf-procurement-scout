"""Bid history: what an agency has bought before, and how often.

Knowing a contract is open today is worth less than knowing the county rebids
it every three years and the last cycle closed in March. Bonfire publishes a
public archive of closed solicitations, so this module collects it, keeps it in
its own snapshot (history is not a pipeline of live opportunities), and matches
open bids against it to expose recurrence.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from ..models.opportunity import Opportunity

# Words that appear in almost every solicitation title and carry no signal
# about what is being bought.
_NOISE = frozenset(
    """
    the a an and or for of to in on at by with from services service
    project projects program city county town village district department
    request proposal proposals qualifications bid bids invitation notice
    rfp rfq rfi itb ifb itn rpq itq rli no number contract annual
    various citywide countywide phase re rebid new
    """.split()
)

_YEAR = re.compile(r"\b(?:19|20)\d{2}\b")
_TOKEN = re.compile(r"[a-z0-9]+")

# Two titles are the same recurring buy when this much of the smaller token set
# is shared. Tuned against Broward's archive: high enough that "Roof Repairs at
# Station 12" and "Roof Repairs at Station 8" stay distinct, low enough that
# "Janitorial Services" matches "Janitorial Services Citywide".
MATCH_THRESHOLD = 0.7

# One token is enough. Recurring commodity buys reduce to a single word once
# boilerplate is stripped — "Janitorial Services" is just "janitorial" — and
# requiring two would exclude exactly the contracts whose cadence matters most.
# Agency scoping keeps a single shared token from over-matching.
MIN_TOKENS = 1


def significant_tokens(title: str) -> frozenset:
    """The words that identify *what* is being bought."""
    words = _TOKEN.findall(_YEAR.sub(" ", (title or "").lower()))
    return frozenset(
        w
        for w in words
        # Bare digits are reference-number fragments, never subject matter.
        if w not in _NOISE and len(w) > 2 and not w.isdigit()
    )


def similarity(a: frozenset, b: frozenset) -> float:
    """Overlap as a fraction of the smaller set.

    Containment rather than Jaccard: a longer title that fully contains a
    shorter one is the same buy described in more words, and Jaccard would
    penalise that.
    """
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


class BidHistory:
    """An index of previously-closed solicitations, keyed by agency."""

    def __init__(self, records: Optional[Iterable[Opportunity]] = None):
        self._by_agency: Dict[str, List[Tuple[frozenset, Opportunity]]] = defaultdict(list)
        for rec in records or []:
            tokens = significant_tokens(rec.title)
            if len(tokens) >= MIN_TOKENS:
                self._by_agency[rec.agency.lower()].append((tokens, rec))

    def __len__(self) -> int:
        return sum(len(v) for v in self._by_agency.values())

    @property
    def agencies(self) -> List[str]:
        return sorted(self._by_agency)

    def prior_cycles(self, opp: Opportunity) -> List[Opportunity]:
        """Past solicitations from the same agency for the same thing."""
        tokens = significant_tokens(opp.title)
        if len(tokens) < MIN_TOKENS:
            return []
        matches = [
            rec
            for rec_tokens, rec in self._by_agency.get(opp.agency.lower(), [])
            if similarity(tokens, rec_tokens) >= MATCH_THRESHOLD
            and rec.opportunity_id != opp.opportunity_id
        ]
        matches.sort(key=lambda r: r.due_date or datetime.min, reverse=True)
        return matches


def annotate_recurrence(opps: List[Opportunity], history: BidHistory) -> int:
    """Attach prior-cycle counts and dates to each opportunity. Returns hits."""
    hits = 0
    for opp in opps:
        prior = history.prior_cycles(opp)
        if not prior:
            continue
        opp.prior_cycles = len(prior)
        last = next((p.due_date for p in prior if p.due_date), None)
        opp.last_cycle_closed = last.date() if last else None
        hits += 1
    return hits


# ---------------------------------------------------------------------------
# Persistence — history lives in its own file, refreshed on its own cadence
# ---------------------------------------------------------------------------


def history_path() -> Path:
    from .store import data_dir

    return data_dir() / "history.json"


def save_history(records: List[Opportunity]) -> Path:
    path = history_path()
    payload = {
        "fetched_at": datetime.utcnow().isoformat() + "Z",
        "count": len(records),
        "records": [r.model_dump(mode="json") for r in records],
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, default=str)
    # Mirror into the database so recurrence survives ephemeral-disk restarts.
    try:
        from ..db.store import save_history_records

        save_history_records(records)
    except Exception:  # noqa: BLE001 — the file remains the fallback
        pass
    return path


def load_history() -> BidHistory:
    # Database first (survives restarts), file as fallback.
    try:
        from ..db.store import load_history_records

        records = load_history_records()
        if records:
            return BidHistory(records)
    except Exception:  # noqa: BLE001
        pass
    path = history_path()
    if not path.exists():
        return BidHistory()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return BidHistory()
    records = []
    for raw in data.get("records") or []:
        try:
            records.append(Opportunity.model_validate(raw))
        except Exception:  # noqa: BLE001 — a stale record must not break startup
            continue
    return BidHistory(records)


def fetch_history(*, only: Optional[List[str]] = None, quiet: bool = False) -> List[Opportunity]:
    """Collect the closed-solicitation archive from every source that has one."""
    from rich.console import Console

    from ..sources.registry import get_adapters

    console = Console()
    records: List[Opportunity] = []
    for adapter in get_adapters(only=only):
        if not hasattr(adapter, "fetch_history"):
            continue
        try:
            got = adapter.fetch_history()
        except Exception as e:  # noqa: BLE001 — history is best-effort
            if not quiet:
                console.print(f"[yellow]![/yellow] {adapter.name}: {type(e).__name__}: {e}")
            continue
        records.extend(got)
        if not quiet:
            console.print(f"[green]✓[/green] {adapter.name}: {len(got)} past solicitations")
    return records
