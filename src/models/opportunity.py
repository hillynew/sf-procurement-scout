"""Normalized procurement opportunity model."""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field, computed_field
import hashlib
import re


class SolicitationType(str, Enum):
    ITB = "ITB"  # Invitation to Bid
    IFB = "IFB"  # Invitation for Bids
    RFP = "RFP"  # Request for Proposals
    RFQ = "RFQ"  # Request for Qualifications
    RFI = "RFI"  # Request for Information
    ITN = "ITN"  # Invitation to Negotiate
    RPQ = "RPQ"  # Request for Price Quotation — Miami-Dade's most common type
    ITQ = "ITQ"  # Invitation to Quote
    RLI = "RLI"  # Request for Letters of Interest
    CCNA = "CCNA"  # Consultants' Competitive Negotiation Act
    OTHER = "OTHER"
    UNKNOWN = "UNKNOWN"


class OfferType(str, Enum):
    """High-level goods vs services vs construction."""

    GOODS = "goods"  # products / supplies / equipment
    SERVICES = "services"
    CONSTRUCTION = "construction"
    PROFESSIONAL_SERVICES = "professional_services"
    MIXED = "mixed"
    UNKNOWN = "unknown"


class Document(BaseModel):
    """A bid package file published alongside a solicitation."""

    name: str
    url: str
    kind: str = "document"  # document | addendum | drawing | specification

    @property
    def is_addendum(self) -> bool:
        return self.kind == "addendum"


class Opportunity(BaseModel):
    """A single government procurement opportunity."""

    # Identity
    source_id: str
    source_name: str
    external_id: Optional[str] = None  # agency ref / event id
    title: str
    url: str

    # Geography / agency
    # Any of the 67 county slugs in `src.fl_geo`, or `statewide` / `unknown`.
    # (This was three tri-county literals before the statewide expansion; the
    # comment outlived the constraint and read as if the limit were still real.)
    county: str
    agency: str
    department: Optional[str] = None
    # state | county | municipal | school_district | higher_ed |
    # special_district | federal | unknown. Stamped by the pipeline from the
    # agency name when an adapter doesn't set it.
    tier: Optional[str] = None

    # Classification
    solicitation_type: SolicitationType = SolicitationType.UNKNOWN
    offer_type: OfferType = OfferType.UNKNOWN
    categories: List[str] = Field(default_factory=list)
    keywords: List[str] = Field(default_factory=list)
    # The source's own classification text, verbatim — kept so a bad call by
    # our classifier can always be traced back to what the portal said.
    raw_category: Optional[str] = None
    # Commodity codes as the source publishes them, scheme-prefixed:
    # "UNSPSC 78101804 Relocation services", "NIGP 91450 HVAC".
    commodity_codes: List[str] = Field(default_factory=list)

    # Dates & status
    posted_date: Optional[date] = None
    due_date: Optional[datetime] = None
    # `award` is a notice of intended decision rather than something biddable.
    # It is a separate status precisely so it stays out of every open-bid view:
    # the thing to do with it is protest it, not respond to it.
    status: str = "open"  # open | closed | cancelled | upcoming | catalog | award

    # Set on an `award` notice: when a notice of protest is due under
    # s. 120.57(3)(b), 72 hours excluding weekends and state holidays. This is
    # the tightest deadline in the system by an order of magnitude.
    protest_deadline: Optional[datetime] = None

    # Award facts, populated when the source publishes them. Awards and open
    # solicitations are two linked record types: an award record names the
    # solicitation it decides via `linked_ref` where the source provides one
    # (MFMP's linkedAdNumber, a bid number quoted in an agenda item), and
    # `award_linkage` records how the join was made so a bad match can be
    # traced: "ref" (explicit reference) | "fuzzy" (agency+title+date).
    awarded_vendor: Optional[str] = None
    award_amount: Optional[int] = None  # whole dollars
    award_date: Optional[date] = None
    linked_ref: Optional[str] = None
    award_linkage: Optional[str] = None

    # Contract term as published, free text: "1 year, two 1-year renewals".
    contract_term: Optional[str] = None

    # Narrative
    description: Optional[str] = None
    brief: Optional[str] = None  # short deal summary
    contact: Optional[str] = None
    budget: Optional[str] = None

    # Detail — populated by a second pass against the solicitation's own page,
    # since list pages carry almost nothing beyond a title and a date.
    scope: Optional[str] = None  # full scope-of-work narrative
    requirements: List[str] = Field(default_factory=list)  # bonding, licensing, insurance…
    documents: List[Document] = Field(default_factory=list)
    submittal_info: Optional[str] = None  # where/how to deliver a response
    pre_bid_meeting: Optional[str] = None
    questions_due: Optional[datetime] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    bid_opening: Optional[str] = None
    detail_fetched: bool = False

    # Commercial terms, which only ever appear inside the bid package PDF.
    project_location: Optional[str] = None
    duration_days: Optional[int] = None
    liquidated_damages: Optional[str] = None
    licenses: Optional[str] = None
    package_parsed: bool = False

    # Recurrence, from the agency's archive of closed solicitations.
    prior_cycles: int = 0
    last_cycle_closed: Optional[date] = None

    # Set when a configured vendor session surfaced this listing as one this
    # account was invited to or is following — visible only to a signed-in
    # vendor, never to an anonymous scrape.
    personalized: bool = False

    # Meta
    raw: Optional[dict] = None
    fetched_at: datetime = Field(default_factory=datetime.utcnow)

    model_config = {"use_enum_values": True}

    @computed_field
    @property
    def opportunity_id(self) -> str:
        """Stable id across refreshes for the same source + external key/title."""
        key = f"{self.source_id}|{self.external_id or ''}|{self.title}|{self.url}"
        return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]

    @computed_field
    @property
    def budget_amount(self) -> Optional[int]:
        """Numeric dollars parsed from the free-text budget, for sorting and totals.

        Ranges ("$100,000 - $250,000") count their low end.
        """
        if not self.budget:
            return None
        digits = re.sub(r"[^\d]", "", self.budget.split("-")[0].split("–")[0])
        return int(digits) if digits else None

    @computed_field
    @property
    def days_until_due(self) -> Optional[int]:
        if not self.due_date:
            return None
        delta = self.due_date.date() - date.today()
        return delta.days

    @computed_field
    @property
    def detail_score(self) -> int:
        """How much is actually known about this bid, 0-100.

        Surfaced in the UI so a listing with a full scope, documents and a
        contact is visibly more actionable than a bare title and date.
        """
        weights = (
            (bool(self.scope), 22),
            (bool(self.documents), 16),
            (bool(self.due_date), 13),
            (bool(self.requirements), 9),
            (bool(self.contact or self.contact_email), 8),
            (bool(self.budget), 8),
            (bool(self.description), 4),
            (bool(self.external_id), 3),
            (bool(self.submittal_info or self.pre_bid_meeting), 2),
            # Terms that only exist inside the bid package.
            (bool(self.duration_days), 5),
            (bool(self.liquidated_damages), 5),
            (bool(self.licenses), 3),
            (bool(self.project_location), 2),
        )
        return sum(points for present, points in weights if present)

    def to_row(self) -> dict:
        sol = (
            self.solicitation_type.value
            if hasattr(self.solicitation_type, "value")
            else str(self.solicitation_type)
        )
        offer = (
            self.offer_type.value
            if hasattr(self.offer_type, "value")
            else str(self.offer_type)
        )
        return {
            "opportunity_id": self.opportunity_id,
            "title": self.title,
            "external_id": self.external_id or "",
            "county": self.county,
            "agency": self.agency,
            "source_id": self.source_id,
            "source_name": self.source_name,
            "solicitation_type": sol,
            "offer_type": offer,
            "categories": ", ".join(self.categories),
            "status": self.status,
            "due_date": self.due_date.isoformat() if self.due_date else "",
            "days_until_due": self.days_until_due if self.days_until_due is not None else "",
            "posted_date": self.posted_date.isoformat() if self.posted_date else "",
            "brief": self.brief or "",
            "url": self.url,
            "contact": self.contact or "",
            "contact_email": self.contact_email or "",
            "contact_phone": self.contact_phone or "",
            "budget": self.budget or "",
            "department": self.department or "",
            "requirements": "; ".join(self.requirements),
            "documents": len(self.documents),
            "document_urls": " | ".join(d.url for d in self.documents[:10]),
            "pre_bid_meeting": self.pre_bid_meeting or "",
            "project_location": self.project_location or "",
            "duration_days": self.duration_days if self.duration_days is not None else "",
            "liquidated_damages": self.liquidated_damages or "",
            "licenses": self.licenses or "",
            "tier": self.tier or "",
            "raw_category": self.raw_category or "",
            "commodity_codes": "; ".join(self.commodity_codes),
            "awarded_vendor": self.awarded_vendor or "",
            "award_amount": self.award_amount if self.award_amount is not None else "",
            "award_date": self.award_date.isoformat() if self.award_date else "",
            "linked_ref": self.linked_ref or "",
            "award_linkage": self.award_linkage or "",
            "contract_term": self.contract_term or "",
            "prior_cycles": self.prior_cycles,
            "last_cycle_closed": self.last_cycle_closed.isoformat() if self.last_cycle_closed else "",
            "personalized": self.personalized,
            "questions_due": self.questions_due.isoformat() if self.questions_due else "",
            "submittal_info": self.submittal_info or "",
            "detail_score": self.detail_score,
            # Scope last: it is long, and trailing columns keep a CSV readable.
            "scope": (self.scope or "").replace("\n", " ")[:2000],
        }


class HealthStatus(str, Enum):
    """Outcome of a single source fetch.

    `ok` and `error` are not enough: a scraper whose page layout changed
    returns zero rows without raising, and a WAF-blocked portal falls back to
    a registration pointer. Both looked healthy before this distinction.
    """

    OK = "ok"
    EMPTY = "empty"  # fetched cleanly, portal genuinely has nothing listed
    DEGRADED = "degraded"  # blocked or parsed nothing where rows were expected
    ERROR = "error"


class SourceHealth(BaseModel):
    source_id: str
    name: str
    ok: bool
    count: int = 0
    error: Optional[str] = None
    elapsed_ms: int = 0
    status: HealthStatus = HealthStatus.OK
    note: Optional[str] = None
    # Per-run field coverage for this source: how many of its records carried
    # a category, documents, a due date, a budget, an award amount. Stored on
    # every run so a source that quietly stops yielding a field is visible
    # against its own history, not just against zero.
    coverage: Optional[dict] = None

    model_config = {"use_enum_values": True}

    @property
    def healthy(self) -> bool:
        """True only when the source returned usable rows (or is legitimately empty)."""
        return self.status in (HealthStatus.OK, HealthStatus.OK.value, "ok")
