"""Shared fixtures. Tests never touch the network."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.models.opportunity import Opportunity  # noqa: E402


def make_opp(**overrides) -> Opportunity:
    base = dict(
        source_id="test_src",
        source_name="Test Source",
        title="Roof Replacement at Fire Station 12",
        url="https://example.gov/bids/1",
        county="broward",
        agency="Broward County",
    )
    base.update(overrides)
    return Opportunity(**base)


@pytest.fixture
def opp_factory():
    return make_opp


@pytest.fixture
def soon() -> datetime:
    return datetime.now() + timedelta(days=5)


@pytest.fixture
def past() -> datetime:
    return datetime.now() - timedelta(days=5)


@pytest.fixture
def fixtures_dir() -> Path:
    return Path(__file__).parent / "fixtures"
