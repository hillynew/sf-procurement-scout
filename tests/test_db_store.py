"""DB store: snapshot round-trips, tracked-row retention, workflow state."""

from datetime import date, datetime, timedelta

import pytest

from src.models.opportunity import Opportunity, SourceHealth


@pytest.fixture()
def db(tmp_path, monkeypatch):
    from src.db import engine as db_engine

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    db_engine.reset_engine()
    from src.db import store

    store.bootstrap()
    yield store
    db_engine.reset_engine()


def make_opp(title: str, **kw) -> Opportunity:
    defaults = dict(
        source_id="test-src",
        source_name="Test Source",
        title=title,
        url=f"https://example.gov/{title.replace(' ', '-')}",
        county="broward",
        agency="City of Testville",
        status="open",
        due_date=datetime.utcnow() + timedelta(days=14),
        posted_date=date.today(),
    )
    defaults.update(kw)
    return Opportunity(**defaults)


HEALTH = [SourceHealth(source_id="test-src", name="Test Source", ok=True, count=2)]


def test_snapshot_round_trip(db):
    opps = [make_opp("Roof Replacement"), make_opp("Janitorial Services", budget="$120,000")]
    result = db.save_snapshot(opps, HEALTH)
    assert result.count == 2
    assert sorted(result.new_ids) == sorted(o.opportunity_id for o in opps)

    loaded = db.load_opportunities()
    assert {o.title for o in loaded} == {"Roof Replacement", "Janitorial Services"}
    jan = next(o for o in loaded if o.title == "Janitorial Services")
    assert jan.budget_amount == 120_000

    run = db.latest_run()
    assert run["status"] == "done"
    assert run["opp_count"] == 2
    assert run["new_count"] == 2
    assert db.latest_health()[0].source_id == "test-src"


def test_second_snapshot_counts_only_new(db):
    a = make_opp("Sidewalk Repairs")
    db.save_snapshot([a], HEALTH)
    b = make_opp("Tree Trimming")
    result = db.save_snapshot([a, b], HEALTH)
    assert result.new_ids == [b.opportunity_id]


def test_vanished_rows_are_kept_not_deleted(db):
    """A captured record is the archive — nothing is deleted on replace."""
    a, b = make_opp("Guardrail Install"), make_opp("Fleet Fuel Contract")
    db.save_snapshot([a, b], HEALTH)
    db.set_tracked(a.opportunity_id, True)

    # Next fetch: both bids fell off the portals.
    db.save_snapshot([], HEALTH)
    loaded = db.load_opportunities()
    assert {o.opportunity_id for o in loaded} == {a.opportunity_id, b.opportunity_id}
    # ...and every retained row is flagged as no longer present.
    assert db.load_opportunities(present_only=True) == []
    # The untracked one is aged to closed — a bid the portal no longer lists
    # is over; the tracked one keeps its status for the user's pipeline.
    by_id = {o.opportunity_id: o for o in loaded}
    assert by_id[b.opportunity_id].status == "closed"
    assert by_id[a.opportunity_id].status == "open"


def test_untrack_removes_result_too(db):
    a = make_opp("Pool Resurfacing")
    db.save_snapshot([a], HEALTH)
    db.set_tracked(a.opportunity_id, True)
    db.set_result(a.opportunity_id, "won", amount_cents=9_240_000)
    db.set_tracked(a.opportunity_id, False)
    assert db.workflow_state() == {}


def test_workflow_stage_and_result(db):
    a = make_opp("HVAC Maintenance")
    db.save_snapshot([a], HEALTH)
    oid = a.opportunity_id
    db.set_tracked(oid, True)

    state = db.workflow_state()[oid]
    assert state["stage"] == "watching"

    db.update_tracked(oid, stage="submitted", notes="sent Tuesday")
    db.set_result(oid, "won", amount_cents=9_240_000, notes="beat 3 others")
    state = db.workflow_state()[oid]
    assert state["stage"] == "result"
    assert state["result"]["outcome"] == "won"
    assert state["result"]["amount_cents"] == 9_240_000

    with pytest.raises(ValueError):
        db.update_tracked(oid, stage="bogus")
    with pytest.raises(ValueError):
        db.set_result(oid, "maybe")


def test_go_decision_advances_watching_to_preparing(db):
    a = make_opp("Lift Station Rehab")
    db.save_snapshot([a], HEALTH)
    db.set_tracked(a.opportunity_id, True)
    db.update_tracked(a.opportunity_id, decision="go")
    assert db.workflow_state()[a.opportunity_id]["stage"] == "preparing"


def test_watchlist_crud_and_seen(db):
    lists = db.list_watchlists()
    assert len(lists) == 3  # seeded defaults

    wl = db.create_watchlist("Paving", {"keywords": ["asphalt", "paving"]})
    db.update_watchlist(wl["id"], name="Paving + milling", email_digest=True)
    db.mark_watchlist_seen(wl["id"], ["abc123", "def456"])
    got = next(w for w in db.list_watchlists() if w["id"] == wl["id"])
    assert got["name"] == "Paving + milling"
    assert got["email_digest"] is True
    assert got["seen_ids"] == ["abc123", "def456"]

    assert db.delete_watchlist(wl["id"]) is True
    assert db.delete_watchlist(wl["id"]) is False


def test_notifications_feed_and_read(db):
    db.add_notification("fetch_done", "Fetch finished", "214 bids")
    db.add_notification("deadline_soon", "Due in 3 days", opportunity_id="abc")
    unread, items = db.list_notifications()
    assert unread == 2
    assert items[0]["kind"] == "deadline_soon"  # newest first

    db.mark_notifications_read([items[0]["id"]])
    unread, _ = db.list_notifications()
    assert unread == 1
    db.mark_notifications_read(None)
    unread, _ = db.list_notifications()
    assert unread == 0


def test_settings_merge_and_patch(db):
    settings = db.get_settings()
    assert settings["auto_fetch"]["mode"] == "off"

    db.update_settings({"auto_fetch": {"mode": "interval", "interval_minutes": 120},
                        "bogus_section": {"x": 1}})
    settings = db.get_settings()
    assert settings["auto_fetch"]["mode"] == "interval"
    assert settings["auto_fetch"]["interval_minutes"] == 120
    # Untouched keys keep their defaults; unknown sections are ignored.
    assert settings["auto_fetch"]["stale_minutes"] == 360
    assert "bogus_section" not in settings


def test_summary_cache(db):
    assert db.get_summary("opp1", "hash1", "claude-haiku-4-5", 1) is None
    db.put_summary("opp1", "hash1", "claude-haiku-4-5", 1,
                   {"what_the_work_is": "Fix roofs."}, input_chars=1234)
    got = db.get_summary("opp1", "hash1", "claude-haiku-4-5", 1)
    assert got["what_the_work_is"] == "Fix roofs."
    # Different content hash misses.
    assert db.get_summary("opp1", "hash2", "claude-haiku-4-5", 1) is None
    assert db.latest_summary("opp1")["model"] == "claude-haiku-4-5"


def test_latest_summary_ignores_superseded_prompt_versions(db):
    db.put_summary("opp2", "h1", "claude-haiku-4-5", 1,
                   {"what_the_work_is": "old shape"}, input_chars=10)
    # A v1-only brief is invisible once the caller requires v2.
    assert db.latest_summary("opp2", min_prompt_version=2) is None
    assert db.summarized_ids(min_prompt_version=2) == set()

    db.put_summary("opp2", "h2", "claude-haiku-4-5", 2,
                   {"what_the_work_is": "new shape"}, input_chars=10)
    got = db.latest_summary("opp2", min_prompt_version=2)
    assert got["summary"]["what_the_work_is"] == "new shape"
    assert db.summarized_ids(min_prompt_version=2) == {"opp2"}


def test_prune_summaries_deletes_only_older_versions(db):
    db.put_summary("a", "h", "m", 1, {"what_the_work_is": "v1"}, input_chars=1)
    db.put_summary("b", "h", "m", 2, {"what_the_work_is": "v2"}, input_chars=1)
    assert db.prune_summaries(2) == 1
    assert db.latest_summary("a") is None
    assert db.latest_summary("b") is not None
    assert db.prune_summaries(2) == 0


def test_custom_sources(db):
    db.add_custom_source(source_id="custom-x", name="Town of X", county="broward",
                         agency="Town of X", adapter="civicplus",
                         portal_url="https://townofx.gov/bids.aspx")
    assert db.list_custom_sources()[0]["id"] == "custom-x"
    assert db.delete_custom_source("custom-x") is True
    assert db.list_custom_sources() == []


def test_history_records(db):
    rec = make_opp("Janitorial Services 2023", status="closed")
    db.save_history_records([rec])
    loaded = db.load_history_records()
    assert loaded[0].title == "Janitorial Services 2023"


def test_purge_targets(db):
    a = make_opp("Something")
    db.save_snapshot([a], HEALTH)
    db.set_tracked(a.opportunity_id, True)
    db.purge("snapshot")
    assert db.load_opportunities() == []
    assert db.latest_run() is None
    # Workflow survives a snapshot purge.
    assert a.opportunity_id in db.workflow_state()
    db.purge("workflow")
    assert db.workflow_state() == {}
    with pytest.raises(ValueError):
        db.purge("everything")


def test_save_opportunity_persists_enrichment_in_place(db):
    """A bid enriched outside a fetch run keeps its scope and documents."""
    from src.models.opportunity import Document

    opp = make_opp("Roof Replacement")
    db.save_snapshot([opp], HEALTH)

    stored = db.get_opportunity(opp.opportunity_id)
    assert stored.documents == []

    stored.scope = "Tear off to deck and re-roof."
    stored.documents = [Document(name="ITB package.pdf", url="https://example.gov/p.pdf")]
    stored.detail_fetched = True
    assert db.save_opportunity(stored) is True

    again = db.get_opportunity(opp.opportunity_id)
    assert again.detail_fetched is True
    assert again.scope == "Tear off to deck and re-roof."
    assert [d.name for d in again.documents] == ["ITB package.pdf"]


def test_save_opportunity_refuses_to_create_a_row(db):
    """An opportunity no snapshot has seen has no business appearing in one."""
    orphan = make_opp("Never Fetched")
    assert db.save_opportunity(orphan) is False
    assert db.get_opportunity(orphan.opportunity_id) is None


def test_save_opportunity_keeps_the_filter_columns_in_step(db):
    """The extracted columns back the county/status filters, not just payload."""
    opp = make_opp("Roof Replacement", county="broward")
    db.save_snapshot([opp], HEALTH)

    stored = db.get_opportunity(opp.opportunity_id)
    stored.county = "duval"
    stored.status = "closed"
    db.save_opportunity(stored)

    # Read the extracted columns directly — the payload round-trip alone would
    # pass even if the columns had gone stale, which is what backs the filters.
    from src.db.engine import session_scope
    from src.db.models import OpportunityRow

    with session_scope() as s:
        row = s.get(OpportunityRow, opp.opportunity_id)
        assert row.county == "duval"
        assert row.status == "closed"


def test_deduped_notification_updates_in_place(db):
    db.add_notification("deadline_soon", "Due in 3 days: A", "x", opportunity_id="o1", dedupe=True)
    db.add_notification("deadline_soon", "Due in 2 days: A", "x", opportunity_id="o1", dedupe=True)
    unread, items = db.list_notifications()
    assert unread == 1
    assert [i["title"] for i in items] == ["Due in 2 days: A"]


def test_unread_count_spans_the_whole_table(db):
    for i in range(60):
        db.add_notification("fetch_done", f"n{i}")
    unread, items = db.list_notifications(limit=50)
    assert len(items) == 50
    assert unread == 60


def _health(count, status="ok"):
    return [SourceHealth(source_id="test-src", name="Test Source",
                         ok=status == "ok", count=count, status=status)]


def test_source_going_quiet_is_flagged_against_its_own_norm(db):
    """Zero rows from a source that usually yields ten is a breakage, not an
    empty result."""
    for _ in range(4):
        db.save_snapshot([make_opp(f"Bid {_}")], _health(10))

    quiet = _health(0, status="empty")
    db.save_snapshot([], quiet)
    assert str(quiet[0].status) == "degraded"
    assert "recent norm is 10" in (quiet[0].note or "")
    unread, items = db.list_notifications()
    assert any(i["kind"] == "source_drop" for i in items)


def test_first_run_has_no_history_and_no_flag(db):
    fresh = _health(0, status="empty")
    db.save_snapshot([], fresh)
    assert str(fresh[0].status) == "empty"


# ---------------------------------------------------------------------------
# Run lifecycle: a fetch opens its run row first, so a death leaves evidence
# ---------------------------------------------------------------------------


def test_run_started_is_finalized_by_save_snapshot(db):
    started = datetime.utcnow()
    run_id = db.record_run_started(started)

    result = db.save_snapshot([make_opp("Ditch Mowing")], HEALTH, started_at=started,
                              run_id=run_id)
    assert result.run_id == run_id, "the running row is finalized, not duplicated"
    runs = db.recent_runs()
    assert len(runs) == 1
    assert runs[0]["status"] == "done"
    assert runs[0]["opp_count"] == 1


def test_run_started_is_finalized_by_failed_run(db):
    started = datetime.utcnow()
    run_id = db.record_run_started(started)
    db.record_failed_run(started, "boom", run_id=run_id)
    runs = db.recent_runs()
    assert len(runs) == 1
    assert runs[0]["status"] == "error"


def test_stale_running_row_is_flagged_as_died(db):
    """An OOM-killed fetch writes nothing; the next run must expose the corpse."""
    db.record_run_started(datetime.utcnow())          # dies silently
    db.record_run_started(datetime.utcnow())          # next fetch starts

    statuses = [r["status"] for r in db.recent_runs()]
    assert statuses.count("died") == 1
    assert statuses.count("running") == 1
    _, notes = db.list_notifications()
    assert "fetch_died" in [n["kind"] for n in notes]


# ---------------------------------------------------------------------------
# Demo data stays out of a live database
# ---------------------------------------------------------------------------


def _sample_opp(title: str) -> Opportunity:
    return make_opp(title, source_id="sample", source_name="Sample data")


def test_count_real_opportunities_ignores_the_demo_seed(db):
    db.save_snapshot([_sample_opp("Fake Roof"), make_opp("Real Roof")], HEALTH)
    assert db.count_real_opportunities() == 1


def test_purge_demo_removes_only_sample_records(db):
    from src.contracts import Contract

    fake, real = _sample_opp("Fake Roof"), make_opp("Real Roof")
    db.save_snapshot([fake, real], HEALTH)
    db.save_contracts([
        Contract(contract_id="SAMPLE-1", agency="A", name="Fake", source_id="sample"),
        Contract(contract_id="REAL-1", agency="A", name="Real", source_id="facts"),
    ])
    # The demo seeds a pipeline on top of its bids; purge must take that too.
    db.set_tracked(fake.opportunity_id, True)
    db.set_result(fake.opportunity_id, "won", amount_cents=100)
    db.set_tracked(real.opportunity_id, True)

    db.purge("demo")
    assert [o.title for o in db.load_opportunities()] == ["Real Roof"]
    assert [c.contract_id for c in db.load_contracts()] == ["REAL-1"]
    assert list(db.workflow_state()) == [real.opportunity_id]


def test_purge_demo_removes_the_demo_run_but_keeps_real_runs(db):
    from src.models.opportunity import HealthStatus

    db.save_snapshot([make_opp("Real Roof")], HEALTH)
    demo_health = [SourceHealth(source_id="sample", name="Sample data", ok=True,
                                count=15, status=HealthStatus.OK)]
    db.save_snapshot([make_opp("Real Roof")], demo_health)

    db.purge("demo")
    remaining = db.recent_runs()
    assert len(remaining) == 1
    assert remaining[0]["opp_count"] == 1


def _rewind_runs(days: int) -> None:
    """Backdate every recorded run — `finished_at` is stamped `utcnow()` and
    the never-verified window is measured in days, so tests cannot get there
    through the public API alone."""
    from datetime import timedelta as _td

    from src.db.engine import session_scope
    from src.db.models import FetchRun

    with session_scope() as s:
        for run in s.query(FetchRun).all():
            if run.started_at:
                run.started_at = run.started_at - _td(days=days)
            if run.finished_at:
                run.finished_at = run.finished_at - _td(days=days)


def test_a_source_that_never_yields_a_row_reads_unverified(db):
    """Long enough silence stops being 'no listings' and starts being
    'nothing has ever shown this board works'."""
    for _ in range(6):
        db.save_snapshot([], _health(0, status="empty"))
    _rewind_runs(10)

    still_quiet = _health(0, status="empty")
    db.save_snapshot([], still_quiet)
    assert str(still_quiet[0].status) == "unverified"
    assert "never verified" in (still_quiet[0].note or "")


def test_a_source_with_any_history_of_rows_is_never_unverified(db):
    """A board that has produced work before is quiet, not unproven — even
    after a long dry spell. Counts stay under the drop threshold so the
    norm check abstains and only the never-verified rule is under test."""
    for _ in range(6):
        db.save_snapshot([make_opp("Bid")], _health(2))
    _rewind_runs(10)

    quiet = _health(0, status="empty")
    db.save_snapshot([], quiet)
    assert str(quiet[0].status) == "empty"


def test_recent_silence_is_not_yet_unverified(db):
    """Six fetches inside a single day is what a normal weekend looks like."""
    for _ in range(6):
        db.save_snapshot([], _health(0, status="empty"))

    quiet = _health(0, status="empty")
    db.save_snapshot([], quiet)
    assert str(quiet[0].status) == "empty"


def test_too_few_fetches_is_not_yet_unverified(db):
    """Age alone is not evidence; the source has to have been asked enough
    times for its silence to mean something."""
    for _ in range(2):
        db.save_snapshot([], _health(0, status="empty"))
    _rewind_runs(30)

    quiet = _health(0, status="empty")
    db.save_snapshot([], quiet)
    assert str(quiet[0].status) == "empty"


def test_a_row_clears_an_unverified_source_immediately(db):
    """The state is not sticky: one listing proves the board is live."""
    for _ in range(6):
        db.save_snapshot([], _health(0, status="empty"))
    _rewind_runs(10)

    alive = _health(1)
    db.save_snapshot([make_opp("First real bid")], alive)
    assert str(alive[0].status) == "ok"
