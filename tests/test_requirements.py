"""Extracting bid terms, pricing and deadlines from scope prose."""

from __future__ import annotations

from datetime import datetime

import pytest

from src.requirements import (
    extract_contact_email,
    extract_contact_phone,
    extract_estimated_value,
    extract_pre_bid_meeting,
    extract_questions_due,
    extract_requirements,
)


# ---------------------------------------------------------------------------
# Requirements
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text, expected",
    [
        ("A 5% bid bond is required with each proposal.", "Bid bond"),
        ("The successful bidder shall furnish a performance bond.", "Performance bond"),
        ("Contractor shall provide a payment bond.", "Payment bond"),
        ("Submit a certificate of insurance naming the City.", "Insurance certificate"),
        ("Bids from qualified, licensed contractors.", "Licensed contractor"),
        ("Firms must be pre-qualified prior to submitting.", "Prequalification required"),
        ("A mandatory pre-bid conference will be held.", "Mandatory pre-bid meeting"),
        ("Attendance at the mandatory site visit is required.", "Mandatory site visit"),
        ("The vendor must comply with E-Verify.", "E-Verify"),
        ("An SBE participation goal applies.", "SBE/MBE/DBE participation"),
        ("Local business preference will be applied.", "Local preference"),
        ("Davis-Bacon wage rates apply.", "Living wage"),
        ("This is a drug-free workplace.", "Drug-free workplace"),
        ("Complete the public entity crimes affidavit.", "Public entity crimes affidavit"),
        ("Level 2 screening is required for all staff.", "Background screening"),
    ],
)
def test_each_requirement_is_detected(text, expected):
    assert expected in extract_requirements(text)


def test_multiple_requirements_from_one_scope():
    scope = (
        "Bidders shall furnish a bid bond and a performance bond. "
        "Contractor must be licensed. A mandatory pre-bid conference will be held. "
        "E-Verify compliance is required."
    )
    found = extract_requirements(scope)
    assert {"Bid bond", "Performance bond", "Licensed contractor", "E-Verify"} <= set(found)


def test_requirements_are_not_duplicated():
    text = "bid bond ... bid bond ... bid security"
    assert extract_requirements(text).count("Bid bond") == 1


def test_no_requirements_in_ordinary_prose():
    assert extract_requirements("Furnish and deliver ten office chairs.") == []


@pytest.mark.parametrize("texts", [(), (None,), ("",), (None, "")])
def test_empty_input_is_safe(texts):
    assert extract_requirements(*texts) == []


def test_reads_across_several_text_blocks():
    found = extract_requirements("A bid bond is required.", None, "Contractor must be licensed.")
    assert {"Bid bond", "Licensed contractor"} <= set(found)


# ---------------------------------------------------------------------------
# Estimated value
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text, expected",
    [
        ("The estimated construction budget is $2,450,000 for this work.", "$2,450,000"),
        ("Compensation shall not to exceed $750,000 annually.", "$750,000"),
        ("Contract value of $1,200,000.", "$1,200,000"),
        ("The anticipated budget is $95,000.", "$95,000"),
    ],
)
def test_qualified_figures_win(text, expected):
    assert extract_estimated_value(text) == expected


def test_a_small_bare_figure_is_not_a_contract_value():
    """A plan fee is not what the job is worth."""
    assert extract_estimated_value("A nonrefundable $50 plan fee applies.") is None


def test_large_bare_figure_is_accepted_as_a_fallback():
    assert extract_estimated_value("Work valued around $450,000 in total.") == "$450,000"


def test_largest_bare_figure_wins():
    text = "Phase one is $30,000 and the full program is $900,000."
    assert extract_estimated_value(text) == "$900,000"


def test_magnitude_suffix_is_kept_readable():
    assert extract_estimated_value("budget of $2.5 million for the project") == "$2.5 million"


def test_no_money_returns_none():
    assert extract_estimated_value("Provide janitorial services weekly.") is None


# ---------------------------------------------------------------------------
# Dates and contacts
# ---------------------------------------------------------------------------


def test_question_deadline_is_extracted_with_its_time():
    scope = (
        "DEADLINE FOR ADDITIONAL INFORMATION & CLARIFICATION "
        "Friday, May 8, 2026, by no later no 3:30PM (EST) "
        "DEADLINE FOR SUBMITTAL OF BIDS Monday, June 8, 2026"
    )
    assert extract_questions_due(scope) == datetime(2026, 5, 8, 15, 30)


def test_question_deadline_in_slash_format():
    assert extract_questions_due("Questions are due 05/08/2026.") == datetime(2026, 5, 8)


def test_trailing_prose_does_not_break_the_date():
    """The captured span used to swallow 'by no later no 3:' and fail to parse."""
    assert extract_questions_due("Questions: March 3, 2026, by no later than noon") is not None


def test_no_question_deadline_returns_none():
    assert extract_questions_due("Bids are due June 1, 2026.") is None


def test_pre_bid_meeting_text_is_captured():
    text = "A pre-bid conference will be held on May 1, 2026 at 10:00 AM in Room 212."
    got = extract_pre_bid_meeting(text)
    assert got and got.startswith("pre-bid conference") is False or "pre-bid" in got.lower()
    assert "Room 212" in got


def test_contact_details():
    text = "Direct questions to Jane Buyer, jane.buyer@city.gov, (305) 555-1234."
    assert extract_contact_email(text) == "jane.buyer@city.gov"
    assert extract_contact_phone(text) == "(305) 555-1234"


def test_trailing_sentence_period_is_not_part_of_the_email():
    assert extract_contact_email("Email buyer@city.gov.") == "buyer@city.gov"


def test_missing_contacts_return_none():
    assert extract_contact_email("No contact listed.") is None
    assert extract_contact_phone("No contact listed.") is None
