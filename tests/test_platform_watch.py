"""Comparing today's fingerprints against the recorded ones.

The comparison, not the fetching — nothing here goes near the network. What is
under test is which differences count as a migration, which count as a site
having a bad day, and which entities are worth asking about at all.
"""

from __future__ import annotations

import json

from src.pipeline.fingerprint import Fingerprint
from src.pipeline.platform_watch import (
    compare,
    identified,
    recorded,
    roster_rows,
)


def _fp(entity_id="mun-x", name="City of X", platform="ionwave", **kw):
    return Fingerprint(entity_id=entity_id, name=name, website="https://x.gov",
                       platform=platform, **kw)


def _baseline(**by_entity):
    return {e: {"entity_id": e, "platform": p} for e, p in by_entity.items()}


# -- what counts as a move -------------------------------------------------


def test_a_platform_change_is_a_move():
    """Deerfield Beach, found the hard way: the DemandStar feed kept working
    and kept returning nothing, which reads as a quiet agency."""
    result = compare(_baseline(mun_x="demandstar"),
                     [_fp(entity_id="mun_x", platform="ionwave")])

    assert result.unchanged == 0
    assert [m.describe() for m in result.moved] == ["City of X: demandstar -> ionwave"]
    assert result.lost == []


def test_the_same_platform_is_not_a_move():
    result = compare(_baseline(mun_x="ionwave"), [_fp(entity_id="mun_x")])

    assert result.unchanged == 1
    assert result.moved == [] and result.lost == []


def test_becoming_unreadable_is_kept_apart_from_moving():
    """A WAF or a slow site would otherwise cry migration every sweep."""
    result = compare(_baseline(mun_x="civicplus"),
                     [_fp(entity_id="mun_x", platform="unknown", note="blocked (WAF)")])

    assert result.moved == []
    assert [m.was for m in result.lost] == ["civicplus"]
    assert result.lost[0].note == "blocked (WAF)"


def test_an_entity_with_no_baseline_reads_as_newly_identified():
    result = compare({}, [_fp(entity_id="new_one", platform="bonfire")])

    assert [m.was for m in result.moved] == ["unknown"]


def test_the_move_carries_the_portal_url_that_makes_it_actionable():
    """A platform name alone leaves someone hunting for the tenant key."""
    result = compare(
        _baseline(mun_x="demandstar"),
        [_fp(entity_id="mun_x", portal_url="https://deerfieldbeach.ionwave.net/Login.aspx")],
    )

    assert result.moved[0].portal_url.endswith("ionwave.net/Login.aspx")


def test_the_summary_counts_all_three_outcomes():
    result = compare(
        _baseline(a="demandstar", b="civicplus", c="bonfire"),
        [_fp(entity_id="a", platform="ionwave"),
         _fp(entity_id="b", platform="unknown"),
         _fp(entity_id="c", platform="bonfire")],
    )

    assert result.summary() == (
        "3 rechecked · 1 unchanged · 1 moved · 1 no longer readable"
    )


# -- reading the baseline --------------------------------------------------


def test_the_latest_line_for_an_entity_wins(tmp_path):
    """The file is append-only, so a recheck adds a line rather than editing
    one — which keeps the history of a migration readable in the file itself."""
    path = tmp_path / "fingerprints.jsonl"
    path.write_text(
        json.dumps({"entity_id": "mun_x", "platform": "demandstar"}) + "\n"
        + json.dumps({"entity_id": "mun_x", "platform": "ionwave"}) + "\n",
        encoding="utf-8",
    )

    assert recorded(path)["mun_x"]["platform"] == "ionwave"


def test_a_torn_last_line_is_not_fatal(tmp_path):
    path = tmp_path / "fingerprints.jsonl"
    path.write_text(
        json.dumps({"entity_id": "mun_x", "platform": "bonfire"}) + "\n{\"entity_id\": \"mu",
        encoding="utf-8",
    )

    assert recorded(path) == {"mun_x": {"entity_id": "mun_x", "platform": "bonfire"}}


def test_a_missing_file_is_an_empty_baseline(tmp_path):
    assert recorded(tmp_path / "nope.jsonl") == {}


def test_only_identified_entities_are_worth_rechecking():
    """An agency that was never placed cannot have migrated away from anything,
    and re-reading 635 unknowns to learn they are still unknown is 1,270
    requests for no answer."""
    baseline = _baseline(a="bonfire", b="unknown", c="civicplus")

    assert identified(baseline) == {"a", "c"}


# -- picking the roster rows ----------------------------------------------


def _roster(tmp_path, rows):
    path = tmp_path / "roster.csv"
    lines = ["entity_id,name,website"]
    lines += [",".join(r) for r in rows]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_only_the_named_entities_are_returned(tmp_path):
    path = _roster(tmp_path, [
        ("a", "City of A", "https://a.gov"),
        ("b", "City of B", "https://b.gov"),
    ])

    assert [r["entity_id"] for r in roster_rows({"b"}, path)] == ["b"]


def test_an_entity_without_a_website_cannot_be_asked(tmp_path):
    path = _roster(tmp_path, [("a", "City of A", ""), ("b", "City of B", "https://b.gov")])

    assert [r["entity_id"] for r in roster_rows({"a", "b"}, path)] == ["b"]


def test_a_missing_roster_is_no_rows_rather_than_a_crash(tmp_path):
    """The roster ships in the image, but a check that dies on a missing file
    would take the scheduler's whole tick with it."""
    assert roster_rows({"a"}, tmp_path / "nope.csv") == []


# -- the shipped baseline --------------------------------------------------


def test_the_committed_baseline_is_readable():
    """It is the reference the monthly check compares against, so a broken
    line in it would silently turn every agency into a migration."""
    baseline = recorded()

    assert len(baseline) > 500
    assert len(identified(baseline)) > 100
    assert all(row.get("platform") for row in baseline.values())
