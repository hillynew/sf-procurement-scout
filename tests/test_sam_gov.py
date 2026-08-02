"""SAM.gov adapter: fixture mapping and the inert-without-key state."""

import json

import pytest

from src.sources.sam_gov import SamGovAdapter

CFG = {
    "id": "sam_gov_fl",
    "name": "SAM.gov federal bids (Florida)",
    "county": "federal",
    "agency": "U.S. Federal (SAM.gov)",
    "portal_url": "https://sam.gov/search/",
    "adapter": "sam_gov",
}


@pytest.fixture()
def fixture_payload(fixtures_dir):
    return json.loads((fixtures_dir / "sam_gov.json").read_text())


def test_inert_without_key(monkeypatch):
    for env in ("SF_SCOUT_SAM_KEY", "SAM_API_KEY"):
        monkeypatch.delenv(env, raising=False)
    adapter = SamGovAdapter(CFG)
    assert adapter.fetch() == []
    assert "SF_SCOUT_SAM_KEY" in adapter.empty_note


def test_fixture_mapping(monkeypatch, fixture_payload):
    monkeypatch.setenv("SF_SCOUT_SAM_KEY", "test-key")
    captured = {}

    def fake_get_json(url, params=None, **kwargs):
        captured["url"] = url
        captured["params"] = dict(params)
        return fixture_payload

    monkeypatch.setattr("src.sources.sam_gov.get_json", fake_get_json)
    adapter = SamGovAdapter(CFG)
    opps = adapter.fetch()

    assert captured["url"].startswith("https://api.sam.gov/opportunities/v2/search")
    assert captured["params"]["state"] == "FL"
    assert captured["params"]["ptype"] == "o,k,p"
    assert "/" in captured["params"]["postedFrom"]  # MM/dd/yyyy

    # Inactive notice filtered out.
    assert len(opps) == 1
    opp = opps[0]
    assert opp.title.startswith("Roof Replacement")
    assert opp.county == "federal"
    assert opp.external_id == "FA648726B0011"
    assert opp.url == "https://sam.gov/opp/abc123def456/view"
    assert opp.due_date is not None and opp.due_date.year == 2026
    assert opp.posted_date is not None
    assert opp.contact_email == "kt.officer@us.af.mil"
    assert opp.project_location == "Homestead, FL"
    assert "482 Cons" in (opp.department or "")
    # Description link is replaced with a readable meta line.
    assert "Set-aside: Total Small Business Set-Aside" in opp.description
    assert str(opp.offer_type) in ("construction", "OfferType.CONSTRUCTION")


def test_pagination_stops_at_total(monkeypatch, fixture_payload):
    monkeypatch.setenv("SF_SCOUT_SAM_KEY", "test-key")
    calls = []

    def fake_get_json(url, params=None, **kwargs):
        calls.append(dict(params))
        return fixture_payload  # totalRecords=2 < PAGE_SIZE → one call only

    monkeypatch.setattr("src.sources.sam_gov.get_json", fake_get_json)
    SamGovAdapter(CFG).fetch()
    assert len(calls) == 1
