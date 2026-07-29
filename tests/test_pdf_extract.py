"""Reading commercial terms out of the bid package PDF."""

from __future__ import annotations

import pytest

from src import pdf_extract
from src.models.opportunity import Document
from src.pdf_extract import PdfFacts, fetch_text, parse_facts
from src.pipeline.runner import _primary_package, parse_packages

# The shape Miami-Dade RPQ packages actually use: labels packed onto shared
# lines, separated by as little as one space.
BREAKDOWN = """
MIAMI-DADE COUNTY, FLORIDA
REQUEST FOR PRICE QUOTATION (RPQ)
RPQ DETAILED BREAKDOWN
Bid Due Date: 7/31/2026 Time Due:02:00 PM Submitted Via:Sealed Envelopes
Estimated Value: $1,348,873 (excluding Contingencies and Dedicated Allowances)
Project Name: Pump Station Generator Relocation
Project Location: 5700 E 8th Avenue, Hialeah, FL 33013
License Requirements:Primary: General Building Contractor; General Engineering
Additional Insurance Required:YES If Yes - Minimum Coverage:$5,000,000.00
Performance & Payment Bond Required:YES Bid Bond Required:YES
Davis Bacon: NO Maintenance Wages:NO AIPP:NO Amount:
DBE Participation: NO Percentage:0.00% DBE Subcontractor Forms Required:NO
Liquidated Damages: YES $$ Per Day:$1,000.00
Anticipated Start Date:10/1/2026 Calendar Days for Project Completion:330
Scope of Work: Furnish all labor and materials to relocate the emergency
generator, including electrical tie-ins and site restoration.
GENERAL CONDITIONS AND BOILERPLATE
Nothing here matters to a bidder screening the job.
"""


@pytest.fixture
def facts() -> PdfFacts:
    return parse_facts(BREAKDOWN)


# ---------------------------------------------------------------------------
# Field extraction
# ---------------------------------------------------------------------------


def test_estimated_value(facts):
    assert facts.estimated_value == "$1,348,873"


def test_project_duration(facts):
    assert facts.duration_days == 330


def test_liquidated_damages_amount(facts):
    """The figure sits under its own 'Per Day:' label, not with the yes/no."""
    assert facts.liquidated_damages == "$1,000.00 per day"


def test_licence_classes(facts):
    assert facts.licenses and "General Engineering" in facts.licenses


def test_project_location(facts):
    assert facts.project_location == "5700 E 8th Avenue, Hialeah, FL 33013"


def test_bond_requirements_are_both_found(facts):
    """Two bond fields share one line separated by a single space."""
    assert "Bid bond required" in facts.requirements
    assert "Performance & payment bond required" in facts.requirements


def test_insurance_requirement(facts):
    assert "Additional insurance" in facts.requirements


def test_no_answers_do_not_become_requirements(facts):
    joined = " ".join(facts.requirements)
    assert "Davis-Bacon" not in joined
    assert "DBE subcontractor" not in joined


def test_scope_stops_at_the_boilerplate_banner(facts):
    assert facts.scope and "relocate the emergency" in facts.scope
    assert "boilerplate" not in facts.scope.lower()


def test_zero_percent_set_aside_is_not_reported(facts):
    assert not any("set-aside" in r for r in facts.requirements)


def test_nonzero_set_aside_is_reported():
    text = "SBE-S Requirements YES Percentage:10.00%"
    assert "SBE set-aside 10.00%" in parse_facts(text).requirements


# ---------------------------------------------------------------------------
# Robustness
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("text", ["", None, "   ", "no labelled fields at all"])
def test_unhelpful_text_yields_empty_facts(text):
    assert parse_facts(text or "").is_empty()


def test_liquidated_damages_marked_no_is_ignored():
    assert parse_facts("Liquidated Damages: NO").liquidated_damages is None


def test_liquidated_damages_without_an_amount():
    assert parse_facts("Liquidated Damages: YES").liquidated_damages == "Yes"


def test_value_without_a_dollar_figure_is_skipped():
    assert parse_facts("Estimated Value: To be determined").estimated_value is None


# ---------------------------------------------------------------------------
# Download guards
# ---------------------------------------------------------------------------


def test_non_pdf_response_is_rejected(monkeypatch, tmp_path):
    class _Resp:
        content = b"<html>not a pdf</html>"

    monkeypatch.setattr(pdf_extract, "cache_dir", lambda: tmp_path)
    monkeypatch.setattr(pdf_extract, "get", lambda *a, **k: _Resp())
    assert fetch_text("https://x.gov/a.pdf") == ""


def test_oversized_download_is_rejected(monkeypatch, tmp_path):
    class _Resp:
        content = b"%PDF" + b"x" * (pdf_extract.MAX_BYTES + 1)

    monkeypatch.setattr(pdf_extract, "cache_dir", lambda: tmp_path)
    monkeypatch.setattr(pdf_extract, "get", lambda *a, **k: _Resp())
    assert fetch_text("https://x.gov/big.pdf") == ""


def test_download_failure_is_swallowed(monkeypatch, tmp_path):
    def _boom(*a, **k):
        raise RuntimeError("network down")

    monkeypatch.setattr(pdf_extract, "cache_dir", lambda: tmp_path)
    monkeypatch.setattr(pdf_extract, "get", _boom)
    assert fetch_text("https://x.gov/a.pdf") == ""


def test_cache_avoids_a_second_download(monkeypatch, tmp_path):
    calls = []

    class _Resp:
        content = b"%PDF-1.4 fake"

    monkeypatch.setattr(pdf_extract, "cache_dir", lambda: tmp_path)
    monkeypatch.setattr(pdf_extract, "_extract", lambda raw: "Estimated Value: $10,000")
    monkeypatch.setattr(pdf_extract, "get", lambda *a, **k: (calls.append(1), _Resp())[1])

    first = fetch_text("https://x.gov/a.pdf")
    second = fetch_text("https://x.gov/a.pdf")
    assert first == second == "Estimated Value: $10,000"
    assert len(calls) == 1, "the second read must come from cache"


# ---------------------------------------------------------------------------
# Package selection and the pipeline pass
# ---------------------------------------------------------------------------


def test_the_solicitation_is_preferred_over_its_addenda(opp_factory):
    opp = opp_factory(
        external_id="IFB 2026-021",
        documents=[
            Document(name="IFB 2026-021 Addendum 1", url="https://x.gov/add1.pdf", kind="addendum"),
            Document(name="IFB 2026-021 Bid Package", url="https://x.gov/pkg.pdf"),
        ],
    )
    assert _primary_package(opp) == "https://x.gov/pkg.pdf"


def test_a_document_named_for_the_reference_wins(opp_factory):
    opp = opp_factory(
        external_id="RPQ No P16370",
        documents=[
            Document(name="General Conditions", url="https://x.gov/gc.pdf"),
            Document(name="RPQ_No_P16370.pdf", url="https://x.gov/rpq.pdf"),
        ],
    )
    assert _primary_package(opp) == "https://x.gov/rpq.pdf"


def test_non_pdf_documents_are_not_candidates(opp_factory):
    opp = opp_factory(documents=[Document(name="Plans", url="https://x.gov/plans.zip")])
    assert _primary_package(opp) is None


def test_no_documents_means_no_package(opp_factory):
    assert _primary_package(opp_factory()) is None


def test_package_facts_are_applied(monkeypatch, opp_factory):
    monkeypatch.setattr("src.pipeline.runner.fetch_text", lambda url: BREAKDOWN)
    opp = opp_factory(
        status="open",
        documents=[Document(name="Package", url="https://x.gov/pkg.pdf")],
    )
    assert parse_packages([opp], quiet=True) == 1
    assert opp.budget == "$1,348,873"
    assert opp.duration_days == 330
    assert opp.liquidated_damages == "$1,000.00 per day"
    assert opp.package_parsed


def test_one_pdf_serves_every_bid_that_shares_it(monkeypatch, opp_factory):
    """Framework contracts split into several bids behind a single package."""
    reads = []
    monkeypatch.setattr(
        "src.pipeline.runner.fetch_text", lambda url: (reads.append(url), BREAKDOWN)[1]
    )
    shared = [Document(name="Package", url="https://x.gov/shared.pdf")]
    opps = [opp_factory(status="open", title=f"Lot {i}", documents=list(shared)) for i in range(3)]

    assert parse_packages(opps, quiet=True) == 3
    assert len(reads) == 1, "the shared package must only be downloaded once"
    assert all(o.budget == "$1,348,873" for o in opps)


def test_package_value_overrides_a_guess_from_prose(monkeypatch, opp_factory):
    """The solicitation's own figure beats one inferred from a blurb."""
    monkeypatch.setattr("src.pipeline.runner.fetch_text", lambda url: BREAKDOWN)
    opp = opp_factory(
        status="open",
        budget="$99,000",
        documents=[Document(name="Package", url="https://x.gov/pkg.pdf")],
    )
    parse_packages([opp], quiet=True)
    assert opp.budget == "$1,348,873"


def test_closed_listings_are_not_parsed(monkeypatch, opp_factory):
    monkeypatch.setattr("src.pipeline.runner.fetch_text", lambda url: BREAKDOWN)
    opp = opp_factory(
        status="closed", documents=[Document(name="Package", url="https://x.gov/pkg.pdf")]
    )
    assert parse_packages([opp], quiet=True) == 0


def test_the_pass_respects_its_budget(monkeypatch, opp_factory):
    monkeypatch.setattr("src.pipeline.runner.fetch_text", lambda url: BREAKDOWN)
    opps = [
        opp_factory(
            status="open",
            title=f"Bid {i}",
            documents=[Document(name="Package", url=f"https://x.gov/{i}.pdf")],
        )
        for i in range(8)
    ]
    assert parse_packages(opps, limit=3, quiet=True) == 3


def test_an_unreadable_package_does_not_abort_the_pass(monkeypatch, opp_factory):
    def _reader(url):
        if "bad" in url:
            raise RuntimeError("corrupt pdf")
        return BREAKDOWN

    monkeypatch.setattr("src.pipeline.runner.fetch_text", _reader)
    opps = [
        opp_factory(status="open", title="bad", documents=[Document(name="P", url="https://x.gov/bad.pdf")]),
        opp_factory(status="open", title="good", documents=[Document(name="P", url="https://x.gov/ok.pdf")]),
    ]
    assert parse_packages(opps, quiet=True) == 1


def test_already_parsed_listings_are_skipped(monkeypatch, opp_factory):
    monkeypatch.setattr("src.pipeline.runner.fetch_text", lambda url: BREAKDOWN)
    opp = opp_factory(status="open", documents=[Document(name="P", url="https://x.gov/p.pdf")])
    opp.package_parsed = True
    assert parse_packages([opp], quiet=True) == 0


def test_package_fields_survive_a_snapshot_round_trip(opp_factory):
    from src.models.opportunity import Opportunity

    opp = opp_factory(
        duration_days=330,
        liquidated_damages="$1,000.00 per day",
        licenses="Primary: General Building Contractor",
        project_location="Hialeah, FL",
    )
    restored = Opportunity.model_validate(opp.model_dump(mode="json"))
    assert restored.duration_days == 330
    assert restored.liquidated_damages == "$1,000.00 per day"
    assert restored.project_location == "Hialeah, FL"
