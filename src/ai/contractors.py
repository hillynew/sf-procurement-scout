"""Contractor matching: find real local firms that could fill one bid.

The rest of the app answers "should *we* bid this?". This module answers the
brokering question instead: *who could we hand this to?* For one solicitation
it web-searches for three or four real businesses — plumbers, paving crews,
janitorial shops, IT firms — that could perform the work, with a deliberate
preference for small local outfits that do commercial work but never touch
government contracts. Those are the firms the pitch is built for: we found the
bid, we'll file it properly and keep the job compliant, for a share of the
award.

Every firm surfaced gets folded into a persistent ``contractors`` directory,
so the network compounds across bids instead of being re-found each time.

Design notes:

* **Search first, record second.** A forced tool call would forbid searching,
  so the first request offers both the ``web_search`` server tool and the
  ``record_contractor_matches`` tool and lets the model work. If it ends the
  turn without recording, one follow-up request forces the record tool — the
  research is already in the transcript, so nothing is lost.
* **Grounded by instruction.** A hallucinated company with a fake phone
  number is worse than an empty result: every firm must come from a search
  result and carry its source URLs; unknown contact fields stay empty.
* Same plumbing as ``research.py``: model-dependent search-tool version,
  ``pause_turn`` continuation, one module-level ``_call_claude`` for tests.
"""

from __future__ import annotations

import hashlib
import re
from typing import Dict, List, Optional, Tuple

from src.db import store as db
from src.models.opportunity import Opportunity

from .research import _search_tool, build_context
from .summarizer import ALLOWED_MODELS, DEFAULT_MODEL, api_key, enabled

MATCH_PROMPT_VERSION = 1

MAX_SEARCHES = 10        # web searches per matching run
MAX_CONTINUATIONS = 5    # pause_turn resumes before we give up
MAX_MATCH_TOKENS = 5000

GOV_EXPERIENCE = ("none", "some", "regular", "unknown")

SYSTEM_PROMPT = (
    "You are a deal scout for a Florida bid brokerage. The user finds "
    "government solicitations and outsources the work: they guide a "
    "contractor through registration and filing, keep the job compliant, and "
    "take a fee from the awarded contract. For the solicitation provided, use "
    "web search to find 3-4 REAL businesses near the place of performance "
    "that could actually do this work. Prefer small, local, owner-operated "
    "firms with a track record in commercial or residential work but little "
    "or no government contracting — those gain the most from a partner who "
    "handles the red tape. Established government primes are acceptable only "
    "when nothing better exists. Every business MUST come from a search "
    "result — search for local directories, license lookups, trade "
    "associations, review sites, news — and carry the URLs you found it "
    "through. Never invent a phone number, email, or website: leave unknown "
    "fields empty. For each firm, say concretely why it fits this scope and "
    "write a two-sentence outreach angle that leads with the deal, not the "
    "paperwork. When you have your candidates, record them with the "
    "record_contractor_matches tool."
)

# Strict-mode compatible: additionalProperties: false on every object.
MATCH_SCHEMA = {
    "type": "object",
    "properties": {
        "matches": {
            "type": "array",
            # No maxItems: strict tool mode rejects array length constraints
            # (400: "property 'maxItems' is not supported"). The instruction
            # lives in the description and normalize_matches() hard-caps at 4.
            "description": "3-4 real firms found via search — never more than "
                           "4; fewer only if the market is genuinely thin.",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Legal or trading name as found."},
                    "location": {"type": "string", "description": "City/area, e.g. 'Pompano Beach, FL'."},
                    "trade": {"type": "string", "description": "What they do, e.g. 'commercial roofing'."},
                    "website": {"type": "string"},
                    "phone": {"type": "string"},
                    "email": {"type": "string"},
                    "gov_experience": {
                        "type": "string",
                        "enum": ["none", "some", "regular", "unknown"],
                        "description": "Evidence of prior government work.",
                    },
                    "why_fit": {
                        "type": "string",
                        "description": "Concretely why this firm can perform this scope.",
                    },
                    "pitch_angle": {
                        "type": "string",
                        "description": "Two sentences to open outreach with, leading with the deal.",
                    },
                    "sources": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "URLs the firm was found through.",
                    },
                },
                "required": ["name", "trade", "why_fit", "pitch_angle", "sources"],
                "additionalProperties": False,
            },
        },
        "market_note": {
            "type": "string",
            "description": "One or two sentences on the local supplier landscape for this scope.",
        },
    },
    "required": ["matches"],
    "additionalProperties": False,
}

_RECORD_TOOL = {
    "name": "record_contractor_matches",
    "description": "Record the contractor candidates found for this solicitation.",
    "strict": True,
    "input_schema": MATCH_SCHEMA,
}

# Legal-form suffixes stripped when deriving a firm's stable id, so
# "Apex Roofing LLC" and "Apex Roofing, Inc." land on the same network row.
_SUFFIX_RE = re.compile(
    r"\b(llc|l\.l\.c|inc|incorporated|corp|corporation|co|company|ltd|llp|pa|pllc)\b\.?",
)


def contractor_id(name: str) -> str:
    """Stable 16-hex id from a normalized firm name."""
    slug = _SUFFIX_RE.sub("", name.lower())
    slug = re.sub(r"[^a-z0-9]+", "", slug)
    return hashlib.sha1(slug.encode("utf-8")).hexdigest()[:16]


def _clean(value) -> str:
    return str(value or "").strip()


def _url_list(value) -> List[str]:
    if not isinstance(value, list):
        return []
    out, seen = [], set()
    for item in value:
        url = _clean(item)
        if url.startswith("http") and url not in seen:
            seen.add(url)
            out.append(url)
    return out


def normalize_matches(raw: dict) -> dict:
    """Shape-guarantee the model output so the UI can render it blindly."""
    matches: List[dict] = []
    for entry in (raw.get("matches") or [])[:4]:
        if not isinstance(entry, dict) or not _clean(entry.get("name")):
            continue
        gov = _clean(entry.get("gov_experience")).lower()
        matches.append({
            "name": _clean(entry.get("name")),
            "location": _clean(entry.get("location")),
            "trade": _clean(entry.get("trade")),
            "website": _clean(entry.get("website")),
            "phone": _clean(entry.get("phone")),
            "email": _clean(entry.get("email")),
            "gov_experience": gov if gov in GOV_EXPERIENCE else "unknown",
            "why_fit": _clean(entry.get("why_fit")),
            "pitch_angle": _clean(entry.get("pitch_angle")),
            "sources": _url_list(entry.get("sources")),
        })
    return {"matches": matches, "market_note": _clean(raw.get("market_note"))}


def _call_claude(model: str, messages: List[dict], tools: List[dict],
                 tool_choice: Optional[dict] = None):
    """One Messages API request. Module-level so tests can stand it in."""
    import anthropic

    client = anthropic.Anthropic(api_key=api_key())
    kwargs = dict(
        model=model,
        max_tokens=MAX_MATCH_TOKENS,
        system=SYSTEM_PROMPT,
        tools=tools,
        messages=messages,
    )
    if tool_choice is not None:
        kwargs["tool_choice"] = tool_choice
    return client.messages.create(**kwargs)


def _record_input(content) -> Optional[dict]:
    for block in content:
        if getattr(block, "type", None) == "tool_use" \
                and getattr(block, "name", "") == "record_contractor_matches":
            return dict(block.input)
    return None


def _find(model: str, context: str) -> Tuple[dict, int]:
    """Search phase, then a forced record if the model didn't volunteer one."""
    search_tool = dict(_search_tool(model)) | {"max_uses": MAX_SEARCHES}
    messages: List[dict] = [{"role": "user", "content": context}]

    searched = 0
    response = None
    for _ in range(MAX_CONTINUATIONS + 1):
        response = _call_claude(model, messages, [search_tool, _RECORD_TOOL])
        searched += sum(
            1 for b in response.content if getattr(b, "type", "") == "server_tool_use"
        )
        if response.stop_reason != "pause_turn":
            break
        # Server-side search hit its iteration limit mid-turn: send the paused
        # assistant turn back as-is and the server resumes where it stopped.
        messages.append({"role": "assistant", "content": response.content})

    recorded = _record_input(response.content)
    if recorded is None:
        # The research is in the transcript; force the record on a follow-up.
        messages.append({"role": "assistant", "content": response.content})
        messages.append({
            "role": "user",
            "content": "Record your candidates now with record_contractor_matches.",
        })
        response = _call_claude(
            model, messages, [_RECORD_TOOL],
            tool_choice={"type": "tool", "name": "record_contractor_matches"},
        )
        recorded = _record_input(response.content)
    if recorded is None:
        raise RuntimeError("model returned no contractor matches")
    return recorded, searched


def run_match(opp: Opportunity, *, model: Optional[str] = None,
              force: bool = False) -> dict:
    """Run (or return the cached) contractor matching for one bid.

    Blocking — the API layer runs this in a thread. Returns the same envelope
    as ``db.get_contractor_matches``.
    """
    if not enabled():
        raise RuntimeError("no_api_key")
    model = model if model in ALLOWED_MODELS else DEFAULT_MODEL

    context = build_context(opp)
    digest = hashlib.sha256(context.encode("utf-8")).hexdigest()[:16]

    cached = db.get_contractor_matches(opp.opportunity_id, MATCH_PROMPT_VERSION)
    if not force and cached is not None and cached["content_hash"] == digest \
            and cached["model"] == model:
        return cached | {"cached": True}

    raw, searched = _find(model, context)
    normalized = normalize_matches(raw)

    # Outreach already underway on a re-run keeps its status.
    prior_status: Dict[str, str] = {
        m.get("contractor_id"): m.get("status", "suggested")
        for m in (cached or {}).get("matches", [])
    }
    matches: List[dict] = []
    for entry in normalized["matches"]:
        cid = contractor_id(entry["name"])
        db.upsert_contractor({
            "id": cid,
            "name": entry["name"],
            "county": opp.county or "",
            "location": entry["location"],
            "trade": entry["trade"],
            "website": entry["website"],
            "phone": entry["phone"],
            "email": entry["email"],
            "profile": {
                "gov_experience": entry["gov_experience"],
                "sources": entry["sources"],
            },
        })
        matches.append(entry | {
            "contractor_id": cid,
            "status": prior_status.get(cid, "suggested"),
        })

    db.put_contractor_matches(
        opp.opportunity_id,
        content_hash=digest,
        model=model,
        prompt_version=MATCH_PROMPT_VERSION,
        matches=matches,
        market_note=normalized["market_note"],
        searches=searched,
    )
    result = db.get_contractor_matches(opp.opportunity_id, MATCH_PROMPT_VERSION)
    assert result is not None
    return result | {"cached": False}
