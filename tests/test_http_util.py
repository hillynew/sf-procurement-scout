"""HTTP retry / blocking behaviour (no real network)."""

from __future__ import annotations

import pytest
import requests

from src import http_util
from src.http_util import SourceBlocked, get, get_json, session


class _Resp:
    def __init__(self, status=200, payload=None, text=""):
        self.status_code = status
        self._payload = payload
        self.text = text

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} error")


class _Client:
    """Returns each queued response in turn and records the calls made."""

    def __init__(self, *responses):
        self._queue = list(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        item = self._queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


@pytest.fixture(autouse=True)
def no_sleeping(monkeypatch):
    monkeypatch.setattr(http_util.time, "sleep", lambda *_: None)


def test_the_session_identifies_the_crawler_honestly():
    """Spoofing Chrome at sites that would have served us anyway is the risk."""
    ua = session().headers["User-Agent"]
    assert "sf-procurement-scout" in ua
    assert "Mozilla" not in ua


def test_successful_get_makes_one_request():
    client = _Client(_Resp(200, text="ok"))
    assert get("https://x.gov", s=client).text == "ok"
    assert len(client.calls) == 1


def test_transient_server_error_is_retried():
    client = _Client(_Resp(503), _Resp(200, text="ok"))
    assert get("https://x.gov", s=client).text == "ok"
    assert len(client.calls) == 2


def test_rate_limit_is_retried():
    client = _Client(_Resp(429), _Resp(429), _Resp(200, text="ok"))
    assert get("https://x.gov", s=client, retries=2).text == "ok"
    assert len(client.calls) == 3


def test_retries_are_bounded():
    client = _Client(_Resp(503), _Resp(503), _Resp(503))
    with pytest.raises(requests.HTTPError):
        get("https://x.gov", s=client, retries=2)
    assert len(client.calls) == 3


def test_connection_errors_are_retried_then_raised():
    client = _Client(requests.ConnectionError("boom"), _Resp(200, text="ok"))
    assert get("https://x.gov", s=client, retries=1).text == "ok"


@pytest.mark.parametrize("status", [401, 403])
def test_blocked_portals_raise_immediately(status):
    """A WAF block never clears on retry, so it must not burn the retry budget."""
    client = _Client(_Resp(status), _Resp(200, text="ok"))
    with pytest.raises(SourceBlocked):
        get("https://x.gov", s=client)
    assert len(client.calls) == 1


def test_client_errors_are_not_retried():
    client = _Client(_Resp(404))
    with pytest.raises(requests.HTTPError):
        get("https://x.gov", s=client, retries=2)
    assert len(client.calls) == 1


def test_referer_sets_same_origin_fetch_headers():
    client = _Client(_Resp(200))
    get("https://x.gov/list", s=client, referer="https://x.gov/")
    headers = client.calls[0][1]["headers"]
    assert headers["Referer"] == "https://x.gov/"
    assert headers["Sec-Fetch-Site"] == "same-origin"


def test_get_json_sends_xhr_headers():
    client = _Client(_Resp(200, payload=[{"a": 1}]))
    assert get_json("https://x.gov/api", s=client) == [{"a": 1}]
    headers = client.calls[0][1]["headers"]
    assert headers["X-Requested-With"] == "XMLHttpRequest"
    assert "application/json" in headers["Accept"]
