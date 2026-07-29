"""Status normalization, deduplication and filtering."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from src.models.opportunity import HealthStatus
from src.pipeline.runner import (
    STALE_OPEN_DAYS,
    _classify_health,
    _normalize_status,
    dedupe,
    filter_opportunities,
)


class _FakeAdapter:
    source_id = "fake"
    name = "Fake Source"
    degraded_reason = None
    allows_empty = True
    empty_note = None


# ---------------------------------------------------------------------------
# Status normalization
# ---------------------------------------------------------------------------


def test_past_due_open_becomes_closed(opp_factory, past):
    o = opp_factory(due_date=past, status="open")
    _normalize_status([o])
    assert o.status == "closed"


def test_future_due_stays_open(opp_factory, soon):
    o = opp_factory(due_date=soon, status="open")
    _normalize_status([o])
    assert o.status == "open"


def test_timezone_aware_due_date_does_not_crash(opp_factory):
    from datetime import timezone

    o = opp_factory(
        due_date=datetime.now(timezone.utc) - timedelta(days=1), status="open"
    )
    _normalize_status([o])
    assert o.status == "closed"


def test_undated_open_ages_out(opp_factory):
    """MDC listed years-old solicitations as open because they carry no due date."""
    stale = date.today() - timedelta(days=STALE_OPEN_DAYS + 10)
    o = opp_factory(due_date=None, posted_date=stale, status="open")
    _normalize_status([o])
    assert o.status == "closed"


def test_recently_posted_undated_stays_open(opp_factory):
    o = opp_factory(due_date=None, posted_date=date.today() - timedelta(days=3), status="open")
    _normalize_status([o])
    assert o.status == "open"


def test_upcoming_status_is_left_alone(opp_factory, past):
    o = opp_factory(due_date=past, status="upcoming")
    _normalize_status([o])
    assert o.status == "upcoming"


# ---------------------------------------------------------------------------
# Health classification
# ---------------------------------------------------------------------------


def test_rows_fetched_is_ok(opp_factory):
    h = _classify_health(_FakeAdapter(), [opp_factory()], 10)
    assert h.status == HealthStatus.OK.value and h.ok


def test_zero_rows_is_empty_not_ok():
    """A silent zero-row parse used to report as a healthy source."""
    h = _classify_health(_FakeAdapter(), [], 10)
    assert h.status == HealthStatus.EMPTY.value
    assert h.note


def test_zero_rows_is_degraded_when_source_must_have_rows():
    adapter = _FakeAdapter()
    adapter.allows_empty = False
    h = _classify_health(adapter, [], 10)
    assert h.status == HealthStatus.DEGRADED.value
    assert not h.ok


def test_degraded_reason_wins_over_row_count(opp_factory):
    adapter = _FakeAdapter()
    adapter.degraded_reason = "city portal unreachable (403)"
    h = _classify_health(adapter, [opp_factory()], 10)
    assert h.status == HealthStatus.DEGRADED.value
    assert not h.ok
    assert "403" in h.note


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------


def test_same_reference_collapses(opp_factory, soon):
    rich = opp_factory(external_id="RFQ-2024-NL-07", due_date=soon, description="full text")
    thin = opp_factory(external_id="rfq 2024 nl 07", title="2024-NL-07 (announcement)")
    assert len(dedupe([rich, thin])) == 1


def test_duplicate_donates_missing_fields(opp_factory, soon):
    bare = opp_factory(external_id="ITB-99", description="a much longer description here")
    dated = opp_factory(external_id="ITB-99", due_date=soon, contact="buyer@county.gov")
    (kept,) = dedupe([bare, dated])
    assert kept.due_date == soon
    assert kept.contact == "buyer@county.gov"


def test_same_title_different_reference_is_kept(opp_factory):
    """A re-bid shares its title with the original but is a separate solicitation."""
    a = opp_factory(external_id="ITB-100", title="Janitorial Services")
    b = opp_factory(external_id="ITB-200", title="Janitorial Services")
    assert len(dedupe([a, b])) == 2


def test_same_title_collapses_when_reference_missing(opp_factory):
    a = opp_factory(external_id="ITB-100", title="Janitorial Services")
    b = opp_factory(external_id=None, title="janitorial   services")
    assert len(dedupe([a, b])) == 1


def test_same_title_across_counties_is_kept(opp_factory):
    a = opp_factory(county="broward", title="Roof Repair")
    b = opp_factory(county="palm-beach", agency="Town of Palm Beach", title="Roof Repair")
    assert len(dedupe([a, b])) == 2


def test_real_listing_beats_catalog_pointer(opp_factory, soon):
    catalog = opp_factory(external_id="ITB-2026-007", status="catalog", title="Register / browse")
    live = opp_factory(external_id="ITB-2026-007", status="open", due_date=soon)
    (kept,) = dedupe([catalog, live])
    assert kept.status == "open"


def test_short_reference_does_not_collapse_unrelated_bids(opp_factory):
    """A 3-4 character 'reference' is too weak a key to merge distinct listings."""
    a = opp_factory(external_id="A-1", title="Fence Repair")
    b = opp_factory(external_id="A-1", title="Tree Trimming")
    assert len(dedupe([a, b])) == 2


def test_dedupe_preserves_input_order(opp_factory):
    opps = [opp_factory(external_id=f"ITB-{i}", title=f"Bid {i}") for i in range(5)]
    assert [o.external_id for o in dedupe(opps)] == [o.external_id for o in opps]


def test_dedupe_of_empty_list():
    assert dedupe([]) == []


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------


def test_open_only_keeps_upcoming(opp_factory):
    opps = [
        opp_factory(status="open"),
        opp_factory(status="upcoming"),
        opp_factory(status="closed"),
        opp_factory(status="catalog"),
    ]
    assert len(filter_opportunities(opps, open_only=True)) == 2


def test_query_matches_reference(opp_factory):
    opps = [opp_factory(external_id="ITB-2026-042"), opp_factory(external_id="RFP-9")]
    assert len(filter_opportunities(opps, query="2026-042")) == 1


def test_county_filter_normalizes_spacing(opp_factory):
    opps = [opp_factory(county="palm-beach"), opp_factory(county="broward")]
    assert len(filter_opportunities(opps, county="Palm Beach")) == 1


def test_sorted_open_first_then_soonest_due(opp_factory):
    now = datetime.now()
    later = opp_factory(status="open", due_date=now + timedelta(days=30), title="Later")
    sooner = opp_factory(status="open", due_date=now + timedelta(days=2), title="Sooner")
    closed = opp_factory(status="closed", title="Closed")
    out = filter_opportunities([closed, later, sooner])
    assert [o.title for o in out] == ["Sooner", "Later", "Closed"]
