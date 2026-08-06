"""The 72-hour protest clock and the day-31 records sunset."""

from __future__ import annotations

from datetime import date, datetime

import pytest

from src.protest import (
    business_hours_left,
    is_business_day,
    protest_deadline,
    records_ripe_on,
    state_holidays,
)


# -- state holidays --------------------------------------------------------


def test_the_fixed_holidays_are_listed():
    days = state_holidays(2026)
    assert date(2026, 7, 4) not in days or date(2026, 7, 3) in days  # 4th is a Saturday
    assert date(2026, 12, 25) in days  # Friday, observed as-is


def test_a_saturday_holiday_is_observed_the_friday_before():
    """s. 110.117(3). July 4 2026 falls on a Saturday."""
    days = state_holidays(2026)
    assert date(2026, 7, 3) in days
    assert date(2026, 7, 4) not in days


def test_a_sunday_holiday_is_observed_the_monday_after():
    """New Year's Day 2028 falls on a Saturday; 2023 fell on a Sunday."""
    assert date(2023, 1, 2) in state_holidays(2023)


def test_the_floating_holidays_land_on_the_right_mondays():
    days = state_holidays(2026)
    assert date(2026, 1, 19) in days  # MLK, 3rd Monday
    assert date(2026, 5, 25) in days  # Memorial, last Monday
    assert date(2026, 9, 7) in days  # Labor, 1st Monday


def test_thanksgiving_and_the_friday_after_are_both_holidays():
    """Florida takes both, which moves any deadline that spans them."""
    days = state_holidays(2026)
    assert date(2026, 11, 26) in days  # 4th Thursday
    assert date(2026, 11, 27) in days


def test_a_weekend_is_not_a_business_day():
    assert not is_business_day(date(2026, 8, 8))  # Saturday
    assert not is_business_day(date(2026, 8, 9))  # Sunday
    assert is_business_day(date(2026, 8, 10))  # Monday


# -- the protest deadline --------------------------------------------------


def test_a_monday_posting_is_due_thursday():
    """Three clear business days, same time of day."""
    posted = datetime(2026, 8, 3, 14, 30)  # Monday
    assert protest_deadline(posted) == datetime(2026, 8, 6, 14, 30)  # Thursday


def test_a_thursday_posting_skips_the_weekend():
    """Posted Thursday, due Tuesday — Saturday and Sunday do not count."""
    posted = datetime(2026, 8, 6, 16, 0)  # Thursday
    assert protest_deadline(posted) == datetime(2026, 8, 11, 16, 0)  # Tuesday


def test_a_holiday_inside_the_window_pushes_the_deadline_out():
    """Labor Day 2026 is Monday 7 September."""
    posted = datetime(2026, 9, 3, 9, 0)  # Thursday before Labor Day
    # Fri (1), Mon is Labor Day and does not count, Tue (2), Wed (3).
    assert protest_deadline(posted) == datetime(2026, 9, 9, 9, 0)


def test_a_posting_on_a_weekend_starts_counting_monday():
    """The clock cannot run on a day the statute excludes."""
    posted = datetime(2026, 8, 8, 10, 0)  # Saturday
    assert protest_deadline(posted) == datetime(2026, 8, 13, 10, 0)  # Thursday


def test_thanksgiving_week_costs_two_days():
    posted = datetime(2026, 11, 25, 12, 0)  # Wednesday before Thanksgiving
    # Thu and Fri are both holidays; Mon (1), Tue (2), Wed (3).
    assert protest_deadline(posted) == datetime(2026, 12, 2, 12, 0)


def test_no_posting_date_means_no_deadline():
    assert protest_deadline(None) is None


# -- time remaining --------------------------------------------------------


def test_hours_left_counts_down_within_a_business_day():
    deadline = datetime(2026, 8, 6, 17, 0)
    assert business_hours_left(deadline, now=datetime(2026, 8, 6, 14, 0)) == pytest.approx(3.0)


def test_hours_left_skips_a_weekend_in_between():
    """Friday 5pm to Monday 5pm is one business day, not three."""
    deadline = datetime(2026, 8, 10, 17, 0)  # Monday
    left = business_hours_left(deadline, now=datetime(2026, 8, 7, 17, 0))  # Friday
    assert left == pytest.approx(24.0)


def test_an_expired_deadline_reports_negative():
    """"Expired 3 hours ago" and "expires in 3 hours" are different situations."""
    deadline = datetime(2026, 8, 6, 12, 0)
    assert business_hours_left(deadline, now=datetime(2026, 8, 6, 15, 0)) == pytest.approx(-3.0)


def test_no_deadline_means_nothing_to_count():
    assert business_hours_left(None) is None


# -- the records sunset ----------------------------------------------------


def test_the_tabulation_is_requestable_on_day_31():
    """s. 119.071(1)(b)2 — calendar days, no business-day carve-out."""
    assert records_ripe_on(date(2026, 8, 1)) == date(2026, 9, 1)


def test_the_sunset_does_not_skip_weekends():
    """Unlike the protest clock, this one runs every day."""
    ripe = records_ripe_on(date(2026, 8, 6))
    assert (ripe - date(2026, 8, 6)).days == 31


def test_no_opening_date_means_no_trigger():
    assert records_ripe_on(None) is None


# -- the digest surfaces them ----------------------------------------------


def _award(title, deadline, **kw):
    from tests.conftest import make_opp

    return make_opp(title=title, status="award", protest_deadline=deadline, **kw)


def test_the_digest_leads_with_an_open_protest_window(monkeypatch):
    from web.services import digest

    now = datetime(2026, 8, 6, 12, 0)
    monkeypatch.setattr(digest, "business_hours_left",
                        lambda d, now=now: (d - now).total_seconds() / 3600)

    result = digest._award_section([
        _award("Award A", datetime(2026, 8, 6, 20, 0)),
        _award("Award B", datetime(2026, 8, 6, 15, 0)),
    ])
    count, html = result

    assert count == 2
    # Soonest first — the one with three hours left cannot sit under the one
    # with eight.
    assert html.index("Award B") < html.index("Award A")
    assert "120.57(3)(b)" in html


def test_an_expired_window_is_dropped_from_the_digest(monkeypatch):
    from web.services import digest

    now = datetime(2026, 8, 6, 12, 0)
    monkeypatch.setattr(digest, "business_hours_left",
                        lambda d, now=now: (d - now).total_seconds() / 3600)

    assert digest._award_section([_award("Gone", datetime(2026, 8, 6, 9, 0))]) is None


def test_ordinary_bids_never_reach_the_award_section():
    from tests.conftest import make_opp
    from web.services import digest

    assert digest._award_section([make_opp(title="A normal ITB", status="open")]) is None
