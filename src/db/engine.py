"""Engine resolution: DATABASE_URL (Render Postgres) or a local SQLite file.

One code path everywhere. Render injects DATABASE_URL with the legacy
``postgres://`` scheme, which SQLAlchemy no longer accepts, so it is rewritten
to the psycopg3 dialect here. With no DATABASE_URL the app runs against
``data/scout.db`` — local dev and tests need zero setup.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Iterator, Optional

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

_engine: Optional[Engine] = None
_session_factory: Optional[sessionmaker] = None


def database_url() -> str:
    url = (os.environ.get("DATABASE_URL") or "").strip()
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+psycopg://", 1)
    elif url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    if not url:
        from ..sources.registry import project_root

        data = project_root() / "data"
        data.mkdir(parents=True, exist_ok=True)
        url = f"sqlite:///{data / 'scout.db'}"
    return url


def is_postgres() -> bool:
    return database_url().startswith("postgresql")


def get_engine() -> Engine:
    global _engine, _session_factory
    if _engine is None:
        url = database_url()
        kwargs: dict = {"pool_pre_ping": True, "future": True}
        if url.startswith("sqlite"):
            # The fetch pipeline writes from worker threads.
            kwargs["connect_args"] = {"check_same_thread": False}
        _engine = create_engine(url, **kwargs)
        _session_factory = sessionmaker(bind=_engine, expire_on_commit=False, future=True)
    return _engine


def reset_engine() -> None:
    """Drop the cached engine so tests can point DATABASE_URL elsewhere."""
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _session_factory = None


def init_db() -> None:
    """Create any missing tables. Additive-only schema — no migrations."""
    from .models import Base

    Base.metadata.create_all(get_engine())


@contextmanager
def session_scope() -> Iterator[Session]:
    get_engine()
    assert _session_factory is not None
    session = _session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
