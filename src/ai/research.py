"""Follow-up research on one deal: ask Claude to dig past what the documents say.

The deep dive is bounded by the bid package — it compiles what the agency
published, and nothing else. The questions a bidder actually prices with live
outside that boundary: who held this contract last time, what did it close at,
what does the agency typically pay, who else bids this kind of work. Those
answers are on the open web — award tabulations, agenda items, prior
solicitations, USASpending — so this module gives Claude the web search server
tool and lets it go find them.

Design notes:

* **Threaded, not one-shot.** Each question is answered with the prior turns
  of this deal's research in context, so "and what about the year before?"
  works. The thread is stored per opportunity in the DB.
* **Server-side search.** ``web_search`` runs on Anthropic's infrastructure —
  no scraping stack on our side, and results carry citations we surface in
  the UI. The tool *version* depends on the model generation: Sonnet 5 gets
  the dynamic-filtering variant, Haiku 4.5 (pre-4.6) only supports the basic
  one — sending the newer type to it is a 400, not a graceful downgrade.
* **`pause_turn` is a normal outcome.** A long search loop can pause
  mid-turn; the API expects the paused assistant turn to be sent back
  verbatim to resume. Failing to handle it silently truncates answers.
* **Grounded by instruction.** The system prompt requires figures to come
  from search results or the provided context, never from model memory —
  a hallucinated "previous contract value" is worse than none.
"""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional, Tuple

from src.db import store as db
from src.models.opportunity import Opportunity

from .deep_dive import DEEP_PROMPT_VERSION
from .summarizer import ALLOWED_MODELS, DEFAULT_MODEL, api_key, build_input, enabled

MAX_TURNS = 40            # per thread — a runaway conversation stops being research
MAX_SEARCHES_PER_ASK = 8  # web searches the model may run for one question
MAX_CONTINUATIONS = 5     # pause_turn resumes before we give up
MAX_ANSWER_TOKENS = 3000

#: Models released before the 4.6 generation only accept the basic search tool;
#: the dynamic-filtering variant is rejected outright, so this must be exact.
_BASIC_SEARCH_MODELS = {"claude-haiku-4-5"}

SYSTEM_PROMPT = (
    "You are a procurement research analyst for a small Florida contractor "
    "evaluating one government solicitation. The user asks follow-up questions "
    "the bid documents cannot answer — prior contract values, who won last "
    "time, what the agency historically pays, market rates, competitor "
    "landscape. Use web search to find out: look for award tabulations, "
    "commission/board agenda items and minutes, prior solicitations for the "
    "same service, USASpending or state contract registries, and local news. "
    "Government award data is public; be persistent and creative in finding "
    "it. Every dollar figure, date, vendor name, or award fact MUST come from "
    "a search result or the provided deal context — never from memory. If "
    "searches come up empty, say plainly what you looked for and where a "
    "human could look next (public records request, agency clerk, VIP "
    "archive). Answer in plain, direct English; lead with the answer, then "
    "the evidence. Keep it under ~350 words."
)

#: Offered in the UI as one-tap starters. Ordered by how often a bidder
#: actually needs the answer.
SUGGESTED_QUESTIONS = [
    "What did this contract go for last time, and who won it?",
    "What has this agency historically paid for this kind of work?",
    "Who are the likely competitors for this bid?",
    "Has this solicitation been issued before — and was it awarded or cancelled?",
    "What's the market rate for this scope in Florida right now?",
]


def _search_tool(model: str) -> Dict:
    if model in _BASIC_SEARCH_MODELS:
        tool_type = "web_search_20250305"
    else:
        tool_type = "web_search_20260209"
    return {"type": tool_type, "name": "web_search", "max_uses": MAX_SEARCHES_PER_ASK}


def build_context(opp: Opportunity) -> str:
    """Everything we already know about the deal, so search picks up from there."""
    parts = ["DEAL CONTEXT\n" + build_input(opp, "")]
    dive = db.get_deep_dive(opp.opportunity_id, DEEP_PROMPT_VERSION)
    if dive:
        report = dive.get("report") or {}
        bits: List[str] = []
        if report.get("overview"):
            bits.append("Overview: " + report["overview"])
        for d in report.get("dollar_amounts") or []:
            bits.append(f"Amount: {d.get('label')}: {d.get('amount')}")
        for q in report.get("open_questions") or []:
            bits.append("Open question from document review: " + q)
        if bits:
            parts.append("DEEP DIVE FINDINGS (from the bid documents)\n" + "\n".join(bits))
    return "\n\n".join(parts)


def _extract_answer(content) -> Tuple[str, List[dict]]:
    """Pull the answer text and its citations out of the response blocks."""
    text_parts: List[str] = []
    citations: List[dict] = []
    seen_urls = set()
    for block in content:
        btype = getattr(block, "type", None)
        if btype == "text":
            text_parts.append(block.text)
            for cit in getattr(block, "citations", None) or []:
                url = getattr(cit, "url", None)
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    citations.append({
                        "url": url,
                        "title": getattr(cit, "title", None) or url,
                    })
    return "".join(text_parts).strip(), citations


def _call_claude(model: str, messages: List[dict]):
    """One Messages API request. Module-level so tests can stand it in."""
    import anthropic

    client = anthropic.Anthropic(api_key=api_key())
    return client.messages.create(
        model=model,
        max_tokens=MAX_ANSWER_TOKENS,
        system=SYSTEM_PROMPT,
        tools=[_search_tool(model)],
        messages=messages,
    )


def ask(
    opp: Opportunity,
    question: str,
    *,
    model: Optional[str] = None,
) -> dict:
    """Answer one follow-up question and persist it to the deal's thread.

    Blocking (the API layer runs it in a thread). Returns the stored turn.
    """
    if not enabled():
        raise RuntimeError("no_api_key")
    question = (question or "").strip()
    if not question:
        raise ValueError("empty question")
    model = model if model in ALLOWED_MODELS else DEFAULT_MODEL

    history = db.get_research_thread(opp.opportunity_id)
    if len(history) >= MAX_TURNS:
        raise RuntimeError("thread_full")

    # First user turn carries the deal context; later ones just the question,
    # with prior Q&A replayed so the model keeps the conversation's ground.
    messages: List[dict] = []
    for i, turn in enumerate(history):
        q = turn["question"] if i else f"{build_context(opp)}\n\nQUESTION: {turn['question']}"
        messages.append({"role": "user", "content": q})
        messages.append({"role": "assistant", "content": turn["answer"]})
    q = question if history else f"{build_context(opp)}\n\nQUESTION: {question}"
    messages.append({"role": "user", "content": q})

    response = None
    for _ in range(MAX_CONTINUATIONS + 1):
        response = _call_claude(model, messages)
        if response.stop_reason != "pause_turn":
            break
        # Server-side search hit its iteration limit mid-turn: send the paused
        # assistant turn back as-is and the server resumes where it stopped.
        messages.append({"role": "assistant", "content": response.content})

    answer, citations = _extract_answer(response.content)
    searched = sum(
        1 for b in response.content if getattr(b, "type", "") == "server_tool_use"
    )
    if not answer:
        raise RuntimeError("model returned no answer")

    turn = {
        "question": question,
        "answer": answer,
        "citations": citations,
        "searches": searched,
        "model": model,
        "asked_at": datetime.utcnow().isoformat(),
    }
    db.append_research_turn(opp.opportunity_id, turn)
    return turn
