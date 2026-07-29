"""Pull the facts a bidder decides on out of scope-of-work prose.

Solicitation pages publish requirements as free text buried in several
paragraphs of boilerplate. A contractor deciding whether to bid wants to know
four things quickly: what it is worth, what they must post (bonds, insurance),
what they must already hold (licence, prequalification), and when the
non-obvious deadlines fall. These extractors surface exactly those.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import List, Optional

from .dates import parse_dt

# (label, pattern) — order controls display order, not precedence.
REQUIREMENT_RULES: List[tuple[str, str]] = [
    ("Bid bond", r"\bbid\s+bond\b|\bbid\s+security\b|\bproposal\s+bond\b"),
    ("Performance bond", r"\bperformance\s+bond\b"),
    ("Payment bond", r"\bpayment\s+bond\b"),
    ("Insurance certificate", r"\bcertificate\s+of\s+insurance\b|\binsurance\s+requirement|\bliability\s+insurance\b"),
    ("Licensed contractor", r"\blicensed\b|\bstate\s+certified\b|\bgeneral\s+contractor'?s?\s+licen[cs]e\b"),
    ("Prequalification required", r"\bpre[-\s]?qualif"),
    ("Mandatory pre-bid meeting", r"\bmandatory\b[^.]{0,60}\bpre[-\s]?(?:bid|proposal|submittal)\b|\bpre[-\s]?bid\b[^.]{0,40}\bmandatory\b"),
    ("Mandatory site visit", r"\bmandatory\b[^.]{0,40}\bsite\s+(?:visit|inspection)\b"),
    ("E-Verify", r"\be[-\s]?verify\b"),
    ("SBE/MBE/DBE participation", r"\b(?:SBE|MBE|DBE|WBE|M/?WBE)\b|\bsmall\s+business\s+enterprise\b|\bdisadvantaged\s+business\b"),
    ("Local preference", r"\blocal\s+(?:business\s+)?preference\b|\blocal\s+vendor\s+preference\b"),
    ("Living wage", r"\bliving\s+wage\b|\bprevailing\s+wage\b|\bDavis[-\s]?Bacon\b"),
    ("Drug-free workplace", r"\bdrug[-\s]?free\s+workplace\b"),
    ("Public entity crimes affidavit", r"\bpublic\s+entity\s+crimes?\b"),
    ("Background screening", r"\bbackground\s+(?:screening|check)\b|\blevel\s+2\s+screening\b"),
    ("Bonding capacity", r"\bbonding\s+capacity\b"),
    ("References required", r"\b(?:three|3|five|5)\s+(?:\(\d\)\s*)?(?:similar\s+)?references\b|\breference\s+requirement"),
]

_COMPILED = [(label, re.compile(pat, re.I)) for label, pat in REQUIREMENT_RULES]

# Money, with the qualifier that gives it meaning.
# One or two decimals: cents ("$1,200.50") and magnitudes ("$2.5 million")
# both occur, and requiring exactly two silently truncated the latter to "$2".
_MONEY = r"\$\s?[\d,]+(?:\.\d{1,2})?(?:\s*(?:million|billion|M|K)\b)?"
_VALUE_RULES = [
    rf"(?:not\s+to\s+exceed|nte)\s+(?:of\s+)?({_MONEY})",
    rf"(?:estimated|approximate|anticipated)\s+(?:construction\s+)?(?:budget|value|cost|amount)\s*(?:is|of|:)?\s*({_MONEY})",
    rf"(?:budget|value|amount)\s+of\s+({_MONEY})",
    rf"({_MONEY})\s*(?:per\s+year|annually|per\s+annum)",
    rf"(?:total\s+)?(?:contract|project)\s+(?:value|amount|budget)\s*(?:is|of|:)?\s*({_MONEY})",
]
_VALUE_COMPILED = [re.compile(p, re.I) for p in _VALUE_RULES]

# A bare dollar figure is only meaningful above a threshold — "$50 fee" is not
# the contract value.
_BARE_MONEY = re.compile(_MONEY, re.I)
_MIN_BARE_VALUE = 25_000

# A date, with the weekday and time that usually surround it kept separate so
# the trailing prose ("by no later no 3:30PM (EST)") never reaches the parser.
_DATE = (
    r"(?:[A-Z][a-z]+day,?\s+)?"  # optional weekday, discarded
    r"(?P<date>[A-Z][a-z]+\s+\d{1,2},?\s+\d{4}|\d{1,2}/\d{1,2}/\d{4})"
    r"(?:[^\n]{0,30}?(?P<time>\d{1,2}:\d{2}\s*[AP]\.?M\.?))?"
)
_QUESTIONS_RE = re.compile(
    r"(?:questions?|additional\s+information|clarification|inquiries)"
    rf"[^\n]{{0,60}}?\s*{_DATE}",
    re.I,
)

_PREBID = re.compile(
    r"pre[-\s]?(?:bid|proposal|submittal)\s+(?:conference|meeting)[^.\n]{0,180}",
    re.I,
)


def extract_requirements(*texts: Optional[str]) -> List[str]:
    """Labels for every requirement mentioned across the given text blocks."""
    blob = "\n".join(t for t in texts if t)
    if not blob:
        return []
    return [label for label, pattern in _COMPILED if pattern.search(blob)]


def dedupe_requirements(labels: List[str]) -> List[str]:
    """Collapse labels that say the same thing at different specificity.

    Two extractors run over each bid: the prose scanner produces "Bid bond",
    the package parser produces "Bid bond required". Showing both as separate
    chips reads as two obligations when it is one, so the more specific label
    absorbs the shorter one whose words it already contains.
    """
    kept: List[str] = []
    for label in labels:
        words = _words(label)
        if not words:
            continue
        replaced = False
        for i, existing in enumerate(kept):
            other = _words(existing)
            if words <= other:  # already covered by a more specific label
                replaced = True
                break
            if other < words:  # this label is the more specific one
                kept[i] = label
                replaced = True
                break
        if not replaced:
            kept.append(label)
    return kept


def _words(label: str) -> frozenset:
    return frozenset(re.findall(r"[a-z0-9]+", label.lower())) - _STOPWORDS


_STOPWORDS = frozenset({"required", "a", "the", "of", "and", "to"})


def extract_estimated_value(*texts: Optional[str]) -> Optional[str]:
    """A contract value, preferring figures that carry an explicit qualifier."""
    blob = "\n".join(t for t in texts if t)
    if not blob:
        return None

    for pattern in _VALUE_COMPILED:
        m = pattern.search(blob)
        if m:
            return _tidy_money(m.group(1))

    # Fall back to the largest bare figure, if it is big enough to be a contract.
    best, best_amount = None, 0
    for m in _BARE_MONEY.finditer(blob):
        amount = _to_number(m.group(0))
        if amount > best_amount:
            best, best_amount = m.group(0), amount
    if best and best_amount >= _MIN_BARE_VALUE:
        return _tidy_money(best)
    return None


def extract_pre_bid_meeting(*texts: Optional[str]) -> Optional[str]:
    blob = "\n".join(t for t in texts if t)
    if not blob:
        return None
    m = _PREBID.search(blob)
    return re.sub(r"\s+", " ", m.group(0)).strip(" .;:") if m else None


def extract_questions_due(*texts: Optional[str]) -> Optional[datetime]:
    """The question deadline, which usually falls well before the bid date."""
    blob = "\n".join(t for t in texts if t)
    if not blob:
        return None
    m = _QUESTIONS_RE.search(blob)
    return _date_from(m) if m else None


def _date_from(m: re.Match) -> Optional[datetime]:
    parts = [m.group("date")]
    if m.group("time"):
        parts.append(m.group("time"))
    return parse_dt(" ".join(parts))


def extract_contact_email(*texts: Optional[str]) -> Optional[str]:
    blob = "\n".join(t for t in texts if t)
    m = re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", blob or "")
    return m.group(0).rstrip(".") if m else None


def extract_contact_phone(*texts: Optional[str]) -> Optional[str]:
    blob = "\n".join(t for t in texts if t)
    m = re.search(r"\(?\b\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}\b", blob or "")
    return m.group(0).strip() if m else None


def _tidy_money(text: str) -> str:
    """Normalize spacing but keep the agency's own figure: '$ 1,200' -> '$1,200'."""
    compact = re.sub(r"\s+", "", text)
    # Re-space only a magnitude suffix, which reads badly glued on.
    return re.sub(r"(million|billion)$", r" \1", compact, flags=re.I)


def _to_number(text: str) -> float:
    raw = re.sub(r"[^\d.]", "", text)
    if not raw:
        return 0.0
    try:
        value = float(raw)
    except ValueError:
        return 0.0
    lowered = text.lower()
    if "million" in lowered or re.search(r"\dM\b", text):
        value *= 1_000_000
    elif "billion" in lowered:
        value *= 1_000_000_000
    elif re.search(r"\dK\b", text):
        value *= 1_000
    return value

