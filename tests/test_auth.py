"""Optional vendor-session credentials, read from the environment only."""

from __future__ import annotations

import os

import pytest

from src.auth import (
    ENV_BONFIRE_COOKIE,
    bonfire_cookie,
    describe_bonfire,
    has_bonfire_cookie,
    host_suffix,
)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for var in list(os.environ):
        if var.startswith(ENV_BONFIRE_COOKIE):
            monkeypatch.delenv(var, raising=False)


@pytest.mark.parametrize(
    "host, suffix",
    [
        ("broward.bonfirehub.com", "BROWARD"),
        ("tri-rail.bonfirehub.com", "TRI_RAIL"),
        ("townofpalmbeach.bonfirehub.com", "TOWNOFPALMBEACH"),
        ("", ""),
    ],
)
def test_host_suffix_is_env_var_safe(host, suffix):
    assert host_suffix(host) == suffix


def test_no_cookie_configured():
    assert bonfire_cookie("broward.bonfirehub.com") is None
    assert not has_bonfire_cookie("broward.bonfirehub.com")
    assert describe_bonfire("broward.bonfirehub.com") == "not set"


def test_shared_cookie_covers_every_host(monkeypatch):
    monkeypatch.setenv(ENV_BONFIRE_COOKIE, "session=abc")
    assert bonfire_cookie("broward.bonfirehub.com") == "session=abc"
    assert bonfire_cookie("fau.bonfirehub.com") == "session=abc"
    assert has_bonfire_cookie("fau.bonfirehub.com")


def test_host_specific_cookie_wins_over_shared(monkeypatch):
    monkeypatch.setenv(ENV_BONFIRE_COOKIE, "shared=1")
    monkeypatch.setenv(f"{ENV_BONFIRE_COOKIE}_BROWARD", "broward-only=2")
    assert bonfire_cookie("broward.bonfirehub.com") == "broward-only=2"
    assert bonfire_cookie("fau.bonfirehub.com") == "shared=1"


def test_host_specific_cookie_alone_only_covers_that_host(monkeypatch):
    monkeypatch.setenv(f"{ENV_BONFIRE_COOKIE}_BROWARD", "broward-only=2")
    assert bonfire_cookie("broward.bonfirehub.com") == "broward-only=2"
    assert bonfire_cookie("fau.bonfirehub.com") is None


def test_blank_value_counts_as_not_set(monkeypatch):
    monkeypatch.setenv(ENV_BONFIRE_COOKIE, "   ")
    assert bonfire_cookie("broward.bonfirehub.com") is None


def test_describe_never_includes_the_cookie_value(monkeypatch):
    monkeypatch.setenv(ENV_BONFIRE_COOKIE, "super-secret-session-token")
    description = describe_bonfire("broward.bonfirehub.com")
    assert "super-secret-session-token" not in description
    assert description == ENV_BONFIRE_COOKIE


def test_describe_reports_the_host_specific_variable_name(monkeypatch):
    monkeypatch.setenv(f"{ENV_BONFIRE_COOKIE}_TRI_RAIL", "abc")
    assert describe_bonfire("tri-rail.bonfirehub.com") == f"{ENV_BONFIRE_COOKIE}_TRI_RAIL"
