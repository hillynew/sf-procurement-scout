"""Miami-Dade BCC award matters from the Legislative Information Center.

Miami-Dade's Legistar instance is dead — frozen at 2018 — so the Legistar
adapter deliberately does not cover the county (see `legistar.py`). But the
county runs its own legislative record, the Legislative Information Center
("govaction"), with every Board of County Commissioners matter from 1996 to
the present: file number, introduced date, reference (R-/O- number), a Cost
field, and the full resolution text. Award approvals land there with the
vendor and the dollar figure in the title — "AWARD OF $31,366,638.18 TO H&R
PAVING, INC" (live-verified 2026-08-09) — which makes it the same product as
the Legistar awards feed, from the county's own site.

The search is a legacy ASP form, and it has one quirk worth recording: a
POST to ``searchleg.asp`` succeeds only when *every* text/select field of
the form is present (empty string when unused — mtkey, mtcost, mtref,
cborequest, cbotype, mttitle, cboStatus, mtdtpass, cboSponsor, mtAgendaDate,
mtSunsetDate, mtAgendaItemNo, mtSunsetexpdt) **and** the submit control
``btnSubmit=Search`` is included; the ``mtSunsetFlag`` checkbox is omitted
as an unchecked box would be. Anything else — and, confusingly, any search
with zero matches — gets the form re-served with "Please enter the
information you wish to search for". No cookies or viewstate are needed.

``mttitle`` searches the matter's *full* title, but the results table shows
the *short* title (the "File Name"), so rows like "SODIUM HYPOCHLORITE"
arrive for ``mttitle=award`` and are filtered out here on the word "award",
exactly as the Legistar adapter filters its own overbroad substring match.
The results table has no Cost column (all 5,338 award rows checked) and the
detail page's Cost field is typically blank even on nine-figure awards, so
the amount, vendor and reference are parsed out of the short title with the
same helpers Legistar titles go through. Everything comes back as one page,
newest first (file numbers are YYnnnn, ordered descending), so one POST is
the whole fetch and the bound is applied while walking rows.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Dict, List, Optional

from bs4 import BeautifulSoup

from ..classify import enrich
from ..dates import parse_dt
from ..http_util import session
from ..models.opportunity import Opportunity
from ..netpolicy import check
from .base import SourceAdapter
from .legistar import _AWARD_WORDS, _first_amount, _ref_from, _vendor_from

SEARCH_URL = "https://www.miamidade.gov/govaction/searchleg.asp"
MATTER_URL = "https://www.miamidade.gov/govaction/matter.asp?matter={}"

#: Awards are useful as intelligence for about a year (same window as the
#: Legistar feed); the archive back to 1996 stays on the server.
LOOKBACK_DAYS = 365
MAX_RECORDS = 100

#: The full field set the form posts. Every key must be present or the server
#: re-serves the form; `btnSubmit` doubles as navigation ("Home"), so its
#: value must be exactly "Search".
_FORM = {
    "mtkey": "",          # File Number
    "mtcost": "",         # Cost
    "mtref": "",          # Resolution/Ordinance number
    "cborequest": "",     # Requester
    "cbotype": "",        # File Type
    "mttitle": "",        # Title/Keyword — searches the full title
    "cboStatus": "",      # Status
    "mtdtpass": "",       # Final Action Date, MM-DD-YYYY
    "cboSponsor": "",     # Sponsor
    "mtAgendaDate": "",   # Board Agenda Date
    "mtSunsetDate": "",   # Effective Date
    "mtAgendaItemNo": "", # Agenda Item Number
    "mtSunsetexpdt": "",  # Expiration Date
    "btnSubmit": "Search",
}

_MATTER_HREF = re.compile(r"matter\.asp\?matter=(\d+)", re.I)
_ROW_DATE = re.compile(r"^\d{1,2}/\d{1,2}/\d{4}$")

#: Result-row short titles are ALL CAPS, which the shared vendor patterns are
#: deliberately case-sensitive against (they anchor on capitalized names in
#: mixed-case prose). Recasing the title and lowercasing the connectors gives
#: those patterns the shape they expect: "AWARD OF $31M TO H&R PAVING, INC"
#: becomes "Award of $31M to H&R Paving, Inc" and parses.
_CONNECTORS = re.compile(r"\b(To|With|The|And|Of|For|In|At|A|An)\b")


class MiamiDadeGovactionAdapter(SourceAdapter):
    """BCC award matters, searched by title on the county's own record."""

    #: A quiet stretch is conceivable and the window/word filter is narrow.
    allows_empty = True
    #: Awards only — must never supersede a live bid source for the county.
    provides_open_bids = False

    def fetch(self) -> List[Opportunity]:
        rows = _result_rows(_search("award"))
        if not rows:
            # Zero matches and an unrecognized POST are served identically —
            # the form again, with no results table. A title search that
            # matches five thousand matters of record cannot honestly return
            # nothing, so a rowless page means the search broke, not that the
            # county stopped awarding contracts.
            self.degraded_reason = (
                "searchleg.asp returned no result rows "
                "(form re-served or results layout changed)"
            )
            return []

        cutoff = date.today() - timedelta(days=LOOKBACK_DAYS)
        out: List[Opportunity] = []
        for row in rows:  # newest first: file numbers are YYnnnn, descending
            introduced = parse_dt(row.get("date") or "")
            if introduced and introduced.date() < cutoff:
                break
            opp = self._from_row(row)
            if opp is not None:
                out.append(opp)
            if len(out) >= MAX_RECORDS:
                break
        if not out:
            self.empty_note = "no award-titled matters in the lookback window"
        return out

    def _from_row(self, row: Dict[str, str]) -> Optional[Opportunity]:
        title = row.get("title") or ""
        # mttitle matched the full title; the short title shown in the row is
        # the record we keep, so the word test is applied to what we have.
        if not _AWARD_WORDS.search(title):
            return None

        introduced = parse_dt(row.get("date") or "")
        amount = _first_amount(title) or None  # never 0 — absent is None
        vendor = _vendor(title)
        ref = _ref_from(title)

        fields = enrich(title[:160], title, external_id=None)
        file_no = row.get("file_number") or row["matter"]
        return Opportunity(
            **self._base_kwargs(),
            external_id=file_no,
            title=title[:200],
            url=MATTER_URL.format(row["matter"]),
            solicitation_type=fields["solicitation_type"],
            offer_type=fields["offer_type"],
            categories=fields["categories"],
            keywords=fields["keywords"],
            status="award",
            posted_date=introduced.date() if introduced else None,
            award_date=introduced.date() if introduced else None,
            awarded_vendor=vendor,
            award_amount=amount,
            linked_ref=ref,
            award_linkage="ref" if ref else None,
            description=title[:600],
            raw={"govaction": row},
        )


def _search(title_contains: str) -> str:
    """POST the search with the full field set; returns the results HTML."""
    form = dict(_FORM)
    form["mttitle"] = title_contains
    check(SEARCH_URL)
    resp = session().post(
        SEARCH_URL,
        data=form,
        headers={"Referer": SEARCH_URL},
        # mttitle=award returns ~4 MB in one page; give the old ASP room.
        timeout=180,
    )
    resp.raise_for_status()
    return resp.text


def _result_rows(html: str) -> List[Dict[str, str]]:
    """Rows of the results table, keyed by what each cell actually holds.

    A result row is a ``<tr>`` whose cells are (observed live, all rows):
    blank, file number linking to ``matter.asp?matter=N``, introduced date,
    short title, blank, blank. Cells are identified by content rather than
    position so a cosmetic reshuffle does not silently zero the feed.
    """
    soup = BeautifulSoup(html, "lxml")
    rows: List[Dict[str, str]] = []
    seen: set = set()
    for a in soup.find_all("a", href=True):
        m = _MATTER_HREF.search(a["href"])
        if not m or m.group(1) in seen:
            continue
        tr = a.find_parent("tr")
        if tr is None:
            continue
        cells = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
        file_no = a.get_text(strip=True) or m.group(1)
        row_date = next((c for c in cells if _ROW_DATE.match(c)), "")
        rest = [c for c in cells if c and c != file_no and c != row_date]
        title = max(rest, key=len, default="")
        if len(title) < 4:
            continue
        seen.add(m.group(1))
        rows.append(
            {
                "matter": m.group(1),
                "file_number": file_no,
                "date": row_date,
                "title": re.sub(r"\s+", " ", title).strip(),
            }
        )
    return rows


def _vendor(title: str) -> Optional[str]:
    """The shared vendor parser, given an all-caps title in parseable case."""
    direct = _vendor_from(title)
    if direct or title != title.upper():
        return direct
    recased = _CONNECTORS.sub(lambda m: m.group(0).lower(), title.title())
    return _vendor_from(recased)
