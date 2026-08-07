"""Workday Strategic Sourcing — the platform Florida agencies are moving *to*.

Nothing in the research names this. It turned up twice in one week: UNF left
Jaggaer for it on 1 July 2026, and `fingerprint_agencies.py --recheck` caught
St. Johns County and its Anastasia Sanitary District leaving DemandStar for it.
Three Florida agencies, found by watching for migrations rather than by reading
a platform table.

## Two hosts, and only one of them is ours to read

This matters more than anything else here, so it goes first.

* **`<tenant>.us.workdayspend.com`** is the authenticated supplier application.
  It redirects to `auth.workdayspend.com/sign-in` and serves
  `User-agent: * / Disallow: /`. We do not fetch it. Ever.
* **`<tenant>.public-portal.us.workdayspend.com`** is the public opportunity
  portal — no login, no robots.txt (every path returns the same 1,489-byte SPA
  shell, so `netpolicy` reads it as "none (HTML, not robots)"). This is the
  one the adapter reads, and it needs no override.

The two are one character apart in a hostname and opposite in what they permit.
`bidUrl` on every row points at the *first* host, which is why it is carried as
a link and never fetched: giving a person a URL their browser will open behind
their own login is not the same act as crawling it.

## Getting the data

The portal is a Vite/React SPA talking Apollo GraphQL, and the route takes five
steps to work out and two requests to use:

1. `/Home`-equivalent: the shell names its entry bundle, which lazy-loads
   `index-*.js` chunks; `BidOpportunitiesQuery` lives in the one that renders
   the bids table.
2. That query's AST gives the field set and its variables — `first`, `after`,
   and a **non-null** `input: EventInput!`.
3. Apollo posts to `/graphql` on the same host.
4. **The CSRF header is `X-XSRF-TOKEN`.** `X-CSRF-Token` and `X-Csrf-Token`
   both return `422 Unprocessable Content` with an empty error body — which
   reads as a malformed query rather than a missing header, and is the whole
   afternoon.
5. The token is the `_pp_xsrf` cookie, URL-decoded, set by any page load.

So a fetch is one GET for the cookie and one POST per page of results.
Introspection is disabled, so the field set comes from the app's own query
rather than from the schema.

## Two things that would embarrass a board

* **`requestType: "TEST"`.** St. Johns County's portal currently holds exactly
  one record: *"Testing Solicitation for Suppliers"*, a TEST event from their
  migration. Shipping that to someone's bid board would be worse than shipping
  nothing, so test events are dropped.
* **`restricted: true`** means invitation-only. A bid you cannot respond to is
  not an opportunity, and it is filtered out of `fetch` for the same reason a
  closed one is.

Both are counted rather than silently dropped, and reported when they are all
that a tenant returned — so "this agency published only a test record" is
distinguishable from "this adapter is broken".
"""

from __future__ import annotations

import urllib.parse
from typing import Any, Dict, List, Optional

from ..classify import enrich
from ..dates import parse_dt
from ..http_util import get, session
from ..models.opportunity import Opportunity
from ..netpolicy import check
from .base import SourceAdapter

#: The public portal. Note `public-portal` — the bare `<tenant>.us.workdayspend.com`
#: is the authenticated app and is `Disallow: /`.
PORTAL = "https://{tenant}.public-portal.us.workdayspend.com"

#: Any page load sets the CSRF cookie; this is the one the app itself lands on.
COOKIE_PATH = "/opportunities"

#: The cookie carrying the CSRF token, and the header it must be sent back in.
#: `X-CSRF-Token` and `X-Csrf-Token` are both rejected with an empty 422.
XSRF_COOKIE = "_pp_xsrf"
XSRF_HEADER = "X-XSRF-TOKEN"

#: Lifted from the app's own compiled query. Introspection is disabled, so this
#: field set is the contract — asking for anything the app does not ask for is
#: guesswork against a schema nobody can read.
QUERY = """query BidOpportunitiesQuery($first: Int, $after: String, $input: EventInput!) {
  events(first: $first, after: $after, input: $input) {
    nodes {
      id
      projectId
      title
      bidSubmissionDeadline
      publishedAt
      requestType
      state
      translatedState
      restricted
      commodityCodes
      bidUrl
    }
    pageInfo { endCursor hasNextPage }
    totalCount
  }
}"""

#: `state` is the machine value; `translatedState` is what the portal shows.
#: Mapped on `state`, because the translated one is localised.
STATUS = {
    "published": "open",
    "closed": "closed",
    "awarded": "award",
    "cancelled": "cancelled",
    "canceled": "cancelled",
}

#: Events that exist for the agency's own testing rather than for bidders.
TEST_TYPES = frozenset({"TEST"})

PAGE_SIZE = 50

#: Hard stop. At 50 a page this is 1,000 events, well past any Florida tenant.
MAX_PAGES = 20


class WorkdaySourcingAdapter(SourceAdapter):
    """One tenant's public portal. `workday_tenant` is its subdomain."""

    #: `bidUrl` is on the authenticated host, which robots forbids. It is a
    #: link for a person, not an address for this crawler.
    supports_detail = False

    def __init__(self, cfg: Dict[str, Any]):
        super().__init__(cfg)
        self._s = None
        self.skipped: Dict[str, int] = {}

    # -- public ------------------------------------------------------------

    def fetch(self) -> List[Opportunity]:
        """Open opportunities anyone may respond to."""
        rows = self._events()
        out = [o for o in (self._to_opportunity(r) for r in rows) if o is not None]
        live = [o for o in out if o.status == "open"]

        if rows and not out:
            # Everything the tenant published was a test or invitation-only.
            # That is an agency mid-migration, not a broken parse, and saying
            # which one is the difference between a shrug and an investigation.
            self.empty_note = "the portal published only " + " and ".join(
                f"{n} {k if n == 1 else k + 's'}" for k, n in sorted(self.skipped.items())
            )
        return live

    def fetch_history(self) -> List[Opportunity]:
        """Closed, awarded and cancelled events."""
        rows = self._events()
        out = [o for o in (self._to_opportunity(r) for r in rows) if o is not None]
        return [o for o in out if o.status != "open"]

    # -- internals ---------------------------------------------------------

    def _tenant(self) -> str:
        value = str(self.cfg.get("workday_tenant") or "").strip()
        if not value:
            raise ValueError(f"{self.source_id}: workday_tenant required")
        return value

    def _host(self) -> str:
        return PORTAL.format(tenant=self._tenant())

    def _session(self):
        if self._s is None:
            self._s = session()
        return self._s

    def _token(self) -> Optional[str]:
        """The CSRF token, from the cookie any page load sets."""
        host = self._host()
        try:
            get(host + COOKIE_PATH, s=self._session(), timeout=45)
        except Exception:  # noqa: BLE001 — one tenant is not the run
            self.degraded_reason = "the portal page could not be read"
            return None
        raw = self._session().cookies.get(XSRF_COOKIE)
        if not raw:
            self.degraded_reason = "the portal set no CSRF cookie"
            return None
        return urllib.parse.unquote(raw)

    def _events(self) -> List[Dict[str, Any]]:
        """Every event the portal will show us, paged."""
        self.skipped = {}
        host = self._host()
        token = self._token()
        if token is None:
            return []

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            XSRF_HEADER: token,
            "Origin": host,
            "Referer": host + COOKIE_PATH,
        }

        rows: List[Dict[str, Any]] = []
        after: Optional[str] = None
        for page in range(MAX_PAGES):
            payload = {
                "operationName": "BidOpportunitiesQuery",
                "query": QUERY,
                # `input` is non-null but every field in it is optional, so an
                # empty object is "no filter" rather than a missing argument.
                "variables": {"first": PAGE_SIZE, "after": after, "input": {}},
            }
            check(host + "/graphql")
            try:
                resp = self._session().post(
                    host + "/graphql", json=payload, headers=headers, timeout=60
                )
                resp.raise_for_status()
                body = resp.json()
            except Exception:  # noqa: BLE001
                self.degraded_reason = "the portal's GraphQL endpoint did not answer"
                break

            if body.get("errors"):
                first = (body["errors"] or [{}])[0].get("message", "")
                self.degraded_reason = f"the ad query was rejected: {first[:80]}"
                break

            events = ((body.get("data") or {}).get("events")) or {}
            rows.extend(events.get("nodes") or [])
            info = events.get("pageInfo") or {}
            after = info.get("endCursor")
            if not info.get("hasNextPage") or not after:
                break
        else:
            self.degraded_reason = f"stopped at the {MAX_PAGES}-page cap"
        return rows

    def _to_opportunity(self, row: Dict[str, Any]) -> Optional[Opportunity]:
        title = (row.get("title") or "").strip()
        if not title:
            return None

        if (row.get("requestType") or "").strip().upper() in TEST_TYPES:
            self.skipped["test event"] = self.skipped.get("test event", 0) + 1
            return None
        if row.get("restricted"):
            self.skipped["invitation-only event"] = (
                self.skipped.get("invitation-only event", 0) + 1
            )
            return None

        ref = (row.get("projectId") or "").strip() or (row.get("id") or "").strip() or None
        fields = enrich(title, external_id=ref)
        posted = parse_dt(row.get("publishedAt"))

        return Opportunity(
            **self._base_kwargs(),
            external_id=fields["external_id"] or ref,
            title=title,
            # The authenticated host. Handed to a person's browser, never
            # fetched here — see the module docstring.
            url=(row.get("bidUrl") or "").strip() or self._host() + COOKIE_PATH,
            solicitation_type=fields["solicitation_type"] or (row.get("requestType") or "").strip(),
            offer_type=fields["offer_type"],
            categories=fields["categories"],
            keywords=_keywords(fields["keywords"], row.get("commodityCodes")),
            posted_date=posted.date() if posted else None,
            due_date=parse_dt(row.get("bidSubmissionDeadline")),
            status=STATUS.get((row.get("state") or "").strip().lower(), "closed"),
            raw={"workday": row},
        )


def _keywords(base: List[str], codes: Any) -> List[str]:
    """Commodity codes as keywords, so an NIGP search finds the bid.

    They arrive as `"NIGP - 00500"`, a prefix and a number. Both halves are
    kept: the number is what a vendor knows their own classification by.
    """
    out = list(base)
    for code in codes or []:
        text = str(code).strip()
        if text and text not in out:
            out.append(text)
    return out
