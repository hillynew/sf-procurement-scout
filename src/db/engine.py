"""Engine resolution: DATABASE_URL (Render Postgres) or a local SQLite file.

One code path everywhere. Render injects DATABASE_URL with the legacy
``postgres://`` scheme, which SQLAlchemy no longer accepts, so it is rewritten
to the psycopg3 dialect here. With no DATABASE_URL the app runs against
``data/scout.db`` — local dev and tests need zero setup.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Iterator, List, Optional

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
    """Create any missing tables and columns. Additive-only — no migrations."""
    from .models import Base

    engine = get_engine()
    Base.metadata.create_all(engine)
    add_missing_columns(engine)


def add_missing_columns(engine: Engine) -> List[str]:
    """Add nullable columns the models declare and the live tables lack.

    `create_all` creates missing *tables* and silently ignores missing
    *columns*, so "additive-only schema" was only half true: adding a table was
    free, adding a column meant the next read raised `no such column` against
    any database that already existed. Which in practice meant nobody added
    one, and data the adapters already had — a contract's dollar value, say —
    stayed unstored.

    This closes that gap and nothing wider. It only ever runs
    `ALTER TABLE ... ADD COLUMN`, only for columns that are nullable or have a
    default, and only on tables that already exist. It never drops, renames,
    retypes or reorders anything, so there is no rollback to get wrong and no
    ordering between deployments to coordinate. Anything beyond that is a
    migration and still wants a migration tool.

    Returns the `table.column` names it added, for the tests and for the log.
    """
    from sqlalchemy import inspect, text

    from .models import Base

    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    added: List[str] = []

    for table in Base.metadata.sorted_tables:
        if table.name not in existing_tables:
            continue  # create_all just made it, with every column.
        have = {c["name"] for c in inspector.get_columns(table.name)}
        for column in table.columns:
            if column.name in have:
                continue
            if not column.nullable and column.default is None and column.server_default is None:
                # A NOT NULL column with no default cannot be added to a table
                # that already has rows. That is a real migration; say so
                # rather than failing halfway through startup.
                raise RuntimeError(
                    f"{table.name}.{column.name} is NOT NULL with no default; "
                    "adding it to an existing table needs a migration, not this"
                )
            ddl = column.type.compile(engine.dialect)
            with engine.begin() as conn:
                conn.execute(text(f'ALTER TABLE {table.name} ADD COLUMN "{column.name}" {ddl}'))
            added.append(f"{table.name}.{column.name}")

    return added


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
