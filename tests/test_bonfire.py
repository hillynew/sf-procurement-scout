"""Bonfire adapter: open listing, history, and the authenticated overlay."""

from __future__ import annotations

import os
from datetime import datetime

import pytest

from src.auth import ENV_BONFIRE_COOKIE
from src.sources.bonfire import BonfireAdapter

CFG = {
    "id": "broward_bpro",
    "name": "Broward County BPRO (Bonfire)",
    "county": "broward",
    "agency": "Broward County",
    "portal_url": "https://broward.bonfirehub.com/portal/?tab=openOpportunities",
    "bonfire_host": "broward.bonfirehub.com",
}


def _project(project_id="100", ref="ITB-1", name="Roof Repair", close="2026-08-19 18:00:00"):
    return {
        "ProjectID": project_id,
        "ReferenceID": ref,
        "ProjectName": name,
        "DateClose": close,
        "DepartmentID": "1",
    }


def _payload(*projects):
    return {
        "success": 1,
        "payload": {
            "projects": {p["ProjectID"]: p for p in projects},
            "departments": {"1": {"DepartmentName": "Public Works"}},
        },
    }


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for var in list(os.environ):
        if var.startswith(ENV_BONFIRE_COOKIE):
            monkeypatch.delenv(var, raising=False)


def _stub(monkeypatch, responses):
    """responses: dict endpoint -> payload dict."""

    def fake_payload(self, endpoint, *, cookie=None):
        data = responses[endpoint]
        if not data.get("success"):
            raise RuntimeError(f"Bonfire API error: {data}")
        return data.get("payload") or {}

    monkeypatch.setattr(BonfireAdapter, "_payload", fake_payload)


# ---------------------------------------------------------------------------
# Open listing
# ---------------------------------------------------------------------------


def test_open_opportunities_are_parsed(monkeypatch):
    _stub(monkeypatch, {"getOpenPublicOpportunitiesSectionData": _payload(_project())})
    (o,) = BonfireAdapter(CFG).fetch()
    assert o.title == "Roof Repair"
    assert o.external_id == "ITB-1"
    assert o.status == "open"
    # DateClose is UTC on the wire; 18:00Z on an August day is 2:00 PM EDT.
    assert o.due_date == datetime(2026, 8, 19, 14, 0)
    assert o.department == "Public Works"
    assert o.url == "https://broward.bonfirehub.com/opportunities/100"


def test_project_without_a_name_is_skipped(monkeypatch):
    empty = _project(name="")
    _stub(monkeypatch, {"getOpenPublicOpportunitiesSectionData": _payload(empty)})
    assert BonfireAdapter(CFG).fetch() == []


def test_api_error_response_raises(monkeypatch):
    _stub(monkeypatch, {"getOpenPublicOpportunitiesSectionData": {"success": 0, "message": "no"}})
    with pytest.raises(RuntimeError):
        BonfireAdapter(CFG).fetch()


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------


def test_history_is_marked_closed(monkeypatch):
    _stub(monkeypatch, {"getPastPublicOpportunitiesSectionData": _payload(_project())})
    (o,) = BonfireAdapter(CFG).fetch_history()
    assert o.status == "closed"


# ---------------------------------------------------------------------------
# Authenticated overlay (getMyOpportunitiesSectionData)
# ---------------------------------------------------------------------------


def test_no_cookie_means_public_list_only(monkeypatch):
    _stub(monkeypatch, {"getOpenPublicOpportunitiesSectionData": _payload(_project())})
    opps = BonfireAdapter(CFG).fetch()
    assert len(opps) == 1
    assert opps[0].personalized is False


def test_configured_cookie_adds_invited_opportunities(monkeypatch):
    monkeypatch.setenv(ENV_BONFIRE_COOKIE, "session=abc")
    _stub(
        monkeypatch,
        {
            "getOpenPublicOpportunitiesSectionData": _payload(_project("100", "ITB-1", "Roof Repair")),
            "getMyOpportunitiesSectionData": _payload(
                _project("200", "RFP-2", "Invited-Only Consulting Contract")
            ),
        },
    )
    opps = BonfireAdapter(CFG).fetch()
    assert len(opps) == 2
    invited = next(o for o in opps if o.external_id == "RFP-2")
    assert invited.personalized is True
    assert "invited" in invited.categories
    public = next(o for o in opps if o.external_id == "ITB-1")
    assert public.personalized is False


def test_a_project_visible_in_both_lists_is_tagged_not_duplicated(monkeypatch):
    monkeypatch.setenv(ENV_BONFIRE_COOKIE, "session=abc")
    same = _project("100", "ITB-1", "Roof Repair")
    _stub(
        monkeypatch,
        {
            "getOpenPublicOpportunitiesSectionData": _payload(same),
            "getMyOpportunitiesSectionData": _payload(dict(same)),
        },
    )
    opps = BonfireAdapter(CFG).fetch()
    assert len(opps) == 1
    assert opps[0].personalized is True
    assert "invited" in opps[0].categories


def test_an_expired_session_does_not_break_the_public_list(monkeypatch):
    """A stale cookie must degrade to public-only, not fail the whole fetch."""
    monkeypatch.setenv(ENV_BONFIRE_COOKIE, "session=expired")

    def fake_payload(self, endpoint, *, cookie=None):
        if endpoint == "getMyOpportunitiesSectionData":
            raise RuntimeError("Bonfire API error: session expired")
        return _payload(_project()).get("payload") or {}

    monkeypatch.setattr(BonfireAdapter, "_payload", fake_payload)
    opps = BonfireAdapter(CFG).fetch()
    assert len(opps) == 1
    assert opps[0].personalized is False


def test_host_specific_cookie_is_used_over_shared(monkeypatch):
    monkeypatch.setenv(ENV_BONFIRE_COOKIE, "shared=1")
    monkeypatch.setenv(f"{ENV_BONFIRE_COOKIE}_BROWARD", "broward=2")
    seen_cookies = []

    def fake_payload(self, endpoint, *, cookie=None):
        if endpoint == "getMyOpportunitiesSectionData":
            seen_cookies.append(cookie)
        return _payload(_project()).get("payload") or {}

    monkeypatch.setattr(BonfireAdapter, "_payload", fake_payload)
    BonfireAdapter(CFG).fetch()
    assert seen_cookies == ["broward=2"]


def test_missing_host_config_raises():
    bad_cfg = {**CFG, "bonfire_host": None}
    del bad_cfg["bonfire_host"]
    with pytest.raises(ValueError):
        BonfireAdapter(bad_cfg).fetch()


def test_past_awarded_row_becomes_award_status(monkeypatch):
    """SubStatus 3 / IsPublicAward is an award, not a generic closed row."""
    awarded = _project("300", "ITB-9", "Awarded Roofing")
    awarded["ProjectSubStatusID"] = "3"
    awarded["IsPublicAward"] = True
    _stub(monkeypatch, {"getPastPublicOpportunitiesSectionData": _payload(awarded)})
    (o,) = BonfireAdapter(CFG).fetch_history()
    assert o.status == "award"


def test_past_cancelled_row_becomes_cancelled_status(monkeypatch):
    cancelled = _project("301", "ITB-10", "Cancelled Roofing")
    cancelled["ProjectSubStatusID"] = "2"
    cancelled["IsPublicAward"] = False
    _stub(monkeypatch, {"getPastPublicOpportunitiesSectionData": _payload(cancelled)})
    (o,) = BonfireAdapter(CFG).fetch_history()
    assert o.status == "cancelled"


def test_contract_extendable_flag_is_captured(monkeypatch):
    payload = {
        "success": 1,
        "payload": {
            "publicContracts": {
                "10": {
                    "ContractID": "10",
                    "Name": "Janitorial",
                    "VendorID": "5",
                    "ContractStatusID": "2",
                    "StartDate": "2025-01-01 00:00:00",
                    "EndDate": "2027-01-01 00:00:00",
                    "IsExtendable": "1",
                }
            },
            "vendors": {"5": {"VendorID": "5", "VendorContactOrganizationName": "CleanCo"}},
        },
    }
    _stub(monkeypatch, {"getPublicContractsSectionData": payload})
    (c,) = BonfireAdapter(CFG).fetch_contracts()
    assert c.vendor == "CleanCo"
    assert c.extendable is True
