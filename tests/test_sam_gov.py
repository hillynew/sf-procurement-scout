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
        # First call is the solicitation query; the award pass follows it.
        captured.setdefault("params", dict(params))
        if params.get("ptype") == "a":
            return {"totalRecords": 0, "opportunitiesData": []}
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
        if params.get("ptype") == "a":
            return {"totalRecords": 0, "opportunitiesData": []}
        return fixture_payload  # totalRecords=2 < PAGE_SIZE → one call only

    monkeypatch.setattr("src.sources.sam_gov.get_json", fake_get_json)
    SamGovAdapter(CFG).fetch()
    # One solicitation page + one award page.
    assert [c.get("ptype") for c in calls] == ["o,k,p", "a"]


def test_award_notices_carry_the_structured_award(monkeypatch):
    """ptype=a rows map vendor, amount, date, and the solicitation linkage."""
    monkeypatch.setenv("SF_SCOUT_SAM_KEY", "test-key")

    award_row = {
        "title": "Runway Repair — Award",
        "noticeId": "n1",
        "solicitationNumber": "FA648726B0011",
        "postedDate": "2026-08-01",
        "type": "Award Notice",
        "active": "No",
        "fullParentPathName": "DEPT OF DEFENSE.DEPT OF THE AIR FORCE",
        "naicsCode": "237310",
        "classificationCode": "Z2AZ",
        "resourceLinks": ["https://sam.gov/api/prod/opps/v3/opportunities/resources/files/x/download"],
        "award": {
            "date": "2026-07-28",
            "number": "FA6487-26-C-0001",
            "amount": "1234567.89",
            "awardee": {"name": "Acme Paving LLC"},
        },
    }

    def fake_get_json(url, params=None, **kwargs):
        if params.get("ptype") == "a":
            return {"totalRecords": 1, "opportunitiesData": [award_row]}
        return {"totalRecords": 0, "opportunitiesData": []}

    monkeypatch.setattr("src.sources.sam_gov.get_json", fake_get_json)
    (opp,) = SamGovAdapter(CFG).fetch()

    assert opp.status == "award"
    assert opp.awarded_vendor == "Acme Paving LLC"
    assert opp.award_amount == 1234568
    assert str(opp.award_date) == "2026-07-28"
    assert opp.linked_ref == "FA648726B0011"
    assert opp.award_linkage == "ref"
    assert opp.commodity_codes == ["NAICS 237310", "PSC Z2AZ"]
    assert len(opp.documents) == 1
