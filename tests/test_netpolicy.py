"""Crawl policy: identity, robots, per-host rate limiting, and the fetch log."""

from __future__ import annotations

import json
import threading
import time

import pytest

from src import netpolicy


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    netpolicy.reset_for_tests()
    monkeypatch.setattr(netpolicy, "FETCH_LOG", "")
    yield
    netpolicy.reset_for_tests()


def _serve(monkeypatch, body: str, status: int = 200):
    """Answer every robots.txt fetch with this body."""

    class _Resp:
        status_code = status
        text = body

    class _Requests:
        @staticmethod
        def get(url, **kw):
            assert url.endswith("/robots.txt")
            return _Resp()

    monkeypatch.setattr("requests.get", _Requests.get)


# -- identity --------------------------------------------------------------


def test_the_crawler_names_itself_and_offers_a_contact():
    assert "sf-procurement-scout" in netpolicy.CRAWLER_UA
    assert "+http" in netpolicy.CRAWLER_UA
    assert "Mozilla" not in netpolicy.CRAWLER_UA


def test_the_browser_string_is_reserved_for_listed_hosts():
    assert netpolicy.user_agent_for("https://api.procurement.opengov.com/x") == netpolicy.CRAWLER_UA
    assert netpolicy.user_agent_for("https://www.wpb.org/bids") == netpolicy.BROWSER_UA


# -- robots ----------------------------------------------------------------


def test_a_disallowed_path_is_refused(monkeypatch):
    _serve(monkeypatch, "User-agent: *\nDisallow: /private\n")
    allowed, _ = netpolicy.robots_allows("https://example.gov/private/bids")
    assert not allowed

    allowed, _ = netpolicy.robots_allows("https://example.gov/public/bids")
    assert allowed


def test_dms_myflorida_is_refused_outright(monkeypatch):
    """Disallow: / for everyone but search engines, and VIP carries the same data."""
    _serve(monkeypatch, "User-agent: *\nAllow: /\n")  # even a permissive file loses

    allowed, why = netpolicy.robots_allows("https://dms.myflorida.com/business_operations")
    assert not allowed
    assert "deny list" in why

    with pytest.raises(netpolicy.RobotsDisallowed):
        netpolicy.check("https://dms.myflorida.com/anything")


def test_a_missing_robots_file_means_unrestricted(monkeypatch):
    _serve(monkeypatch, "", status=404)
    allowed, why = netpolicy.robots_allows("https://vendor.myfloridamarketplace.com/mfmp/x")
    assert allowed
    assert "404" in why


def test_an_html_error_page_is_not_read_as_a_prohibition(monkeypatch):
    """Some hosts answer /robots.txt with their SPA shell, HTTP 200."""
    _serve(monkeypatch, "<!DOCTYPE html><html><head><title>App</title></head></html>")
    allowed, why = netpolicy.robots_allows("https://procurement.opengov.com/portal/x")
    assert allowed
    assert "HTML" in why


def test_an_unreachable_robots_file_does_not_block_the_crawl(monkeypatch):
    def boom(url, **kw):
        raise OSError("connection reset")

    monkeypatch.setattr("requests.get", boom)
    allowed, why = netpolicy.robots_allows("https://example.gov/bids")
    assert allowed
    assert "unreachable" in why


def test_robots_is_cached_rather_than_refetched(monkeypatch):
    calls = {"n": 0}

    class _Resp:
        status_code = 200
        text = "User-agent: *\nDisallow:\n"

    def counting(url, **kw):
        calls["n"] += 1
        return _Resp()

    monkeypatch.setattr("requests.get", counting)
    for _ in range(5):
        netpolicy.robots_allows("https://example.gov/bids")
    assert calls["n"] == 1


# -- overrides -------------------------------------------------------------


def test_bonfire_is_an_explicit_documented_override(monkeypatch):
    _serve(monkeypatch, "User-agent: *\nDisallow: /\n")
    allowed, why = netpolicy.robots_allows("https://broward.bonfirehub.com/PublicPortal/x")
    assert allowed
    assert "override" in why


def test_strict_mode_drops_every_override(monkeypatch):
    """A deployment that wants no judgement calls sets one env var."""
    _serve(monkeypatch, "User-agent: *\nDisallow: /\n")
    monkeypatch.setenv("SF_SCOUT_STRICT_ROBOTS", "1")

    allowed, _ = netpolicy.robots_allows("https://broward.bonfirehub.com/PublicPortal/x")
    assert not allowed


def test_an_override_does_not_leak_to_a_lookalike_host(monkeypatch):
    _serve(monkeypatch, "User-agent: *\nDisallow: /\n")
    allowed, _ = netpolicy.robots_allows("https://evilbonfirehub.com.attacker.test/x")
    assert not allowed


# -- rate limiting ---------------------------------------------------------


def test_one_host_is_held_to_the_interval(monkeypatch):
    _serve(monkeypatch, "User-agent: *\nDisallow:\n")
    slept = []
    monkeypatch.setattr(netpolicy.time, "sleep", lambda s: slept.append(s))

    # Pin the interval so this test is about the limiter alone; robots_for
    # reads the clock too, and would otherwise consume the ticks below.
    monkeypatch.setattr(netpolicy, "interval_for", lambda host: 1.0)

    ticks = [100.0, 100.0, 100.2, 100.2]
    monkeypatch.setattr(netpolicy.time, "monotonic", lambda: ticks.pop(0) if ticks else 100.2)

    netpolicy.pace("https://example.gov/a")
    netpolicy.pace("https://example.gov/b")

    assert slept and slept[-1] == pytest.approx(0.8, abs=0.01)


def test_separate_hosts_do_not_wait_on_each_other(monkeypatch):
    _serve(monkeypatch, "User-agent: *\nDisallow:\n")
    slept = []
    monkeypatch.setattr(netpolicy.time, "sleep", lambda s: slept.append(s))

    netpolicy.pace("https://a.example.gov/x")
    netpolicy.pace("https://b.example.gov/x")

    assert not slept


def test_crawl_delay_raises_the_interval_but_never_lowers_it(monkeypatch):
    _serve(monkeypatch, "User-agent: *\nCrawl-delay: 10\nDisallow:\n")
    assert netpolicy.interval_for("flsheriffs.org") == 10.0

    netpolicy.reset_for_tests()
    _serve(monkeypatch, "User-agent: *\nCrawl-delay: 0.1\nDisallow:\n")
    assert netpolicy.interval_for("fast.example.gov") == netpolicy.MIN_INTERVAL


def test_concurrent_callers_against_one_host_still_queue(monkeypatch):
    """The limiter is shared, so threads serialise instead of each feeling polite."""
    _serve(monkeypatch, "User-agent: *\nDisallow:\n")
    monkeypatch.setattr(netpolicy, "MIN_INTERVAL", 0.05)

    stamps = []
    lock = threading.Lock()

    def worker():
        netpolicy.pace("https://example.gov/x")
        with lock:
            stamps.append(time.monotonic())

    threads = [threading.Thread(target=worker) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    stamps.sort()
    gaps = [b - a for a, b in zip(stamps, stamps[1:])]
    assert all(g >= 0.04 for g in gaps), gaps


# -- the fetch log ---------------------------------------------------------


def test_the_log_records_what_robots_said_at_the_time(tmp_path, monkeypatch):
    path = tmp_path / "fetches.jsonl"
    monkeypatch.setattr(netpolicy, "FETCH_LOG", str(path))

    netpolicy.log_fetch(
        "https://example.gov/bids", status=200,
        robots_note="allowed by robots", ua=netpolicy.CRAWLER_UA, elapsed_ms=42,
    )
    record = json.loads(path.read_text().strip())

    assert record["url"] == "https://example.gov/bids"
    assert record["status"] == 200
    assert record["robots"] == "allowed by robots"
    assert record["ua"] == netpolicy.CRAWLER_UA
    assert record["ts"].endswith("Z")


def test_a_refusal_is_logged_before_it_is_raised(tmp_path, monkeypatch):
    path = tmp_path / "fetches.jsonl"
    monkeypatch.setattr(netpolicy, "FETCH_LOG", str(path))

    with pytest.raises(netpolicy.RobotsDisallowed):
        netpolicy.check("https://dms.myflorida.com/x")

    record = json.loads(path.read_text().strip())
    assert record["status"] == "refused"


def test_logging_is_off_unless_a_path_is_configured(monkeypatch):
    monkeypatch.setattr(netpolicy, "FETCH_LOG", "")
    netpolicy.log_fetch("https://example.gov/x", status=200, robots_note="n", ua="u")


def test_an_unwritable_log_never_breaks_a_fetch(monkeypatch):
    monkeypatch.setattr(netpolicy, "FETCH_LOG", "/nonexistent-dir/does/not/exist.jsonl")
    netpolicy.log_fetch("https://example.gov/x", status=200, robots_note="n", ua="u")
