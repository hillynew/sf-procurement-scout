"""What 305 sources do to the output end.

Every defect here was created by growth, not by a bug in the code that had it.
Each one was measured against a live sample of 307 opportunities drawn from ten
sources on 7 Aug 2026, and the numbers in the docstrings are from that run.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from tests.conftest import make_opp
from web.services.digest import _bid_line, _bullets, build_daily_digest
from web.services.matching import counties_named, matches_rules, wl_matches

TRI = {"counties": ["broward", "miami-dade", "palm-beach"]}


def _fdot(district="FDOT District 4", counties=("broward", "palm-beach"), **kw):
    """An FDOT advertisement: statewide by county, county-bearing by keyword."""
    base = dict(
        title="CEI Services for SR736/Davie Blvd Bridge",
        county="statewide",
        agency="Florida Department of Transportation",
        department=district,
        keywords=list(counties),
        source_id="fdot_ps",
    )
    base.update(kw)
    return make_opp(**base)


# -- the county filter that hid the user's own county ----------------------


def test_a_statewide_bid_that_names_the_county_matches_it():
    """The measured defect: a tri-county rule kept 24 of 307 bids and dropped
    all 24 FDOT District 4 advertisements — which are Broward and Palm Beach
    road work. The user's own county filter was hiding work in their county.
    """
    assert matches_rules(_fdot(), TRI)


def test_a_statewide_bid_naming_a_different_county_does_not_match():
    """The recovery must not become a flood: District 3 is the panhandle."""
    panhandle = _fdot(district="FDOT District 3", counties=("escambia", "leon"),
                      title="Resurfacing US 90 west of Pensacola")

    assert not matches_rules(panhandle, TRI)
    assert matches_rules(panhandle, {"counties": ["escambia"]})


def test_a_place_name_in_the_title_outvotes_the_district_it_was_filed_under():
    """Found by a fixture rather than by design, and kept because it is right.

    "CEI Services for SR736/Davie Blvd Bridge" resolves to Broward off the
    title alone. A district is six counties; the street is one town. When the
    text names a place, that is better evidence than the district, and a
    Broward watchlist should see it whichever district filed it.
    """
    davie = _fdot(district="FDOT District 3", counties=("escambia",),
                  title="CEI Services for SR736/Davie Blvd Bridge")

    assert "broward" in counties_named(davie)
    assert matches_rules(davie, TRI)


def test_an_unlocated_statewide_bid_stays_out_by_default():
    """94 of the 241 statewide rows in the sample name no county at all — a
    state contract performable anywhere. Four times as much unlocated noise as
    located signal is not a filter."""
    anywhere = make_opp(title="BadgePass, Inc.", county="statewide",
                        agency="Department of Management Services", keywords=[])

    assert not matches_rules(anywhere, TRI)


def test_an_unlocated_statewide_bid_can_be_asked_for():
    anywhere = make_opp(title="BadgePass, Inc.", county="statewide",
                        agency="Department of Management Services", keywords=[])

    assert matches_rules(anywhere, {**TRI, "include_statewide": True})


def test_a_county_bid_from_another_county_is_still_excluded():
    """The ordinary case has to keep working."""
    assert not matches_rules(make_opp(county="leon"), TRI)
    assert matches_rules(make_opp(county="broward"), TRI)


def test_no_county_rule_means_no_county_filtering():
    assert matches_rules(make_opp(county="statewide"), {})
    assert matches_rules(_fdot(district="FDOT District 3", counties=("escambia",)), {})


def test_the_county_can_come_from_the_text_when_no_keyword_carries_it():
    """MFMP writes the location into the title rather than into keywords; 15 of
    the sample's 241 statewide rows are only findable that way."""
    named = make_opp(title="Comprehensive Mechanical Systems Maintenance, Levy County",
                     county="statewide", keywords=[])

    assert "levy" in counties_named(named)
    assert matches_rules(named, {"counties": ["levy"]})


def test_counties_named_reads_both_places():
    assert counties_named(_fdot()) >= {"broward", "palm-beach"}
    assert counties_named(make_opp(county="broward", keywords=[], title="Roof Repair")) == set()


def test_a_keyword_that_is_not_a_county_is_not_treated_as_one():
    """Keywords carry NIGP codes and classifier output too."""
    noisy = make_opp(county="statewide", keywords=["roofing", "NIGP - 00500", "broward"])

    assert counties_named(noisy) == {"broward"}


# -- planned work must not read as biddable --------------------------------


def test_a_planned_bid_is_labelled():
    """FDOT publishes 124 of these at a time, with deadlines into 2027. On a
    busy day they are the majority of a watchlist's new matches, and rendered
    like an open bid they read as one with a long fuse.
    """
    line = _bid_line(make_opp(status="upcoming", title="SR 45 Resurfacing"))

    assert "PLANNED" in line.upper()


def test_an_open_bid_carries_no_label():
    assert "planned" not in _bid_line(make_opp(status="open")).lower()


def test_planned_bids_still_reach_the_watchlist():
    """Early warning is the whole value of them — the fix is honesty about what
    they are, not hiding them."""
    planned = make_opp(status="upcoming", county="broward")

    assert wl_matches(TRI, [planned]) == [planned]


# -- a capped list that admits what it left out ----------------------------


def test_a_truncated_section_says_how_much_it_dropped():
    """Every section has always shown ten. That was the whole story at a dozen
    portals; at 305 sources it reports the same "10" whether there were eleven
    matches or two hundred."""
    many = [make_opp(title=f"Job {i}", url=f"https://x/{i}") for i in range(37)]
    html = _bullets(many)

    assert "+ 27 more" in html
    assert html.count("<li") == 11, "ten bids and the overflow line"


def test_an_untruncated_section_says_nothing_extra():
    html = _bullets([make_opp(title=f"Job {i}", url=f"https://x/{i}") for i in range(4)])

    assert "more in the app" not in html
    assert html.count("<li") == 4


def test_an_empty_section_is_an_empty_list():
    html = _bullets([])

    assert "<li" not in html
    assert "more in the app" not in html


# -- planned work needs its own section, not just a label ------------------


def _digest(monkeypatch, opps, rules=None):
    from src.db import store as db
    from web.services import digest as d

    monkeypatch.setattr(d, "load_stored", lambda: [])
    monkeypatch.setattr(db, "latest_health", lambda: [])
    watchlists = [{"name": "Broward roads", "email_digest": True,
                   "rules": rules or TRI, "seen_ids": []}]
    return build_daily_digest(opps, {}, watchlists)


def test_planned_work_gets_its_own_section(monkeypatch):
    """The label alone was not enough, and the live sample proved it.

    Every watchlist list is sorted soonest-due-first, and a planned
    advertisement's projected deadline is months out — so mixed in with open
    bids the planned ones sort to the bottom and fall off the ten-row cap every
    single day. Measured: 43 of 72 matches were planned and *none* appeared.
    """
    soon = datetime.now() + timedelta(days=5)
    later = datetime.now() + timedelta(days=300)
    opps = [make_opp(title=f"Open job {i}", county="broward", due_date=soon,
                     url=f"https://x/o{i}") for i in range(12)]
    opps += [_fdot(title=f"Planned job {i}", status="upcoming", due_date=later,
                   url=f"https://fdot/{i}") for i in range(6)]

    subject, html = _digest(monkeypatch, opps)

    assert "Planned work" in html
    assert "12 new matches" in subject and "6 planned" in subject
    # Without the split, all six would have sorted behind twelve open bids and
    # fallen off the cap.
    assert "Planned job 0" in html


def test_the_subject_separates_biddable_from_planned(monkeypatch):
    """"72 new matches" over-promised when 43 of them could not be bid."""
    later = datetime.now() + timedelta(days=300)
    opps = [_fdot(title=f"Planned {i}", status="upcoming", due_date=later,
                  url=f"https://fdot/{i}") for i in range(14)]

    subject, _ = _digest(monkeypatch, opps)

    assert subject == "Scout daily: 14 planned"
    assert "new match" not in subject


def test_a_watchlist_with_only_planned_work_prints_no_empty_section(monkeypatch):
    later = datetime.now() + timedelta(days=300)
    opps = [_fdot(status="upcoming", due_date=later, url="https://fdot/1")]

    _, html = _digest(monkeypatch, opps)

    assert "Broward roads" not in html, "no heading for a section with no rows"
    assert "Planned work" in html


# -- end to end ------------------------------------------------------------


def test_the_daily_digest_carries_every_fix(monkeypatch):
    due = datetime.now() + timedelta(days=200)
    opps = [_fdot(title=f"District 4 job {i}", status="upcoming", due_date=due,
                  url=f"https://fdot/{i}") for i in range(14)]

    subject, html = _digest(monkeypatch, opps)

    # Statewide-by-county, Broward-by-keyword: all 14 matched a tri-county rule
    # that would have kept none of them before.
    assert "14 planned" in subject
    assert "PLANNED" in html.upper()
    assert "+ 4 more" in html


def test_the_new_rule_key_survives_the_api_round_trip():
    """A rule the matcher honours but the API drops is a setting nobody can set."""
    from web.api.watchlists import Rules

    assert Rules(counties=["broward"], include_statewide=True).compact() == {
        "counties": ["broward"], "include_statewide": True,
    }
    assert "include_statewide" not in Rules(counties=["broward"]).compact()
