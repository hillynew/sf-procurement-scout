"""The additive column-add: what it does, and what it refuses to do.

`create_all` makes missing tables and ignores missing columns, so a database
that already existed would raise `no such column` the first time a model gained
one. These tests build that exact situation — an old table, then a new model —
and check the gap closes.
"""

from __future__ import annotations

import pytest
from sqlalchemy import Column, Float, Integer, MetaData, String, Table, create_engine, inspect, text

from src.db.engine import add_missing_columns


def _old_table(engine, extra=()):
    """A table as an earlier release left it, with a row already in it."""
    meta = MetaData()
    Table(
        "contracts", meta,
        Column("contract_id", String(64), primary_key=True),
        Column("agency", String(256)),
        *extra,
    )
    meta.create_all(engine)
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO contracts (contract_id, agency) VALUES ('facts:A1', 'DOT')"
        ))
    return engine


@pytest.fixture
def engine(tmp_path):
    e = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    yield e
    e.dispose()


# -- what it does ----------------------------------------------------------


def test_a_new_column_is_added_to_a_table_that_already_exists(engine, monkeypatch):
    """The whole point: without this the next read raises `no such column`."""
    _old_table(engine)
    added = add_missing_columns(engine)

    columns = {c["name"] for c in inspect(engine).get_columns("contracts")}
    assert "amount" in columns
    assert "contracts.amount" in added


def test_the_existing_row_survives_with_the_new_column_null(engine):
    _old_table(engine)
    add_missing_columns(engine)

    with engine.begin() as conn:
        row = conn.execute(text("SELECT contract_id, amount FROM contracts")).one()
    assert row[0] == "facts:A1"
    assert row[1] is None


def test_it_is_idempotent(engine):
    """Startup runs it every boot; the second run must be a no-op."""
    _old_table(engine)
    first = add_missing_columns(engine)
    second = add_missing_columns(engine)

    assert first, "the fixture table is missing columns, so the first run does work"
    assert second == []


def test_a_table_that_does_not_exist_yet_is_left_to_create_all(engine):
    """`create_all` has already made it, with every column. Touching it here
    would be a second, redundant path to the same schema."""
    added = add_missing_columns(engine)
    assert added == []


def test_a_column_that_is_already_there_is_not_re_added(engine):
    _old_table(engine, extra=(Column("amount", Float),))
    added = add_missing_columns(engine)

    assert "contracts.amount" not in added


# -- what it refuses to do -------------------------------------------------


def test_a_not_null_column_with_no_default_is_refused(engine, monkeypatch):
    """That is a migration, not an addition — it cannot be applied to a table
    with rows in it, and failing loudly at startup beats failing halfway."""
    from src.db import models

    meta = MetaData()
    Table("widgets", meta, Column("id", Integer, primary_key=True))
    meta.create_all(engine)

    strict = MetaData()
    Table(
        "widgets", strict,
        Column("id", Integer, primary_key=True),
        Column("owner", String(64), nullable=False),
    )
    monkeypatch.setattr(models.Base, "metadata", strict)

    with pytest.raises(RuntimeError, match="needs a migration"):
        add_missing_columns(engine)


def test_it_never_drops_a_column_the_models_stopped_declaring(engine, monkeypatch):
    """Additive means additive. A removed column stays until someone means it."""
    from src.db import models

    _old_table(engine, extra=(Column("legacy_note", String(64)),))

    meta = MetaData()
    Table("contracts", meta, Column("contract_id", String(64), primary_key=True))
    monkeypatch.setattr(models.Base, "metadata", meta)
    add_missing_columns(engine)

    columns = {c["name"] for c in inspect(engine).get_columns("contracts")}
    assert "legacy_note" in columns


# -- the real schema -------------------------------------------------------


def test_init_db_closes_the_gap_end_to_end(tmp_path, monkeypatch):
    """An old contracts table, then a boot, then a read that used to explode."""
    from src.contracts import Contract
    from src.db import engine as db_engine, store

    url = f"sqlite:///{tmp_path / 'live.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    db_engine.reset_engine()

    _old_table(create_engine(url))
    db_engine.init_db()

    store.save_contracts([Contract(
        contract_id="A2", agency="DOT", name="Resurfacing", source_id="facts",
        amount=41_000_000.0, method="Competitive",
    )])
    loaded = {c.contract_id: c for c in store.load_contracts()}

    assert loaded["A2"].amount == 41_000_000.0
    assert loaded["A2"].method == "Competitive"
    db_engine.reset_engine()


def test_the_new_contract_columns_are_nullable():
    """The two columns this mechanism was built for.

    A blanket "every column must be addable" guard would be wrong — the 26
    NOT NULL columns already in the schema shipped *with* their tables, so
    nothing ever tries to add them. What matters is that a column added after
    a table exists is nullable, and these are the ones that were.
    """
    from src.db.models import ContractRow

    for name in ("amount", "method"):
        column = ContractRow.__table__.columns[name]
        assert column.nullable, f"{name} cannot be added to an existing table"
