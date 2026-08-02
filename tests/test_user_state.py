"""User workflow state: persistence and the mutation helpers the UI uses."""

from datetime import date

import pytest

from src.pipeline import user_state as us


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.setattr(us, "data_dir", lambda: tmp_path)
    return us.load_user_state()


def test_defaults_include_seed_watchlists(state):
    assert [w["id"] for w in state["watchlists"]] == [
        "construction-500k", "janitorial-facilities", "roofing-anywhere",
    ]
    assert state["selected_watchlist"] == "construction-500k"
    assert state["tracked"] == {}


def test_round_trip(tmp_path, monkeypatch, state):
    us.toggle_tracked(state, "abc", when=date(2026, 8, 1))
    us.skip(state, "def")
    state["notes"]["abc"] = "call Ray re: crane access"
    us.save_user_state(state)

    again = us.load_user_state()
    assert again["tracked"] == {"abc": "2026-08-01"}
    assert "def" in again["skipped"]
    assert again["notes"]["abc"] == "call Ray re: crane access"


def test_damaged_file_falls_back_to_defaults(tmp_path, monkeypatch, state):
    us.state_path().write_text("{not json", encoding="utf-8")
    assert us.load_user_state()["tracked"] == {}


def test_unknown_keys_dropped_and_wrong_types_ignored(state):
    us.save_user_state({**state, "bogus": 1, "tracked": "not-a-dict"})
    again = us.load_user_state()
    assert "bogus" not in again
    assert again["tracked"] == {}


def test_track_toggle_sets_stage_and_untrack_clears_it(state):
    assert us.toggle_tracked(state, "abc") is True
    assert us.stage_of(state, "abc") == "watching"
    assert us.toggle_tracked(state, "abc") is False
    assert us.stage_of(state, "abc") is None
    assert state["stages"] == {}


def test_skip_and_undo(state):
    us.skip(state, "a")
    us.skip(state, "b")
    assert len(state["skipped"]) == 2
    us.undo_skips(state)
    assert state["skipped"] == {}


def test_checklist_toggle(state):
    assert us.toggle_check(state, "bid", 2) is True
    assert state["checks"]["bid"] == {"2": True}
    assert us.toggle_check(state, "bid", 2) is False


def test_go_decision_promotes_stage(state):
    us.toggle_tracked(state, "bid")
    us.set_decision(state, "bid", "go")
    assert state["decisions"]["bid"] == "go"
    assert us.stage_of(state, "bid") == "preparing"
    us.set_decision(state, "bid", None)
    assert "bid" not in state["decisions"]
    with pytest.raises(ValueError):
        us.set_decision(state, "bid", "maybe")


def test_open_watchlist_tracks_previous_open(state):
    us.open_watchlist(state, "roofing-anywhere", "2026-08-01T10:00:00")
    us.open_watchlist(state, "roofing-anywhere", "2026-08-02T10:00:00")
    wl = next(w for w in state["watchlists"] if w["id"] == "roofing-anywhere")
    assert wl["prev_opened"] == "2026-08-01T10:00:00"
    assert wl["last_opened"] == "2026-08-02T10:00:00"
    assert state["selected_watchlist"] == "roofing-anywhere"
