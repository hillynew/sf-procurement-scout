"""Normalized procurement opportunity model."""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field, computed_field
import hashlib


class SolicitationType(str, Enum):
    ITB = "ITB"  # Invitation to Bid
    IFB = "IFB"
    RFP = "RFP"
    RFQ = "RFQ"
    RFI = "RFI"
    ITN = "ITN"
    CCNA = "CCNA"
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


class Opportunity(BaseModel):
    """A single government procurement opportunity."""

    # Identity
    source_id: str
    source_name: str
    external_id: Optional[str] = None  # agency ref / event id
    title: str
    url: str

    # Geography / agency
    county: str  # miami-dade | broward | palm-beach
    agency: str
    department: Optional[str] = None

    # Classification
    solicitation_type: SolicitationType = SolicitationType.UNKNOWN
    offer_type: OfferType = OfferType.UNKNOWN
    categories: List[str] = Field(default_factory=list)
    keywords: List[str] = Field(default_factory=list)

    # Dates & status
    posted_date: Optional[date] = None
    due_date: Optional[datetime] = None
    status: str = "open"  # open | closed | cancelled | upcoming | catalog

    # Narrative
    description: Optional[str] = None
    brief: Optional[str] = None  # short deal summary
    contact: Optional[str] = None
    budget: Optional[str] = None

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
    def days_until_due(self) -> Optional[int]:
        if not self.due_date:
            return None
        delta = self.due_date.date() - date.today()
        return delta.days

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
            "budget": self.budget or "",
            "department": self.department or "",
        }


class SourceHealth(BaseModel):
    source_id: str
    name: str
    ok: bool
    count: int = 0
    error: Optional[str] = None
    elapsed_ms: int = 0
