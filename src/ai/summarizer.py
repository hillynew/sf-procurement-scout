"""Claude-powered deal briefs.

Turns a solicitation's scraped fields + bid-package text into a structured
plain-English brief. Inert without an API key (``SF_SCOUT_ANTHROPIC_KEY`` or
``ANTHROPIC_API_KEY``): callers check :func:`enabled` and fall back to the
rule-based ``src.summarize`` brief.

Summaries are cached in the database keyed on (opportunity, input hash,
model, prompt version) — a bid is only ever re-summarized when an addendum
changes its text, the model is switched, or the prompt is revised.
"""

from __future__ import annotations

import hashlib
import os
import re
from typing import Dict, List, Optional

from src.db import store as db
from src.models.opportunity import Opportunity

# v2: strict tool use + output normalization (v1 briefs could carry
# stringified lists from non-strict tool calls).
PROMPT_VERSION = 2

DEFAULT_MODEL = "claude-haiku-4-5"
ALLOWED_MODELS = ("claude-haiku-4-5", "claude-sonnet-5")

# ~8K tokens. Commercial terms live in a package's front pages, so a hard cap
# keeps cost predictable without losing the labelled facts.
MAX_INPUT_CHARS = 30_000

SYSTEM_PROMPT = (
    "You are a bid analyst for a small South Florida contractor. Summarize the "
    "government solicitation the user provides into a plain-English deal brief. "
    "Be concrete and skeptical: surface bonding, licensing, insurance, wage and "
    "set-aside obligations, unrealistic timelines, mandatory pre-bid meetings, "
    "and liquidated damages as red flags. Never invent dollar figures or dates — "
    "omit anything the text does not support."
)

# Strict-mode compatible: additionalProperties: false on every object so the
# API validates the tool input exactly (no stringified lists slipping through).
BRIEF_SCHEMA = {
    "type": "object",
    "properties": {
        "what_the_work_is": {
            "type": "string",
            "description": "2-3 plain-English sentences describing the work.",
        },
        "key_dates": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "label": {"type": "string"},
                    "date": {"type": "string"},
                    "note": {"type": "string"},
                },
                "required": ["label", "date"],
                "additionalProperties": False,
            },
        },
        "money": {
            "type": "object",
            "properties": {
                "estimated_value": {"type": "string"},
                "bonding": {"type": "string"},
                "payment_terms": {"type": "string"},
            },
            "additionalProperties": False,
        },
        "requirements": {
            "type": "array",
            "items": {"type": "string"},
            "description": "License/insurance/wage obligations in plain English.",
        },
        "red_flags": {
            "type": "array",
            "items": {"type": "string"},
        },
        "fit_hint": {
            "type": "string",
            "description": "One sentence on who this bid suits.",
        },
    },
    "required": ["what_the_work_is", "requirements", "red_flags", "fit_hint"],
    "additionalProperties": False,
}

_ITEM_RE = re.compile(r"<item>\s*(.*?)\s*</item>", re.DOTALL)
_TAG_RE = re.compile(r"</?[a-zA-Z][^>]*>")


def _string_list(value) -> List[str]:
    """Coerce a model-emitted list field into a clean list of strings.

    Defense in depth for non-strict responses: models occasionally emit a
    whole list as one XML-ish string ("<item>a</item><item>b</item>") or a
    newline-joined blob. Strict tool use should prevent this, but a cached
    or fallback response must still render sanely.
    """
    if isinstance(value, str):
        chunks = _ITEM_RE.findall(value)
        if not chunks:
            chunks = value.splitlines()
        value = chunks
    if not isinstance(value, list):
        return []
    out: List[str] = []
    for item in value:
        text = _TAG_RE.sub("", str(item)).strip()
        if text:
            out.append(text)
    return out


def _normalize_brief(raw: dict) -> dict:
    """Coerce a model result into the shape the UI renders."""
    brief: dict = {}
    brief["what_the_work_is"] = str(raw.get("what_the_work_is") or "").strip()
    brief["requirements"] = _string_list(raw.get("requirements"))
    brief["red_flags"] = _string_list(raw.get("red_flags"))
    brief["fit_hint"] = str(raw.get("fit_hint") or "").strip()

    dates = []
    for entry in raw.get("key_dates") or []:
        if isinstance(entry, dict) and entry.get("label"):
            dates.append({
                "label": str(entry["label"]).strip(),
                "date": str(entry.get("date") or "").strip(),
                "note": str(entry.get("note") or "").strip(),
            })
    brief["key_dates"] = dates

    money = raw.get("money")
    brief["money"] = {
        k: str(money[k]).strip()
        for k in ("estimated_value", "bonding", "payment_terms")
        if isinstance(money, dict) and isinstance(money.get(k), str) and money[k].strip()
    }
    return brief


def api_key() -> Optional[str]:
    return (
        os.environ.get("SF_SCOUT_ANTHROPIC_KEY")
        or os.environ.get("ANTHROPIC_API_KEY")
        or None
    )


def enabled() -> bool:
    return api_key() is not None


def build_input(opp: Opportunity, package_text: str = "") -> str:
    """Assemble the model input from everything the pipeline knows."""
    lines: List[str] = [
        f"Title: {opp.title}",
        f"Agency: {opp.agency} ({opp.county} county)",
        f"Type: {opp.to_row()['solicitation_type']} / {opp.to_row()['offer_type']}",
    ]
    if opp.external_id:
        lines.append(f"Reference: {opp.external_id}")
    if opp.due_date:
        lines.append(f"Due: {opp.due_date.isoformat()}")
    if opp.questions_due:
        lines.append(f"Questions due: {opp.questions_due.isoformat()}")
    if opp.pre_bid_meeting:
        lines.append(f"Pre-bid meeting: {opp.pre_bid_meeting}")
    if opp.budget:
        lines.append(f"Stated budget: {opp.budget}")
    if opp.duration_days:
        lines.append(f"Contract duration (days): {opp.duration_days}")
    if opp.liquidated_damages:
        lines.append(f"Liquidated damages: {opp.liquidated_damages}")
    if opp.licenses:
        lines.append(f"License requirements: {opp.licenses}")
    if opp.project_location:
        lines.append(f"Location: {opp.project_location}")
    if opp.requirements:
        lines.append("Requirements found: " + "; ".join(opp.requirements))
    if opp.prior_cycles:
        lines.append(
            f"Recurring buy: {opp.prior_cycles} prior cycle(s), "
            f"last closed {opp.last_cycle_closed}"
        )
    if opp.submittal_info:
        lines.append(f"Submittal: {opp.submittal_info}")
    if opp.description:
        lines.append("\nDescription:\n" + opp.description)
    if opp.scope:
        lines.append("\nScope of work:\n" + opp.scope)
    if package_text:
        lines.append("\nBid package text (extracted from PDF):\n" + package_text)
    return "\n".join(lines)[:MAX_INPUT_CHARS]


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _package_text(opp: Opportunity) -> str:
    """Cached text of the first non-addendum package document, if any."""
    from src.pdf_extract import fetch_text

    for doc in opp.documents:
        if doc.kind != "addendum" and doc.url.lower().endswith(".pdf"):
            try:
                return fetch_text(doc.url)
            except Exception:  # noqa: BLE001
                return ""
    return ""


def _call_claude(model: str, text: str) -> Dict:
    """One isolated call site. Structured output via a forced tool call."""
    import anthropic

    client = anthropic.Anthropic(api_key=api_key())
    response = client.messages.create(
        model=model,
        max_tokens=1200,
        system=SYSTEM_PROMPT,
        tools=[{
            "name": "record_deal_brief",
            "description": "Record the structured deal brief for this solicitation.",
            "strict": True,  # API-side guarantee the input matches the schema
            "input_schema": BRIEF_SCHEMA,
        }],
        tool_choice={"type": "tool", "name": "record_deal_brief"},
        messages=[{"role": "user", "content": text}],
    )
    for block in response.content:
        if block.type == "tool_use" and block.name == "record_deal_brief":
            return dict(block.input)
    raise RuntimeError("model returned no structured brief")


def summarize(
    opp: Opportunity,
    *,
    model: Optional[str] = None,
    force: bool = False,
    with_package: bool = True,
) -> dict:
    """Return {'summary', 'model', 'cached'} for one bid, generating if needed."""
    if not enabled():
        raise RuntimeError("no_api_key")
    model = model if model in ALLOWED_MODELS else DEFAULT_MODEL
    text = build_input(opp, _package_text(opp) if with_package else "")
    digest = content_hash(text)

    if not force:
        cached = db.get_summary(opp.opportunity_id, digest, model, PROMPT_VERSION)
        if cached is not None:
            return {"summary": cached, "model": model, "cached": True}

    summary = _normalize_brief(_call_claude(model, text))
    db.put_summary(opp.opportunity_id, digest, model, PROMPT_VERSION,
                   summary, input_chars=len(text))
    return {"summary": summary, "model": model, "cached": False}


def auto_summarize_tracked(opps: List[Opportunity], workflow: Dict[str, dict]) -> int:
    """Summarize every tracked, unarchived bid missing a cached brief.

    Sequential on purpose — volume is tiny and rate limits are a non-issue.
    Returns the number of new summaries generated; never raises.
    """
    if not enabled():
        return 0
    settings = db.get_settings()
    if not settings["ai"].get("auto_summarize_tracked", True):
        return 0
    model = settings["ai"].get("model") or DEFAULT_MODEL
    by_id = {o.opportunity_id: o for o in opps}
    done = 0
    for oid, wf in workflow.items():
        if wf["archived"] or wf["stage"] == "result":
            continue
        opp = by_id.get(oid)
        if opp is None:
            continue
        try:
            result = summarize(opp, model=model)
            if not result["cached"]:
                done += 1
        except Exception:  # noqa: BLE001 — a summary failure must not kill the run
            continue
    return done
