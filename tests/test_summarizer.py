"""AI summarizer: disabled mode, cache behavior, auto-summarize scope."""

from __future__ import annotations

import pytest

from src.db import store as db
from src.models.opportunity import Opportunity

BRIEF = {
    "what_the_work_is": "Replace the roof at Fire Station 12.",
    "key_dates": [{"label": "Due", "date": "2026-08-20"}],
    "money": {"estimated_value": "$150,000"},
    "requirements": ["Licensed roofing contractor"],
    "red_flags": ["5% bid bond required"],
    "fit_hint": "Suits a small licensed roofer.",
}


@pytest.fixture()
def opp():
    return Opportunity(
        source_id="s", source_name="S", title="Roof Replacement",
        url="https://example.gov/roof", county="broward", agency="Testville",
        scope="Tear off and replace the roof.",
    )


@pytest.fixture()
def with_key(monkeypatch):
    monkeypatch.setenv("SF_SCOUT_ANTHROPIC_KEY", "test-key")
    from src.ai import summarizer

    calls = {"n": 0}

    def fake_call(model, text):
        calls["n"] += 1
        return dict(BRIEF)

    monkeypatch.setattr(summarizer, "_call_claude", fake_call)
    db.bootstrap()
    return calls


def test_disabled_without_key(monkeypatch, opp):
    monkeypatch.delenv("SF_SCOUT_ANTHROPIC_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    from src.ai import summarizer

    assert summarizer.enabled() is False
    with pytest.raises(RuntimeError, match="no_api_key"):
        summarizer.summarize(opp)
    # Auto mode silently does nothing.
    assert summarizer.auto_summarize_tracked([opp], {}) == 0


def test_summarize_caches_by_content(with_key, opp):
    from src.ai import summarizer

    first = summarizer.summarize(opp, with_package=False)
    assert first["cached"] is False
    assert first["summary"]["what_the_work_is"].startswith("Replace")

    again = summarizer.summarize(opp, with_package=False)
    assert again["cached"] is True
    assert with_key["n"] == 1  # only one real call

    # Changed input text -> cache miss.
    opp.scope = "Now with an addendum about decking."
    changed = summarizer.summarize(opp, with_package=False)
    assert changed["cached"] is False
    assert with_key["n"] == 2

    # force=True regenerates even without changes.
    summarizer.summarize(opp, force=True, with_package=False)
    assert with_key["n"] == 3


def test_unknown_model_falls_back_to_default(with_key, opp):
    from src.ai import summarizer

    result = summarizer.summarize(opp, model="gpt-9000", with_package=False)
    assert result["model"] == summarizer.DEFAULT_MODEL


def test_auto_summarize_only_active_tracked(with_key, opp, monkeypatch):
    from src.ai import summarizer

    monkeypatch.setattr(summarizer, "_package_text", lambda o: "")
    other = Opportunity(
        source_id="s", source_name="S", title="Sidewalks",
        url="https://example.gov/sidewalks", county="broward", agency="Testville",
    )
    workflow = {
        opp.opportunity_id: {"archived": False, "stage": "preparing",
                             "checks": {}, "notes": "", "decision": None,
                             "tracked_on": "2026-08-01", "result": None},
        other.opportunity_id: {"archived": True, "stage": "watching",
                               "checks": {}, "notes": "", "decision": None,
                               "tracked_on": "2026-08-01", "result": None},
    }
    done = summarizer.auto_summarize_tracked([opp, other], workflow)
    assert done == 1  # archived bid skipped
    assert db.latest_summary(opp.opportunity_id) is not None
    assert db.latest_summary(other.opportunity_id) is None


def test_input_truncation(opp):
    from src.ai import summarizer

    opp.scope = "x" * 100_000
    text = summarizer.build_input(opp)
    assert len(text) <= summarizer.MAX_INPUT_CHARS


def test_normalize_brief_fixes_stringified_lists():
    """The exact production failure: lists emitted as one <item> markup string."""
    from src.ai.summarizer import _normalize_brief

    raw = {
        "what_the_work_is": "Flood mitigation work.",
        "requirements": (
            "\n<item>Primary license: General Building Contractor</item>"
            "\n<item>Worker's Compensation Insurance</item>"
            "\n<item>Commercial General Liability: $300,000</item>"
        ),
        "red_flags": "<item>LDs $500/day</item><item>Tight 120-day window</item>",
        "fit_hint": "Suits licensed drainage contractors.",
        "key_dates": [
            {"label": "Due", "date": "2026-08-20"},
            {"bogus": "no label"},
            "not-a-dict",
        ],
        "money": {"estimated_value": "$150,000", "bonding": "", "extra": 42},
    }
    brief = _normalize_brief(raw)
    assert brief["requirements"] == [
        "Primary license: General Building Contractor",
        "Worker's Compensation Insurance",
        "Commercial General Liability: $300,000",
    ]
    assert brief["red_flags"] == ["LDs $500/day", "Tight 120-day window"]
    assert brief["key_dates"] == [{"label": "Due", "date": "2026-08-20", "note": ""}]
    assert brief["money"] == {"estimated_value": "$150,000"}


def test_normalize_brief_passthrough_and_newline_split():
    from src.ai.summarizer import _normalize_brief

    good = _normalize_brief(dict(BRIEF))
    assert good["requirements"] == BRIEF["requirements"]
    assert good["red_flags"] == BRIEF["red_flags"]
    assert good["what_the_work_is"] == BRIEF["what_the_work_is"]

    newline = _normalize_brief({
        "what_the_work_is": "x", "fit_hint": "y",
        "requirements": "Bid bond 5%\nE-Verify\n\n",
        "red_flags": [],
    })
    assert newline["requirements"] == ["Bid bond 5%", "E-Verify"]


def test_strict_tool_schema_shape():
    """Strict tool use requires additionalProperties: false on every object."""
    from src.ai.summarizer import BRIEF_SCHEMA

    assert BRIEF_SCHEMA["additionalProperties"] is False
    assert BRIEF_SCHEMA["properties"]["money"]["additionalProperties"] is False
    assert BRIEF_SCHEMA["properties"]["key_dates"]["items"]["additionalProperties"] is False
