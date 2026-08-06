"""Day 31: which tabulations become requestable, and how the request reads."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from src.pipeline.history import significant_tokens
from src.records import (
    has_posted_award,
    request_text,
    ripe_for_request,
    summarise,
)
from tests.conftest import make_opp

TODAY = date(2026, 8, 6)


def _closed(title="Roof Replacement", days_ago=40, **kw):
    """A solicitation whose bids were opened `days_ago` days back."""
    opened = datetime.combine(TODAY - timedelta(days=days_ago), datetime.min.time())
    return make_opp(title=title, status="closed", due_date=opened, **kw)


def _award(title, agency="Broward County"):
    return make_opp(title=title, status="award", agency=agency)


# -- what becomes a lead ---------------------------------------------------


def test_a_bid_opened_31_days_ago_is_requestable():
    (lead,) = ripe_for_request([_closed(days_ago=31)], today=TODAY)

    assert lead.ripe_on == TODAY
    assert lead.ripe_for_days == 0


def test_a_bid_opened_30_days_ago_is_still_exempt():
    """The sunset is at 30 days *after* opening — day 31 is the first day."""
    assert ripe_for_request([_closed(days_ago=30)], today=TODAY) == []


def test_an_open_bid_is_never_a_records_lead():
    assert ripe_for_request([make_opp(status="open")], today=TODAY) == []


def test_a_bid_with_no_due_date_cannot_be_dated():
    """No opening date, no clock — better silent than guessing."""
    assert ripe_for_request([make_opp(status="closed", due_date=None)], today=TODAY) == []


def test_a_very_old_bid_falls_out_of_the_window():
    assert ripe_for_request([_closed(days_ago=800)], today=TODAY) == []
    assert len(ripe_for_request([_closed(days_ago=800)], today=TODAY, max_age_days=2000)) == 1


def test_leads_are_sorted_newest_ripe_first():
    """A bid that crossed day 31 today beats one nobody chased for months."""
    leads = ripe_for_request(
        [_closed("Old Job", days_ago=200), _closed("Fresh Job", days_ago=31)],
        today=TODAY,
    )
    assert [lead.opportunity.title for lead in leads] == ["Fresh Job", "Old Job"]


# -- awards suppress the lead ----------------------------------------------


def test_a_posted_award_removes_the_lead():
    """The exemption lapsed at the notice; the award is the interesting record."""
    pool = [
        _closed("Roof Replacement at Fire Station 12", days_ago=40),
        _award("Roof Replacement at Fire Station 12"),
    ]
    assert ripe_for_request(pool, today=TODAY) == []


def test_an_award_for_a_different_buy_does_not_suppress():
    pool = [
        _closed("Janitorial Services Countywide", days_ago=40),
        _award("Roof Replacement at Fire Station 12"),
    ]
    assert len(ripe_for_request(pool, today=TODAY)) == 1


def test_an_award_from_another_agency_does_not_suppress():
    """Two counties buying the same thing are two different solicitations."""
    pool = [
        _closed("Roof Replacement at Fire Station 12", days_ago=40, agency="Broward County"),
        _award("Roof Replacement at Fire Station 12", agency="Miami-Dade County"),
    ]
    assert len(ripe_for_request(pool, today=TODAY)) == 1


def test_a_longer_restatement_of_the_title_still_matches():
    opp = _closed("Janitorial Services", days_ago=40)
    awards = {"broward county": [significant_tokens("Janitorial Services Citywide Contract")]}
    assert has_posted_award(opp, awards)


def test_an_untitled_solicitation_is_not_matched_by_accident():
    assert not has_posted_award(make_opp(title="RFP 2024"), {"broward county": [frozenset()]})


# -- the request text ------------------------------------------------------


def test_the_request_asks_for_a_copy_not_a_compilation():
    """*Seigle v. Barry*: an agency need not re-sort data. So never ask it to."""
    text = request_text(_closed(days_ago=40), today=TODAY)

    assert "119.01(2)(f)" in text
    assert "medium in which" in text
    assert "not asking that any list be" in text.replace("\n", " ")


def test_the_request_cites_the_lapsed_exemption():
    text = request_text(_closed(days_ago=40), today=TODAY)

    assert "119.071(1)(b)2" in text
    assert "30 days" in text


def test_the_request_demands_an_estimate_before_the_work():
    """s. 119.07(4)(d) charges are the real gatekeeper; get it in writing first."""
    text = request_text(_closed(days_ago=40), today=TODAY)

    assert "119.07(4)(d)" in text
    assert "before performing the work" in text


def test_the_request_names_the_solicitation_and_its_reference():
    opp = _closed("Roof Replacement", days_ago=40, external_id="ITB-24-001")
    text = request_text(opp, today=TODAY)

    assert "ITB-24-001" in text
    assert "Roof Replacement" in text
    assert "Broward County" in text


def test_the_requester_is_a_placeholder_until_supplied():
    assert "[your name" in request_text(_closed(), today=TODAY)
    assert "Nature Guard" in request_text(_closed(), requester="Nature Guard", today=TODAY)


# -- the summary line ------------------------------------------------------


def test_the_summary_counts_what_is_newly_ripe():
    leads = ripe_for_request([_closed("A", days_ago=31), _closed("B", days_ago=60)], today=TODAY)
    assert "2 tabulation(s) requestable" in summarise(leads)
    assert "1 newly ripe today" in summarise(leads)


def test_the_summary_says_so_when_there_is_nothing():
    assert summarise([]) == "no tabulations ripe for request"


# -- the digest ------------------------------------------------------------


def test_the_digest_reports_only_what_ripened_today(monkeypatch):
    """The backlog is real, but a daily email that repeats it goes unread."""
    from web.services import digest

    monkeypatch.setattr(digest, "ripe_for_request", lambda opps: ripe_for_request(opps, today=TODAY))

    result = digest._records_section([
        _closed("Ripe today", days_ago=31),
        _closed("Ripe last month", days_ago=90),
    ])
    count, html = result

    assert count == 1
    assert "Ripe today" in html
    assert "Ripe last month" not in html
    assert "119.071(1)(b)2" in html


def test_the_digest_says_nothing_when_nothing_ripened(monkeypatch):
    from web.services import digest

    monkeypatch.setattr(digest, "ripe_for_request", lambda opps: ripe_for_request(opps, today=TODAY))

    assert digest._records_section([_closed("Old news", days_ago=90)]) is None
