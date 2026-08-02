"""Go/no-go scorecard heuristics."""

from datetime import datetime, timedelta

from src.models.opportunity import Opportunity
from src.scoring import capacity_score, fit_score, go_no_go, margin_score


def opp(key="x", **kw):
    base = dict(
        source_id="s",
        source_name="S",
        title=f"Bid {key}",
        url=f"https://example.com/{key}",
        county="broward",
        agency="Agency",
    )
    base.update(kw)
    return Opportunity(**base)


def test_fit_rewards_watchlists_pipeline_and_wins():
    target = opp("t", offer_type="construction")
    tracked = [opp("a", offer_type="construction"), opp("b", offer_type="construction")]
    lone = fit_score(target, [], watchlist_hits=0)
    strong = fit_score(
        target, tracked, watchlist_hits=2, won_offers=["construction"]
    )
    assert lone.score == 40
    # 40 + 30 (two watchlists) + 15 (modal offer) + 5 (county) + 10 (won) = 95 cap
    assert strong.score == 95
    assert any("watchlist" in r for r in strong.reasons)


def test_fit_penalizes_unknown_offer():
    m = fit_score(opp("u", offer_type="unknown"), [])
    assert m.score == 30
    assert any("unclear" in r for r in m.reasons)


def test_capacity_drops_with_nearby_committed_bids():
    due = datetime(2026, 8, 10, 14, 0)
    target = opp("t", due_date=due)
    quiet = capacity_score(target, [])
    busy = capacity_score(
        target,
        [opp("a", due_date=due + timedelta(days=3)),
         opp("b", due_date=due - timedelta(days=10)),
         opp("far", due_date=due + timedelta(days=40))],
    )
    assert quiet.score == 90
    assert busy.score == 50  # two within the 14-day window
    assert "August" in busy.label


def test_capacity_without_due_date_is_neutral():
    assert capacity_score(opp("t"), []).score == 60


def test_margin_reads_commercial_risk_off_the_bid():
    clean = margin_score(
        opp("c", budget="$450,000", duration_days=90, scope="x" * 400,
            documents=[], due_date=datetime(2026, 9, 1))
    )
    risky = margin_score(
        opp(
            "r",
            prior_cycles=2,
            liquidated_damages="$500 / day",
            requirements=["Bid bond 5%", "Prevailing wage"],
            budget="$60,000",
            duration_days=90,
        )
    )
    # clean: 60 + 10 (roomy $/day) − 5 (thin listing not triggered? detail>=50 via scope+due+budget+duration)
    assert clean.score >= 65
    # risky: 60 −10 rebid −10 LD −5 bond −5 compliance −10 tight $/day −5 thin
    assert risky.score == 15
    assert any("incumbent" in r for r in risky.reasons)


def test_go_no_go_returns_three_labeled_meters():
    target = opp("t", offer_type="construction", due_date=datetime(2026, 8, 10))
    tracked = {"w": opp("w", offer_type="construction")}
    meters = go_no_go(
        target,
        tracked=list(tracked.values()),
        committed=[],
        watchlist_hits=1,
        results={"w": "WON · $92,400"},
        tracked_by_id=tracked,
    )
    labels = [m.label for m in meters]
    assert labels[0] == "Fit for our crews"
    assert labels[1].startswith("Capacity in")
    assert labels[2] == "Expected margin"
    assert all(0 <= m.score <= 100 for m in meters)
    assert all(m.tooltip for m in meters)
    # the WON result feeds fit
    assert any("won" in r for r in meters[0].reasons)
