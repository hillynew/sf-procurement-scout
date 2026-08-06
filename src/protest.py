"""The two clocks Florida law puts on a procurement, and when they run out.

Both come out of the legal research, and both are deadlines rather than
nice-to-haves — the value of knowing about an intended award decays to nothing
within days of it posting.

**The 72-hour protest window.** Under s. 120.57(3)(b), a notice of protest is
due within 72 hours of the posting of a notice of intended decision, *excluding
Saturdays, Sundays, and state holidays*. For state agencies that posting is
electronic and statutorily required, which makes it the one event in this whole
system with a hard, short, legally-defined response time. An aggregator that
surfaces intended awards a week late has no protest value at all.

**Day 31.** Under s. 119.071(1)(b)2, sealed bids are exempt from disclosure
only until the agency notices an intended decision *or* 30 days after bid
opening, whichever is earlier. That is a self-executing sunset: on day 31 after
an opening with no posted award, the tabulation becomes a public record you can
simply ask for.

The holiday list is s. 110.117(1). The observed-day rule in
`_observed` is s. 110.117(3): a holiday falling on a Saturday is observed the
preceding Friday, and one falling on a Sunday the following Monday. That rule
matters here — it moves a deadline by a full day, and a protest filed a day
late is not filed.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from functools import lru_cache
from typing import Optional, Set

#: s. 120.57(3)(b). Expressed in hours because the statute is, but the clock
#: only runs on business days, so in practice this is three of them.
PROTEST_HOURS = 72

#: s. 119.071(1)(b)2 — the exemption lapses 30 days after opening, so the
#: request is ripe the day after.
RECORDS_RIPE_DAYS = 31


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """The nth <weekday> of a month; n = -1 for the last one."""
    if n > 0:
        d = date(year, month, 1)
        offset = (weekday - d.weekday()) % 7
        return d + timedelta(days=offset + 7 * (n - 1))

    d = date(year, month + 1, 1) - timedelta(days=1) if month < 12 else date(year, 12, 31)
    return d - timedelta(days=(d.weekday() - weekday) % 7)


def _observed(d: date) -> date:
    """s. 110.117(3): shift a weekend holiday to the adjacent weekday."""
    if d.weekday() == 5:  # Saturday -> preceding Friday
        return d - timedelta(days=1)
    if d.weekday() == 6:  # Sunday -> following Monday
        return d + timedelta(days=1)
    return d


@lru_cache(maxsize=None)
def state_holidays(year: int) -> frozenset:
    """Florida state holidays for one year, as observed. s. 110.117(1)."""
    thanksgiving = _nth_weekday(year, 11, 3, 4)  # 4th Thursday
    fixed = [date(year, 1, 1), date(year, 7, 4), date(year, 11, 11), date(year, 12, 25)]

    days: Set[date] = {_observed(d) for d in fixed}
    days |= {
        _nth_weekday(year, 1, 0, 3),  # MLK — 3rd Monday in January
        _nth_weekday(year, 5, 0, -1),  # Memorial — last Monday in May
        _nth_weekday(year, 9, 0, 1),  # Labor — 1st Monday in September
        thanksgiving,
        thanksgiving + timedelta(days=1),  # the Friday after
    }
    return frozenset(days)


def is_business_day(d: date) -> bool:
    """A day the protest clock runs: not a weekend, not a state holiday."""
    return d.weekday() < 5 and d not in state_holidays(d.year)


def protest_deadline(posted: Optional[datetime], hours: int = PROTEST_HOURS) -> Optional[datetime]:
    """When a notice of protest is due for a decision posted at `posted`.

    The statute says 72 hours excluding weekends and state holidays, which is
    counted as whole business days at the same time of day — post at 4pm
    Thursday and the deadline is 4pm the following Tuesday, because Saturday,
    Sunday and any holiday in between simply do not count.

    A posting that lands on a non-business day starts counting from the next
    business day, since the clock cannot run on a day the statute excludes.
    """
    if posted is None:
        return None

    remaining, cursor = hours // 24, posted
    # A notice posted Saturday does not start its clock until Monday.
    while not is_business_day(cursor.date()):
        cursor += timedelta(days=1)

    while remaining > 0:
        cursor += timedelta(days=1)
        if is_business_day(cursor.date()):
            remaining -= 1
    return cursor


def business_hours_left(deadline: Optional[datetime], now: Optional[datetime] = None) -> Optional[float]:
    """Hours until a protest deadline, counting only days the clock runs.

    Negative once it has passed, which is the number worth showing: "expired 3
    hours ago" and "expires in 3 hours" are different situations.
    """
    if deadline is None:
        return None
    now = now or datetime.now()
    if now >= deadline:
        return -_span_hours(deadline, now)
    return _span_hours(now, deadline)


def _span_hours(start: datetime, end: datetime) -> float:
    """Hours between two points, skipping whole non-business days."""
    if end <= start:
        return 0.0

    skipped = 0
    cursor = start.date() + timedelta(days=1)
    while cursor < end.date():
        if not is_business_day(cursor):
            skipped += 1
        cursor += timedelta(days=1)
    return (end - start).total_seconds() / 3600 - skipped * 24


def records_ripe_on(bid_opening: Optional[date], days: int = RECORDS_RIPE_DAYS) -> Optional[date]:
    """The date a sealed-bid tabulation stops being exempt, absent an award.

    s. 119.071(1)(b)2 is self-executing: nobody has to decide to release it,
    and no request is needed before this date because the exemption still
    applies. Calendar days — this sunset has no business-day carve-out.
    """
    if bid_opening is None:
        return None
    return bid_opening + timedelta(days=days)
