"""SQLAlchemy models.

JSON columns use JSONB on Postgres and plain JSON on SQLite; all JSON
filtering happens in Python (the data set is a few hundred rows), so no
dialect-specific operators are ever needed.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, List, Optional

from sqlalchemy import (
    Float,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Integer,
    JSON,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

JSONVariant = JSON().with_variant(JSONB(), "postgresql")


class Base(DeclarativeBase):
    pass


class FetchRun(Base):
    """One pipeline run — powers the Sources screen and trend charts."""

    __tablename__ = "fetch_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    started_at: Mapped[datetime] = mapped_column(DateTime)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="done")  # done | error
    opp_count: Mapped[int] = mapped_column(Integer, default=0)
    new_count: Mapped[int] = mapped_column(Integer, default=0)
    health: Mapped[Optional[List[Any]]] = mapped_column(JSONVariant, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class OpportunityRow(Base):
    """Latest snapshot, one row per opportunity.

    ``payload`` is the full pydantic dump; the extracted columns exist only
    for cheap ordering/filtering. Rows for tracked bids are never deleted on
    snapshot replace — that retention is the backbone of the archive feature.
    """

    __tablename__ = "opportunities"

    opportunity_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    payload: Mapped[dict] = mapped_column(JSONVariant)
    county: Mapped[str] = mapped_column(String(32), default="")
    status: Mapped[str] = mapped_column(String(16), default="open")
    offer_type: Mapped[str] = mapped_column(String(32), default="unknown")
    due_date: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    posted_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    budget_amount: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime)
    # True while the bid still appears in the newest snapshot; tracked bids
    # that fall off the portals stay in the table with present=False.
    present: Mapped[bool] = mapped_column(Boolean, default=True)


class HistoryRecord(Base):
    """Closed-solicitation archive used for recurrence matching."""

    __tablename__ = "bid_history"

    opportunity_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    agency: Mapped[str] = mapped_column(String(256), default="")
    county: Mapped[str] = mapped_column(String(32), default="")
    closed_on: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    payload: Mapped[dict] = mapped_column(JSONVariant)


class ContractRow(Base):
    """An executed contract published by an agency's portal.

    Not an opportunity: it is work already awarded, and its value here is the
    end date — the earliest warning that a rebid is coming. Kept in its own
    table for the same reason history is, so it never reaches a board of things
    someone could bid on today.
    """

    __tablename__ = "contracts"

    contract_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    agency: Mapped[str] = mapped_column(String(256), default="")
    name: Mapped[str] = mapped_column(Text, default="")
    vendor: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    vendor_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    status_id: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    start_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    end_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True, index=True)
    url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    #: Total compensation, where the portal publishes it. The ranking signal a
    #: date alone cannot give: a $40M highway contract and a $4,000 canine
    #: agreement expire on the same day and are not the same lead.
    amount: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    #: How it was bought — competitive, sole source, state term contract. Tells
    #: you whether the rebid is a real opening or a formality. Wide because
    #: FACTS writes the statutory citation into it: 9% of its values exceed 128
    #: characters and the longest is 300, and the citation is the tail that
    #: would be lost. This column only ever gets added, never widened, so the
    #: room has to be there from the start.
    method: Mapped[Optional[str]] = mapped_column(String(320), nullable=True)
    refreshed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class TrackedBid(Base):
    """The user's workflow layer for one bid."""

    __tablename__ = "tracked_bids"

    opportunity_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    tracked_on: Mapped[date] = mapped_column(Date)
    stage: Mapped[str] = mapped_column(String(16), default="watching")
    decision: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)  # go | nogo
    notes: Mapped[str] = mapped_column(Text, default="")
    checks: Mapped[dict] = mapped_column(JSONVariant, default=dict)  # {"0": true, ...}
    archived: Mapped[bool] = mapped_column(Boolean, default=False)


class BidResult(Base):
    __tablename__ = "bid_results"

    opportunity_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    outcome: Mapped[str] = mapped_column(String(8))  # won | lost
    amount_cents: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    decided_on: Mapped[date] = mapped_column(Date)


class Watchlist(Base):
    __tablename__ = "watchlists"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    rules: Mapped[dict] = mapped_column(JSONVariant, default=dict)
    email_digest: Mapped[bool] = mapped_column(Boolean, default=False)
    seen_ids: Mapped[list] = mapped_column(JSONVariant, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime)


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    kind: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(String(256))
    body: Mapped[str] = mapped_column(Text, default="")
    opportunity_id: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    read: Mapped[bool] = mapped_column(Boolean, default=False)


class Setting(Base):
    """One row per settings section, e.g. key='auto_fetch'."""

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict] = mapped_column(JSONVariant, default=dict)


class AiSummary(Base):
    """Cached Claude deal briefs — never regenerated for unchanged input."""

    __tablename__ = "ai_summaries"

    opportunity_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    content_hash: Mapped[str] = mapped_column(String(16), primary_key=True)
    model: Mapped[str] = mapped_column(String(64), primary_key=True)
    prompt_version: Mapped[int] = mapped_column(Integer, primary_key=True)
    summary: Mapped[dict] = mapped_column(JSONVariant)
    input_chars: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime)


class DeepDive(Base):
    """Cached "Go Deep" reports — the exhaustive all-documents analysis."""

    __tablename__ = "deep_dives"

    opportunity_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    content_hash: Mapped[str] = mapped_column(String(16), default="")
    model: Mapped[str] = mapped_column(String(64), default="")
    prompt_version: Mapped[int] = mapped_column(Integer, default=1)
    report: Mapped[dict] = mapped_column(JSONVariant)
    input_chars: Mapped[int] = mapped_column(Integer, default=0)
    docs_read: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime)


class ResearchThread(Base):
    """Follow-up research on one deal — the Q&A that comes after a deep dive.

    ``turns`` is the whole conversation as a JSON list of
    ``{question, answer, citations, model, asked_at}`` dicts. One row per
    opportunity: research is a running dialogue about a deal, not a set of
    independent lookups, and each new question is answered with the prior
    turns in context.
    """

    __tablename__ = "research_threads"

    opportunity_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    turns: Mapped[list] = mapped_column(JSONVariant, default=list)
    updated_at: Mapped[datetime] = mapped_column(DateTime)


class Contractor(Base):
    """One business in the outsourcing network.

    Rows are created when AI matching surfaces a firm for a bid and are kept
    forever after — the network is the durable asset, the matches are how it
    grows. ``profile`` holds whatever the finder learned (government
    experience, source URLs, size hints); the flat columns exist for cheap
    listing and filtering.
    """

    __tablename__ = "contractors"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(256))
    county: Mapped[str] = mapped_column(String(32), default="")
    location: Mapped[str] = mapped_column(String(256), default="")
    trade: Mapped[str] = mapped_column(String(256), default="")
    website: Mapped[str] = mapped_column(String(512), default="")
    phone: Mapped[str] = mapped_column(String(64), default="")
    email: Mapped[str] = mapped_column(String(256), default="")
    # prospect | contacted | in_network | passed — the relationship, not a match
    status: Mapped[str] = mapped_column(String(16), default="prospect")
    notes: Mapped[str] = mapped_column(Text, default="")
    profile: Mapped[dict] = mapped_column(JSONVariant, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime)


class ContractorMatchSet(Base):
    """Cached AI contractor matches for one bid — same shape rules as DeepDive.

    ``matches`` is a JSON list of per-contractor entries; each carries its own
    outreach status (suggested → pitched → interested → committed | passed),
    which is the per-deal pipeline layered over the per-firm relationship.
    """

    __tablename__ = "contractor_matches"

    opportunity_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    content_hash: Mapped[str] = mapped_column(String(16), default="")
    model: Mapped[str] = mapped_column(String(64), default="")
    prompt_version: Mapped[int] = mapped_column(Integer, default=1)
    matches: Mapped[list] = mapped_column(JSONVariant, default=list)
    market_note: Mapped[str] = mapped_column(Text, default="")
    searches: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime)


class CustomSource(Base):
    """User-added portals (CivicPlus), merged into the yaml config at runtime."""

    __tablename__ = "custom_sources"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    county: Mapped[str] = mapped_column(String(32), default="broward")
    agency: Mapped[str] = mapped_column(String(120), default="")
    adapter: Mapped[str] = mapped_column(String(32), default="civicplus")
    portal_url: Mapped[str] = mapped_column(String(512))
    created_at: Mapped[datetime] = mapped_column(DateTime)


class PdfCacheEntry(Base):
    """Extracted bid-package text, so restarts don't re-download PDFs."""

    __tablename__ = "pdf_cache"

    url_hash: Mapped[str] = mapped_column(String(40), primary_key=True)
    text: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime)
