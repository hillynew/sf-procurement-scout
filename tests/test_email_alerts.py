"""Bid notices delivered by email — the only push feed these portals offer."""

from __future__ import annotations

import email
from datetime import date, datetime
from email.message import EmailMessage

import pytest

from src.sources import email_alerts
from src.sources.email_alerts import (
    ENV_HOST,
    ENV_PASSWORD,
    ENV_USER,
    EmailAlertsAdapter,
    MailboxNotConfigured,
    is_configured,
    mailbox_settings,
)

CFG = {
    "id": "email_alerts",
    "name": "Subscribed bid alerts (email)",
    "county": "broward",
    "agency": "Email subscriptions",
    "portal_url": "https://www.northmiamifl.gov/list.aspx?Mode=Subscribe#bids",
}


def _message(
    subject="Bids: ITB 2026-014 Roof Replacement at City Hall",
    body=(
        "A new bid has been posted.\n"
        "ITB 2026-014 Roof Replacement at City Hall\n"
        "Closing date: August 19, 2026 2:00 PM\n"
        "View it here: https://www.northmiamifl.gov/bids.aspx?bidID=210\n"
        "Unsubscribe: https://www.northmiamifl.gov/list.aspx?Mode=Unsubscribe\n"
    ),
    sent="Tue, 28 Jul 2026 09:15:00 -0400",
    html=None,
):
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = "notify@northmiamifl.gov"
    msg["Date"] = sent
    if html is not None:
        msg.set_content(body)
        msg.add_alternative(html, subtype="html")
    else:
        msg.set_content(body)
    return email.message_from_bytes(msg.as_bytes())


def _adapter(monkeypatch, messages, **cfg):
    monkeypatch.setattr(email_alerts, "read_messages", lambda **k: messages)
    return EmailAlertsAdapter({**CFG, **cfg})


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for var in (ENV_HOST, ENV_USER, ENV_PASSWORD):
        monkeypatch.delenv(var, raising=False)


def test_unconfigured_mailbox_reports_not_configured():
    assert not is_configured()
    with pytest.raises(MailboxNotConfigured):
        mailbox_settings()


def test_configured_mailbox_is_detected(monkeypatch):
    monkeypatch.setenv(ENV_HOST, "imap.example.com")
    monkeypatch.setenv(ENV_USER, "bids@example.com")
    monkeypatch.setenv(ENV_PASSWORD, "secret")
    assert is_configured()
    assert mailbox_settings() == ("imap.example.com", "bids@example.com", "secret")


@pytest.mark.parametrize("missing", [ENV_HOST, ENV_USER, ENV_PASSWORD])
def test_a_partial_configuration_is_not_usable(monkeypatch, missing):
    for var, value in ((ENV_HOST, "h"), (ENV_USER, "u"), (ENV_PASSWORD, "p")):
        if var != missing:
            monkeypatch.setenv(var, value)
    assert not is_configured()


def test_an_unconfigured_source_yields_nothing_and_says_why():
    """A checkout without a mailbox must behave exactly as before."""
    adapter = EmailAlertsAdapter(dict(CFG))
    assert adapter.fetch() == []
    assert adapter.empty_note and ENV_HOST in adapter.empty_note
    assert adapter.degraded_reason is None, "opt-in and off is not a fault"


# ---------------------------------------------------------------------------
# Parsing a notice
# ---------------------------------------------------------------------------


def test_a_bid_notice_becomes_an_opportunity(monkeypatch):
    (o,) = _adapter(monkeypatch, [_message()]).fetch()
    assert o.title == "ITB 2026-014 Roof Replacement at City Hall"
    assert o.external_id and "2026-014" in o.external_id
    assert o.solicitation_type == "ITB"
    assert o.status == "open"


def test_the_closing_date_is_read_from_the_body(monkeypatch):
    (o,) = _adapter(monkeypatch, [_message()]).fetch()
    assert o.due_date == datetime(2026, 8, 19, 14, 0)


def test_the_send_date_becomes_the_posted_date(monkeypatch):
    (o,) = _adapter(monkeypatch, [_message()]).fetch()
    assert o.posted_date == date(2026, 7, 28)


def test_the_bid_link_is_preferred_over_the_unsubscribe_link(monkeypatch):
    (o,) = _adapter(monkeypatch, [_message()]).fetch()
    assert o.url == "https://www.northmiamifl.gov/bids.aspx?bidID=210"


def test_the_subject_prefix_is_stripped(monkeypatch):
    msg = _message(subject="Notify Me: RFP 2026-007 Grounds Maintenance")
    (o,) = _adapter(monkeypatch, [msg]).fetch()
    assert o.title == "RFP 2026-007 Grounds Maintenance"


def test_the_subscription_footer_is_not_part_of_the_description(monkeypatch):
    (o,) = _adapter(monkeypatch, [_message()]).fetch()
    assert o.description and "Unsubscribe" not in o.description


def test_an_html_only_notice_is_read(monkeypatch):
    msg = _message(
        body="",
        html=(
            "<html><body><p>ITB 2026-021 Pipe Lining</p>"
            "<p>Closing date: September 2, 2026</p>"
            '<a href="https://city.gov/bids.aspx?bidID=9">View</a></body></html>'
        ),
    )
    (o,) = _adapter(monkeypatch, [msg]).fetch()
    assert o.due_date == datetime(2026, 9, 2)
    assert o.url == "https://city.gov/bids.aspx?bidID=9"


def test_an_encoded_subject_is_decoded(monkeypatch):
    msg = _message(subject="=?utf-8?q?Bids=3A_ITB_2026-030_Caf=C3=A9_Renovation?=")
    (o,) = _adapter(monkeypatch, [msg]).fetch()
    assert "Café Renovation" in o.title


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "subject",
    [
        "Your water bill is ready",
        "Parks & Recreation newsletter",
        "Meeting agenda for Tuesday",
    ],
)
def test_ordinary_mail_is_ignored(monkeypatch, subject):
    """A shared mailbox will contain mail that is not a bid notice."""
    assert _adapter(monkeypatch, [_message(subject=subject)]).fetch() == []


def test_the_same_bid_arriving_twice_is_recorded_once(monkeypatch):
    """Reminder mails repeat the original notice."""
    msgs = [_message(), _message(subject="Bids: ITB 2026-014 Roof Replacement — reminder")]
    assert len(_adapter(monkeypatch, msgs).fetch()) == 1


def test_a_notice_without_a_usable_link_falls_back_to_the_portal(monkeypatch):
    msg = _message(body="ITB 2026-014 Roof Replacement was posted. No link provided.")
    (o,) = _adapter(monkeypatch, [msg]).fetch()
    assert o.url == CFG["portal_url"]


def test_link_host_config_rejects_foreign_links(monkeypatch):
    msg = _message(
        body=(
            "ITB 2026-014 Roof Replacement\n"
            "Tracking: https://analytics.example.net/click?id=1\n"
            "Bid: https://www.northmiamifl.gov/bids.aspx?bidID=210\n"
        )
    )
    (o,) = _adapter(monkeypatch, [msg], link_host="northmiamifl.gov").fetch()
    assert o.url == "https://www.northmiamifl.gov/bids.aspx?bidID=210"


def test_a_title_too_short_to_be_a_bid_is_skipped(monkeypatch):
    assert _adapter(monkeypatch, [_message(subject="Bids: RFP")]).fetch() == []


def test_an_empty_mailbox_is_not_an_error(monkeypatch):
    adapter = _adapter(monkeypatch, [])
    assert adapter.fetch() == []
    assert adapter.degraded_reason is None
    assert adapter.allows_empty


def test_an_unconfigured_source_is_inactive_not_degraded():
    """An opt-in integration nobody enabled must not raise a standing alarm."""
    from src.pipeline.runner import _classify_health

    adapter = EmailAlertsAdapter(dict(CFG))
    health = _classify_health(adapter, adapter.fetch(), 0)
    assert health.status == "empty"
    assert health.ok
    assert "inactive" in health.note
