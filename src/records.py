"""Day 31: which bid tabulations have stopped being exempt, and how to ask.

Under s. 119.071(1)(b)2 sealed bids are exempt from disclosure only until the
agency notices an intended decision *or* 30 days after bid opening, whichever
is earlier. That is a self-executing sunset — nobody has to decide to release
anything, and on day 31 the tabulation is simply a public record.

That makes it a schedulable event rather than a research task, which is the
whole point: a bid that closed a month ago with no posted award has a
tabulation sitting in an agency's system that anyone may now have for the
asking, and knowing who won at what price is worth more than knowing what is
currently out for bid.

Two things this module is careful about.

**It only flags bids with no award.** If the agency has already noticed an
intended decision, the exemption lapsed at that notice and the interesting
document is the award, not a records request. Awards arrive as `status="award"`
rows (see `src.protest`), matched back to their solicitation on agency plus
title, reusing the recurrence matcher rather than inventing a second one.

**It asks for a copy, never a compilation.** s. 119.01(2)(f) entitles a
requester to a copy in the medium the agency maintains it in, but *Seigle v.
Barry*, 422 So. 2d 63 (Fla. 4th DCA 1982) says an agency need not re-sort or
restructure data on demand. Every modern procurement system has an export
button, so the export is a routinely-produced record — but the request has to
be phrased as "a copy of the record" and never as "a list of X". The wording in
`request_text` is deliberate, and the difference between the two framings is
the difference between a free copy and a quoted special service charge under
s. 119.07(4)(d).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Dict, Iterable, List, Optional, Sequence

from .models.opportunity import Opportunity
from .pipeline.history import significant_tokens, similarity
from .protest import RECORDS_RIPE_DAYS, records_ripe_on

#: Title overlap at which an award notice is taken to be *this* solicitation's
#: award. The same threshold the recurrence matcher uses, and for the same
#: reason: high enough to keep two roof jobs apart, low enough that a longer
#: restatement of one title still matches.
AWARD_MATCH_THRESHOLD = 0.7

#: Past this, an unawarded bid is old news rather than a live lead. A year of
#: lookback is plenty for the onboarding backfill the research describes.
MAX_AGE_DAYS = 365


@dataclass
class RecordsLead:
    """A closed solicitation whose tabulation is now requestable."""

    opportunity: Opportunity
    #: The day the exemption lapsed — opening + 30, so requestable from here.
    ripe_on: date
    #: Days since it became requestable. Zero means today.
    ripe_for_days: int

    @property
    def agency(self) -> str:
        return self.opportunity.agency


def _opening_date(opp: Opportunity) -> Optional[date]:
    """When bids were opened, as best the record shows.

    The statute keys off the *opening*, and most agencies open at the
    submission deadline — so the due date is the honest proxy. `bid_opening` is
    free text on this model ("2:00 PM, Room 512"), so it is not parsed here:
    guessing a date out of it would be worse than using the deadline we know.
    """
    if opp.due_date is not None:
        return opp.due_date.date()
    return None


def _awarded_agencies(opps: Sequence[Opportunity]) -> Dict[str, List[frozenset]]:
    """Award-notice title tokens, indexed by agency."""
    index: Dict[str, List[frozenset]] = {}
    for o in opps:
        if o.status != "award":
            continue
        tokens = significant_tokens(o.title)
        if tokens:
            index.setdefault(o.agency.lower(), []).append(tokens)
    return index


def has_posted_award(opp: Opportunity, awards: Dict[str, List[frozenset]]) -> bool:
    """True when an intended decision for this solicitation is already posted."""
    tokens = significant_tokens(opp.title)
    if not tokens:
        return False
    for other in awards.get(opp.agency.lower(), []):
        if similarity(tokens, other) >= AWARD_MATCH_THRESHOLD:
            return True
    return False


def ripe_for_request(
    opps: Iterable[Opportunity],
    *,
    today: Optional[date] = None,
    max_age_days: int = MAX_AGE_DAYS,
) -> List[RecordsLead]:
    """Closed solicitations whose tabulation is requestable and unawarded.

    Sorted newest-ripe first: a bid that crossed day 31 this morning is a
    better lead than one that crossed six months ago and was never chased.
    """
    today = today or date.today()
    pool = list(opps)
    awards = _awarded_agencies(pool)

    leads: List[RecordsLead] = []
    for opp in pool:
        if opp.status not in ("closed", "cancelled"):
            continue
        opening = _opening_date(opp)
        ripe = records_ripe_on(opening)
        if ripe is None or ripe > today:
            continue
        age = (today - ripe).days
        if age > max_age_days:
            continue
        if has_posted_award(opp, awards):
            continue
        leads.append(RecordsLead(opportunity=opp, ripe_on=ripe, ripe_for_days=age))

    leads.sort(key=lambda lead: lead.ripe_for_days)
    return leads


def request_text(
    opp: Opportunity,
    *,
    requester: str = "",
    today: Optional[date] = None,
) -> str:
    """A Chapter 119 request for one solicitation's tabulation.

    Phrased as a copy of an existing record in the medium it is kept in, which
    is what s. 119.01(2)(f) entitles you to and what keeps the agency's labour —
    and therefore its special service charge — near zero.
    """
    today = today or date.today()
    opening = _opening_date(opp)
    ref = opp.external_id or opp.title
    opened = f"{opening:%B %-d, %Y}" if opening else "the date of opening"

    who = requester.strip() or "[your name, business, and contact details]"
    return f"""\
Public records request — {opp.agency}
Re: {ref}

To the custodian of public records:

Under Chapter 119, Florida Statutes, I request a copy of the following records
concerning solicitation {ref} ({opp.title}), which was opened on {opened}:

  1. The bid tabulation for this solicitation.
  2. The plan-holder and addenda registry maintained for it under
     s. 255.0525(3), F.S., if one exists.

Pursuant to s. 119.01(2)(f), F.S., I request the copy in the medium in which
your office maintains the record — a native export from your procurement
system (CSV, XLSX, or your system's standard export output) is entirely
acceptable and is what I am asking for. I am not asking that any list be
compiled or that data be re-sorted or reformatted.

More than 30 days have passed since the opening of this solicitation and no
notice of intended decision appears to have been posted, so the exemption in
s. 119.071(1)(b)2, F.S. has lapsed by its own terms.

If any portion is withheld or redacted, please state the statutory basis for
each, as required by s. 119.07(1)(e), F.S. If you anticipate a special service
charge under s. 119.07(4)(d), F.S., please provide a written itemized estimate
before performing the work rather than after.

Requested {today:%B %-d, %Y} by {who}.
"""


def summarise(leads: Sequence[RecordsLead]) -> str:
    """One line for a log or a digest subject."""
    if not leads:
        return "no tabulations ripe for request"
    fresh = sum(1 for lead in leads if lead.ripe_for_days == 0)
    if fresh:
        return f"{len(leads)} tabulation(s) requestable, {fresh} newly ripe today"
    return f"{len(leads)} tabulation(s) requestable"


__all__ = [
    "AWARD_MATCH_THRESHOLD",
    "RECORDS_RIPE_DAYS",
    "RecordsLead",
    "has_posted_award",
    "request_text",
    "ripe_for_request",
    "summarise",
]
