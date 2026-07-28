"""Date parsing — the layer every adapter depends on."""

from __future__ import annotations

from datetime import date, datetime

import pytest

from src.dates import default_anchor, looks_like_bare_date, parse_date, parse_dt


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("08/19/2026", datetime(2026, 8, 19, 0, 0)),
        ("7/27/2026 12:00:00 AM", datetime(2026, 7, 27, 0, 0)),
        ("August 19, 2026, 2:00 PM", datetime(2026, 8, 19, 14, 0)),
        ("2026-08-19T18:00:00", datetime(2026, 8, 19, 18, 0)),
    ],
)
def test_parses_portal_formats(raw, expected):
    assert parse_dt(raw) == expected


def test_eastern_abbreviations_are_understood():
    """Florida portals print 'EST'; dateutil warns and drops it without tzinfos."""
    dt = parse_dt("07/28/2026 02:00 PM EST")
    assert dt == datetime(2026, 7, 28, 14, 0)
    assert dt.tzinfo is None, "downstream comparisons assume naive datetimes"


def test_offset_is_converted_to_eastern_wall_clock():
    # 18:00 UTC is 13:00 Eastern standard time.
    assert parse_dt("2026-08-19T18:00:00+00:00") == datetime(2026, 8, 19, 13, 0)


@pytest.mark.parametrize("raw", [None, "", "   ", "n/a", "TBD", "see documents"])
def test_unparseable_values_return_none(raw):
    assert parse_dt(raw) is None


def test_parse_date_returns_date():
    assert parse_date("05/26/2026") == date(2026, 5, 26)
    assert parse_date(None) is None


def test_partial_date_anchors_to_current_year():
    """'August' used to resolve to a hardcoded 2026 regardless of the real year."""
    anchor = default_anchor()
    assert anchor.year == date.today().year
    assert parse_dt("August", default=anchor).year == date.today().year


@pytest.mark.parametrize("raw", ["8/10/2026", "12-31-2026", " 1/2/26 "])
def test_bare_dates_are_detected(raw):
    assert looks_like_bare_date(raw)


@pytest.mark.parametrize("raw", ["Sidewalk Improvements", "", None, "Roof Repair 8/10/2026"])
def test_real_titles_are_not_bare_dates(raw):
    assert not looks_like_bare_date(raw)
