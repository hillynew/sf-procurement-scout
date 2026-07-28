"""Category + offer-type classification from titles/descriptions."""

from __future__ import annotations

import re
from typing import List, Optional, Tuple

from .models.opportunity import OfferType, SolicitationType


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


# (category, offer_type, patterns)
CATEGORY_RULES: List[Tuple[str, OfferType, List[str]]] = [
    (
        "construction",
        OfferType.CONSTRUCTION,
        [
            r"\bconstruction\b",
            r"\brenovation\b",
            r"\bremodel\b",
            r"\broof(?:ing)?\b",
            r"\bdemolition\b",
            r"\bpaving\b",
            r"\basphalt\b",
            r"\bconcrete\b",
            r"\butility\s+relocation",
            r"\bpipeline\b",
            r"\blift\s+station\b",
            r"\bstormwater\b",
            r"\bsanitary\s+sewer\b",
            r"\bwater\s+main\b",
            r"\bbridge\b",
            r"\bdesign[- ]build\b",
            r"\bCMAR\b",
            r"construction\s+management",
            r"\bhvac\b",
            r"\bair\s+handler\b",
            r"\bgenerator\b",
            r"\bcrane\b",
            r"\bpier\b",
            r"\bfacility\s+renovation",
        ],
    ),
    (
        "architecture_engineering",
        OfferType.PROFESSIONAL_SERVICES,
        [
            r"\barchitect(?:ural|ure)?\b",
            r"\bengineering\b",
            r"\bengineer(?:ing)?\s+consult",
            r"\bCCNA\b",
            r"\bsurvey(?:ing|or)?\b",
            r"\bcivil\s+engineer",
            r"\bdesign\s+services\b",
            r"\burban\s+design\b",
        ],
    ),
    (
        "it_software",
        OfferType.SERVICES,
        [
            r"\bsoftware\b",
            r"\binformation\s+technology\b",
            r"\bIT\b",
            r"\bcyber\b",
            r"\bnetwork\s+service",
            r"\bcloud\b",
            r"\bservice\s+desk\b",
            r"\bmanaged\s+security\b",
            r"\bSOC\b",
            r"\bERP\b",
            r"\bapplication\b",
            r"\bdata\s+center\b",
            r"\btelecom\b",
            r"\bwireless\b",
            r"\bcellular\b",
            r"\bcamera\s+system\b",
            r"\brecording\s+system\b",
        ],
    ),
    (
        "facilities_maintenance",
        OfferType.SERVICES,
        [
            r"\bjanitorial\b",
            r"\bcustodial\b",
            r"\bcleaning\b",
            r"\blandscape\b",
            r"\blawn\b",
            r"\btree\s+trimm",
            r"\bpest\b",
            r"\bpressure\s+wash",
            r"\bmaintenance\b",
            r"\bfence\b",
            r"\blot\s+clear",
            r"\bboard\s+up\b",
        ],
    ),
    (
        "professional_services",
        OfferType.PROFESSIONAL_SERVICES,
        [
            r"\bconsult(?:ing|ant)\b",
            r"\bpublic\s+relations\b",
            r"\blegal\b",
            r"\baudit\b",
            r"\bproject\s+management\b",
            r"\bprogram\s+management\b",
            r"\bstaffing\b",
            r"\bcontract\s+employee\b",
            r"\btraining\b",
            r"\bdispatch\b",
            r"\bplanning\b",
        ],
    ),
    (
        "transportation",
        OfferType.SERVICES,
        [
            r"\btransit\b",
            r"\btransportation\b",
            r"\bbus\b",
            r"\bairport\b",
            r"\bFLL\b",
            r"\bparking\b",
            r"\btowing\b",
        ],
    ),
    (
        "public_safety",
        OfferType.MIXED,
        [
            r"\bfire\b",
            r"\bpolice\b",
            r"\bpublic\s+safety\b",
            r"\bemergency\b",
            r"\bdisaster\s+debris\b",
            r"\bx[- ]?ray\b",
            r"\bsecurity\b",
        ],
    ),
    (
        "utilities_water",
        OfferType.MIXED,
        [
            r"\bwater\b",
            r"\bwastewater\b",
            r"\bWWTF\b",
            r"\butilities?\b",
            r"\bmeter\b",
            r"\bsludge\b",
            r"\bchemical\b",
            r"\baluminum\s+sulfate\b",
            r"\bcarbon\s+dioxide\b",
        ],
    ),
    (
        "waste_recycling",
        OfferType.SERVICES,
        [
            r"\bsolid\s+waste\b",
            r"\brecycl",
            r"\blandfill\b",
            r"\bdebris\b",
            r"\bhazardous\b",
        ],
    ),
    (
        "goods_supplies",
        OfferType.GOODS,
        [
            r"\bpurchase\s+and\s+deliver",
            r"\bfurnish\s+and\s+deliver",
            r"\bsupplies?\b",
            r"\bequipment\b",
            r"\bvehicle\b",
            r"\btrailer\b",
            r"\btire\b",
            r"\buniform\b",
            r"\bshoes?\b",
            r"\bboots?\b",
            r"\bfireworks?\b",
            r"\bsod\b",
            r"\bprinting\b",
        ],
    ),
    (
        "healthcare",
        OfferType.MIXED,
        [
            r"\bmedical\b",
            r"\bhealth\b",
            r"\bhospital\b",
            r"\bEMT\b",
            r"\bsimulator\b",
            r"\bclinical\b",
        ],
    ),
]


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

    for cat, offer, patterns in CATEGORY_RULES:
        for pat in patterns:
            if re.search(pat, blob, re.I):
                if cat not in cats:
                    cats.append(cat)
                offer_votes.append(offer)
                # capture keyword token-ish
                m = re.search(pat, blob, re.I)
                if m:
                    kw = m.group(0).lower().strip()
                    if kw not in keywords:
                        keywords.append(kw)
                break

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
