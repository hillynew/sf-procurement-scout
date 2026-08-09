"""Snapshot, workflow-state, and settings persistence over the database.

This replaces both ``data/latest.json`` (what the portals say) and
``data/user_state.json`` (what the user has done about it). The two keep
separate tables so a snapshot replace can never touch workflow state:
rows in ``opportunities`` are replaced wholesale on every fetch *except*
those referenced by ``tracked_bids``, which are retained forever and simply
flagged ``present=False`` once they fall off the portals.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import TYPE_CHECKING, Dict, Iterable, List, Optional, Tuple

from sqlalchemy import String, cast, delete, func, select, update

from ..models.opportunity import Opportunity, SourceHealth
from .engine import init_db, session_scope

if TYPE_CHECKING:  # pragma: no cover — import cycle at runtime, fine for typing
    from ..contracts import Contract
from .models import (
    AiSummary,
    BidResult,
    CustomSource,
    DeepDive,
    FetchRun,
    HistoryRecord,
    Notification,
    OpportunityRow,
    Setting,
    TrackedBid,
    Watchlist,
)

STAGES = ("watching", "preparing", "submitted", "result")

# Relationship with a firm in the network vs. outreach on one specific match.
CONTRACTOR_STATUSES = ("prospect", "contacted", "in_network", "passed")
MATCH_STATUSES = ("suggested", "pitched", "interested", "committed", "passed")

DEFAULT_SETTINGS: Dict[str, dict] = {
    "auto_fetch": {"mode": "off", "interval_minutes": 240, "stale_minutes": 360},
    "notifications": {"deadline_days": 5, "watchlist": True, "fetch_events": True},
    "digest": {"enabled": False, "cadence": "daily", "hour": 7, "email": ""},
    "ai": {"model": "claude-haiku-4-5", "auto_summarize_tracked": True},
    # The two slow walks that run on their own cadence rather than with the bid
    # fetch: the contract register weekly, the platform check monthly. Both are
    # measured in days since the last run, not on a clock — see
    # web/services/maintenance.py.
    # Off by default, like auto-fetch and the digest: both jobs make hundreds of
    # requests to agency websites, and nothing in this build starts doing that
    # on its own until someone asks it to.
    "maintenance": {"enabled": False, "contracts_enabled": False,
                    "platform_check_enabled": True,
                    "contracts_days": 7, "platform_check_days": 30},
    # Internal bookkeeping (not exposed for editing): last digest/deadline scan.
    "internal": {
        "last_digest_on": None,
        "last_deadline_scan_on": None,
        "last_contracts_refresh_on": None,
        "last_platform_check_on": None,
    },
}

# Seeded on first run so Watchlists is useful before the user builds their own.
DEFAULT_WATCHLISTS = [
    {
        "name": "Construction < $500k",
        "rules": {"offers": ["construction"], "max_value": 500_000,
                  "counties": ["broward", "miami-dade"]},
    },
    {
        "name": "Janitorial / facilities",
        "rules": {"keywords": ["janitorial", "custodial", "facilities",
                               "maintenance", "porter"]},
    },
    {
        "name": "Roofing anywhere",
        "rules": {"keywords": ["roof", "re-roof", "reroof", "recoat"]},
    },
]


def bootstrap() -> None:
    """Create tables and seed defaults. Safe to call on every startup."""
    init_db()
    with session_scope() as s:
        if s.execute(select(Watchlist.id).limit(1)).first() is None:
            now = datetime.utcnow()
            for wl in DEFAULT_WATCHLISTS:
                s.add(Watchlist(id=uuid.uuid4().hex[:12], name=wl["name"],
                                rules=wl["rules"], email_digest=False,
                                seen_ids=[], created_at=now))


# ---------------------------------------------------------------------------
# Snapshot
# ---------------------------------------------------------------------------


@dataclass
class SnapshotResult:
    run_id: int
    count: int
    new_ids: List[str] = field(default_factory=list)


#: Snapshot writes touch every stored row; these bound how many of them sit
#: in the session at once. Loading the whole table held every old payload and
#: every new one together, and on a 512MB instance that peak — stacked on the
#: fetch's own — is what got the process OOM-killed. `_IN_CHUNK` also stays
#: under SQLite's ~999 bound-parameter limit for IN() lists.
_SNAPSHOT_CHUNK = 200
_IN_CHUNK = 500


def save_snapshot(
    opportunities: List[Opportunity],
    health: List[SourceHealth],
    *,
    started_at: Optional[datetime] = None,
    error: Optional[str] = None,
    run_id: Optional[int] = None,
) -> SnapshotResult:
    now = datetime.utcnow()
    with session_scope() as s:
        _flag_source_drops(s, health)
        existing_ids = set(s.execute(select(OpportunityRow.opportunity_id)).scalars())
        tracked_ids = set(s.execute(select(TrackedBid.opportunity_id)).scalars())

        incoming_ids = set()
        new_ids: List[str] = []
        for start in range(0, len(opportunities), _SNAPSHOT_CHUNK):
            for opp in opportunities[start : start + _SNAPSHOT_CHUNK]:
                oid = opp.opportunity_id
                incoming_ids.add(oid)
                payload = opp.model_dump(mode="json")
                row = s.get(OpportunityRow, oid)
                if row is None:
                    new_ids.append(oid)
                    row = OpportunityRow(opportunity_id=oid, first_seen_at=now)
                    s.add(row)
                row.payload = payload
                row.county = opp.county or ""
                row.status = str(opp.status or "open")
                row.offer_type = str(payload.get("offer_type") or "unknown")
                row.due_date = opp.due_date
                row.posted_date = opp.posted_date
                row.budget_amount = opp.budget_amount
                row.last_seen_at = now
                row.present = True
            # Write the chunk and drop its payloads from memory; the expired
            # rows stay in the identity map as shells and are never re-read.
            s.flush()
            s.expire_all()

        # Rows that vanished from the portals are kept and flagged absent —
        # never deleted. A captured record is the archive: award linkage joins
        # against closed solicitations, and "what was open last month" has to
        # come from somewhere. A vanished open row is also aged to closed,
        # since a bid a portal no longer lists is over even if we never saw a
        # close date. Flipping `present` needs no payload, so it happens in
        # bulk; only the rows being aged are actually loaded.
        gone = sorted(existing_ids - incoming_ids)
        aged: List[str] = []
        for start in range(0, len(gone), _IN_CHUNK):
            chunk = gone[start : start + _IN_CHUNK]
            aged.extend(
                oid
                for oid, status in s.execute(
                    select(OpportunityRow.opportunity_id, OpportunityRow.status)
                    .where(OpportunityRow.opportunity_id.in_(chunk))
                )
                if status in ("open", "upcoming") and oid not in tracked_ids
            )
            s.execute(
                update(OpportunityRow)
                .where(OpportunityRow.opportunity_id.in_(chunk))
                .values(present=False),
                execution_options={"synchronize_session": False},
            )
        s.expire_all()
        for start in range(0, len(aged), _SNAPSHOT_CHUNK):
            for oid in aged[start : start + _SNAPSHOT_CHUNK]:
                row = s.get(OpportunityRow, oid)
                if row is None:
                    continue
                row.status = "closed"
                payload = dict(row.payload or {})
                if payload.get("status") in ("open", "upcoming"):
                    payload["status"] = "closed"
                    row.payload = payload
            s.flush()
            s.expire_all()

        run = s.get(FetchRun, run_id) if run_id is not None else None
        if run is None:
            run = FetchRun(started_at=started_at or now)
            s.add(run)
        run.finished_at = now
        run.status = "error" if error else "done"
        run.opp_count = len(opportunities)
        run.new_count = len(new_ids)
        run.health = [h.model_dump(mode="json") for h in health]
        run.error = error
        s.flush()
        return SnapshotResult(run_id=run.id, count=len(opportunities), new_ids=new_ids)


def record_run_started(started_at: datetime) -> int:
    """Open a 'running' run row before fetching, so a death leaves evidence.

    A process the kernel kills for memory writes no error row — its run just
    never appears, and the failure is invisible. The row opened here is
    finalized by ``save_snapshot``/``record_failed_run`` via ``run_id``; one
    fetch runs at a time, so any 'running' row still present when a new run
    starts is a predecessor that died mid-run, and is flagged as such.
    """
    with session_scope() as s:
        stale = s.execute(
            select(FetchRun).where(FetchRun.status == "running")
        ).scalars().all()
        for run in stale:
            run.status = "died"
            run.finished_at = run.finished_at or datetime.utcnow()
            run.error = ("the process stopped mid-run without recording an "
                         "error — most likely killed for memory")
        if stale:
            _notify_in_session(
                s, "fetch_died", "A fetch died mid-run",
                "The previous fetch never finished; the process most likely "
                "ran out of memory. The run is marked 'died' in run history.",
                key="fetch:died",
            )
        run = FetchRun(started_at=started_at, finished_at=None, status="running",
                       opp_count=0, new_count=0, health=[], error=None)
        s.add(run)
        s.flush()
        return run.id


#: How many past runs a source is judged against, and the floor below which a
#: history is too thin to say anything.
_DROP_LOOKBACK_RUNS = 8
_DROP_MIN_NORM = 3


def _flag_source_drops(s, health: List[SourceHealth]) -> None:
    """Compare each source's run to its own history; flag what fell off a cliff.

    A scraper that quietly returns nothing must show as broken, not as an
    empty result. "Broken" is judged against the source's own recent norm:
    zero rows from a source that usually yields a dozen is a breakage even
    when the fetch itself succeeded, and a sharp drop (< 30% of norm) is
    worth a note even when it isn't zero.
    """
    runs = s.execute(
        select(FetchRun).where(FetchRun.status == "done")
        .order_by(FetchRun.id.desc()).limit(_DROP_LOOKBACK_RUNS)
    ).scalars().all()
    history: Dict[str, List[int]] = {}
    for run in runs:
        for row in run.health or []:
            if isinstance(row, dict) and row.get("source_id"):
                history.setdefault(row["source_id"], []).append(int(row.get("count") or 0))

    for h in health:
        counts = history.get(h.source_id)
        if not counts:
            continue
        norm = sorted(counts)[len(counts) // 2]  # median of recent runs
        if norm < _DROP_MIN_NORM:
            continue
        status = str(h.status)
        if h.count == 0 and status in ("ok", "empty"):
            h.status = "degraded"
            h.note = f"returned 0 rows; this source's recent norm is {norm}"
            _notify_in_session(
                s, "source_drop",
                f"Source went quiet: {h.name}",
                f"0 rows this run; recent norm {norm}. The portal may have "
                "changed or the agency may have migrated.",
                key=f"src:{h.source_id}"[:32],
            )
        elif h.count < norm * 0.3 and norm >= 10:
            h.note = (f"{h.note}; " if h.note else "") + (
                f"sharp drop: {h.count} rows vs recent norm {norm}"
            )
            _notify_in_session(
                s, "source_drop",
                f"Source dropped sharply: {h.name}",
                f"{h.count} rows this run vs a recent norm of {norm}.",
                key=f"src:{h.source_id}"[:32],
            )


def _notify_in_session(s, kind: str, title: str, body: str, *, key: str) -> None:
    """Deduped notification inside an already-open session.

    `add_notification` opens its own session; calling it mid-snapshot would
    stack a second write transaction on SQLite. The `key` rides in the
    opportunity_id column so one live notification exists per source.
    """
    existing = s.execute(
        select(Notification)
        .where(Notification.kind == kind)
        .where(Notification.opportunity_id == key)
        .where(Notification.read.is_(False))
    ).scalars().first()
    if existing is not None:
        existing.title, existing.body = title, body
        existing.created_at = datetime.utcnow()
        return
    s.add(Notification(created_at=datetime.utcnow(), kind=kind, title=title,
                       body=body, opportunity_id=key, read=False))


def record_failed_run(started_at: datetime, error: str,
                      run_id: Optional[int] = None) -> None:
    with session_scope() as s:
        run = s.get(FetchRun, run_id) if run_id is not None else None
        if run is None:
            run = FetchRun(started_at=started_at, opp_count=0, new_count=0, health=[])
            s.add(run)
        run.finished_at = datetime.utcnow()
        run.status = "error"
        run.error = error


def count_real_opportunities() -> int:
    """Stored rows that came from a portal rather than the demo seed."""
    with session_scope() as s:
        return int(
            s.execute(
                select(func.count())
                .select_from(OpportunityRow)
                .where(OpportunityRow.payload["source_id"].as_string() != "sample")
            ).scalar_one()
            or 0
        )


def load_opportunities(*, present_only: bool = False) -> List[Opportunity]:
    with session_scope() as s:
        rows = s.execute(select(OpportunityRow)).scalars().all()
    out: List[Opportunity] = []
    for row in rows:
        if present_only and not row.present:
            continue
        try:
            out.append(Opportunity.model_validate(row.payload))
        except Exception:  # noqa: BLE001 — one stale payload must not 500 the app
            continue
    return out


def first_seen_map() -> Dict[str, str]:
    """opportunity_id -> ISO first-seen timestamp, for 'new since last visit'."""
    with session_scope() as s:
        rows = s.execute(
            select(OpportunityRow.opportunity_id, OpportunityRow.first_seen_at)
        ).all()
    return {oid: ts.isoformat() for oid, ts in rows if ts is not None}


def get_opportunity(opportunity_id: str) -> Optional[Opportunity]:
    with session_scope() as s:
        row = s.get(OpportunityRow, opportunity_id)
    if row is None:
        return None
    try:
        return Opportunity.model_validate(row.payload)
    except Exception:  # noqa: BLE001
        return None


def save_opportunity(opp: Opportunity) -> bool:
    """Persist one already-known opportunity in place.

    Used when a single bid is enriched outside a fetch run — the detail pass is
    capped, so a bid someone opens or deep-dives may be the first to get its
    scope and documents. Deliberately narrow: it refuses to create rows, since
    an opportunity that no snapshot has seen has no business appearing in one.
    """
    with session_scope() as s:
        row = s.get(OpportunityRow, opp.opportunity_id)
        if row is None:
            return False
        payload = opp.model_dump(mode="json")
        row.payload = payload
        row.county = opp.county or ""
        row.status = str(opp.status or "open")
        row.offer_type = str(payload.get("offer_type") or "unknown")
        row.due_date = opp.due_date
        row.posted_date = opp.posted_date
        row.budget_amount = opp.budget_amount
        return True


def latest_run() -> Optional[dict]:
    with session_scope() as s:
        run = s.execute(
            select(FetchRun).order_by(FetchRun.id.desc()).limit(1)
        ).scalar_one_or_none()
    if run is None:
        return None
    return {
        "id": run.id,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "status": run.status,
        "opp_count": run.opp_count,
        "new_count": run.new_count,
        "health": run.health or [],
        "error": run.error,
    }


def recent_runs(limit: int = 30) -> List[dict]:
    with session_scope() as s:
        runs = s.execute(
            select(FetchRun).order_by(FetchRun.id.desc()).limit(limit)
        ).scalars().all()
    return [
        {
            "id": r.id,
            "finished_at": r.finished_at,
            "status": r.status,
            "opp_count": r.opp_count,
            "new_count": r.new_count,
        }
        for r in reversed(runs)
    ]


def latest_health() -> List[SourceHealth]:
    run = latest_run()
    if not run:
        return []
    out = []
    for raw in run["health"]:
        try:
            out.append(SourceHealth.model_validate(raw))
        except Exception:  # noqa: BLE001
            continue
    return out


# ---------------------------------------------------------------------------
# History (recurrence archive)
# ---------------------------------------------------------------------------


def save_history_records(records: Iterable[Opportunity]) -> int:
    count = 0
    with session_scope() as s:
        for rec in records:
            row = s.get(HistoryRecord, rec.opportunity_id)
            if row is None:
                row = HistoryRecord(opportunity_id=rec.opportunity_id)
                s.add(row)
            row.agency = rec.agency or ""
            row.county = rec.county or ""
            row.closed_on = rec.due_date.date() if rec.due_date else None
            row.payload = rec.model_dump(mode="json")
            count += 1
    return count


def load_history_records() -> List[Opportunity]:
    with session_scope() as s:
        rows = s.execute(select(HistoryRecord)).scalars().all()
    out = []
    for row in rows:
        try:
            out.append(Opportunity.model_validate(row.payload))
        except Exception:  # noqa: BLE001
            continue
    return out


# ---------------------------------------------------------------------------
# Bid workflow
# ---------------------------------------------------------------------------


def workflow_state() -> Dict[str, dict]:
    """All tracked bids keyed by opportunity_id, with results folded in."""
    with session_scope() as s:
        tracked = s.execute(select(TrackedBid)).scalars().all()
        results = {r.opportunity_id: r for r in s.execute(select(BidResult)).scalars()}
    out: Dict[str, dict] = {}
    for t in tracked:
        r = results.get(t.opportunity_id)
        out[t.opportunity_id] = {
            "tracked_on": t.tracked_on.isoformat(),
            "stage": t.stage,
            "decision": t.decision,
            "notes": t.notes,
            "checks": t.checks or {},
            "archived": t.archived,
            "result": {
                "outcome": r.outcome,
                "amount_cents": r.amount_cents,
                "notes": r.notes,
                "decided_on": r.decided_on.isoformat(),
            } if r else None,
        }
    return out


def set_tracked(opportunity_id: str, tracked: bool) -> bool:
    with session_scope() as s:
        row = s.get(TrackedBid, opportunity_id)
        if tracked and row is None:
            s.add(TrackedBid(opportunity_id=opportunity_id, tracked_on=date.today(),
                             stage="watching", notes="", checks={}))
        elif not tracked and row is not None:
            s.delete(row)
            result = s.get(BidResult, opportunity_id)
            if result is not None:
                s.delete(result)
    return tracked


def update_tracked(opportunity_id: str, **fields) -> Optional[dict]:
    """Patch stage/decision/notes/checks/archived on a tracked bid."""
    allowed = {"stage", "decision", "notes", "checks", "archived"}
    bad = set(fields) - allowed
    if bad:
        raise ValueError(f"unknown fields {sorted(bad)}")
    if "stage" in fields and fields["stage"] not in STAGES:
        raise ValueError(f"unknown stage {fields['stage']!r}")
    if "decision" in fields and fields["decision"] not in ("go", "nogo", None):
        raise ValueError(f"unknown decision {fields['decision']!r}")
    with session_scope() as s:
        row = s.get(TrackedBid, opportunity_id)
        if row is None:
            return None
        for key, value in fields.items():
            setattr(row, key, value)
        # A GO decision moves the bid into Preparing, same as the old app.
        if fields.get("decision") == "go" and row.stage == "watching":
            row.stage = "preparing"
        s.flush()
        return {
            "stage": row.stage, "decision": row.decision, "notes": row.notes,
            "checks": row.checks or {}, "archived": row.archived,
        }


def set_result(opportunity_id: str, outcome: str, *, amount_cents: Optional[int] = None,
               notes: str = "", decided_on: Optional[date] = None) -> None:
    if outcome not in ("won", "lost"):
        raise ValueError(f"unknown outcome {outcome!r}")
    with session_scope() as s:
        tracked = s.get(TrackedBid, opportunity_id)
        if tracked is None:
            raise KeyError(opportunity_id)
        tracked.stage = "result"
        row = s.get(BidResult, opportunity_id)
        if row is None:
            row = BidResult(opportunity_id=opportunity_id, outcome=outcome,
                            decided_on=decided_on or date.today())
            s.add(row)
        row.outcome = outcome
        row.amount_cents = amount_cents
        row.notes = notes or ""
        row.decided_on = decided_on or date.today()


def clear_result(opportunity_id: str) -> None:
    with session_scope() as s:
        row = s.get(BidResult, opportunity_id)
        if row is not None:
            s.delete(row)


# ---------------------------------------------------------------------------
# Watchlists
# ---------------------------------------------------------------------------


def list_watchlists() -> List[dict]:
    with session_scope() as s:
        rows = s.execute(select(Watchlist).order_by(Watchlist.created_at)).scalars().all()
    return [
        {
            "id": w.id, "name": w.name, "rules": w.rules or {},
            "email_digest": w.email_digest, "seen_ids": w.seen_ids or [],
            "created_at": w.created_at.isoformat(),
        }
        for w in rows
    ]


def create_watchlist(name: str, rules: dict, *, email_digest: bool = False) -> dict:
    wl = Watchlist(id=uuid.uuid4().hex[:12], name=name.strip() or "Watchlist",
                   rules=rules or {}, email_digest=email_digest, seen_ids=[],
                   created_at=datetime.utcnow())
    with session_scope() as s:
        s.add(wl)
    return {"id": wl.id, "name": wl.name, "rules": wl.rules,
            "email_digest": wl.email_digest, "seen_ids": []}


def update_watchlist(wl_id: str, **fields) -> Optional[dict]:
    allowed = {"name", "rules", "email_digest", "seen_ids"}
    bad = set(fields) - allowed
    if bad:
        raise ValueError(f"unknown fields {sorted(bad)}")
    with session_scope() as s:
        row = s.get(Watchlist, wl_id)
        if row is None:
            return None
        for key, value in fields.items():
            setattr(row, key, value)
        s.flush()
        return {"id": row.id, "name": row.name, "rules": row.rules or {},
                "email_digest": row.email_digest, "seen_ids": row.seen_ids or []}


def mark_watchlist_seen(wl_id: str, ids: List[str]) -> Optional[int]:
    with session_scope() as s:
        row = s.get(Watchlist, wl_id)
        if row is None:
            return None
        merged = set(row.seen_ids or []) | set(ids)
        row.seen_ids = sorted(merged)
        return len(merged)


def delete_watchlist(wl_id: str) -> bool:
    with session_scope() as s:
        row = s.get(Watchlist, wl_id)
        if row is None:
            return False
        s.delete(row)
        return True


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------


def add_notification(kind: str, title: str, body: str = "",
                     opportunity_id: Optional[str] = None,
                     dedupe: bool = False) -> None:
    with session_scope() as s:
        if dedupe and opportunity_id:
            # One live notification per (kind, bid): re-raising the same alarm
            # every day buried the bell in near-identical rows.
            existing = s.execute(
                select(Notification)
                .where(Notification.kind == kind)
                .where(Notification.opportunity_id == opportunity_id)
                .where(Notification.read.is_(False))
            ).scalars().first()
            if existing is not None:
                existing.title, existing.body = title, body
                existing.created_at = datetime.utcnow()
                return
        s.add(Notification(created_at=datetime.utcnow(), kind=kind, title=title,
                           body=body, opportunity_id=opportunity_id, read=False))


def list_notifications(limit: int = 50) -> Tuple[int, List[dict]]:
    with session_scope() as s:
        rows = s.execute(
            select(Notification).order_by(Notification.id.desc()).limit(limit)
        ).scalars().all()
        # Counted over the whole table, not the visible slice — the badge was
        # capping out (wrongly) once more than `limit` unread rows piled up.
        unread = s.execute(
            select(func.count()).select_from(Notification).where(Notification.read.is_(False))
        ).scalar() or 0
    items = [
        {
            "id": r.id, "kind": r.kind, "title": r.title, "body": r.body,
            "opportunity_id": r.opportunity_id,
            "created_at": r.created_at.isoformat(), "read": r.read,
        }
        for r in rows
    ]
    return unread, items


def mark_notifications_read(ids: Optional[List[int]] = None) -> int:
    """Mark the given ids read, or everything when ids is None."""
    with session_scope() as s:
        query = select(Notification).where(Notification.read.is_(False))
        if ids is not None:
            query = query.where(Notification.id.in_(ids))
        rows = s.execute(query).scalars().all()
        for r in rows:
            r.read = True
        return len(rows)


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


def get_settings() -> Dict[str, dict]:
    with session_scope() as s:
        stored = {row.key: row.value for row in s.execute(select(Setting)).scalars()}
    out: Dict[str, dict] = {}
    for section, defaults in DEFAULT_SETTINGS.items():
        merged = dict(defaults)
        value = stored.get(section)
        if isinstance(value, dict):
            for k in defaults:
                if k in value:
                    merged[k] = value[k]
        out[section] = merged
    return out


def update_settings(patch: Dict[str, dict]) -> Dict[str, dict]:
    current = get_settings()
    with session_scope() as s:
        for section, values in patch.items():
            if section not in DEFAULT_SETTINGS or not isinstance(values, dict):
                continue
            merged = dict(current[section])
            for k, v in values.items():
                if k in DEFAULT_SETTINGS[section]:
                    merged[k] = v
            row = s.get(Setting, section)
            if row is None:
                s.add(Setting(key=section, value=merged))
            else:
                row.value = merged
    return get_settings()


# ---------------------------------------------------------------------------
# AI summary cache
# ---------------------------------------------------------------------------


def get_summary(opportunity_id: str, content_hash: str, model: str,
                prompt_version: int) -> Optional[dict]:
    with session_scope() as s:
        row = s.get(AiSummary, (opportunity_id, content_hash, model, prompt_version))
    return dict(row.summary) if row is not None else None


def latest_summary(opportunity_id: str, min_prompt_version: int = 0) -> Optional[dict]:
    """Newest cached summary for a bid, ignoring superseded prompt versions.

    Callers pass the summarizer's current PROMPT_VERSION so briefs cached
    under an older, differently-shaped prompt are never served to the UI.
    """
    with session_scope() as s:
        row = s.execute(
            select(AiSummary)
            .where(AiSummary.opportunity_id == opportunity_id,
                   AiSummary.prompt_version >= min_prompt_version)
            .order_by(AiSummary.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()
    if row is None:
        return None
    return {"summary": dict(row.summary), "model": row.model,
            "created_at": row.created_at.isoformat()}


def put_summary(opportunity_id: str, content_hash: str, model: str,
                prompt_version: int, summary: dict, input_chars: int) -> None:
    with session_scope() as s:
        row = s.get(AiSummary, (opportunity_id, content_hash, model, prompt_version))
        if row is None:
            s.add(AiSummary(opportunity_id=opportunity_id, content_hash=content_hash,
                            model=model, prompt_version=prompt_version,
                            summary=summary, input_chars=input_chars,
                            created_at=datetime.utcnow()))
        else:
            row.summary = summary
            row.input_chars = input_chars
            row.created_at = datetime.utcnow()


def summarized_ids(min_prompt_version: int = 0) -> set:
    with session_scope() as s:
        return set(s.execute(
            select(AiSummary.opportunity_id)
            .where(AiSummary.prompt_version >= min_prompt_version)
        ).scalars())


def get_deep_dive(opportunity_id: str, min_prompt_version: int = 0) -> Optional[dict]:
    with session_scope() as s:
        row = s.get(DeepDive, opportunity_id)
    if row is None or row.prompt_version < min_prompt_version:
        return None
    return {
        "report": dict(row.report),
        "model": row.model,
        "content_hash": row.content_hash,
        "docs_read": row.docs_read,
        "created_at": row.created_at.isoformat(),
    }


def put_deep_dive(opportunity_id: str, *, content_hash: str, model: str,
                  prompt_version: int, report: dict, input_chars: int,
                  docs_read: int) -> None:
    with session_scope() as s:
        row = s.get(DeepDive, opportunity_id)
        if row is None:
            row = DeepDive(opportunity_id=opportunity_id, report={})
            s.add(row)
        row.content_hash = content_hash
        row.model = model
        row.prompt_version = prompt_version
        row.report = report
        row.input_chars = input_chars
        row.docs_read = docs_read
        row.created_at = datetime.utcnow()


def get_research_thread(opportunity_id: str) -> List[dict]:
    from .models import ResearchThread

    with session_scope() as s:
        row = s.get(ResearchThread, opportunity_id)
    return list(row.turns or []) if row else []


def append_research_turn(opportunity_id: str, turn: dict) -> List[dict]:
    from .models import ResearchThread

    with session_scope() as s:
        row = s.get(ResearchThread, opportunity_id)
        if row is None:
            row = ResearchThread(opportunity_id=opportunity_id, turns=[])
            s.add(row)
        # JSON columns don't detect in-place mutation; assign a new list.
        row.turns = list(row.turns or []) + [turn]
        row.updated_at = datetime.utcnow()
        return list(row.turns)


def clear_research_thread(opportunity_id: str) -> bool:
    from .models import ResearchThread

    with session_scope() as s:
        row = s.get(ResearchThread, opportunity_id)
        if row is None:
            return False
        s.delete(row)
        return True


def prune_deep_dives(current_version: int) -> int:
    with session_scope() as s:
        rows = s.execute(
            select(DeepDive).where(DeepDive.prompt_version < current_version)
        ).scalars().all()
        for row in rows:
            s.delete(row)
        return len(rows)


def prune_summaries(current_version: int) -> int:
    """Delete briefs cached under an older prompt version. Returns count."""
    with session_scope() as s:
        rows = s.execute(
            select(AiSummary).where(AiSummary.prompt_version < current_version)
        ).scalars().all()
        for row in rows:
            s.delete(row)
        return len(rows)


# ---------------------------------------------------------------------------
# Contractor network
# ---------------------------------------------------------------------------


def _contractor_out(row) -> dict:
    return {
        "id": row.id, "name": row.name, "county": row.county,
        "location": row.location, "trade": row.trade, "website": row.website,
        "phone": row.phone, "email": row.email, "status": row.status,
        "notes": row.notes, "profile": dict(row.profile or {}),
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }


def list_contractors() -> List[dict]:
    from .models import Contractor

    with session_scope() as s:
        rows = s.execute(select(Contractor).order_by(Contractor.name)).scalars().all()
    return [_contractor_out(r) for r in rows]


def get_contractor(contractor_id: str) -> Optional[dict]:
    from .models import Contractor

    with session_scope() as s:
        row = s.get(Contractor, contractor_id)
        return _contractor_out(row) if row is not None else None


def upsert_contractor(record: dict) -> dict:
    """Create or enrich one firm; existing user-entered fields never regress.

    A re-run of the matcher must not blow away the phone number or notes the
    user corrected by hand, so incoming values only fill blanks — except
    ``profile``, where fresh finder output merges over the old keys.
    """
    from .models import Contractor

    now = datetime.utcnow()
    with session_scope() as s:
        row = s.get(Contractor, record["id"])
        if row is None:
            row = Contractor(id=record["id"], name=record.get("name") or "",
                             status="prospect", notes="", profile={},
                             created_at=now)
            s.add(row)
        for field_name in ("name", "county", "location", "trade",
                          "website", "phone", "email"):
            incoming = (record.get(field_name) or "").strip()
            if incoming and not getattr(row, field_name, ""):
                setattr(row, field_name, incoming)
        if isinstance(record.get("profile"), dict):
            row.profile = dict(row.profile or {}) | record["profile"]
        row.updated_at = now
        s.flush()
        return _contractor_out(row)


def update_contractor(contractor_id: str, **fields) -> Optional[dict]:
    """Patch the user-editable fields on one firm."""
    from .models import Contractor

    allowed = {"status", "notes", "phone", "email", "website", "trade", "county"}
    bad = set(fields) - allowed
    if bad:
        raise ValueError(f"unknown fields {sorted(bad)}")
    if "status" in fields and fields["status"] not in CONTRACTOR_STATUSES:
        raise ValueError(f"unknown status {fields['status']!r}")
    with session_scope() as s:
        row = s.get(Contractor, contractor_id)
        if row is None:
            return None
        for key, value in fields.items():
            setattr(row, key, value)
        row.updated_at = datetime.utcnow()
        s.flush()
        return _contractor_out(row)


def delete_contractor(contractor_id: str) -> bool:
    from .models import Contractor

    with session_scope() as s:
        row = s.get(Contractor, contractor_id)
        if row is None:
            return False
        s.delete(row)
        return True


def get_contractor_matches(opportunity_id: str,
                           min_prompt_version: int = 0) -> Optional[dict]:
    from .models import ContractorMatchSet

    with session_scope() as s:
        row = s.get(ContractorMatchSet, opportunity_id)
    if row is None or row.prompt_version < min_prompt_version:
        return None
    return {
        "matches": list(row.matches or []),
        "market_note": row.market_note,
        "model": row.model,
        "content_hash": row.content_hash,
        "searches": row.searches,
        "created_at": row.created_at.isoformat(),
    }


def put_contractor_matches(opportunity_id: str, *, content_hash: str, model: str,
                           prompt_version: int, matches: List[dict],
                           market_note: str, searches: int) -> None:
    from .models import ContractorMatchSet

    with session_scope() as s:
        row = s.get(ContractorMatchSet, opportunity_id)
        if row is None:
            row = ContractorMatchSet(opportunity_id=opportunity_id, matches=[])
            s.add(row)
        row.content_hash = content_hash
        row.model = model
        row.prompt_version = prompt_version
        row.matches = matches
        row.market_note = market_note or ""
        row.searches = searches
        row.created_at = datetime.utcnow()


def set_match_status(opportunity_id: str, contractor_id: str,
                     status: str) -> Optional[List[dict]]:
    """Move one bid↔contractor match through the outreach pipeline."""
    from .models import ContractorMatchSet

    if status not in MATCH_STATUSES:
        raise ValueError(f"unknown status {status!r}")
    with session_scope() as s:
        row = s.get(ContractorMatchSet, opportunity_id)
        if row is None:
            return None
        found = False
        # JSON columns don't detect in-place mutation; assign a new list.
        updated = []
        for m in row.matches or []:
            if m.get("contractor_id") == contractor_id:
                m = dict(m) | {"status": status}
                found = True
            updated.append(m)
        if not found:
            return None
        row.matches = updated
        return updated


def list_match_sets() -> Dict[str, dict]:
    """All match sets keyed by opportunity_id, for Python-side joins."""
    from .models import ContractorMatchSet

    with session_scope() as s:
        rows = s.execute(select(ContractorMatchSet)).scalars().all()
    return {
        r.opportunity_id: {"matches": list(r.matches or []),
                           "created_at": r.created_at.isoformat()}
        for r in rows
    }


def prune_contractor_matches(current_version: int) -> int:
    from .models import ContractorMatchSet

    with session_scope() as s:
        rows = s.execute(
            select(ContractorMatchSet)
            .where(ContractorMatchSet.prompt_version < current_version)
        ).scalars().all()
        for row in rows:
            s.delete(row)
        return len(rows)


# ---------------------------------------------------------------------------
# Custom sources
# ---------------------------------------------------------------------------


def list_custom_sources() -> List[dict]:
    with session_scope() as s:
        rows = s.execute(select(CustomSource).order_by(CustomSource.created_at)).scalars().all()
    return [
        {"id": r.id, "name": r.name, "county": r.county, "agency": r.agency,
         "adapter": r.adapter, "portal_url": r.portal_url, "custom": True}
        for r in rows
    ]


def add_custom_source(*, source_id: str, name: str, county: str, agency: str,
                      adapter: str, portal_url: str) -> dict:
    with session_scope() as s:
        row = s.get(CustomSource, source_id)
        if row is None:
            row = CustomSource(id=source_id, created_at=datetime.utcnow())
            s.add(row)
        row.name = name
        row.county = county
        row.agency = agency or name
        row.adapter = adapter
        row.portal_url = portal_url
    return {"id": source_id, "name": name, "county": county, "agency": agency or name,
            "adapter": adapter, "portal_url": portal_url, "custom": True}


def delete_custom_source(source_id: str) -> bool:
    with session_scope() as s:
        row = s.get(CustomSource, source_id)
        if row is None:
            return False
        s.delete(row)
        return True


# ---------------------------------------------------------------------------
# Data management
# ---------------------------------------------------------------------------


def purge(target: str) -> None:
    """Explicit destructive resets for the Settings screen."""
    from .models import PdfCacheEntry

    with session_scope() as s:
        if target == "snapshot":
            s.execute(delete(OpportunityRow))
            s.execute(delete(FetchRun))
        elif target == "workflow":
            s.execute(delete(TrackedBid))
            s.execute(delete(BidResult))
        elif target == "summaries":
            s.execute(delete(AiSummary))
            s.execute(delete(DeepDive))
        elif target == "notifications":
            s.execute(delete(Notification))
        elif target == "pdf_cache":
            s.execute(delete(PdfCacheEntry))
        elif target == "contractors":
            from .models import Contractor, ContractorMatchSet

            s.execute(delete(ContractorMatchSet))
            s.execute(delete(Contractor))
        elif target == "demo":
            # Only what load_sample() wrote: seeded bids, the pipeline rows
            # seeded on top of them (tracked bids, results, any AI briefs),
            # seeded contracts, and demo run rows (identified by the sentinel
            # health entry the loader stamps). Real captured records are
            # untouched.
            from .models import ContractRow

            sample_ids = select(OpportunityRow.opportunity_id).where(
                OpportunityRow.payload["source_id"].as_string() == "sample"
            )
            for table in (BidResult, TrackedBid, AiSummary, DeepDive):
                s.execute(delete(table).where(
                    table.opportunity_id.in_(sample_ids.scalar_subquery())
                ))
            s.execute(delete(OpportunityRow).where(
                OpportunityRow.payload["source_id"].as_string() == "sample"
            ))
            s.execute(delete(ContractRow).where(ContractRow.source_id == "sample"))
            s.execute(delete(FetchRun).where(
                cast(FetchRun.health, String).like('%"source_id": "sample"%')
            ))
        else:
            raise ValueError(f"unknown purge target {target!r}")


# ---------------------------------------------------------------------------
# PDF cache
# ---------------------------------------------------------------------------


def get_pdf_text(url_hash: str) -> Optional[str]:
    from .models import PdfCacheEntry

    with session_scope() as s:
        row = s.get(PdfCacheEntry, url_hash)
    return row.text if row is not None else None


def put_pdf_text(url_hash: str, text: str) -> None:
    from .models import PdfCacheEntry

    with session_scope() as s:
        row = s.get(PdfCacheEntry, url_hash)
        if row is None:
            s.add(PdfCacheEntry(url_hash=url_hash, text=text, created_at=datetime.utcnow()))
        else:
            row.text = text
            row.created_at = datetime.utcnow()


# ---------------------------------------------------------------------------
# Contracts
# ---------------------------------------------------------------------------


def save_contracts(contracts: Iterable["Contract"]) -> int:
    """Upsert the contract register for whichever sources published one.

    Upsert rather than replace: portals publish per-tenant, so a refresh that
    only reached three of nine agencies must not delete the other six.
    """
    from datetime import datetime as _dt

    from ..db.models import ContractRow

    count = 0
    now = _dt.utcnow()
    with session_scope() as s:
        for c in contracts:
            key = f"{c.source_id}:{c.contract_id}"
            row = s.get(ContractRow, key)
            if row is None:
                row = ContractRow(contract_id=key)
                s.add(row)
            row.source_id = c.source_id
            row.agency = c.agency or ""
            row.name = c.name or ""
            row.vendor = c.vendor
            row.vendor_id = c.vendor_id
            row.status_id = c.status_id
            row.start_date = c.start_date
            row.end_date = c.end_date
            row.url = c.url
            row.amount = c.amount
            row.method = c.method
            row.extendable = c.extendable
            row.commodity = c.commodity
            row.executed = c.executed
            row.justification = c.justification
            row.state_term_id = c.state_term_id
            row.agency_ref = c.agency_ref
            row.refreshed_at = now
            count += 1
    return count


def load_contracts() -> List["Contract"]:
    from ..contracts import Contract
    from ..db.models import ContractRow

    with session_scope() as s:
        rows = s.execute(select(ContractRow)).scalars().all()
    return [
        Contract(
            # Strip the source prefix the primary key carries.
            contract_id=row.contract_id.split(":", 1)[-1],
            agency=row.agency,
            name=row.name,
            source_id=row.source_id,
            vendor=row.vendor,
            vendor_id=row.vendor_id,
            status_id=row.status_id,
            start_date=row.start_date,
            end_date=row.end_date,
            url=row.url,
            amount=row.amount,
            method=row.method,
            extendable=row.extendable,
            commodity=row.commodity,
            executed=row.executed,
            justification=row.justification,
            state_term_id=row.state_term_id,
            agency_ref=row.agency_ref,
        )
        for row in rows
    ]


# ---------------------------------------------------------------------------
# Records requests (Chapter 119)
# ---------------------------------------------------------------------------

RECORDS_STATUSES = ("ready", "sent", "received", "no_response", "skipped")


def refresh_records_queue() -> int:
    """Mint a ready request for every newly-ripe lead. Returns rows added.

    The letter is generated once, at minting, and stored — the text a user
    actually sent must never drift under them when the generator changes.
    """
    from ..records import request_text, ripe_for_request
    from .models import RecordsRequest

    leads = ripe_for_request(load_opportunities())
    added = 0
    with session_scope() as s:
        existing = set(s.execute(select(RecordsRequest.opportunity_id)).scalars())
        for lead in leads:
            opp = lead.opportunity
            if opp.opportunity_id in existing:
                continue
            s.add(RecordsRequest(
                opportunity_id=opp.opportunity_id,
                agency=opp.agency,
                title=opp.title,
                external_id=opp.external_id,
                contact_email=opp.contact_email,
                letter=request_text(opp),
                status="ready",
                ripe_on=lead.ripe_on,
                created_at=datetime.utcnow(),
            ))
            added += 1
    return added


def list_records_requests() -> List[dict]:
    from .models import RecordsRequest

    with session_scope() as s:
        rows = s.execute(
            select(RecordsRequest).order_by(RecordsRequest.ripe_on.desc())
        ).scalars().all()
        return [
            {
                "opportunity_id": r.opportunity_id,
                "agency": r.agency,
                "title": r.title,
                "external_id": r.external_id,
                "contact_email": r.contact_email,
                "letter": r.letter,
                "status": r.status,
                "ripe_on": r.ripe_on.isoformat() if r.ripe_on else None,
                "sent_on": r.sent_on.isoformat() if r.sent_on else None,
                "received_on": r.received_on.isoformat() if r.received_on else None,
                "notes": r.notes,
            }
            for r in rows
        ]


def update_records_request(opportunity_id: str, **patch) -> Optional[dict]:
    """Patch status/notes/contact_email; date stamps follow the status."""
    from .models import RecordsRequest

    with session_scope() as s:
        row = s.get(RecordsRequest, opportunity_id)
        if row is None:
            return None
        if "status" in patch:
            status = patch["status"]
            if status not in RECORDS_STATUSES:
                raise ValueError(f"unknown status {status!r}")
            row.status = status
            today = date.today()
            if status == "sent" and row.sent_on is None:
                row.sent_on = today
            if status == "received" and row.received_on is None:
                row.received_on = today
        if "notes" in patch and patch["notes"] is not None:
            row.notes = str(patch["notes"])
        if "contact_email" in patch and patch["contact_email"] is not None:
            row.contact_email = str(patch["contact_email"]).strip() or None
        s.flush()
        return {
            "opportunity_id": row.opportunity_id, "status": row.status,
            "sent_on": row.sent_on.isoformat() if row.sent_on else None,
            "received_on": row.received_on.isoformat() if row.received_on else None,
            "notes": row.notes, "contact_email": row.contact_email,
        }
