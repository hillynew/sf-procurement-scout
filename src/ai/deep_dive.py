"""'Go Deep': exhaustive Claude analysis of one deal.

Where the regular brief reads the scraped fields plus the primary package
PDF, a deep dive downloads **every** attached document (specs, addenda,
plans, forms — capped for cost), feeds the lot to Claude, and compiles a
structured dossier: every dollar figure with its context, all dates, the
scope broken into line items, categorized requirements, evaluation criteria,
contacts, per-document gists, red flags, and open questions worth asking the
agency. Cached per (documents+fields content hash, model, prompt version).
"""

from __future__ import annotations

import hashlib
from typing import Dict, List, Optional, Tuple

from src.db import store as db
from src.models.opportunity import Opportunity

from .summarizer import ALLOWED_MODELS, DEFAULT_MODEL, api_key, build_input, enabled

DEEP_PROMPT_VERSION = 2  # v2: contacts + documents_reviewed became required

MAX_DOCS = 8                 # documents downloaded per dive
MAX_DOC_CHARS = 60_000       # per document
MAX_INPUT_CHARS = 160_000    # total (~45K tokens — well inside the context window)

SYSTEM_PROMPT = (
    "You are a senior estimator and bid analyst for a small South Florida "
    "contractor doing an exhaustive read of one government solicitation. The "
    "user provides the scraped listing plus the text of every attached "
    "document. Compile EVERYTHING a bidder needs: every dollar figure with "
    "what it refers to, every date, the scope as concrete line items, every "
    "requirement (bonding, insurance, licensing, submission mechanics, "
    "wage/set-aside), how the award is decided, who to contact, what each "
    "document contains, what could hurt the bidder, and what remains unclear "
    "and should be asked before the question deadline. Quote amounts and "
    "dates exactly as written. Never invent figures — omit what the "
    "documents do not support. Plain English throughout."
)

DEEP_SCHEMA = {
    "type": "object",
    "properties": {
        "overview": {
            "type": "string",
            "description": "One tight paragraph: what is being bought, by whom, and the shape of the deal.",
        },
        "dollar_amounts": {
            "type": "array",
            "description": "EVERY dollar figure found, with what it refers to and where it came from.",
            "items": {
                "type": "object",
                "properties": {
                    "label": {"type": "string"},
                    "amount": {"type": "string"},
                    "source": {"type": "string"},
                },
                "required": ["label", "amount"],
                "additionalProperties": False,
            },
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
        "scope_items": {
            "type": "array",
            "items": {"type": "string"},
            "description": "The work broken into concrete line items / bid items.",
        },
        "requirements": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "enum": ["bonding", "insurance", "licensing",
                                 "submission", "wage_set_aside", "other"],
                    },
                    "item": {"type": "string"},
                },
                "required": ["category", "item"],
                "additionalProperties": False,
            },
        },
        "evaluation": {
            "type": "array",
            "items": {"type": "string"},
            "description": "How the award is decided: criteria, weights, low-bid vs best-value.",
        },
        "contacts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "role": {"type": "string"},
                    "email": {"type": "string"},
                    "phone": {"type": "string"},
                },
                "required": ["name"],
                "additionalProperties": False,
            },
        },
        "documents_reviewed": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "gist": {"type": "string"},
                },
                "required": ["name", "gist"],
                "additionalProperties": False,
            },
        },
        "red_flags": {"type": "array", "items": {"type": "string"}},
        "open_questions": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Unclear points worth asking the agency before the question deadline.",
        },
        "fit_assessment": {
            "type": "string",
            "description": "2-3 sentences: who wins this and what it takes to compete.",
        },
    },
    "required": ["overview", "dollar_amounts", "key_dates", "scope_items",
                 "requirements", "evaluation", "contacts",
                 "documents_reviewed", "red_flags", "open_questions",
                 "fit_assessment"],
    "additionalProperties": False,
}


def _gather_documents(opp: Opportunity) -> Tuple[str, int]:
    """Download and concatenate text from every attached PDF (bounded)."""
    from src.pdf_extract import fetch_text

    chunks: List[str] = []
    read = 0
    for doc in opp.documents[:MAX_DOCS]:
        # Try every real link — fetch_text sniffs the %PDF magic itself and
        # returns '' for anything that isn't a PDF, so extensionless
        # download URLs (common on county portals) still get read.
        if not doc.url.lower().startswith(("http://", "https://")):
            continue
        try:
            text = fetch_text(doc.url)
        except Exception:  # noqa: BLE001 — a dead link must not kill the dive
            text = ""
        if text:
            read += 1
            chunks.append(
                f"\n===== DOCUMENT {read}: {doc.name} ({doc.kind}) =====\n"
                + text[:MAX_DOC_CHARS]
            )
    return "".join(chunks), read


def build_deep_input(opp: Opportunity) -> Tuple[str, int]:
    listing = build_input(opp, "")  # scraped fields, scope, description
    docs, read = _gather_documents(opp)
    text = (
        "SCRAPED LISTING\n" + listing +
        ("\n\nATTACHED DOCUMENTS" + docs if docs else
         "\n\n(No documents could be read — analyze the listing alone and "
         "say so in open_questions.)")
    )
    return text[:MAX_INPUT_CHARS], read


def _string_list(value) -> List[str]:
    if not isinstance(value, list):
        return []
    return [str(v).strip() for v in value if str(v).strip()]


def _dict_list(value, required: str) -> List[dict]:
    if not isinstance(value, list):
        return []
    return [v for v in value if isinstance(v, dict) and v.get(required)]


def normalize_report(raw: dict) -> dict:
    """Shape-guarantee the report so the UI can render it blindly."""
    return {
        "overview": str(raw.get("overview") or "").strip(),
        "dollar_amounts": _dict_list(raw.get("dollar_amounts"), "amount"),
        "key_dates": _dict_list(raw.get("key_dates"), "label"),
        "scope_items": _string_list(raw.get("scope_items")),
        "requirements": _dict_list(raw.get("requirements"), "item"),
        "evaluation": _string_list(raw.get("evaluation")),
        "contacts": _dict_list(raw.get("contacts"), "name"),
        "documents_reviewed": _dict_list(raw.get("documents_reviewed"), "name"),
        "red_flags": _string_list(raw.get("red_flags")),
        "open_questions": _string_list(raw.get("open_questions")),
        "fit_assessment": str(raw.get("fit_assessment") or "").strip(),
    }


def _call_claude(model: str, text: str) -> Dict:
    import anthropic

    client = anthropic.Anthropic(api_key=api_key())
    response = client.messages.create(
        model=model,
        max_tokens=8000,
        system=SYSTEM_PROMPT,
        tools=[{
            "name": "record_deep_dive",
            "description": "Record the exhaustive structured analysis of this solicitation.",
            "strict": True,
            "input_schema": DEEP_SCHEMA,
        }],
        tool_choice={"type": "tool", "name": "record_deep_dive"},
        messages=[{"role": "user", "content": text}],
    )
    for block in response.content:
        if block.type == "tool_use" and block.name == "record_deep_dive":
            return dict(block.input)
    raise RuntimeError("model returned no deep-dive report")


def run_deep_dive(opp: Opportunity, *, model: Optional[str] = None,
                  force: bool = False) -> dict:
    """Run (or return the cached) deep dive for one bid.

    Blocking — the API layer runs this in a thread. Returns the same envelope
    as ``db.get_deep_dive``.
    """
    if not enabled():
        raise RuntimeError("no_api_key")
    model = model if model in ALLOWED_MODELS else DEFAULT_MODEL

    text, docs_read = build_deep_input(opp)
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]

    if not force:
        cached = db.get_deep_dive(opp.opportunity_id, DEEP_PROMPT_VERSION)
        if cached is not None and cached["content_hash"] == digest \
                and cached["model"] == model:
            return cached | {"cached": True}

    report = normalize_report(_call_claude(model, text))
    db.put_deep_dive(
        opp.opportunity_id,
        content_hash=digest,
        model=model,
        prompt_version=DEEP_PROMPT_VERSION,
        report=report,
        input_chars=len(text),
        docs_read=docs_read,
    )
    result = db.get_deep_dive(opp.opportunity_id, DEEP_PROMPT_VERSION)
    assert result is not None
    return result | {"cached": False}
