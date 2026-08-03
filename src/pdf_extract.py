"""Read the bid package PDF, which is where the commercial terms actually live.

HTML listings describe a project; the solicitation PDF states what it is worth,
what bond is required, which licences the bidder must hold, how many calendar
days the work gets and what the liquidated damages are. Miami-Dade's RPQ
packages in particular open with a labelled "DETAILED BREAKDOWN" block:

    Bid Due Date: 7/31/2026 Time Due:02:00 PM Submitted Via:Sealed Envelopes
    Estimated Value: $68,400 (excluding Contingencies and Dedicated Allowances)
    Project Location: 930 Dunad Ave, Opa-locka Florida 33054
    License Requirements:Primary: General Building Contractor
    Bid Bond Required:YES        Liquidated Damages: YES $$ Per Day:$250
    Calendar Days for Project Completion:1095

Downloads are bounded and cached on disk: several solicitations often share one
package, and a refresh should never re-fetch what it already read.
"""

from __future__ import annotations

import hashlib
import io
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from .http_util import get

# Bid packages run to hundreds of pages of boilerplate; the terms are at the
# front. These caps keep a refresh bounded in both time and memory.
MAX_BYTES = 12 * 1024 * 1024
MAX_PAGES = 15
MAX_TEXT_CHARS = 200_000
FETCH_TIMEOUT = 45

_YES = re.compile(r"^\s*(yes|y|required)\b", re.I)
_MONEY = r"\$\s?[\d,]+(?:\.\d{1,2})?"


@dataclass
class PdfFacts:
    """Structured terms lifted out of a bid package."""

    estimated_value: Optional[str] = None
    project_location: Optional[str] = None
    licenses: Optional[str] = None
    duration_days: Optional[int] = None
    liquidated_damages: Optional[str] = None
    scope: Optional[str] = None
    requirements: List[str] = field(default_factory=list)
    text_chars: int = 0

    def is_empty(self) -> bool:
        return not any(
            (
                self.estimated_value,
                self.project_location,
                self.licenses,
                self.duration_days,
                self.liquidated_damages,
                self.scope,
                self.requirements,
            )
        )


def cache_dir() -> Path:
    from .sources.registry import project_root

    d = project_root() / "data" / "pdf_cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _db_cache_get(key: str):
    """Second cache tier: the database survives ephemeral-disk restarts."""
    try:
        from .db.store import get_pdf_text

        return get_pdf_text(key)
    except Exception:  # noqa: BLE001 — cache misses must never fail a fetch
        return None


def _db_cache_put(key: str, text: str) -> None:
    try:
        from .db.store import put_pdf_text

        put_pdf_text(key, text)
    except Exception:  # noqa: BLE001
        pass


def fetch_text(url: str, *, use_cache: bool = True, headers: Optional[dict] = None) -> str:
    """Download a PDF and return its leading text. '' when unusable.

    `headers` carries any portal-specific quirk the source declares — some
    portals content-negotiate on Accept and answer an HTML-first request with
    their SPA shell instead of the file, which lands here as "not a PDF".
    """
    key = hashlib.sha1(url.encode("utf-8")).hexdigest()[:20]
    cached = cache_dir() / f"{key}.txt"
    if use_cache and cached.exists():
        try:
            return cached.read_text(encoding="utf-8")
        except OSError:
            pass
    if use_cache:
        from_db = _db_cache_get(key)
        if from_db:
            try:
                cached.write_text(from_db, encoding="utf-8")
            except OSError:
                pass
            return from_db

    try:
        resp = get(url, timeout=FETCH_TIMEOUT, retries=1, headers=headers or None)
    except Exception:  # noqa: BLE001 — a missing package must not fail the bid
        return ""

    raw = resp.content or b""
    if len(raw) > MAX_BYTES or not raw.startswith(b"%PDF"):
        return ""

    text = _extract(raw)
    if use_cache and text:
        try:
            cached.write_text(text, encoding="utf-8")
        except OSError:
            pass
        _db_cache_put(key, text)
    return text


def _extract(raw: bytes) -> str:
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(raw))
        pages = reader.pages[:MAX_PAGES]
        text = "\n".join((p.extract_text() or "") for p in pages)
    except Exception:  # noqa: BLE001 — encrypted/damaged PDFs are common
        return ""
    return text[:MAX_TEXT_CHARS]


def parse_facts(text: str) -> PdfFacts:
    """Pull the labelled terms out of extracted package text."""
    facts = PdfFacts(text_chars=len(text or ""))
    if not text:
        return facts

    fields = _labelled_fields(text)

    value = fields.get("estimated value")
    if value:
        m = re.search(_MONEY, value)
        if m:
            facts.estimated_value = re.sub(r"\s+", "", m.group(0))

    facts.project_location = _tidy(fields.get("project location"))
    facts.licenses = _tidy(fields.get("license requirements"))

    days = fields.get("calendar days for project completion")
    if days:
        m = re.search(r"\d{1,5}", days)
        if m:
            facts.duration_days = int(m.group(0))

    ld = fields.get("liquidated damages")
    if ld and _YES.match(ld):
        # The amount usually lands under its own "Per Day:" label, because the
        # PDF writes "Liquidated Damages: YES $$ Per Day:$333.71".
        facts.liquidated_damages = _liquidated_damages(ld, fields.get("per day"))

    facts.requirements = _requirements_from(fields, text)
    facts.scope = _scope_from(text)
    return facts


def _liquidated_damages(value: str, per_day_field: Optional[str] = None) -> str:
    """'YES $$' + 'Per Day: $333' -> '$333 per day'."""
    for candidate in (per_day_field, value):
        if not candidate:
            continue
        m = re.search(_MONEY, candidate)
        if m:
            compact = re.sub(r"\s+", "", m.group(0))
            return f"{compact} per day"
    return "Yes"


#: A label is one or more capitalised words before a colon. `&` is included so
#: "Performance & Payment Bond Required" survives whole.
_LABEL = re.compile(
    r"(?<![A-Za-z0-9])"
    # A label never starts with an answer token. Without this, the YES ending
    # one field is swallowed into the name of the next ("YES Bid Bond Required").
    r"(?!(?:YES|NO|N/A|TBD)\b)"
    r"([A-Z][A-Za-z0-9]*"
    # Separator is whitespace, or an ampersand/slash/hyphen that may itself be
    # spaced — "Performance & Payment Bond Required" is one label, not three.
    r"(?:(?:\s*[&/-]\s*|\s+)[A-Za-z0-9][A-Za-z0-9]*){0,6})"
    r"\s*:"
)


def _labelled_fields(text: str) -> Dict[str, str]:
    """`Label: value` pairs, parsed a line at a time.

    The breakdown block packs several pairs onto one line with as little as a
    single space between them — "Performance & Payment Bond Required:YES Bid
    Bond Required:YES" — so each value must end where the *next* label begins,
    not at some fixed amount of whitespace.
    """
    fields: Dict[str, str] = {}
    for line in text.splitlines():
        matches = list(_LABEL.finditer(line))
        for i, m in enumerate(matches):
            label = re.sub(r"\s+", " ", m.group(1)).strip().lower()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(line)
            value = line[m.end() : end].strip()
            if not value:
                # A label with nothing before the next one is a prefix, e.g.
                # "License Requirements:Primary: General Building Contractor".
                value = line[m.end() :].strip()
            if label and value and label not in fields:
                fields[label] = value[:400]
    return fields


def _requirements_from(fields: Dict[str, str], text: str) -> List[str]:
    """Yes/no term flags, expressed the way a bidder would read them."""
    out: List[str] = []

    def flag(label: str, phrasing: str) -> None:
        value = fields.get(label)
        if value and _YES.match(value):
            out.append(phrasing)

    flag("bid bond required", "Bid bond required")
    flag("performance bond required", "Performance bond required")
    flag("payment bond required", "Payment bond required")
    flag("performance & payment bond required", "Performance & payment bond required")
    flag("davis bacon", "Davis-Bacon wage rates")
    flag("additional insurance required", "Additional insurance")
    flag("maintenance wages", "Maintenance wage rates")
    flag("aipp", "Art in Public Places contribution")
    flag("dbe subcontractor forms required", "DBE subcontractor forms")
    flag("responsible wages", "Responsible wages")
    flag("living wage", "Living wage")

    licences = fields.get("license requirements")
    if licences:
        out.append(f"Licence: {_tidy(licences)}"[:140])

    # Set-aside percentages appear as "SBE-S Requirements YES Percentage: 10%".
    m = re.search(r"(SBE|DBE|MBE|WBE)[-\w]*\s+Requirements?\s*:?\s*YES[^%\n]{0,40}?(\d+(?:\.\d+)?)\s*%", text, re.I)
    if m and float(m.group(2)) > 0:
        out.append(f"{m.group(1).upper()} set-aside {m.group(2)}%")

    return out


def _scope_from(text: str) -> Optional[str]:
    """The narrative under a 'Scope of Work' heading."""
    m = re.search(r"scope\s+of\s+work\s*:?\s*", text, re.I)
    if not m:
        return None
    body = text[m.end() : m.end() + 6000].strip()
    # Stop at the next all-caps section banner, which marks the start of
    # boilerplate. The floor only guards against a scope that itself opens with
    # a heading, which would otherwise truncate to nothing.
    stop = re.search(r"\n\s*(?:[A-Z][A-Z \d.&/-]{12,})\n", body)
    if stop and stop.start() > 60:
        body = body[: stop.start()]
    body = re.sub(r"[ \t]+", " ", body).strip()
    return body or None


def _tidy(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    cleaned = re.sub(r"\s+", " ", value).strip(" .;:")
    return cleaned or None
