"""Bid history: matching open solicitations to prior cycles."""

from __future__ import annotations

from datetime import date, datetime

import pytest

from src.pipeline import history as history_mod
from src.pipeline.history import (
    BidHistory,
    annotate_recurrence,
    load_history,
    save_history,
    significant_tokens,
    similarity,
)


# ---------------------------------------------------------------------------
# Tokenising
# ---------------------------------------------------------------------------


def test_boilerplate_words_are_dropped():
    tokens = significant_tokens("Request for Proposals for Janitorial Services — City of Doral")
    assert "janitorial" in tokens
    assert not {"request", "proposals", "services", "city"} & tokens


def test_years_are_dropped_so_annual_rebids_match():
    """'Janitorial 2024' and 'Janitorial 2026' are the same recurring buy."""
    assert significant_tokens("Janitorial Contract 2024") == significant_tokens(
        "Janitorial Contract 2026"
    )


def test_reference_noise_is_dropped():
    assert significant_tokens("ITB 2026-014 Roof Replacement") == frozenset(
        {"roof", "replacement"}
    )


def test_a_title_of_pure_boilerplate_yields_nothing():
    assert significant_tokens("Request for Proposals") == frozenset()


@pytest.mark.parametrize("title", ["", None])
def test_empty_titles_are_safe(title):
    assert significant_tokens(title) == frozenset()


# ---------------------------------------------------------------------------
# Similarity
# ---------------------------------------------------------------------------


def test_containment_scores_full_for_a_longer_restatement():
    """A longer title containing a shorter one is the same buy, described more."""
    short = significant_tokens("Janitorial Services")
    long = significant_tokens("Janitorial Services Citywide Facilities")
    assert similarity(short, long) == 1.0


def test_unrelated_titles_score_low():
    a = significant_tokens("Janitorial Services")
    b = significant_tokens("Bridge Deck Reconstruction")
    assert similarity(a, b) == 0.0


def test_empty_sets_score_zero():
    assert similarity(frozenset(), significant_tokens("Roof Repair")) == 0.0


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------


_seq = iter(range(1, 10_000))


def _past(factory, title, closed, agency="Broward County"):
    """A closed solicitation. Each gets its own URL, as real portals do —
    identity is derived from it, so sharing one would look like the same row."""
    return factory(
        title=title,
        agency=agency,
        status="closed",
        due_date=closed,
        url=f"https://portal.gov/opportunities/{next(_seq)}",
    )


def test_a_repeat_buy_is_matched(opp_factory):
    hist = BidHistory(
        [
            _past(opp_factory, "Janitorial Services Citywide", datetime(2023, 5, 1)),
            _past(opp_factory, "Janitorial Services", datetime(2020, 5, 1)),
        ]
    )
    live = opp_factory(title="Janitorial Services", agency="Broward County", status="open")
    assert annotate_recurrence([live], hist) == 1
    assert live.prior_cycles == 2
    assert live.last_cycle_closed == date(2023, 5, 1)


def test_the_most_recent_cycle_is_reported(opp_factory):
    hist = BidHistory(
        [
            _past(opp_factory, "Tree Trimming", datetime(2019, 1, 1)),
            _past(opp_factory, "Tree Trimming", datetime(2024, 6, 1)),
        ]
    )
    live = opp_factory(title="Tree Trimming", agency="Broward County", status="open")
    annotate_recurrence([live], hist)
    assert live.last_cycle_closed == date(2024, 6, 1)


def test_another_agencys_history_does_not_match(opp_factory):
    """Each agency runs its own procurements; cadence is not transferable."""
    hist = BidHistory([_past(opp_factory, "Janitorial Services", datetime(2023, 5, 1))])
    live = opp_factory(title="Janitorial Services", agency="City of Doral", status="open")
    assert annotate_recurrence([live], hist) == 0
    assert live.prior_cycles == 0


def test_different_work_at_the_same_agency_does_not_match(opp_factory):
    hist = BidHistory([_past(opp_factory, "Bridge Deck Reconstruction", datetime(2023, 5, 1))])
    live = opp_factory(title="Janitorial Services", agency="Broward County", status="open")
    assert annotate_recurrence([live], hist) == 0


def test_similar_but_distinct_sites_stay_separate(opp_factory):
    """Roof work at two different stations is two jobs, not a recurrence."""
    hist = BidHistory([_past(opp_factory, "Roof Repairs Fire Station 12", datetime(2023, 1, 1))])
    live = opp_factory(
        title="Roof Repairs Water Treatment Plant", agency="Broward County", status="open"
    )
    assert annotate_recurrence([live], hist) == 0


def test_a_title_without_enough_signal_never_matches(opp_factory):
    hist = BidHistory([_past(opp_factory, "Request for Proposals", datetime(2023, 5, 1))])
    live = opp_factory(title="Request for Proposals", agency="Broward County", status="open")
    assert annotate_recurrence([live], hist) == 0


def test_an_opportunity_does_not_match_itself(opp_factory):
    live = opp_factory(title="Janitorial Services", agency="Broward County", status="open")
    assert annotate_recurrence([live], BidHistory([live])) == 0


def test_an_empty_archive_is_harmless(opp_factory):
    live = opp_factory(title="Janitorial Services", status="open")
    assert annotate_recurrence([live], BidHistory()) == 0
    assert live.prior_cycles == 0


def test_index_reports_its_agencies(opp_factory):
    hist = BidHistory(
        [
            _past(opp_factory, "Janitorial Services", datetime(2023, 1, 1), "Broward County"),
            _past(opp_factory, "Tree Trimming", datetime(2023, 1, 1), "City of Doral"),
        ]
    )
    assert hist.agencies == ["broward county", "city of doral"]
    assert len(hist) == 2


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


@pytest.fixture
def temp_history(tmp_path, monkeypatch):
    monkeypatch.setattr(history_mod, "history_path", lambda: tmp_path / "history.json")
    return tmp_path


def test_history_round_trips(temp_history, opp_factory):
    records = [_past(opp_factory, "Janitorial Services", datetime(2023, 5, 1))]
    save_history(records)
    restored = load_history()
    assert len(restored) == 1
    live = opp_factory(title="Janitorial Services", agency="Broward County", status="open")
    assert annotate_recurrence([live], restored) == 1


def test_a_missing_archive_yields_an_empty_index(temp_history):
    assert len(load_history()) == 0


def test_a_corrupt_archive_does_not_break_startup(temp_history):
    (temp_history / "history.json").write_text("{not json")
    assert len(load_history()) == 0


def test_an_unreadable_record_is_skipped_not_fatal(temp_history, opp_factory):
    import json

    good = _past(opp_factory, "Janitorial Services", datetime(2023, 5, 1))
    payload = {"records": [good.model_dump(mode="json"), {"garbage": True}]}
    (temp_history / "history.json").write_text(json.dumps(payload, default=str))
    assert len(load_history()) == 1


# ---------------------------------------------------------------------------
# Collection
# ---------------------------------------------------------------------------


class _HistoryAdapter:
    source_id = "fake"
    name = "Fake Bonfire"

    def __init__(self, records=None, boom=False):
        self._records = records or []
        self._boom = boom

    def fetch_history(self):
        if self._boom:
            raise RuntimeError("portal error")
        return self._records


class _NoHistoryAdapter:
    source_id = "plain"
    name = "Plain"


def test_only_sources_with_an_archive_are_asked(monkeypatch, opp_factory):
    rec = _past(opp_factory, "Janitorial Services", datetime(2023, 5, 1))
    monkeypatch.setattr(
        history_mod, "get_adapters", lambda **k: [_HistoryAdapter([rec]), _NoHistoryAdapter()],
        raising=False,
    )
    monkeypatch.setattr(
        "src.sources.registry.get_adapters",
        lambda **k: [_HistoryAdapter([rec]), _NoHistoryAdapter()],
    )
    assert len(history_mod.fetch_history(quiet=True)) == 1


def test_a_failing_source_does_not_abort_collection(monkeypatch, opp_factory):
    rec = _past(opp_factory, "Tree Trimming", datetime(2023, 5, 1))
    monkeypatch.setattr(
        "src.sources.registry.get_adapters",
        lambda **k: [_HistoryAdapter(boom=True), _HistoryAdapter([rec])],
    )
    assert len(history_mod.fetch_history(quiet=True)) == 1
