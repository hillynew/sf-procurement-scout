"""Shared date parsing for portal scrapes.

Every adapter had its own `_parse_dt` copy, and none of them handled the
US timezone abbreviations Florida portals print ("07/28/2026 02:00 PM EST"),
which made dateutil emit UnknownTimezoneWarning and silently drop the zone.

Deadlines on these portals are always local Eastern wall-clock time, and that
is what a bidder reads off the page, so we normalize to a naive datetime
carrying that wall clock rather than converting into the host's timezone.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from dateutil import parser as dateparser

# Eastern time is what these agencies publish; the others appear in the odd
# statewide notice. Offsets are in seconds, as dateutil expects.
TZINFOS = {
    "EST": -5 * 3600,
    "EDT": -4 * 3600,
    "ET": -5 * 3600,
    "CST": -6 * 3600,
    "CDT": -5 * 3600,
    "MST": -7 * 3600,
    "MDT": -6 * 3600,
    "PST": -8 * 3600,
    "PDT": -7 * 3600,
    "UTC": 0,
    "GMT": 0,
}

EASTERN = timezone(timedelta(hours=-5))

# Rows that are just a date, e.g. a portal that mis-files a date in the title.
_BARE_DATE_RE = re.compile(r"^\s*\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\s*$")

_PARSE_ERRORS = (ValueError, OverflowError, TypeError)


def parse_dt(value: Optional[str], *, default: Optional[datetime] = None) -> Optional[datetime]:
    """Parse a portal date string to a naive Eastern wall-clock datetime.

    Returns None rather than raising: a single unparseable cell should leave
    the opportunity dateless, not fail the whole source.
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        dt = dateparser.parse(text, tzinfos=TZINFOS, default=default)
    except _PARSE_ERRORS:
        return None
    if dt is None:
        return None
    if dt.tzinfo is not None:
        # Express the instant in Eastern, then drop the zone so all downstream
        # comparisons (status aging, days-until-due) stay naive-to-naive.
        dt = dt.astimezone(EASTERN).replace(tzinfo=None)
    return dt


def parse_date(value: Optional[str]) -> Optional[date]:
    dt = parse_dt(value)
    return dt.date() if dt else None


def default_anchor() -> datetime:
    """January 1st of the current year, for parsing partial dates like "August"."""
    return datetime(date.today().year, 1, 1)


def looks_like_bare_date(text: Optional[str]) -> bool:
    """True when a supposed title is really just a date the portal mis-filed."""
    return bool(text) and bool(_BARE_DATE_RE.match(text))
