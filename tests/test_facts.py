"""FACTS: the export, the two date traps, and the id that is not unique."""

from __future__ import annotations

from datetime import date, timedelta

from bs4 import BeautifulSoup

from src.contracts import expiring_within
from src.sources.facts import (
    CONTRACTS_ONLY,
    DEFAULT_BEGIN_YEAR,
    EXPORT_TARGET,
    FactsAdapter,
    agency_codes,
    end_date_of,
    hidden_fields,
    parse_export,
)

CFG = {
    "id": "facts",
    "name": "FACTS — Florida state contract register",
    "county": "statewide",
    "agency": "State of Florida",
    "portal_url": "https://facts.fldfs.com/Search/ContractSearch.aspx",
}

COLUMNS = [
    "Agency Name", "Vendor/Grantor Name", "Type", "Agency Contract ID", "PO Number",
    "Grant Award ID", "Vendor/Grantor Name Line 2", "Original Contract Amount",
    "Total Amount", "Long Title/PO Title", "Status", "Short Title",
    "Begin Date", "Original End Date", "New End Date", "Method of Procurement",
]

SEARCH_PAGE = """
<html><body><form>
  <input type="hidden" name="__VIEWSTATE" value="VS1"/>
  <input type="hidden" name="__VIEWSTATEGENERATOR" value="G1"/>
  <select id="PC_ddlAgency">
    <option value="">ALL AGENCIES</option>
    <option value="700000">DEPARTMENT OF CORRECTIONS</option>
    <option value="680000">AGENCY FOR HEALTH CARE ADMINISTRATION</option>
    <option value="210000">JUSTICE ADMINISTRATION</option>
  </select>
</form></body></html>
"""


def _csv(*rows):
    def cell(v):
        return f'"{v}"' if ("," in str(v) or '"' in str(v)) else str(v)

    lines = [",".join(COLUMNS)]
    for row in rows:
        lines.append(",".join(cell(row.get(c, "")) for c in COLUMNS))
    return ("\n".join(lines)).encode()


def _row(agency="DEPARTMENT OF CORRECTIONS", cid="A4895", title="Canine Tracking Assistance",
         vendor="CITY OF DELAND", vendor2="", begin="7/1/2024",
         original="6/30/2026", new="", status="Active"):
    return {
        "Agency Name": agency, "Agency Contract ID": cid, "Long Title/PO Title": title,
        "Vendor/Grantor Name": vendor, "Vendor/Grantor Name Line 2": vendor2,
        "Begin Date": begin, "Original End Date": original, "New End Date": new,
        "Status": status, "Total Amount": "6000000.00",
    }


def _results_page(total=2):
    return (
        '<html><body><form><input type="hidden" name="__VIEWSTATE" value="VS2"/>'
        f'<input type="hidden" name="PC_pcContract_hdnTotalCount" id="PC_pcContract_hdnTotalCount" value="{total}"/>'
        "</form></body></html>"
    )


# -- the export ------------------------------------------------------------


def test_hidden_state_is_carried_forward():
    fields = hidden_fields(BeautifulSoup(SEARCH_PAGE, "lxml"))
    assert fields["__VIEWSTATE"] == "VS1"
    assert fields["__VIEWSTATEGENERATOR"] == "G1"


def test_agency_codes_come_from_the_forms_own_dropdown():
    """The export names agencies and never numbers them; the detail page is
    addressed by number. Without the join every row links to the search form."""
    codes = agency_codes(BeautifulSoup(SEARCH_PAGE, "lxml"))

    assert codes["DEPARTMENT OF CORRECTIONS"] == "700000"
    assert "ALL AGENCIES" not in codes, "the blank option is not an agency"


def test_a_missing_dropdown_yields_no_codes():
    assert agency_codes(BeautifulSoup("<html></html>", "lxml")) == {}


def test_rows_come_out_of_the_csv():
    rows = list(parse_export(_csv(_row(), _row(cid="A9"))))
    assert len(rows) == 2
    assert rows[0]["Agency Contract ID"] == "A4895"


def test_an_empty_export_is_no_rows_not_a_crash():
    assert list(parse_export(b"")) == []
    assert list(parse_export(None)) == []


def test_a_mangled_row_is_skipped_rather_than_aborting_the_parse():
    """The export's quoting is not reliable — a stray `""` inside a title shifts
    that row's remaining fields. Sixty-three thousand good rows should not be
    lost to one bad one."""
    good = _csv(_row(cid="GOOD"))
    broken = good + b'\nDEPARTMENT OF CORRECTIONS,VENDOR,Type,BAD,,,,,,, Design Elevator Modernization"",x,y,z,extra,extra2,extra3\n'
    rows = list(parse_export(broken))

    assert [r["Agency Contract ID"] for r in rows] == ["GOOD"]


# -- the dates -------------------------------------------------------------


def test_a_new_end_date_supersedes_the_original():
    """An amendment writes New End Date and leaves the original untouched.

    2,146 of the 10,295 contracts expiring within a year carry one. Reading the
    original for those raises a rebid alert for a date already renegotiated.
    """
    assert end_date_of(_row(original="6/30/2026", new="6/30/2028")) == date(2028, 6, 30)


def test_the_original_end_date_is_used_when_there_is_no_amendment():
    assert end_date_of(_row(original="6/30/2026", new="")) == date(2026, 6, 30)


def test_a_contract_with_no_usable_end_date_is_dateless_not_wrong():
    assert end_date_of(_row(original="", new="")) is None
    assert end_date_of(_row(original="n/a", new="")) is None


def test_the_portals_american_dates_are_read_as_american():
    """7/1/2024 is July, not the first of the seventh week of something."""
    assert end_date_of(_row(original="7/1/2024")) == date(2024, 7, 1)
    assert end_date_of(_row(original="12/31/2027")) == date(2027, 12, 31)


# -- the adapter -----------------------------------------------------------


def _adapter(monkeypatch, export, *, total=2):
    a = FactsAdapter(CFG)
    posts = []

    class FakeSession:
        def post(self, url, data=None, timeout=None):
            posts.append(data)
            body = _results_page(total) if "ctl00$PC$btnSearch" in data else export
            return type("R", (), {
                "text": body if isinstance(body, str) else "",
                "content": body if isinstance(body, bytes) else b"",
                "status_code": 200, "raise_for_status": lambda self=None: None,
            })()

    monkeypatch.setattr("src.sources.facts.get",
                        lambda url, **kw: type("R", (), {"text": SEARCH_PAGE})())
    monkeypatch.setattr("src.sources.facts.check", lambda url: None)
    monkeypatch.setattr(FactsAdapter, "_session", lambda self: FakeSession())
    return a, posts


def test_a_row_becomes_a_contract(monkeypatch):
    future = (date.today() + timedelta(days=200)).strftime("%m/%d/%Y")
    a, _ = _adapter(monkeypatch, _csv(_row(original=future)))
    (contract,) = a.fetch_contracts()

    assert contract.agency == "DEPARTMENT OF CORRECTIONS"
    assert contract.name == "Canine Tracking Assistance"
    assert contract.vendor == "CITY OF DELAND"
    assert contract.source_id == "facts"
    assert contract.url == (
        "https://facts.fldfs.com/Search/ContractDetail.aspx?AgencyId=700000&ContractId=A4895"
    )


def test_the_contract_id_is_agency_qualified(monkeypatch):
    """516 contract ids are used by more than one agency — AHCA and Justice
    Administration both number things `SF030`. The store keys on source plus
    contract id and every FACTS row shares one source, so a bare id would have
    those 516 quietly overwrite each other.
    """
    future = (date.today() + timedelta(days=100)).strftime("%m/%d/%Y")
    export = _csv(
        _row(agency="AGENCY FOR HEALTH CARE ADMINISTRATION", cid="SF030",
             title="Theirs", original=future),
        _row(agency="JUSTICE ADMINISTRATION", cid="SF030", title="Ours", original=future),
    )
    a, _ = _adapter(monkeypatch, export)
    contracts = a.fetch_contracts()

    assert len({c.contract_id for c in contracts}) == 2
    assert {"680000:SF030", "210000:SF030"} == {c.contract_id for c in contracts}


def test_an_unknown_agency_still_gets_a_distinct_key(monkeypatch):
    """A new agency the dropdown has not caught up with must not collide."""
    future = (date.today() + timedelta(days=100)).strftime("%m/%d/%Y")
    a, _ = _adapter(monkeypatch, _csv(_row(agency="DEPARTMENT OF SOMETHING NEW",
                                           cid="SF030", original=future)))
    (contract,) = a.fetch_contracts()

    assert contract.contract_id.endswith(":SF030")
    assert not contract.contract_id.startswith(":")


def test_already_expired_contracts_are_dropped(monkeypatch):
    """The form has no lower bound on the end date, so the cut happens here."""
    past = (date.today() - timedelta(days=5)).strftime("%m/%d/%Y")
    future = (date.today() + timedelta(days=5)).strftime("%m/%d/%Y")
    a, _ = _adapter(monkeypatch, _csv(_row(cid="OLD", original=past),
                                      _row(cid="NEW", original=future)))
    contracts = a.fetch_contracts()

    assert [c.contract_id for c in contracts] == ["700000:NEW"]


def test_a_row_without_a_name_or_id_is_skipped(monkeypatch):
    future = (date.today() + timedelta(days=100)).strftime("%m/%d/%Y")
    a, _ = _adapter(monkeypatch, _csv(_row(title="", original=future),
                                      _row(cid="", original=future)))
    assert a.fetch_contracts() == []


def test_the_search_asks_for_contracts_only(monkeypatch):
    """The same form serves grants and purchase orders, which have no term."""
    a, posts = _adapter(monkeypatch, _csv(_row()))
    a.fetch_contracts()

    assert posts[0]["ctl00$PC$rblSrchOption"] == CONTRACTS_ONLY
    assert posts[0]["ctl00$PC$txtBeginDate"] == f"01/01/{DEFAULT_BEGIN_YEAR}"


def test_the_export_is_a_postback_not_a_second_search(monkeypatch):
    a, posts = _adapter(monkeypatch, _csv(_row()))
    a.fetch_contracts()

    assert len(posts) == 2, "one search, one export"
    assert posts[1]["__EVENTTARGET"] == EXPORT_TARGET
    assert posts[1]["__VIEWSTATE"] == "VS2", "the results page's state, not the form's"


def test_the_begin_year_is_configurable(monkeypatch):
    """The lever that trades transfer size against the oldest contracts."""
    a, posts = _adapter(monkeypatch, _csv(_row()))
    a.cfg["facts_begin_year"] = 2016
    a.fetch_contracts()

    assert posts[0]["ctl00$PC$txtBeginDate"] == "01/01/2016"


def test_a_nonsense_begin_year_falls_back(monkeypatch):
    a, posts = _adapter(monkeypatch, _csv(_row()))
    a.cfg["facts_begin_year"] = "not a year"
    a.fetch_contracts()

    assert posts[0]["ctl00$PC$txtBeginDate"] == f"01/01/{DEFAULT_BEGIN_YEAR}"


def test_a_search_that_found_rows_but_exported_none_is_reported(monkeypatch):
    """Silence from the export would otherwise look like an agency with no
    contracts, which is the failure mode worth naming."""
    a, _ = _adapter(monkeypatch, b"", total=63515)
    assert a.fetch_contracts() == []
    assert a.degraded_reason and "63515" in a.degraded_reason


def test_an_unreachable_search_page_is_reported(monkeypatch):
    a = FactsAdapter(CFG)

    def boom(url, **kw):
        raise RuntimeError("timeout")

    monkeypatch.setattr("src.sources.facts.get", boom)
    assert a.fetch_contracts() == []
    assert a.degraded_reason and "search page" in a.degraded_reason


# -- the vendor column -----------------------------------------------------


def test_a_split_vendor_name_is_rejoined(monkeypatch):
    future = (date.today() + timedelta(days=100)).strftime("%m/%d/%Y")
    a, _ = _adapter(monkeypatch, _csv(_row(vendor="FLORIDA TOURISM INDUSTRY MARKET",
                                           vendor2="VISIT FLORIDA", original=future)))
    (contract,) = a.fetch_contracts()

    assert contract.vendor == "FLORIDA TOURISM INDUSTRY MARKET VISIT FLORIDA"


def test_a_restated_vendor_name_is_not_doubled(monkeypatch):
    """Line 2 is a continuation on some rows and a restatement on others.

    USF arrives as "UNIVERSITY OF SOUTH FLORIDA" and "THE UNIVERSITY OF SOUTH
    FLORIDA", which a naive join renders twice.
    """
    future = (date.today() + timedelta(days=100)).strftime("%m/%d/%Y")
    a, _ = _adapter(monkeypatch, _csv(_row(vendor="UNIVERSITY OF SOUTH FLORIDA",
                                           vendor2="THE UNIVERSITY OF SOUTH FLORIDA",
                                           original=future)))
    (contract,) = a.fetch_contracts()

    assert contract.vendor == "THE UNIVERSITY OF SOUTH FLORIDA"


# -- how it fits -----------------------------------------------------------


def test_it_is_not_a_bid_feed(monkeypatch):
    a, _ = _adapter(monkeypatch, _csv(_row()))
    assert a.fetch() == []
    assert a.empty_note and "contract register" in a.empty_note


def test_it_cannot_supersede_an_agencys_catalog_pointer():
    """FACTS names 31 state agencies. Executed contracts are not coverage of
    what those agencies are buying today — MyFloridaMarketPlace is."""
    assert FactsAdapter.provides_open_bids is False


def test_the_register_flows_into_the_expiry_horizon(monkeypatch):
    """What the whole adapter is for: `expiring_within` is the consumer."""
    soon = (date.today() + timedelta(days=30)).strftime("%m/%d/%Y")
    later = (date.today() + timedelta(days=380)).strftime("%m/%d/%Y")
    a, _ = _adapter(monkeypatch, _csv(_row(cid="SOON", original=soon),
                                      _row(cid="LATER", original=later)))
    contracts = a.fetch_contracts()

    assert len(contracts) == 2
    assert [c.contract_id for c in expiring_within(contracts, days=365)] == ["700000:SOON"]


def test_the_scheduler_does_not_walk_facts():
    """53 MB and fifty seconds of server time has no business on the event loop,
    for the same reason the Bonfire register does not."""
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "web/services/scheduler.py").read_text()
    assert "facts" not in source.lower()


# -- the duplicate records -------------------------------------------------


def test_the_more_complete_of_two_records_wins(monkeypatch):
    """177 agency/id pairs appear twice, entered against two FLAIR ids.

    148 of them differ: one copy usually has no vendor and sometimes an older
    end date. Left to insertion order, `Use of Outside Firing Range` is either
    an unnamed contract that expired last September — dropped entirely — or the
    Osceola County Sheriff's Office through this one.
    """
    future = (date.today() + timedelta(days=100)).strftime("%m/%d/%Y")
    past = (date.today() - timedelta(days=300)).strftime("%m/%d/%Y")
    a, _ = _adapter(monkeypatch, _csv(
        _row(cid="IA24-1168", title="Use of Outside Firing Range", vendor="", original=past),
        _row(cid="IA24-1168", title="Use of Outside Firing Range",
             vendor="OSCEOLA COUNTY SHERIFF'S OFFICE", original=future),
    ))
    (contract,) = a.fetch_contracts()

    assert contract.vendor == "OSCEOLA COUNTY SHERIFF'S OFFICE"
    assert contract.end_date is not None and contract.end_date > date.today()


def test_the_better_record_wins_whichever_order_it_arrives_in(monkeypatch):
    future = (date.today() + timedelta(days=100)).strftime("%m/%d/%Y")
    past = (date.today() - timedelta(days=300)).strftime("%m/%d/%Y")
    a, _ = _adapter(monkeypatch, _csv(
        _row(cid="SA640", vendor="NOBLES GAS SERVICES, INC.", original=future),
        _row(cid="SA640", vendor="", original=past),
    ))
    (contract,) = a.fetch_contracts()

    assert contract.vendor == "NOBLES GAS SERVICES, INC."


def test_two_records_with_a_vendor_keep_the_later_end_date(monkeypatch):
    """A day's difference between two copies; under-reporting a live contract
    as expired is the failure worth avoiding."""
    soon = (date.today() + timedelta(days=30)).strftime("%m/%d/%Y")
    later = (date.today() + timedelta(days=31)).strftime("%m/%d/%Y")
    a, _ = _adapter(monkeypatch, _csv(
        _row(cid="LA-21-001", vendor="PRIDE ENTERPRISES", original=soon),
        _row(cid="LA-21-001", vendor="PRIDE ENTERPRISES", original=later),
    ))
    (contract,) = a.fetch_contracts()

    assert contract.days_until_expiry() == 31


def test_distinct_contracts_are_not_merged(monkeypatch):
    future = (date.today() + timedelta(days=100)).strftime("%m/%d/%Y")
    a, _ = _adapter(monkeypatch, _csv(_row(cid="A1", original=future),
                                      _row(cid="A2", original=future)))
    assert len(a.fetch_contracts()) == 2
