"""Incumbent contracts: payload shapes, the vendor join, and expiry horizons."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from src.contracts import (
    Contract,
    by_vendor,
    expiring_within,
    index_vendors,
    parse_date,
    summarise,
)
from src.sources.bonfire import CONTRACTS_ENDPOINT, BonfireAdapter

TODAY = date(2026, 8, 6)

CFG = {
    "id": "bf_hills",
    "name": "Hillsborough County (Bonfire)",
    "county": "hillsborough",
    "agency": "Hillsborough County",
    "portal_url": "https://hillsboroughcounty.bonfirehub.com/portal/",
    "bonfire_host": "hillsboroughcounty.bonfirehub.com",
}


def _contract(name="Janitorial", ends="2026-09-05", vendor="ACME INC", cid="1"):
    return Contract(
        contract_id=cid, agency="Hillsborough County", name=name,
        source_id="bf_hills", vendor=vendor, end_date=parse_date(ends),
    )


# -- parsing ---------------------------------------------------------------


def test_a_portal_timestamp_becomes_a_date():
    assert parse_date("2024-04-30 04:00:00") == date(2024, 4, 30)


@pytest.mark.parametrize("value", [None, "", "n/a", "0000", 12345])
def test_unusable_dates_are_none_rather_than_wrong(value):
    assert parse_date(value) is None


def test_vendors_are_indexed_by_id():
    vendors = [
        {"VendorID": "7", "VendorContactOrganizationName": "FERGUSON WATERWORKS"},
        {"VendorID": "8", "VendorContactOrganizationName": "Graybar Electric"},
    ]
    assert index_vendors(vendors) == {"7": "FERGUSON WATERWORKS", "8": "Graybar Electric"}


def test_vendors_index_from_either_shape():
    """Contracts arrive keyed by id; there is no promise vendors stay a list."""
    keyed = {"7": {"VendorID": "7", "VendorContactOrganizationName": "ACME"}}
    assert index_vendors(keyed) == {"7": "ACME"}
    assert index_vendors(None) == {}


def test_a_vendor_without_a_name_is_not_indexed():
    assert index_vendors([{"VendorID": "9", "VendorContactOrganizationName": ""}]) == {}


# -- the adapter -----------------------------------------------------------


def _stub(monkeypatch, payload):
    monkeypatch.setattr(BonfireAdapter, "_payload", lambda self, ep, cookie=None: payload)


def test_contracts_are_read_from_an_object_keyed_by_id(monkeypatch):
    """`publicContracts` is keyed by ContractID — the same trap as `projects`.

    Treating it as a list yields id strings, which parse to nothing and report
    an agency with two thousand contracts as having none.
    """
    _stub(monkeypatch, {
        "publicContracts": {
            "158896": {"ContractID": "158896", "Name": "Consulting Liaison",
                       "VendorID": "42", "ContractStatusID": "3",
                       "StartDate": "2021-06-08 04:00:00", "EndDate": "2026-09-30 04:00:00"},
        },
        "vendors": [{"VendorID": "42", "VendorContactOrganizationName": "ACME INC"}],
    })
    (contract,) = BonfireAdapter(CFG).fetch_contracts()

    assert contract.contract_id == "158896"
    assert contract.name == "Consulting Liaison"
    assert contract.vendor == "ACME INC"
    assert contract.end_date == date(2026, 9, 30)
    assert contract.agency == "Hillsborough County"


def test_a_list_payload_is_also_accepted(monkeypatch):
    _stub(monkeypatch, {
        "publicContracts": [{"ContractID": "1", "Name": "Mowing", "VendorID": "42"}],
        "vendors": [{"VendorID": "42", "VendorContactOrganizationName": "ACME"}],
    })
    (contract,) = BonfireAdapter(CFG).fetch_contracts()
    assert contract.name == "Mowing"


def test_a_tenant_that_publishes_nothing_is_an_absence_not_a_fault(monkeypatch):
    """Five of twelve Florida tenants answer success:0 here."""
    def refuse(self, ep, cookie=None):
        raise RuntimeError("Bonfire API error: {'success': 0}")

    monkeypatch.setattr(BonfireAdapter, "_payload", refuse)
    assert BonfireAdapter(CFG).fetch_contracts() == []


def test_a_contract_without_a_name_or_id_is_skipped(monkeypatch):
    _stub(monkeypatch, {
        "publicContracts": {"1": {"ContractID": "1", "Name": ""},
                            "2": {"Name": "No id"}},
        "vendors": [],
    })
    assert BonfireAdapter(CFG).fetch_contracts() == []


def test_an_unknown_vendor_id_leaves_the_name_empty(monkeypatch):
    """Better an unnamed incumbent than a wrong one."""
    _stub(monkeypatch, {
        "publicContracts": {"1": {"ContractID": "1", "Name": "Mowing", "VendorID": "999"}},
        "vendors": [{"VendorID": "42", "VendorContactOrganizationName": "ACME"}],
    })
    (contract,) = BonfireAdapter(CFG).fetch_contracts()
    assert contract.vendor is None
    assert contract.vendor_id == "999"


def test_the_endpoint_name_is_the_documented_one():
    assert CONTRACTS_ENDPOINT == "getPublicContractsSectionData"


# -- expiry ----------------------------------------------------------------


def test_expiring_lists_soonest_first():
    rows = [_contract("Later", "2026-12-01"), _contract("Sooner", "2026-09-01")]
    assert [c.name for c in expiring_within(rows, today=TODAY)] == ["Sooner", "Later"]


def test_an_expired_contract_is_dropped():
    """A rebid you missed is history; this list exists for lead time."""
    assert expiring_within([_contract(ends="2026-01-01")], today=TODAY) == []


def test_a_contract_past_the_horizon_is_dropped():
    rows = [_contract(ends="2028-01-01")]
    assert expiring_within(rows, days=365, today=TODAY) == []
    assert len(expiring_within(rows, days=1000, today=TODAY)) == 1


def test_a_contract_with_no_end_date_cannot_be_scheduled():
    assert expiring_within([_contract(ends=None)], today=TODAY) == []


def test_days_until_expiry_counts_from_today():
    assert _contract(ends="2026-08-16").days_until_expiry(TODAY) == 10


def test_grouping_by_vendor_shows_who_holds_the_work():
    rows = [_contract("A", vendor="ACME"), _contract("B", vendor="ACME"),
            _contract("C", vendor="OTHER"), _contract("D", vendor=None)]
    grouped = by_vendor(rows)

    assert len(grouped["ACME"]) == 2
    assert len(grouped["OTHER"]) == 1
    assert None not in grouped


def test_the_summary_flags_the_imminent_ones():
    rows = [_contract("Soon", "2026-09-01"), _contract("Later", "2027-06-01")]
    line = summarise(rows, today=TODAY)

    assert "2 contract(s) expiring within a year" in line
    assert "1 within 90 days" in line


def test_the_summary_says_so_when_there_is_nothing():
    assert summarise([], today=TODAY) == "no contracts expiring in the next year"


# -- storage and the digest ------------------------------------------------


def test_contracts_round_trip_through_the_store():
    from src.db import store as dbstore
    from src.db.engine import init_db

    init_db()
    dbstore.save_contracts([_contract("Mowing", "2026-12-01", cid="7")])
    (loaded,) = dbstore.load_contracts()

    assert loaded.contract_id == "7"
    assert loaded.name == "Mowing"
    assert loaded.end_date == date(2026, 12, 1)


def test_a_refresh_updates_rather_than_duplicates():
    """Portals publish per tenant; a partial refresh must not delete the rest."""
    from src.db import store as dbstore
    from src.db.engine import init_db

    init_db()
    dbstore.save_contracts([_contract("Mowing", "2026-12-01", cid="7")])
    dbstore.save_contracts([_contract("Mowing (amended)", "2027-01-01", cid="7")])
    rows = dbstore.load_contracts()

    assert len(rows) == 1
    assert rows[0].name == "Mowing (amended)"


def test_two_agencies_can_share_a_contract_id():
    """ContractID is per-portal, so the key has to carry the source."""
    from src.db import store as dbstore
    from src.db.engine import init_db

    init_db()
    a = _contract("Theirs", "2026-12-01", cid="1")
    b = Contract(contract_id="1", agency="Marion County", name="Ours",
                 source_id="bf_marion", end_date=date(2026, 12, 1))
    dbstore.save_contracts([a, b])

    assert len(dbstore.load_contracts()) == 2


def test_the_digest_lists_contracts_about_to_run_out(monkeypatch):
    from web.services import digest

    monkeypatch.setattr(digest, "load_stored", lambda: [
        _contract("Janitorial Services", "2026-09-05", vendor="ACME INC"),
        _contract("Fleet Fuel", "2030-01-01", vendor="LATER LLC"),
    ])
    result = digest._contracts_section()
    count, html = result

    assert count == 1
    assert "Janitorial Services" in html
    assert "ACME INC" in html
    assert "Fleet Fuel" not in html, "a contract years out is not a lead"


def test_the_digest_stays_quiet_with_no_register(monkeypatch):
    from web.services import digest

    monkeypatch.setattr(digest, "load_stored", lambda: [])
    assert digest._contracts_section() is None


def test_the_scheduler_does_not_walk_registers_on_the_event_loop():
    """A full register walk is minutes of blocking HTTP; tick() is async.

    Doing it inline stalls the interval fetch, the deadline scan and the daily
    digest behind it — and made the scheduler tests hit the network. Contracts
    refresh from the CLI, on their own cadence, exactly as bid history does.
    """
    source = (Path(__file__).resolve().parents[1] / "web/services/scheduler.py").read_text()

    assert "refresh_contracts" not in source
    assert "src.contracts" not in source


# -- ranking the digest ----------------------------------------------------


def test_the_digest_leads_with_the_biggest_contracts(monkeypatch):
    """Three thousand of these fit in ten lines once the state register loads.

    Picked by date alone, a $4,000 canine agreement displaces a $40M highway
    contract expiring the same week.
    """
    from web.services import digest

    def _c(name, amount, ends="2026-09-05"):
        c = _contract(name, ends)
        c.amount = amount
        return c

    monkeypatch.setattr(digest, "load_stored", lambda: [
        _c("Canine Tracking Assistance", 4_000.0, "2026-09-01"),
        _c("SR 516 Resurfacing", 41_000_000.0, "2026-09-05"),
        _c("Janitorial Services", 250_000.0, "2026-09-03"),
    ])
    count, html = digest._contracts_section()

    assert count == 3
    assert html.index("SR 516") < html.index("Janitorial") < html.index("Canine")


def test_an_unpriced_contract_still_appears(monkeypatch):
    """Bonfire's register publishes no amounts. An unpriced lead is still a
    lead — it sorts after the priced ones rather than being dropped."""
    from web.services import digest

    priced = _contract("Priced", "2026-09-05")
    priced.amount = 10_000.0
    monkeypatch.setattr(digest, "load_stored", lambda: [
        _contract("Unpriced", "2026-09-01"), priced,
    ])
    count, html = digest._contracts_section()

    assert count == 2
    assert html.index("Priced") < html.index("Unpriced")


def test_the_amount_is_shown_in_units_a_person_reads():
    from web.services.digest import _money

    assert _money(41_000_000.0) == " · $41.0M"
    assert _money(250_000.0) == " · $250k"
    assert _money(4_000.0) == " · $4k"
    assert _money(750.0) == " · $750"
    assert _money(None) == ""
    assert _money(0.0) == ""


def test_amount_and_method_round_trip_through_the_store():
    from src.db import store as dbstore
    from src.db.engine import init_db

    init_db()
    c = _contract("Resurfacing", "2026-12-01", cid="9")
    c.amount = 41_000_000.0
    c.method = "Competitive Solicitation"
    dbstore.save_contracts([c])
    (loaded,) = dbstore.load_contracts()

    assert loaded.amount == 41_000_000.0
    assert loaded.method == "Competitive Solicitation"
