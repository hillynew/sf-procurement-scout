"""Category + offer-type classification from titles/descriptions.

The category vocabulary lives in :mod:`src.taxonomy`, not here. This module is
only the matcher. That split is deliberate: the watchlist dropdown offers every
category in the taxonomy, so a category the matcher cannot reach becomes a
filter that silently matches nothing forever. Keeping the list in one place
makes "is this filterable?" and "is this detectable?" the same question.
"""

from __future__ import annotations

import re
from typing import List, Optional, Tuple

from .models.opportunity import OfferType, SolicitationType
from .taxonomy import BY_SLUG, CATEGORIES, Category


SOLICITATION_PATTERNS = [
    (r"\bITN\b", SolicitationType.ITN),
    (r"\bCCNA\b", SolicitationType.CCNA),
    (r"\bRPQ\b", SolicitationType.RPQ),
    (r"\bITQ\b", SolicitationType.ITQ),
    (r"\bRLI\b", SolicitationType.RLI),
    (r"\bRFQ\b", SolicitationType.RFQ),
    (r"\bRFI\b", SolicitationType.RFI),
    (r"\bRFP\b", SolicitationType.RFP),
    (r"\bIFB\b", SolicitationType.IFB),
    (r"\bITB\b", SolicitationType.ITB),
    (r"invitation\s+to\s+negotiate", SolicitationType.ITN),
    (r"request\s+for\s+(?:price\s+)?quotations?", SolicitationType.RPQ),
    (r"invitation\s+to\s+quote", SolicitationType.ITQ),
    (r"request\s+for\s+letters?\s+of\s+interest", SolicitationType.RLI),
    (r"request\s+for\s+qualifications?", SolicitationType.RFQ),
    (r"request\s+for\s+information", SolicitationType.RFI),
    (r"request\s+for\s+proposals?", SolicitationType.RFP),
    (r"invitation\s+(?:to|for)\s+bid", SolicitationType.ITB),
]


#: Patterns are compiled once — the taxonomy is ~200 categories deep and a
#: fetch classifies hundreds of bids, so recompiling per call is wasted work.
_COMPILED: List[Tuple[Category, List[re.Pattern]]] = [
    (c, [re.compile(p, re.I) for p in c.patterns]) for c in CATEGORIES if c.patterns
]

#: A title matching a dozen categories helps nobody read the badge row. The cap
#: is on *detected* categories; umbrellas are added afterwards regardless, since
#: dropping one would silently break a watchlist saved against the old
#: twelve-category vocabulary.
MAX_DETECTED = 8


def detect_solicitation_type(text: str) -> SolicitationType:
    if not text:
        return SolicitationType.UNKNOWN
    for pat, st in SOLICITATION_PATTERNS:
        if re.search(pat, text, re.I):
            return st
    return SolicitationType.UNKNOWN


def extract_external_id(text: str) -> Optional[str]:
    if not text:
        return None
    patterns = [
        r"\b((?:ITB|IFB|RFP|RFQ|RFI|ITN|RPQ|ITQ|RLI)\s*(?:No\.?\s*)?[\d][\w./-]{2,})",
        r"\b((?:RFP|ITB|EVN|IFB)\d{5,})",
        r"\b([A-Z]{2,}\d{6,}[A-Z0-9]*)\b",
        r"\b(\d{2}C-\d{3}[A-Z]?)\b",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.I)
        if m:
            return re.sub(r"\s+", " ", m.group(1)).strip()
    return None


def classify_text(title: str, description: str = "") -> Tuple[List[str], OfferType, List[str]]:
    blob = f"{title}\n{description or ''}"
    cats: List[str] = []
    offer_votes = []
    keywords: List[str] = []

    for cat, patterns in _COMPILED:
        for pat in patterns:
            m = pat.search(blob)
            if m:
                if cat.slug not in cats and len(cats) < MAX_DETECTED:
                    cats.append(cat.slug)
                    offer_votes.append(cat.offer)
                    kw = m.group(0).lower().strip()
                    if kw not in keywords:
                        keywords.append(kw)
                break

    # Umbrellas are applied after the cap, never subject to it: a bid tagged
    # `roofing` must also carry `construction` or a watchlist written before the
    # taxonomy existed stops matching work it used to catch.
    for slug in list(cats):
        umbrella = BY_SLUG[slug].umbrella
        if umbrella and umbrella not in cats:
            cats.append(umbrella)
            offer_votes.append(BY_SLUG[umbrella].offer)

    if not cats:
        cats = ["general"]
        offer = OfferType.UNKNOWN
    else:
        # majority / priority
        if OfferType.CONSTRUCTION in offer_votes:
            offer = OfferType.CONSTRUCTION
        elif OfferType.PROFESSIONAL_SERVICES in offer_votes and OfferType.GOODS not in offer_votes:
            offer = OfferType.PROFESSIONAL_SERVICES
        elif OfferType.GOODS in offer_votes and OfferType.SERVICES not in offer_votes:
            offer = OfferType.GOODS
        elif OfferType.SERVICES in offer_votes:
            offer = OfferType.SERVICES
        elif OfferType.MIXED in offer_votes:
            offer = OfferType.MIXED
        else:
            offer = offer_votes[0]

    return cats, offer, keywords


def enrich(title: str, description: str = "", external_id: Optional[str] = None):
    """Return classification fields for an opportunity."""
    st = detect_solicitation_type(f"{external_id or ''} {title} {description or ''}")
    cats, offer, keywords = classify_text(title, description or "")
    ext = external_id or extract_external_id(f"{title} {description or ''}")
    return {
        "solicitation_type": st,
        "offer_type": offer,
        "categories": cats,
        "keywords": keywords,
        "external_id": ext,
    }
