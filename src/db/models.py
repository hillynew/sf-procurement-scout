"""SQLAlchemy models.

JSON columns use JSONB on Postgres and plain JSON on SQLite; all JSON
filtering happens in Python (the data set is a few hundred rows), so no
dialect-specific operators are ever needed.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, List, Optional

from sqlalchemy import (
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
