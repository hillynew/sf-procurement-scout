"""Vendor Registry: an archive that is read, and a live feed that is declared gone."""

from __future__ import annotations

import pytest
from bs4 import BeautifulSoup

from src.sources.vendor_registry import (
    ARCHIVE_ROUTES,
    EMPTY_NOTE,
    VendorRegistryAdapter,
    archive_rows,
)

CFG = {
    "id": "vr_santa_rosa",
    "name": "Santa Rosa County (Vendor Registry archive)",
    "county": "santa-rosa",
    "agency": "Santa Rosa County",
    "portal_url": "https://vrapp.vendorregistry.com/Bids/View/ExpiredBidsList?BuyerId=abc",
    "vendor_registry_buyer": "2a63b069-a1a0-47e8-9417-6007f31792d0",
}

HEADERS = ["Type", "Description", "Status", "ID #", "Deadline", "Pre-Bid Meeting", "Docs"]


def _row(number="24-001", title="ITB 24-001 Woodlawn Beach Boat Launch",
         status="Deadline Expired", deadline="10/26/2023 10:00 AM",
         meeting="", docs="3", detail="24c44f64-73ae-4f59-98fb-baf43ad1040a"):
    link = (
        f'<a class="inside_table_link" href="/Bids/View/Bid/{detail}">{title}</a>'
        if detail else title
    )
    # The portal really does label both the status and deadline cells
    # `headers="thDeadline"`. Reproduced exactly, because it is the trap.
    return (
        "<tr>"
        '<td headers="thType">Sealed Solicitation</td>'
        f'<td headers="thName">{link}</td>'
        f'<td headers="thDeadline">{status}</td>'
        f'<td headers="thId">{number}</td>'
        f'<td headers="thDeadline">{deadline}</td>'
        f'<td headers="thMtg">{meeting}</td>'
        f'<td headers="thDocs">{docs}</td>'
        "</tr>"
    )


def _page(rows):
    head = "".join(f"<th>{h}</th>" for h in HEADERS)
    return (
        '<html><body><table id="buyer-solicitation-table">'
        f"<tr>{head}</tr>{''.join(rows)}</table></body></html>"
    )


EMPTY_CURRENT = (
    "<html><body><p>Currently, Santa Rosa County has no open solicitations.</p>"
    '<table id="buyer-solicitation-table">'
    + "".join(f"<th>{h}</th>" for h in HEADERS)
    + "</table></body></html>"
)


# -- parsing ---------------------------------------------------------------


def test_rows_are_read_by_header_position_not_the_headers_attribute():
    """Both the status and deadline cells are labelled `thDeadline`.

    An attribute-keyed read keeps whichever it visits second and loses the
    other, so a closed bid arrives with the words "Deadline Expired" where its
    date should be — or no date at all.
    """
    (row,) = archive_rows(BeautifulSoup(_page([_row()]), "lxml"))

    assert row["status"] == "Deadline Expired"
    assert row["deadline"] == "10/26/2023 10:00 AM"
    assert row["id #"] == "24-001"
    assert row["type"] == "Sealed Solicitation"


def test_the_detail_link_is_kept():
    (row,) = archive_rows(BeautifulSoup(_page([_row()]), "lxml"))
    assert row["detail_url"].endswith("/Bids/View/Bid/24c44f64-73ae-4f59-98fb-baf43ad1040a")


def test_a_row_without_a_detail_link_still_parses():
    (row,) = archive_rows(BeautifulSoup(_page([_row(detail="")]), "lxml"))
    assert "detail_url" not in row
    assert row["description"]


def test_a_missing_table_is_empty_not_an_error():
    assert archive_rows(BeautifulSoup("<html><body>down</body></html>", "lxml")) == []


def test_a_header_only_table_yields_nothing():
    assert archive_rows(BeautifulSoup(EMPTY_CURRENT, "lxml")) == []


# -- the archive -----------------------------------------------------------


def _adapter(monkeypatch, pages):
    """Serve one body per archive route, keyed by route."""
    a = VendorRegistryAdapter(CFG)
    seen = []

    def fake_get(url, **kwargs):
        route = url.split("?")[0].replace("https://vrapp.vendorregistry.com", "")
        seen.append(route)
        body = pages.get(route)
        if body is None:
            raise RuntimeError("404")
        return type("R", (), {"text": body, "status_code": 200})()

    monkeypatch.setattr("src.sources.vendor_registry.get", fake_get)
    monkeypatch.setattr(VendorRegistryAdapter, "_session", lambda self: None)
    return a, seen


def test_an_archived_row_becomes_a_closed_opportunity(monkeypatch):
    a, _ = _adapter(monkeypatch, {ARCHIVE_ROUTES[0]: _page([_row()])})
    (opp,) = a.fetch_history()

    assert opp.status == "closed"
    assert opp.external_id == "24-001"
    assert opp.due_date is not None and opp.due_date.year == 2023
    assert opp.agency == "Santa Rosa County"
    assert opp.url.startswith("https://vrapp.vendorregistry.com/Bids/View/Bid/")


def test_a_cancelled_solicitation_keeps_its_own_status(monkeypatch):
    """Okeechobee's archive really carries these, and "closed" would hide that
    the requirement was pulled rather than bought."""
    page = _page([_row(status="Cancelled", number="2025-07")])
    a, _ = _adapter(monkeypatch, {ARCHIVE_ROUTES[0]: page})
    (opp,) = a.fetch_history()

    assert opp.status == "cancelled"


def test_both_archive_routes_are_read(monkeypatch):
    """Expired holds anything past its deadline; NoDeadline holds standing ones.

    Every Florida buyer sampled had zero of the latter, which is a reason to
    read it cheaply, not a reason to assume it stays empty.
    """
    a, seen = _adapter(monkeypatch, {
        ARCHIVE_ROUTES[0]: _page([_row(number="A-1")]),
        ARCHIVE_ROUTES[1]: _page([_row(number="B-1", deadline="", detail="")]),
    })
    opps = a.fetch_history()

    assert set(seen) == set(ARCHIVE_ROUTES)
    assert {o.external_id for o in opps} == {"A-1", "B-1"}


def test_one_missing_route_does_not_lose_the_other(monkeypatch):
    a, _ = _adapter(monkeypatch, {ARCHIVE_ROUTES[0]: _page([_row()])})
    assert len(a.fetch_history()) == 1
    assert a.degraded_reason is None


def test_no_archive_at_all_is_reported(monkeypatch):
    a, _ = _adapter(monkeypatch, {})
    assert a.fetch_history() == []
    assert a.degraded_reason and "archive" in a.degraded_reason


def test_a_missing_buyer_id_is_a_config_error():
    cfg = {k: v for k, v in CFG.items() if k != "vendor_registry_buyer"}
    with pytest.raises(ValueError, match="vendor_registry_buyer"):
        VendorRegistryAdapter(cfg).fetch_history()


# -- the live feed that is not one -----------------------------------------


def test_fetch_returns_nothing_and_says_why(monkeypatch):
    """Fifteen buyers in five states report no open solicitations, including
    the platform's own flagship. An empty result with no explanation would read
    as a quiet agency; this is a platform that has moved on."""
    a, seen = _adapter(monkeypatch, {})

    assert a.fetch() == []
    assert a.empty_note == EMPTY_NOTE
    assert "archive only" in a.empty_note


def test_fetch_does_not_call_the_portal(monkeypatch):
    """The only possible answer is already recorded, so the round trip is waste."""
    a, seen = _adapter(monkeypatch, {})
    a.fetch()

    assert seen == []


def test_detail_is_not_claimed():
    """Every row is already closed; a detail pass changes no decision."""
    assert VendorRegistryAdapter.supports_detail is False


# -- what the archive is for -----------------------------------------------


def test_the_archive_joins_to_a_live_source_by_agency_name(monkeypatch):
    """The whole point. `history` keys on agency, not source id, so Vendor
    Registry's years back-fill recurrence for the OpenGov feed that replaced it.
    """
    from src.pipeline.history import BidHistory, annotate_recurrence
    from tests.conftest import make_opp

    page = _page([_row(number="21-004", title="Tree Trimming and Removal Services",
                       deadline="9/8/2022 2:00 PM")])
    a, _ = _adapter(monkeypatch, {ARCHIVE_ROUTES[0]: page})
    history = BidHistory(a.fetch_history())

    live = make_opp(title="Tree Trimming and Removal", agency="Santa Rosa County",
                    source_id="og_santarosafl")
    assert annotate_recurrence([live], history) == 1
    assert live.prior_cycles == 1
    assert live.last_cycle_closed is not None


def test_a_different_agency_does_not_borrow_the_history(monkeypatch):
    from src.pipeline.history import BidHistory, annotate_recurrence
    from tests.conftest import make_opp

    a, _ = _adapter(monkeypatch, {ARCHIVE_ROUTES[0]: _page([
        _row(title="Tree Trimming and Removal Services")])})
    history = BidHistory(a.fetch_history())

    other = make_opp(title="Tree Trimming and Removal", agency="Okeechobee County")
    assert annotate_recurrence([other], history) == 0


def test_the_indian_river_agency_name_is_a_name(monkeypatch):
    """The Bonfire tenant is `indianriver`, which the title-caser turned into
    "Indianriver" — and history joins on agency name, so that one word cost the
    county every prior cycle it had.
    """
    from src.sources.registry import get_adapters

    bonfire = get_adapters(only=["bonfire_indianriver"])[0]
    archive = get_adapters(only=["vr_indian_river"])[0]

    assert bonfire.agency == archive.agency == "Indian River County"


def test_an_archive_source_does_not_supersede_a_catalog_pointer():
    """Sebring's pointer says "register at BidNet Direct", which is where it
    posts now. An archive of what it bought in 2025 is not coverage of that,
    and dropping the pointer would leave the agency with nothing actionable.
    """
    from src.sources.registry import load_source_config, _superseded_catalog_ids

    configs = load_source_config()
    superseded = _superseded_catalog_ids(configs)

    assert "pp_sebring" not in superseded
    assert "bidnet_city-of-sebring" not in superseded


def test_a_live_adapter_still_supersedes_one():
    """The guard must not disarm the rule it is narrowing: Indian River County
    is fetched live from Bonfire, so its Public Purchase pointer is redundant.
    """
    from src.sources.registry import load_source_config, _superseded_catalog_ids

    assert "pp_irctrans" in _superseded_catalog_ids(load_source_config())


def test_the_flag_is_declared_on_the_adapter_not_hardcoded():
    from src.sources.base import SourceAdapter
    from src.sources.bonfire import BonfireAdapter

    assert SourceAdapter.provides_open_bids is True
    assert BonfireAdapter.provides_open_bids is True
    assert VendorRegistryAdapter.provides_open_bids is False
