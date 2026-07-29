"""The second pass that reads each bid's own page for scope, docs and terms."""

from __future__ import annotations

from datetime import datetime

import pytest

from src.models.opportunity import Document, Opportunity
from src.pipeline.runner import derive_fields, fetch_details
from src.sources.civicplus import CivicPlusAdapter
from src.sources.miami_dade_construction import MiamiDadeConstructionAdapter

CP_CFG = {
    "id": "north_miami",
    "name": "City of North Miami",
    "county": "miami-dade",
    "agency": "City of North Miami",
    "portal_url": "https://www.northmiamifl.gov/bids.aspx",
}
MD_CFG = {
    "id": "miami_dade_construction",
    "name": "Miami-Dade Construction Solicitations",
    "county": "miami-dade",
    "agency": "Miami-Dade County",
    "portal_url": "https://www.miamidade.gov/apps/ISD/stratproc/Home/CurrentSolicitations",
}


def _stub(monkeypatch, module: str, html: str):
    class _Resp:
        text = html

    monkeypatch.setattr(f"src.sources.{module}.get", lambda *a, **k: _Resp())


# ---------------------------------------------------------------------------
# CivicPlus detail
# ---------------------------------------------------------------------------


@pytest.fixture
def cp_detail(monkeypatch, fixtures_dir, opp_factory):
    _stub(monkeypatch, "civicplus", (fixtures_dir / "civicplus_detail.html").read_text())
    opp = opp_factory(
        source_id="north_miami",
        agency="City of North Miami",
        county="miami-dade",
        url="https://www.northmiamifl.gov/bids.aspx?bidID=110",
    )
    CivicPlusAdapter(CP_CFG).fetch_detail(opp)
    return opp


def test_scope_is_captured(cp_detail):
    assert cp_detail.scope and "SCOPE OF WORK" in cp_detail.scope
    assert len(cp_detail.scope) > 200


def test_detail_flag_is_set(cp_detail):
    assert cp_detail.detail_fetched


def test_documents_are_collected_and_addenda_tagged(cp_detail):
    assert cp_detail.documents
    assert all(d.url.startswith("http") for d in cp_detail.documents)
    assert any(d.kind == "addendum" for d in cp_detail.documents)


def test_requirements_are_derived_from_the_scope(cp_detail):
    assert "Licensed contractor" in cp_detail.requirements


def test_submittal_information_is_captured(cp_detail):
    assert cp_detail.submittal_info and "City Clerk" in cp_detail.submittal_info


def test_question_deadline_comes_out_of_the_scope(cp_detail):
    assert cp_detail.questions_due == datetime(2026, 5, 8, 15, 30)


def test_detail_lifts_the_completeness_score(monkeypatch, fixtures_dir, opp_factory):
    _stub(monkeypatch, "civicplus", (fixtures_dir / "civicplus_detail.html").read_text())
    opp = opp_factory(source_id="north_miami", url="https://x.gov/bids.aspx?bidID=110")
    before = opp.detail_score
    CivicPlusAdapter(CP_CFG).fetch_detail(opp)
    assert opp.detail_score > before + 25


def test_a_listing_url_without_a_bid_id_is_skipped(monkeypatch, opp_factory):
    called = []
    monkeypatch.setattr("src.sources.civicplus.get", lambda *a, **k: called.append(1))
    opp = opp_factory(url="https://www.northmiamifl.gov/bids.aspx")
    CivicPlusAdapter(CP_CFG).fetch_detail(opp)
    assert not called and not opp.detail_fetched


def test_unparseable_detail_page_leaves_the_listing_intact(monkeypatch, opp_factory):
    _stub(monkeypatch, "civicplus", "<html><body><p>nothing here</p></body></html>")
    opp = opp_factory(title="Roof Repair", url="https://x.gov/bids.aspx?bidID=1")
    CivicPlusAdapter(CP_CFG).fetch_detail(opp)
    assert opp.title == "Roof Repair"
    assert opp.scope is None and not opp.detail_fetched


# ---------------------------------------------------------------------------
# Miami-Dade detail
# ---------------------------------------------------------------------------


@pytest.fixture
def md_detail(monkeypatch, fixtures_dir, opp_factory):
    _stub(monkeypatch, "miami_dade_construction", (fixtures_dir / "md_detail.html").read_text())
    opp = opp_factory(
        source_id="miami_dade_construction",
        agency="Miami-Dade County",
        url=(
            "https://www.miamidade.gov/apps/ISD/stratproc/Home/SolicitationDetails"
            "?solNumber=RPQ%20No%20P16370"
        ),
    )
    MiamiDadeConstructionAdapter(MD_CFG).fetch_detail(opp)
    return opp


def test_announcement_text_becomes_the_scope(md_detail):
    assert md_detail.scope and len(md_detail.scope) > 1000
    assert md_detail.detail_fetched


def test_technical_certification_is_recorded_as_a_requirement(md_detail):
    assert any("Technical certification" in r for r in md_detail.requirements)


def test_the_solicitation_pdf_is_linked(md_detail):
    assert md_detail.documents
    assert any(d.url.lower().endswith(".pdf") for d in md_detail.documents)


def test_a_listing_url_without_the_details_path_is_skipped(monkeypatch, opp_factory):
    called = []
    monkeypatch.setattr(
        "src.sources.miami_dade_construction.get", lambda *a, **k: called.append(1)
    )
    opp = opp_factory(url="https://www.miamidade.gov/apps/ISD/stratproc/Home/CurrentSolicitations")
    MiamiDadeConstructionAdapter(MD_CFG).fetch_detail(opp)
    assert not called


# ---------------------------------------------------------------------------
# Pipeline wiring
# ---------------------------------------------------------------------------


class _FakeAdapter:
    source_id = "fake"
    name = "Fake"
    supports_detail = True

    def __init__(self):
        self.seen = []

    def fetch_detail(self, opp):
        self.seen.append(opp)
        opp.scope = "A bid bond is required."
        opp.detail_fetched = True


def test_detail_pass_only_touches_actionable_listings(opp_factory):
    adapter = _FakeAdapter()
    opps = [
        opp_factory(source_id="fake", status="open", title="Open one"),
        opp_factory(source_id="fake", status="upcoming", title="Upcoming one"),
        opp_factory(source_id="fake", status="closed", title="Closed one"),
        opp_factory(source_id="fake", status="catalog", title="Catalog one"),
    ]
    assert fetch_details(opps, [adapter], quiet=True) == 2
    assert {o.title for o in adapter.seen} == {"Open one", "Upcoming one"}


def test_detail_pass_respects_its_budget(opp_factory):
    adapter = _FakeAdapter()
    opps = [opp_factory(source_id="fake", status="open", title=f"Bid {i}") for i in range(10)]
    assert fetch_details(opps, [adapter], limit=3, quiet=True) == 3


def test_soonest_due_are_enriched_first(opp_factory):
    adapter = _FakeAdapter()
    opps = [
        opp_factory(source_id="fake", status="open", title="Later", due_date=datetime(2027, 1, 1)),
        opp_factory(source_id="fake", status="open", title="Sooner", due_date=datetime(2026, 1, 1)),
    ]
    fetch_details(opps, [adapter], limit=1, quiet=True)
    assert [o.title for o in adapter.seen] == ["Sooner"]


def test_already_enriched_listings_are_not_refetched(opp_factory):
    adapter = _FakeAdapter()
    opp = opp_factory(source_id="fake", status="open")
    opp.detail_fetched = True
    assert fetch_details([opp], [adapter], quiet=True) == 0


def test_a_failing_detail_page_does_not_abort_the_pass(opp_factory):
    class _Exploding(_FakeAdapter):
        def fetch_detail(self, opp):
            if opp.title == "bad":
                raise RuntimeError("detail page is broken")
            opp.detail_fetched = True

    opps = [
        opp_factory(source_id="fake", status="open", title="bad"),
        opp_factory(source_id="fake", status="open", title="good"),
    ]
    assert fetch_details(opps, [_Exploding()], quiet=True) == 1


def test_adapters_without_detail_support_are_skipped(opp_factory):
    class _NoDetail:
        source_id = "fake"
        name = "Fake"
        supports_detail = False

    assert fetch_details([opp_factory(source_id="fake", status="open")], [_NoDetail()], quiet=True) == 0


def test_derive_fields_works_without_a_detail_page(opp_factory):
    """Portals with no detail view still put terms in the blurb they publish."""
    opp = opp_factory(
        description="Bidder shall provide a performance bond. Budget of $310,000. "
        "Contact buyer@city.gov or (954) 555-0100."
    )
    derive_fields([opp])
    assert "Performance bond" in opp.requirements
    assert opp.budget == "$310,000"
    assert opp.contact_email == "buyer@city.gov"
    assert opp.contact_phone == "(954) 555-0100"


def test_derive_fields_does_not_overwrite_detail_values(opp_factory):
    opp = opp_factory(budget="$1", description="budget of $999,000")
    derive_fields([opp])
    assert opp.budget == "$1"


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


def test_detail_score_rewards_richer_records(opp_factory):
    bare = opp_factory()
    rich = opp_factory(
        due_date=datetime(2026, 12, 1),
        scope="x" * 500,
        requirements=["Bid bond"],
        documents=[Document(name="Package", url="https://x.gov/a.pdf")],
        contact_email="a@b.gov",
        budget="$100,000",
        description="d",
        external_id="ITB-1",
        submittal_info="Deliver to the City Clerk",
        # Terms that only come from the bid package.
        duration_days=330,
        liquidated_damages="$1,000 per day",
        licenses="General Building Contractor",
        project_location="Hialeah, FL",
    )
    assert rich.detail_score > bare.detail_score
    assert rich.detail_score == 100, "the weights should total 100 for a complete record"


def test_detail_fields_survive_a_snapshot_round_trip(opp_factory):
    opp = opp_factory(
        scope="Full scope text",
        requirements=["Bid bond", "E-Verify"],
        documents=[Document(name="Addendum 1", url="https://x.gov/a.pdf", kind="addendum")],
        questions_due=datetime(2026, 5, 8, 15, 30),
        contact_email="a@b.gov",
    )
    restored = Opportunity.model_validate(opp.model_dump(mode="json"))
    assert restored.scope == "Full scope text"
    assert restored.requirements == ["Bid bond", "E-Verify"]
    assert restored.documents[0].is_addendum
    assert restored.questions_due == datetime(2026, 5, 8, 15, 30)


def test_to_row_flattens_detail_for_csv(opp_factory):
    row = opp_factory(
        requirements=["Bid bond", "E-Verify"],
        documents=[Document(name="A", url="https://x.gov/a.pdf")],
        scope="Line one\nLine two",
    ).to_row()
    assert row["requirements"] == "Bid bond; E-Verify"
    assert row["documents"] == 1
    assert "\n" not in row["scope"]
    assert all(not isinstance(v, (list, dict)) for v in row.values())
