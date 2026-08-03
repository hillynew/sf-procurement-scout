"""Follow-up research: threading, search-tool selection, pause_turn, API."""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from src.ai import research
from src.models.opportunity import Opportunity


def make_opp(**kw) -> Opportunity:
    defaults = dict(
        source_id="test-src",
        source_name="Test Source",
        title="Roof Replacement — City Hall",
        url="https://example.gov/roof",
        county="broward",
        agency="City of Testville",
        status="open",
        due_date=datetime.utcnow() + timedelta(days=14),
    )
    defaults.update(kw)
    return Opportunity(**defaults)


@pytest.fixture()
def db(tmp_path, monkeypatch):
    from src.db import engine as db_engine

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setenv("SF_SCOUT_ANTHROPIC_KEY", "test-key")
    db_engine.reset_engine()
    from src.db import store

    store.bootstrap()
    yield store
    db_engine.reset_engine()


def _text_block(text, urls=()):
    return SimpleNamespace(
        type="text",
        text=text,
        citations=[SimpleNamespace(url=u, title=f"Title for {u}") for u in urls],
    )


def _response(blocks, stop_reason="end_turn"):
    return SimpleNamespace(content=blocks, stop_reason=stop_reason)


# ---------------------------------------------------------------------------
# Thread storage
# ---------------------------------------------------------------------------


def test_thread_round_trip(db):
    assert db.get_research_thread("x") == []
    db.append_research_turn("x", {"question": "q1", "answer": "a1"})
    db.append_research_turn("x", {"question": "q2", "answer": "a2"})
    turns = db.get_research_thread("x")
    assert [t["question"] for t in turns] == ["q1", "q2"]
    assert db.clear_research_thread("x") is True
    assert db.get_research_thread("x") == []
    assert db.clear_research_thread("x") is False


# ---------------------------------------------------------------------------
# ask()
# ---------------------------------------------------------------------------


def test_ask_answers_and_persists(db, monkeypatch):
    calls = []

    def fake_call(model, messages):
        calls.append((model, list(messages)))
        return _response([
            SimpleNamespace(type="server_tool_use", name="web_search"),
            _text_block("The 2023 award went to Acme for $1.2M.",
                        urls=["https://county.gov/award"]),
        ])

    monkeypatch.setattr(research, "_call_claude", fake_call)
    opp = make_opp()

    turn = research.ask(opp, "What did this go for last time?")
    assert "Acme" in turn["answer"]
    assert turn["citations"] == [
        {"url": "https://county.gov/award", "title": "Title for https://county.gov/award"}
    ]
    assert turn["searches"] == 1

    stored = db.get_research_thread(opp.opportunity_id)
    assert len(stored) == 1
    # The first user turn carries the deal context so search starts grounded.
    first_user = calls[0][1][0]["content"]
    assert "DEAL CONTEXT" in first_user and "Roof Replacement" in first_user


def test_follow_up_replays_the_thread(db, monkeypatch):
    responses = [_response([_text_block("Answer one.")]),
                 _response([_text_block("Answer two.")])]
    calls = []

    def fake_call(model, messages):
        calls.append(list(messages))
        return responses[len(calls) - 1]

    monkeypatch.setattr(research, "_call_claude", fake_call)
    opp = make_opp()
    research.ask(opp, "First question?")
    research.ask(opp, "And the year before?")

    second = calls[1]
    # user(context+q1), assistant(a1), user(q2) — the model keeps the ground.
    assert len(second) == 3
    assert second[1] == {"role": "assistant", "content": "Answer one."}
    assert second[2] == {"role": "user", "content": "And the year before?"}


def test_pause_turn_is_resumed_not_truncated(db, monkeypatch):
    paused = _response([_text_block("Searching…")], stop_reason="pause_turn")
    done = _response([_text_block("Found it: $980k in 2022.")])
    seq = [paused, done]
    calls = []

    def fake_call(model, messages):
        calls.append(list(messages))
        return seq[len(calls) - 1]

    monkeypatch.setattr(research, "_call_claude", fake_call)
    turn = research.ask(make_opp(), "Prior value?")
    assert "980k" in turn["answer"]
    # The resume request must end with the paused assistant turn, verbatim.
    assert calls[1][-1]["role"] == "assistant"


def test_empty_question_and_missing_key_fail_loudly(db, monkeypatch):
    with pytest.raises(ValueError):
        research.ask(make_opp(), "   ")
    monkeypatch.delenv("SF_SCOUT_ANTHROPIC_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="no_api_key"):
        research.ask(make_opp(), "Anything?")


def test_search_tool_version_tracks_the_model_generation():
    """Haiku 4.5 predates dynamic filtering; sending it the new type is a 400."""
    assert research._search_tool("claude-haiku-4-5")["type"] == "web_search_20250305"
    assert research._search_tool("claude-sonnet-5")["type"] == "web_search_20260209"
    for tool in (research._search_tool("claude-haiku-4-5"),
                 research._search_tool("claude-sonnet-5")):
        assert tool["name"] == "web_search"
        assert tool["max_uses"] == research.MAX_SEARCHES_PER_ASK


def test_deep_dive_findings_are_folded_into_context(db, monkeypatch):
    from src.ai.deep_dive import DEEP_PROMPT_VERSION

    opp = make_opp()
    db.put_deep_dive(opp.opportunity_id, content_hash="h", model="m",
                     prompt_version=DEEP_PROMPT_VERSION,
                     report={"overview": "Re-roof city hall.",
                             "dollar_amounts": [{"label": "Estimate", "amount": "$1.4M"}],
                             "open_questions": ["Is the deck salvageable?"]},
                     input_chars=1, docs_read=2)
    ctx = research.build_context(opp)
    assert "Re-roof city hall." in ctx
    assert "$1.4M" in ctx
    assert "Is the deck salvageable?" in ctx
