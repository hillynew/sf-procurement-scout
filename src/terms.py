"""What each platform's terms of use say about reading it, and when we checked.

## Why this table exists

On 7 August 2026 an adapter was built against DemandStar's public JSON
endpoint, shipped 14 agencies, and merged — against a decision recorded in
`docs/statewide-coverage.md` since the statewide expansion, which quotes their
terms prohibiting "any robot, spider, data scraping, crawler or other
extraction tool". Nothing in the codebase said no. The only thing standing
between a reasonable-looking endpoint and a merged adapter was whether someone
happened to open the right document, and that day nobody did.

The lesson is narrow and worth stating exactly: **robots.txt is not the test.**
DemandStar serves `User-agent: *` with no rules at all, so a robots check
returns "allowed" and means nothing. An open endpoint is not permission either
— it is an implementation detail of a site that may forbid reading it in prose
a crawler never sees.

So the verdict lives in code, next to the adapters, where a test can enforce it:

* An adapter may not exist for a platform recorded `PROHIBITED` or `UNREADABLE`.
* A *new* adapter must be `PERMITTED` or `AGENCY_SITE` — `UNCHECKED` is
  grandfathered for what already shipped and the set may not grow.

The second rule is the one that would have failed CI on the DemandStar change.

## What the statuses mean

`AGENCY_SITE` is not a loophole, it is the common case. Most adapters here read
a government body's own website — a CivicPlus module on the city's domain,
MyFloridaMarketPlace, FDOT, FACTS, SAM.gov. There is no vendor in between and
no vendor terms; the publisher is the agency, and what is published is a public
record it is required by statute to post.

`UNREADABLE` covers a platform whose terms cannot be fetched — behind a WAF, or
behind a robots `Disallow`. It is deliberately grouped with `PROHIBITED` rather
than with `UNCHECKED`, because a judgement made on evidence one cannot read, in
favour of the party that gains from reading it that way, is not a judgement.

`UNCHECKED` is honest debt: an adapter that shipped before this table existed
and whose terms nobody has located. It is visible here rather than absent, and
the test freezes the list so the debt cannot grow quietly.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

#: Terms read; nothing in them forbids automated reading of public pages.
PERMITTED = "permitted"
#: Terms forbid it, in language that covers what an adapter does.
PROHIBITED = "prohibited"
#: Terms exist and cannot be read — a WAF, or a robots `Disallow` over them.
UNREADABLE = "unreadable"
#: No vendor in between: the agency publishes on its own site.
AGENCY_SITE = "agency_site"
#: Shipped before this table existed; terms not yet located.
UNCHECKED = "unchecked"

#: Statuses that must never have an adapter.
FORBIDS_ADAPTER = frozenset({PROHIBITED, UNREADABLE})

#: What a *new* adapter must be.
ALLOWS_NEW_ADAPTER = frozenset({PERMITTED, AGENCY_SITE})


@dataclass(frozen=True)
class Verdict:
    status: str
    #: Where the terms were read. None for AGENCY_SITE, where there are none.
    source: Optional[str] = None
    #: ISO date of the reading. A verdict with no date is a memory, not a check.
    checked_on: Optional[str] = None
    note: str = ""


TERMS: Dict[str, Verdict] = {
    # -- no vendor in between -------------------------------------------
    # The agency's own website or the state's own system. What is posted is a
    # public record the body is required to publish; there is no intermediary
    # imposing terms on reading it.
    "civicplus": Verdict(AGENCY_SITE, note="CMS module served on each city's own domain"),
    "mfmp_vbs": Verdict(AGENCY_SITE, note="MyFloridaMarketPlace, the state's own system"),
    "fdot_ads": Verdict(AGENCY_SITE, note="FDOT's own advertisement host"),
    "fdot_letting": Verdict(AGENCY_SITE, note="FDOT's own letting-results host, robots Allow: /"),
    "facts": Verdict(AGENCY_SITE, note="the state contract register under s. 215.985(14)"),
    "sam_gov": Verdict(AGENCY_SITE, note="the federal government's own system"),
    "miami_dade_informs": Verdict(AGENCY_SITE, note="Miami-Dade's own supplier portal"),
    "miami_dade_construction": Verdict(AGENCY_SITE, note="miamidade.gov"),
    "miami_dade_future": Verdict(AGENCY_SITE, note="miamidade.gov"),
    "miami_dade_awards": Verdict(AGENCY_SITE, note="miamidade.gov"),
    "west_palm_beach": Verdict(AGENCY_SITE, note="wpb.org"),
    "mdc_college": Verdict(AGENCY_SITE, note="mdc.edu"),
    "palm_beach_schools": Verdict(AGENCY_SITE, note="palmbeachschools.org"),
    "notice_links": Verdict(AGENCY_SITE, note="statutory notice sites under s. 50.0311"),
    # Reads mail already in our own inbox. No site is fetched at all.
    "email_alerts": Verdict(AGENCY_SITE, note="our own mailbox, not a site"),
    # Fetches nothing by design — a pointer for a person to click.
    "catalog": Verdict(AGENCY_SITE, note="a pointer; nothing is fetched"),

    # -- vendor platforms, terms read ------------------------------------
    "ionwave": Verdict(
        PERMITTED, source="https://coconutcreek.ionwave.net/SiteTerms.aspx",
        checked_on="2026-08-07",
        note="binds on registration rather than on reading, and says nothing "
             "about automated access",
    ),
    "bonfire": Verdict(
        PERMITTED, source="https://eunasolutions.com/terms-of-use/",
        checked_on="2026-08-07",
        note="browse-wrap, but its restrictions cover reselling and user-submitted "
             "data; no clause on copying, downloading or automated reading",
    ),

    "legistar": Verdict(
        PERMITTED, source="https://webapi.legistar.com/",
        checked_on="2026-08-09",
        note="Granicus's public read-only web API, self-documenting (Home / "
             "API / Examples), no auth, no robots.txt, no terms of use served "
             "on the host — published precisely so civic data can be read "
             "programmatically",
    ),

    # -- vendor platforms that forbid it ---------------------------------
    "demandstar": Verdict(
        PROHIBITED, source="https://network.demandstar.com/terms-of-use/",
        checked_on="2026-08-07",
        note="prohibited conduct (I): 'use any robot, spider, data scraping, "
             "crawler or other extraction tool (automatic or manual) or similar "
             "device to monitor or copy DemandStar's web pages or Content'. "
             "An adapter was built and reverted — docs/statewide-coverage.md §3",
    ),
    "vendor_registry": Verdict(
        PROHIBITED, source="https://vendorregistry.com/terms/",
        checked_on="2026-08-07",
        note="§1.1 Personal Use: 'You may not copy or download any content from "
             "the Site or Services except with the prior written approval of "
             "Vendor Registry', under a browse-wrap that binds on use of the "
             "site. The archive-only adapter downloaded 1,098 solicitations, "
             "which is squarely inside that. Removed — §3b",
    ),
    "bidnet": Verdict(
        UNREADABLE, source="https://www.bidnetdirect.com/public/info/terms",
        checked_on="2026-08-07",
        note="robots.txt disallows /public/info/, where the terms live, so the "
             "document that decides the question cannot be fetched without "
             "breaking the rule the fetch would rely on — docs §3a",
    ),
    "jaggaer": Verdict(
        UNREADABLE, source="https://www.jaggaer.com/terms-of-use/",
        checked_on="2026-08-07",
        note="the terms page answers 403 to any non-browser client. NOTE: an "
             "adapter shipped before this table existed and is grandfathered "
             "below; this is debt, not permission",
    ),

    # -- shipped before this table; terms not located --------------------
    "opengov": Verdict(
        UNCHECKED, checked_on="2026-08-07",
        note="opengov.com/terms-of-service/ serves a marketing page with no "
             "restrictions section; the operative document was not found",
    ),
    "vendorlink": Verdict(
        UNCHECKED, checked_on="2026-08-07",
        note="myvendorlink.com/terms redirects to the login page",
    ),
    "workday_sourcing": Verdict(
        UNCHECKED, checked_on="2026-08-07",
        note="Workday's website terms 404 at the documented path; the public "
             "portal itself carries no link to any terms",
    ),
}

#: Adapters that shipped before this table existed and whose terms are not
#: settled. Frozen on purpose: the test asserts this set never grows, so the
#: debt is visible and bounded while a new adapter still has to clear the bar.
#:
#: `jaggaer` is here rather than removed because four Florida state
#: universities publish their solicitations there and nowhere else public, and
#: the same is not true of DemandStar or Vendor Registry, whose agencies post
#: elsewhere too. That is a reason to prioritise reading its terms, not a
#: reason to treat 403 as consent.
GRANDFATHERED = frozenset({"opengov", "vendorlink", "workday_sourcing", "jaggaer"})


def verdict_for(platform: str) -> Optional[Verdict]:
    return TERMS.get(platform)


def may_build_adapter(platform: str) -> bool:
    """Whether a *new* adapter for this platform is allowed to exist."""
    v = TERMS.get(platform)
    return bool(v and v.status in ALLOWS_NEW_ADAPTER)
