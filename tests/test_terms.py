"""The guardrail that would have stopped the DemandStar adapter.

On 7 Aug 2026 an adapter was built against DemandStar's public JSON endpoint
and merged, against a decision recorded in `docs/statewide-coverage.md` since
the statewide expansion. Nothing in the codebase said no — the only thing
between a reasonable-looking endpoint and a merged adapter was whether someone
opened the right document.

These tests are that "no". They run on every push, they name the platform, and
they cannot be satisfied by finding a nicer endpoint.
"""

from __future__ import annotations

import pytest

from src.sources.registry import ADAPTERS
from src.terms import (
    AGENCY_SITE,
    ALLOWS_NEW_ADAPTER,
    FORBIDS_ADAPTER,
    GRANDFATHERED,
    PROHIBITED,
    TERMS,
    UNCHECKED,
    UNREADABLE,
    may_build_adapter,
)


def test_every_adapter_has_a_verdict():
    """A platform with no entry is a platform nobody checked. The point of the
    table is that the omission cannot be silent."""
    missing = sorted(set(ADAPTERS) - set(TERMS))

    assert missing == [], f"adapters with no recorded terms verdict: {missing}"


def test_no_adapter_exists_for_a_platform_whose_terms_forbid_it():
    """The test that would have failed on the DemandStar change.

    `demandstar` is `PROHIBITED`; an adapter named `demandstar` in the registry
    fails here, and no amount of finding an easier endpoint changes that.
    """
    forbidden = sorted(
        p for p in ADAPTERS
        if (TERMS.get(p) and TERMS[p].status in FORBIDS_ADAPTER)
        and p not in GRANDFATHERED
    )

    assert forbidden == [], f"adapters for platforms whose terms forbid it: {forbidden}"


def test_a_new_adapter_must_clear_the_bar():
    """`UNCHECKED` is grandfathered debt, not a category new work may join."""
    unchecked_adapters = sorted(
        p for p in ADAPTERS
        if TERMS.get(p) and TERMS[p].status not in ALLOWS_NEW_ADAPTER
    )

    assert set(unchecked_adapters) <= GRANDFATHERED, (
        "a new adapter must be PERMITTED or AGENCY_SITE; these are neither and "
        f"are not grandfathered: {sorted(set(unchecked_adapters) - GRANDFATHERED)}"
    )


def test_the_grandfathered_set_does_not_grow():
    """Debt that can grow is not debt, it is a habit."""
    assert GRANDFATHERED == {"opengov", "workday_sourcing", "jaggaer"}


def test_the_grandfathered_platforms_still_have_adapters():
    """When one is resolved — read the terms, or drop the adapter — it comes
    off this list. An entry here with no adapter is stale."""
    assert GRANDFATHERED <= set(ADAPTERS)


# -- the verdicts themselves ----------------------------------------------


def test_demandstar_is_recorded_prohibited_with_the_clause():
    """The specific mistake, written down. Their terms prohibit "any robot,
    spider, data scraping, crawler or other extraction tool"."""
    v = TERMS["demandstar"]

    assert v.status == PROHIBITED
    assert "robot, spider, data scraping" in v.note
    assert v.source and v.checked_on


def test_vendor_registry_is_recorded_prohibited_with_the_clause():
    """Found by this table's first use: §1.1 forbids copying or downloading any
    content, under a browse-wrap that binds on use of the site rather than on
    registration — the opposite of Ionwave's."""
    v = TERMS["vendor_registry"]

    assert v.status == PROHIBITED
    assert "may not copy or download" in v.note
    assert "vendor_registry" not in ADAPTERS


def test_bidnet_is_unreadable_rather_than_permitted():
    """Its robots.txt allows the listing pages and disallows the terms. The
    permissive half is not the half that decides."""
    v = TERMS["bidnet"]

    assert v.status == UNREADABLE
    assert "bidnet" not in ADAPTERS


def test_an_unreadable_verdict_is_not_a_soft_no():
    """Grouped with prohibited on purpose. A judgement made on evidence one
    cannot read, in favour of the party that gains from reading it that way,
    is not a judgement."""
    assert UNREADABLE in FORBIDS_ADAPTER
    assert UNREADABLE not in ALLOWS_NEW_ADAPTER


def test_robots_txt_is_not_the_test():
    """DemandStar serves `User-agent: *` with no rules, so a robots check
    returns "allowed" and means nothing. Nothing in this module consults it."""
    import inspect

    import src.terms as terms

    assert "robots_allows" not in inspect.getsource(terms)


def test_a_checked_verdict_carries_its_evidence():
    """A verdict with no source and no date is a memory, not a check."""
    for platform, v in TERMS.items():
        if v.status == AGENCY_SITE:
            continue
        assert v.checked_on, f"{platform}: no date"
        if v.status != UNCHECKED:
            assert v.source, f"{platform}: no source document"


def test_an_agency_site_verdict_says_whose_site_it_is():
    for platform, v in TERMS.items():
        if v.status == AGENCY_SITE:
            assert v.note, f"{platform}: AGENCY_SITE with no explanation"


@pytest.mark.parametrize("platform", ["demandstar", "vendor_registry", "bidnet"])
def test_the_helper_refuses_the_platforms_that_forbid_it(platform):
    assert may_build_adapter(platform) is False


@pytest.mark.parametrize("platform", ["civicplus", "bonfire", "ionwave"])
def test_the_helper_allows_the_platforms_that_permit_it(platform):
    assert may_build_adapter(platform) is True


def test_an_unknown_platform_is_not_permission():
    """The default has to be no. A platform nobody has heard of is a platform
    nobody has checked."""
    assert may_build_adapter("some_new_portal") is False


# -- the generator honours the same table ---------------------------------


def test_the_source_generator_cannot_configure_a_forbidden_platform():
    """`sources_from_fingerprints.py` is the other route by which a platform
    becomes something this build fetches, and 36 DemandStar fingerprints are
    sitting in the registry waiting for exactly that."""
    import importlib.util
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location(
        "sff", root / "scripts" / "sources_from_fingerprints.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["sff"] = mod
    spec.loader.exec_module(mod)

    blocked = sorted(
        p for p in mod.PLATFORM_ADAPTERS
        if not may_build_adapter(p) and p not in GRANDFATHERED
    )

    assert blocked == [], (
        f"configurable by the generator but their terms do not allow it: {blocked}"
    )
