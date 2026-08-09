"""FACTS — every executed state contract, and the date each one runs out.

`src/contracts.py` says it plainly: knowing what is out for bid today tells you
about work you are already late to scope; knowing the incumbent's contract ends
in February tells you about work nobody has advertised yet. Bonfire supplies
that for 32 local agencies. This supplies it for the state.

FACTS is the Florida Accountability Contract Tracking System, run by the
Department of Financial Services under **s. 215.985(14)**, which requires every
state entity to post each executed contract within 30 days with its parties,
dates, procurement method, total compensation and the statutory justification
if it was not competitively bid. The same statute, at s. 215.985(2)(d), defines
the website it must go on as one "easily accessible to the public at no cost"
that "does not require the user to provide information" — an anti-registration
wall written into law. There is no robots.txt, and the search page's own terms
are a scope note about what FACTS contains, with nothing about access.

**Live count on 7 Aug 2026: 10,295 state contracts expiring within a year,
across 31 agencies.** For comparison the whole local register is 4,403.

## Getting it out in two requests

The search is ASP.NET WebForms and pages ten rows at a time, which for 63,515
matching contracts would be 6,352 requests. It also has a **Download Results**
link, which is a postback that returns the entire result set as CSV — 52 columns
including the dates, the vendor, the status and the method of procurement.

So a refresh is two POSTs: one to run the search, one to export it. The second
takes about 50 seconds and returns roughly 53 MB. That is why this runs from
`python -m src.cli contracts --refresh` on a weekly cadence and never from the
scheduler, exactly as the Bonfire register does.

## Why the search window looks the way it does

The form's two date fields are **begin ≥ B and end ≤ E**, not a window on the
end date — checked rather than assumed: asking for 08/07/2026 to 08/07/2027
returns 17 contracts statewide, which is the number that both start *and*
finish inside twelve months. There is no way to ask the server for "ending
after today", so the end date is bounded above by the horizon and the
already-expired rows are dropped here.

`DEFAULT_BEGIN_YEAR` is the lever that decides how much gets downloaded, and it
was chosen by measuring rather than guessing. Of the 10,295 contracts expiring
within a year:

    begin >= 2016   keeps 10,294   (100%)
    begin >= 2020   keeps 10,294   (100%)
    begin >= 2022   keeps  9,249    (90%)
    begin >= 2024   keeps  6,437    (63%)

2020 is where the curve flattens: it loses one contract in ten thousand and
halves the transfer against 2016. A deployment that wants the last one can move
it back and pay for it.

## Two traps in the data

* **`New End Date` supersedes `Original End Date`, and 21% of rows have one.**
  An amendment extends a contract without touching the original column. Reading
  only `Original End Date` reports 2,146 of these 10,295 as expiring on a date
  that has already been renegotiated — the failure being an alert for a rebid
  that is not happening, which is worse than silence.
* **The CSV is not always well-formed.** At least one row carries a stray `""`
  that shifts its fields, so `Status` arrives holding part of a contract title.
  A malformed row is skipped rather than allowed to abort a 63,000-row parse.

## Amount and method

Both are carried, because a date alone cannot rank ten thousand contracts: a
$40M highway job and a $4,000 canine agreement expire on the same day and are
not the same lead. `Total Amount` falls back to `Original Contract Amount`,
since an amendment writes the former and leaves the latter — the same shape as
the two end-date columns.

`Method of Procurement` is the second half of the signal. A rebid that was
competitively bid last time is an opening; one recorded as "Non-competitively
awarded grants to governmental entities" — 905 of the contracts expiring within
a year — mostly is not. Its values are long, carrying the statutory citation on
the tail: 9% exceed 128 characters and the longest is 300.

Live on 7 Aug 2026: 82% of rows carry an amount, 100% carry a method, and the
largest expiry inside 120 days is a $7.1B Statewide Medicaid Managed Care
contract ending 30 September — against a $4,000 canine agreement ending the
same week.
"""

from __future__ import annotations

import csv
import io
from datetime import date
from typing import Any, Dict, Iterable, List, Optional

from bs4 import BeautifulSoup

from ..contracts import Contract, parse_date
from ..http_util import get, session
from ..models.opportunity import Opportunity
from ..netpolicy import check
from .base import SourceAdapter

SEARCH_URL = "https://facts.fldfs.com/Search/ContractSearch.aspx"
DETAIL_URL = "https://facts.fldfs.com/Search/ContractDetail.aspx"

#: `rblSrchOption` — the form also serves grants and purchase orders. Contracts
#: are the ones with a term that ends, which is the whole point here.
CONTRACTS_ONLY = "C"

#: Earliest contract start to ask for. See the module docstring: measured, not
#: guessed. Override per deployment with `facts_begin_year` in the source config.
DEFAULT_BEGIN_YEAR = 2020

#: How far ahead to ask for expiries. Wider than `contracts.DEFAULT_HORIZON_DAYS`
#: so a horizon change does not silently need a re-tuned search.
DEFAULT_HORIZON_DAYS = 400

#: Form fields the search needs. Sent complete and blank-by-default: ASP.NET
#: reads absent fields as absent rather than empty, and the page refuses a
#: search with no criteria at all ("At least one search criteria must be
#: provided"), so the date pair is doing double duty as the criterion.
_BLANK_FORM = {
    "ctl00$PC$ddlAgency": "",
    "ctl00$PC$txtVendorName": "",
    "ctl00$PC$txtConntractValueFrom": "",
    "ctl00$PC$txtConntractValueTo": "",
    "ctl00$PC$txtBeginDate": "",
    "ctl00$PC$txtEndDate": "",
    "ctl00$PC$ddlCommodityGroup": "",
    "ctl00$PC$rblSrchOption": CONTRACTS_ONLY,
    "ctl00$PC$txtAgencyContractId": "",
    "ctl00$PC$txtGrantId": "",
    "ctl00$PC$txtPOId": "",
}

#: The postback behind "Download Results".
EXPORT_TARGET = "ctl00$PC$hlkExport"

#: The agency dropdown, whose values are the `AgencyId` a detail URL needs. The
#: export names agencies but never numbers them, so the two are joined here to
#: make each row link to its own contract page rather than to the search form.
AGENCY_SELECT_ID = "PC_ddlAgency"

EMPTY_NOTE = (
    "contract register, not a bid feed — FACTS holds executed state contracts; "
    "open state solicitations come from MyFloridaMarketPlace"
)


class FactsAdapter(SourceAdapter):
    """The state contract register. One source for all 31 reporting agencies."""

    #: Executed contracts are not solicitations, so this must never stand in for
    #: an agency's live coverage or supersede a catalog pointer.
    provides_open_bids = False

    #: There is no per-solicitation detail to enrich; the detail page belongs to
    #: a contract, and contracts are not on the board.
    supports_detail = False

    def __init__(self, cfg: Dict[str, Any]):
        super().__init__(cfg)
        self._s = None

    # -- public ------------------------------------------------------------

    def fetch(self) -> List[Opportunity]:
        """Nothing. FACTS publishes awards already executed, never open bids."""
        self.empty_note = EMPTY_NOTE
        return []

    def fetch_contracts(self) -> List[Contract]:
        """Every state contract ending between today and the horizon.

        Two POSTs — run the search, then export it — and the already-expired
        rows are dropped here because the form cannot express a lower bound on
        the end date.
        """
        today = date.today()
        soup = self._search_page()
        if soup is None:
            return []

        criteria = self._criteria(today)
        results = self._post(soup, {**criteria, "ctl00$PC$btnSearch": "Search"})
        if results is None:
            return []

        total = _reported_total(results)
        agency_ids = agency_codes(soup)

        export = self._post(
            results,
            {**criteria, "__EVENTTARGET": EXPORT_TARGET, "__EVENTARGUMENT": ""},
            raw=True,
        )
        if export is None:
            self.degraded_reason = "the search ran but the export did not return"
            return []

        rows = list(parse_export(export))
        if total and not rows:
            self.degraded_reason = f"the search reported {total} contracts and the export parsed none"

        out = [c for c in (self._to_contract(r, agency_ids) for r in rows) if c is not None]
        return [c for c in merge_duplicates(out) if c.end_date and c.end_date >= today]

    # -- internals ---------------------------------------------------------

    def _begin_year(self) -> int:
        try:
            return int(self.cfg.get("facts_begin_year") or DEFAULT_BEGIN_YEAR)
        except (TypeError, ValueError):
            return DEFAULT_BEGIN_YEAR

    def _horizon_days(self) -> int:
        try:
            return int(self.cfg.get("facts_horizon_days") or DEFAULT_HORIZON_DAYS)
        except (TypeError, ValueError):
            return DEFAULT_HORIZON_DAYS

    def _criteria(self, today: date) -> Dict[str, str]:
        from datetime import timedelta

        end = today + timedelta(days=self._horizon_days())
        return {
            **_BLANK_FORM,
            "ctl00$PC$txtBeginDate": f"01/01/{self._begin_year()}",
            "ctl00$PC$txtEndDate": end.strftime("%m/%d/%Y"),
        }

    def _session(self):
        if self._s is None:
            self._s = session()
        return self._s

    def _search_page(self) -> Optional[BeautifulSoup]:
        try:
            return BeautifulSoup(get(SEARCH_URL, s=self._session(), timeout=60).text, "lxml")
        except Exception:  # noqa: BLE001 — one register missing is not the run
            self.degraded_reason = "the search page could not be read"
            return None

    def _post(self, soup: BeautifulSoup, fields: Dict[str, str], *, raw: bool = False):
        """Post the form back, carrying this page's hidden state forward."""
        form = hidden_fields(soup)
        if "__VIEWSTATE" not in form:
            return None
        form.update(fields)

        check(SEARCH_URL)
        try:
            # The export is ~53 MB and about fifty seconds of server time, so
            # the timeout is generous by intent rather than by oversight.
            resp = self._session().post(SEARCH_URL, data=form, timeout=300)
            resp.raise_for_status()
        except Exception:  # noqa: BLE001
            return None
        return resp.content if raw else BeautifulSoup(resp.text, "lxml")

    def _to_contract(self, row: Dict[str, str], agency_ids: Dict[str, str]) -> Optional[Contract]:
        contract_id = (row.get("Agency Contract ID") or "").strip()
        agency = (row.get("Agency Name") or "").strip()
        name = (row.get("Long Title/PO Title") or "").strip() or (
            row.get("Short Title") or ""
        ).strip()
        if not contract_id or not agency or not name:
            return None

        agency_id = agency_ids.get(agency.upper())
        return Contract(
            # Agency-qualified, because the id alone is not unique: 516 contract
            # ids are used by more than one agency (AHCA and Justice
            # Administration both number things `SF030`). The store keys on
            # source plus contract id, and every FACTS row shares one source, so
            # a bare id would have those 516 silently overwrite each other. The
            # portal addresses a contract by the pair too — its detail page
            # takes both — so this is the identifier rather than a workaround.
            contract_id=f"{agency_id or _slug(agency)}:{contract_id}",
            agency=agency,
            name=name,
            source_id=self.source_id,
            vendor=_vendor(row),
            status_id=(row.get("Status") or "").strip()[:16] or None,
            amount=_money(row.get("Total Amount")) or _money(row.get("Original Contract Amount")),
            method=(row.get("Method of Procurement") or "").strip()[:320] or None,
            commodity=" ".join(p for p in (
                (row.get("Commodity/Service Type Code") or "").strip(),
                (row.get("Commodity/Service Type Description") or "").strip(),
            ) if p)[:200] or None,
            executed=_date(row.get("Contract Execution Date")),
            justification=(row.get("Contract Exemption Explanation") or "").strip() or None,
            state_term_id=(row.get("State Term Contract ID") or "").strip()[:64] or None,
            agency_ref=(row.get("Agency Reference Number") or "").strip()[:128] or None,
            start_date=_date(row.get("Begin Date")),
            end_date=end_date_of(row),
            url=_detail_url(agency_id, contract_id),
        )


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def hidden_fields(soup: BeautifulSoup) -> Dict[str, str]:
    """Every hidden input on the page, which is where ASP.NET keeps its state."""
    return {
        i["name"]: i.get("value", "")
        for i in soup.find_all("input", type="hidden")
        if i.get("name")
    }


def agency_codes(soup: BeautifulSoup) -> Dict[str, str]:
    """AGENCY NAME -> numeric id, from the search form's own dropdown.

    The export names agencies and never numbers them, and the detail page is
    addressed by number, so without this join every row would have to point at
    the search form instead of at the contract.
    """
    select = soup.find("select", id=AGENCY_SELECT_ID)
    if select is None:
        return {}
    out: Dict[str, str] = {}
    for option in select.find_all("option"):
        value = (option.get("value") or "").strip()
        label = option.get_text(" ", strip=True).upper()
        if value and label:
            out[label] = value
    return out


def parse_export(payload: bytes) -> Iterable[Dict[str, str]]:
    """Rows from the CSV export, skipping any the file itself has mangled.

    The export is not reliably quoted — a stray `""` inside a title shifts that
    row's remaining fields — so a row is yielded only when it still has the
    columns the mapping needs. Sixty-three thousand good rows should not be lost
    to one bad one.
    """
    text = (payload or b"").decode("utf-8-sig", errors="replace")
    if not text.strip():
        return []

    reader = csv.DictReader(io.StringIO(text))
    out: List[Dict[str, str]] = []
    for row in reader:
        # A shifted row loses its trailing columns to DictReader's None key.
        if None in row or "Agency Contract ID" not in row:
            continue
        out.append(row)
    return out


def merge_duplicates(contracts: List[Contract]) -> List[Contract]:
    """One record per contract, keeping the more complete of any pair.

    177 agency/id pairs appear twice in the export — the same contract entered
    against two FLAIR ids, one of them truncated ("WC052" beside "WC116",
    " P044" beside "P0448"). 29 of those pairs are identical and collapse
    harmlessly. The other 148 are not: one copy typically has no vendor named
    and sometimes an older end date, so *which* copy survives changes the
    answer. `Use of Outside Firing Range` is either an unnamed contract that
    expired in September 2025 — dropped from the register entirely — or the
    Osceola County Sheriff's Office through September 2026.

    So the survivor is chosen rather than left to insertion order: a named
    vendor beats an unnamed one, then the later end date wins. Both directions
    fail safe, since the risk is under-reporting a live contract as expired.
    """
    best: Dict[str, Contract] = {}
    for contract in contracts:
        current = best.get(contract.contract_id)
        if current is None or _completeness(contract) > _completeness(current):
            best[contract.contract_id] = contract
    return list(best.values())


def _completeness(contract: Contract) -> tuple:
    return (bool(contract.vendor), contract.end_date or date.min)


def end_date_of(row: Dict[str, str]) -> Optional[date]:
    """When the contract actually runs out.

    `New End Date` is written by an amendment and leaves `Original End Date`
    untouched, so the original is a historical fact rather than a deadline.
    2,146 of the 10,295 contracts expiring within a year carry one; trusting the
    original for those raises a rebid alert for a date already renegotiated.
    """
    return _date(row.get("New End Date")) or _date(row.get("Original End Date"))


def _date(value: Optional[str]) -> Optional[date]:
    """FACTS writes m/d/YYYY; `contracts.parse_date` reads ISO."""
    text = (value or "").strip()
    if not text:
        return None
    parts = text.split("/")
    if len(parts) == 3 and all(p.isdigit() for p in parts):
        month, day, year = parts
        return parse_date(f"{year}-{int(month):02d}-{int(day):02d}")
    return parse_date(text)


def _vendor(row: Dict[str, str]) -> Optional[str]:
    """The vendor name, which the export splits across two padded columns.

    Line 2 is a continuation on some rows and a restatement on others — the
    University of South Florida arrives as "UNIVERSITY OF SOUTH FLORIDA" and
    "THE UNIVERSITY OF SOUTH FLORIDA", which a naive join renders twice. So the
    two are concatenated only when neither already contains the other.
    """
    first = (row.get("Vendor/Grantor Name") or "").strip()
    second = (row.get("Vendor/Grantor Name Line 2") or "").strip()
    if not first or not second:
        return first or second or None
    a, b = first.lower(), second.lower()
    if a in b or b in a:
        return first if len(first) >= len(second) else second
    return f"{first} {second}"


def _money(value: Optional[str]) -> Optional[float]:
    """A dollar figure, or None. Never a guess.

    The export writes plain decimals, but not always: blanks, `$` and thousands
    separators all appear, and one row's shifted quoting puts a contract title
    where the amount should be. An unreadable figure is left absent rather than
    coerced to zero, which would sort a $40M contract to the bottom of the list.
    """
    text = (value or "").strip().replace("$", "").replace(",", "")
    if not text:
        return None
    try:
        amount = float(text)
    except ValueError:
        return None
    return amount if amount > 0 else None


def _slug(agency: str) -> str:
    """Fallback key when the dropdown did not name this agency."""
    return "".join(ch for ch in agency.lower() if ch.isalnum())[:32]


def _detail_url(agency_id: Optional[str], contract_id: str) -> Optional[str]:
    if not agency_id:
        return SEARCH_URL
    from urllib.parse import quote

    return f"{DETAIL_URL}?AgencyId={agency_id}&ContractId={quote(contract_id)}"


def _reported_total(soup: BeautifulSoup) -> Optional[int]:
    """What the page says it found, so a silent empty export is detectable."""
    el = soup.find("input", id="PC_pcContract_hdnTotalCount")
    if el is None:
        return None
    try:
        return int(el.get("value") or 0)
    except ValueError:
        return None
