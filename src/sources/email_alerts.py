"""Bid notices delivered by email, read over IMAP.

CivicPlus cities offer a "Notify Me" subscription that emails you the moment a
bid posts. That is the closest thing to a push feed any of these portals
provide — no portal in the set offers webhooks — so subscribing a dedicated
mailbox and reading it turns a polling scraper into near-real-time alerting.

Credentials come from the environment and are never stored in the repo:

    SF_SCOUT_IMAP_HOST=imap.gmail.com
    SF_SCOUT_IMAP_USER=bids@example.com
    SF_SCOUT_IMAP_PASSWORD=<app password>
    SF_SCOUT_IMAP_FOLDER=INBOX          # optional
    SF_SCOUT_IMAP_DAYS=30               # optional lookback

With nothing configured the adapter returns no rows and reports `empty`, so a
checkout without a mailbox behaves exactly as before.
"""

from __future__ import annotations

import email
import imaplib
import os
import re
from datetime import date, datetime, timedelta
from email.header import decode_header, make_header
from email.message import Message
from typing import List, Optional, Tuple

from ..classify import enrich
from ..dates import parse_dt
from ..models.opportunity import Opportunity
from .base import SourceAdapter

ENV_HOST = "SF_SCOUT_IMAP_HOST"
ENV_USER = "SF_SCOUT_IMAP_USER"
ENV_PASSWORD = "SF_SCOUT_IMAP_PASSWORD"
ENV_FOLDER = "SF_SCOUT_IMAP_FOLDER"
ENV_DAYS = "SF_SCOUT_IMAP_DAYS"

DEFAULT_FOLDER = "INBOX"
DEFAULT_DAYS = 30
MAX_MESSAGES = 300

# Subjects a bid notice actually uses, so ordinary mail in a shared box is
# ignored rather than parsed into junk opportunities.
_BID_SUBJECT = re.compile(
    r"\b(bid|solicitation|rfp|rfq|itb|ifb|itn|rpq|procurement|invitation to)\b", re.I
)
# "Notify Me" mails lead with the list name; the bid title follows.
_SUBJECT_PREFIX = re.compile(
    r"^\s*(?:re:|fwd:)?\s*(?:notify\s*me|new\s+bid\s+posting|bid\s+posting|bids?)\s*[:\-–]\s*",
    re.I,
)
_URL = re.compile(r"https?://[^\s<>\"')]+", re.I)
_CLOSING = re.compile(
    r"(?:clos(?:es|ing)|due|deadline|submittal)\s*(?:date)?\s*[:\-]?\s*"
    r"([A-Z][a-z]+\s+\d{1,2},?\s+\d{4}|\d{1,2}/\d{1,2}/\d{4})"
    r"(?:[^\n]{0,20}?(\d{1,2}:\d{2}\s*[AP]\.?M\.?))?",
    re.I,
)
_REF = re.compile(r"\b((?:ITB|IFB|RFP|RFQ|RFI|ITN|RPQ|ITQ|RLI)[\s\-]?[\w.\-/]{3,})", re.I)


class MailboxNotConfigured(RuntimeError):
    """No IMAP settings in the environment."""


class EmailAlertsAdapter(SourceAdapter):
    """Turns subscribed bid-notice emails into opportunities.

    Optional config keys:
      link_host: only accept links on this host (keeps the bid URL, not the
                 unsubscribe footer)
    """

    #: An empty mailbox is a normal state, not a broken scraper.
    allows_empty = True

    def fetch(self) -> List[Opportunity]:
        try:
            messages = read_messages(
                folder=self.cfg.get("imap_folder"),
                days=self.cfg.get("imap_days"),
            )
        except MailboxNotConfigured:
            # Opt-in and switched off is a normal state, not a breakage, so
            # this reports as inactive rather than raising a standing alarm.
            self.empty_note = f"inactive — set {ENV_HOST}/{ENV_USER}/{ENV_PASSWORD} to enable"
            return []

        out: List[Opportunity] = []
        seen: set = set()
        for msg in messages:
            opp = self._from_message(msg)
            if opp and opp.url not in seen:
                seen.add(opp.url)
                out.append(opp)
        return out

    def _from_message(self, msg: Message) -> Optional[Opportunity]:
        subject = _decode(msg.get("Subject"))
        if not subject or not _BID_SUBJECT.search(subject):
            return None

        body = _body_text(msg)
        title = _title_from(subject)
        if len(title) < 5:
            return None

        url = _bid_url(body, self.cfg.get("link_host")) or self.portal_url
        due = _closing_from(body) or _closing_from(subject)
        posted = _sent_date(msg)
        ref_match = _REF.search(subject) or _REF.search(body)
        ref = ref_match.group(1).strip() if ref_match else None

        fields = enrich(title, body[:600], external_id=ref)
        return Opportunity(
            **self._base_kwargs(),
            external_id=fields["external_id"] or ref,
            title=title,
            url=url,
            solicitation_type=fields["solicitation_type"],
            offer_type=fields["offer_type"],
            categories=fields["categories"],
            keywords=fields["keywords"],
            due_date=due,
            posted_date=posted,
            status="open",
            description=_summary(body),
            raw={"subject": subject[:300], "via": "email-alert"},
        )


# ---------------------------------------------------------------------------
# IMAP
# ---------------------------------------------------------------------------


def mailbox_settings() -> Tuple[str, str, str]:
    host = os.environ.get(ENV_HOST, "").strip()
    user = os.environ.get(ENV_USER, "").strip()
    password = os.environ.get(ENV_PASSWORD, "")
    if not (host and user and password):
        raise MailboxNotConfigured(
            f"set {ENV_HOST}, {ENV_USER} and {ENV_PASSWORD} to read bid alerts"
        )
    return host, user, password


def is_configured() -> bool:
    try:
        mailbox_settings()
    except MailboxNotConfigured:
        return False
    return True


def read_messages(
    *,
    folder: Optional[str] = None,
    days: Optional[int] = None,
    limit: int = MAX_MESSAGES,
) -> List[Message]:
    """Recent messages from the alert mailbox. Read-only; nothing is deleted."""
    host, user, password = mailbox_settings()
    folder = folder or os.environ.get(ENV_FOLDER) or DEFAULT_FOLDER
    days = int(days or os.environ.get(ENV_DAYS) or DEFAULT_DAYS)

    since = (date.today() - timedelta(days=days)).strftime("%d-%b-%Y")
    out: List[Message] = []
    client = imaplib.IMAP4_SSL(host)
    try:
        client.login(user, password)
        # readonly: this mailbox is a feed, not something we own
        client.select(folder, readonly=True)
        status, data = client.search(None, "SINCE", since)
        if status != "OK":
            return []
        ids = (data[0] or b"").split()[-limit:]
        for mid in ids:
            status, payload = client.fetch(mid, "(RFC822)")
            if status != "OK" or not payload:
                continue
            raw = next((p[1] for p in payload if isinstance(p, tuple) and len(p) > 1), None)
            if raw:
                out.append(email.message_from_bytes(raw))
    finally:
        try:
            client.close()
        except Exception:  # noqa: BLE001 — closing a read-only box can fail harmlessly
            pass
        try:
            client.logout()
        except Exception:  # noqa: BLE001
            pass
    return out


# ---------------------------------------------------------------------------
# Message parsing
# ---------------------------------------------------------------------------


def _decode(value: Optional[str]) -> str:
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value))).strip()
    except (UnicodeDecodeError, LookupError, ValueError):
        return value.strip()


def _body_text(msg: Message) -> str:
    """Plain text if offered, else HTML with the tags stripped."""
    plain, html = "", ""
    for part in msg.walk() if msg.is_multipart() else [msg]:
        if part.get_content_maintype() == "multipart":
            continue
        try:
            payload = part.get_payload(decode=True) or b""
            text = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
        except (LookupError, UnicodeDecodeError, AttributeError):
            continue
        if part.get_content_type() == "text/plain" and not plain:
            plain = text
        elif part.get_content_type() == "text/html" and not html:
            html = text
    if plain.strip():
        return plain
    if html:
        text = re.sub(r"(?is)<(script|style).*?</\1>", " ", html)
        text = re.sub(r"(?i)<br\s*/?>|</p>", "\n", text)
        # Keep href targets before dropping tags. These notices are HTML and
        # the bid link lives in the attribute, not the anchor text, so naive
        # tag-stripping would discard every link in the message.
        text = re.sub(
            r"(?is)<a\b[^>]*\bhref=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>",
            r"\2 \1 ",
            text,
        )
        text = re.sub(r"<[^>]+>", " ", text)
        return re.sub(r"&nbsp;?", " ", text)
    return ""


def _title_from(subject: str) -> str:
    title = _SUBJECT_PREFIX.sub("", subject).strip(" -–:|")
    return re.sub(r"\s+", " ", title)[:200]


def _bid_url(body: str, link_host: Optional[str]) -> Optional[str]:
    """The first link that points at the bid rather than the mail footer."""
    for match in _URL.finditer(body or ""):
        url = match.group(0).rstrip(".,);")
        lowered = url.lower()
        if any(skip in lowered for skip in ("unsubscribe", "list.aspx", "privacy", "mailto")):
            continue
        if link_host and link_host.lower() not in lowered:
            continue
        return url
    return None


def _closing_from(text: str) -> Optional[datetime]:
    m = _CLOSING.search(text or "")
    if not m:
        return None
    parts = [m.group(1)]
    if m.group(2):
        parts.append(m.group(2))
    return parse_dt(" ".join(parts))


def _sent_date(msg: Message) -> Optional[date]:
    raw = msg.get("Date")
    if not raw:
        return None
    try:
        parsed = email.utils.parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None
    return parsed.date() if parsed else None


def _summary(body: str) -> Optional[str]:
    text = re.sub(r"\s+", " ", (body or "")).strip()
    if not text:
        return None
    # Drop the subscription footer, which is longer than the notice itself.
    text = re.split(r"(?i)\b(unsubscribe|you are receiving this|to stop receiving)\b", text)[0]
    return text.strip()[:600] or None
