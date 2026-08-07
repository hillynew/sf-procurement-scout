# Getting every Florida agency, without paying per county

DemandStar charges per county because it resells something that is, almost
everywhere, already public. Florida law is on our side here: Rule 60A-1.021,
F.A.C. requires competitive solicitations to be posted electronically where
anyone can see them, and Chapter 119 makes the underlying records public. What
DemandStar sells is not access to the information. It is the convenience of
having it in one place.

So the job is not to find a back door. It is to go to the ~10 places agencies
actually post, instead of the one place that aggregates them and charges for it.

This document is the map: what each platform is, whether we can take it for
free, and what it costs when we cannot.

---

## The short version

| | |
|---|---|
| Florida public entities that buy things | ~2,600 (67 counties, 411 cities, 67 school districts, 40 colleges/universities, ~2,000 special districts) |
| Platforms they post on | ~10 cover the overwhelming majority |
| Free and already working | MyFloridaMarketPlace, OpenGov, Bonfire, CivicPlus, Bid Express, SAM.gov, VendorLink, Ionwave |
| Free but needs a vendor account | Public Purchase, BidNet Direct, Periscope |
| Worth paying for | VendorLink ($175/yr statewide), Euna Pro ($50/yr) |
| Do not scrape | DemandStar — their terms explicitly prohibit it |
| **Realistic all-in cost** | **$225–$400/yr, versus $60/county/yr on DemandStar alone** |

Sixty-seven counties on DemandStar's county plan would be about $4,000 a year,
and would still miss every agency not in their network.

---

## 1. What is already built and working

### MyFloridaMarketPlace — the single biggest free win

The state's Vendor Information Portal is the mandatory posting point for all
state-level procurement. One adapter, no login, no API key, no subscription,
and it covers:

- every executive-branch agency (DOT, DOH, DCF, DEP, Corrections, FDACS…)
- all 12 state universities
- ~31 state colleges
- all 5 water management districts
- the Legislature, State Courts, and a long tail of authorities

**Live right now: 109 open biddable solicitations.** Plus ~12,800 closed ones,
which is a genuine historical backfill if we ever want to study who wins what.

Three traps in that portal, all now handled:

- **It has no working pagination.** `pageNumber` is accepted and silently
  ignored, and `pageSize` is capped at 100 no matter what you send. A scraper
  that trusts the paging contract quietly stops at 100 and reports the rest as
  nonexistent. We slice by advertisement type instead, which sums exactly to the
  reported total.
- **Its rate limiter returns HTTP 200 with an HTML page.** Not a 429 — a normal
  success response containing the web page instead of data. Read carelessly,
  that parses as "no bids today." We detect it and raise instead.
- **Its attachments content-negotiate on `Accept`.** Ask for a solicitation PDF
  with the browser-ish `text/html,...` header the shared session sends, and the
  portal returns 1.1 KB of `index.html` — with a 200. Ask with the XHR-style
  `application/json, text/plain, */*` its own SPA uses and the same URL returns
  the 1.9 MB PDF. Nothing else in the header set matters; this was bisected
  against a live attachment. Sources declare the quirk via
  `SourceAdapter.document_headers`.

All three are the kind of failure that does not look like a failure, which is
exactly the kind worth writing down. The third was the most expensive: it made
every state bid look like it had no documents, so deep dives on them read the
listing alone and concluded — wrongly — that the package had to be fetched by
hand from VIP.

### OpenGov — 91 Florida agencies, and the lesson about which host you probe

This platform was in the "needs a vendor account, and a headless browser to get
past Cloudflare" column right up until someone checked the second host.

`procurement.opengov.com/portal/*` is the Cloudflare-challenged SPA, and it does
403 a scraper — which is where the write-off came from. The API that SPA calls,
`api.procurement.opengov.com`, has no challenge, no auth and no cookie. The
platform publishes its own tenant directory there, so the Florida source list is
derived rather than curated: `scripts/discover_opengov_tenants.py` reads
`/api/v1/government`, filters to Florida and active, and writes
`config/sources.opengov.yaml`. **91 active Florida tenants**, ~14,000 projects
between them — Orange County, Escambia, Tampa, Pinellas, Sarasota, Volusia,
St. Petersburg, Collier, Orlando, GOAA, JAXPORT, JTA, and several school
districts.

Two things to know:

- **The project list is a POST.** A GET of the same path returns 404, and a 404
  reads as "this tenant has no public portal." That single wrong verb is most of
  why the platform looked closed.
- **Documents are pre-signed S3 URLs, live in the anonymous response**, carrying
  `X-Amz-Expires=72000`. Twenty hours from when the URL was minted, not from
  when it is read: it is a fetch-now token, not an address. Verified end to end
  — one Orange County project returned 21 attachments and the packet downloaded
  as a 318 KB `application/pdf` with no session at all.

The tenant list is only as current as its last run. Three Florida migrations
were observed during a single week of research, so re-run the discovery script
weekly; `--check` reports drift without writing.

A note on what this displaced: six of the tri-county CivicPlus sources
(Davie, Hollywood, Pembroke Pines, Homestead, Dania Beach, Lauderdale Lakes)
had been returning zero bids because those cities moved to OpenGov. The scout
was reporting them as healthy and empty rather than as migrated.

### Bonfire — 23 Florida agencies, free JSON

Bonfire publishes open opportunities through an unauthenticated JSON endpoint.
There is no directory of which agencies use it, so `scripts/discover_fl_agencies.py`
probes candidate subdomains generated from the place names in `src/fl_geo.py`.
That sweep found 23 live Florida tenants, 19 of which were new — including
Hillsborough County (31 open), Pasco County, Marion County, Indian River,
Panama City, St. Pete Beach, Lee County Schools, St. Lucie Schools, and PSTA.

One caveat worth knowing: Bonfire's `robots.txt` says `Disallow: /`. That is a
blanket crawl prohibition covering their whole site. The counter-argument is
that these are public postings an agency is legally required to publish, we
fetch a handful of records at low rate, and it is the agency's data rather than
Bonfire's. It is a real tension, not a settled question, and it is your call.
Rerunning the discovery sweep frequently is the part I would avoid — it is a
thousand requests to find a handful of tenants, so run it monthly at most.

That call is now written down where it can be seen and reversed rather than
left implicit in the code. `src/netpolicy.py` honors robots.txt everywhere, and
`ROBOTS_OVERRIDES` is the single table of hosts crawled anyway, each with its
reason spelled out. Bonfire is the only entry. Setting
`SF_SCOUT_STRICT_ROBOTS=1` drops the table and obeys robots everywhere — at the
cost of all 30 Bonfire tenants, Broward County and Hillsborough among them.
The point of the table is that turning the exception off is one variable, and
that nobody has to read the crawler to find out it exists.

**Sixty seconds of policy, for reference.** Every Florida host the scout reads
was checked on 6 Aug 2026:

| Host | robots.txt | Effect |
|---|---|---|
| `*.bonfirehub.com` | `Disallow: /` | overridden, reason recorded |
| `dms.myflorida.com` | `Disallow: /` bar search engines | **refused outright** — the data is on VIP anyway |
| `vendor.myfloridamarketplace.com` | none (404) | unrestricted |
| `api.procurement.opengov.com` | none (404) | unrestricted |
| `flsheriffs.org` | `Crawl-delay: 10` | honored — 10s between requests |
| `www.myvendorlink.com` | `Allow: /external/` | our path is explicitly allowed |
| `vrapp.vendorregistry.com` | blocks Zoominfobot only | unrestricted for us |
| CivicPlus cities | path rules, none covering `/Bids.aspx` | unrestricted |

### CivicPlus, Bid Express, SAM.gov

Already wired. CivicPlus is the platform most Florida cities run their bid board
on (28 configured), Bid Express has the most permissive robots policy of any
platform in this space, and SAM.gov is a documented free federal API.

---

## 2. The bid mailbox — for portals that only tell registered vendors

Several platforms show nothing useful without a login: Public Purchase (228
Florida agencies), BidNet, Periscope. Registering is free.
The catch is that a human then has to read a lot of email.

The clean version of "get every deal from every agency" is therefore:

**Register Nature Guard once per platform, truthfully, with a dedicated mailbox
per platform per agency — then parse the notification emails automatically.**

This is the part of the plan I am most comfortable with legally. The emails are
sent to us, on infrastructure we control. No terms-of-service clause about
robots or crawlers governs what we do with mail already in our own inbox.

### How it should be set up

1. A domain we own — `bids.natureguard...` or similar — with **Cloudflare Email
   Routing** (free, supports catch-all) forwarding to one dedicated mailbox.
2. **A unique address per platform per agency**: `pp-alachua@bids.example.com`,
   `bidnet-miami@…`. This gives us the source of every notice for free, before
   parsing a single byte.
3. **Do not use Gmail plus-addressing** (`you+demandstar@gmail.com`). A real
   share of government vendor forms reject the `+` character outright, and some
   ERP vendor-master systems strip it. Subdomain addressing gets the same
   tagging benefit and is accepted everywhere.
4. Read it with the **Gmail API** (push notifications via Pub/Sub, with polling
   as a fallback), not IMAP. Archive the raw message before parsing — we will
   change parsers repeatedly and reprocessing from raw is the only sane way.
5. **Per-sender parsers, routed on sender domain plus a template fingerprint.**
   When a platform redesigns its email, the fingerprint changes and we get an
   alert instead of silently wrong data.
6. **A liveness monitor per source.** This is the one I would not skip. These
   emails failing is completely silent — a spam-folder classification looks
   exactly like "no bids posted this week." If a source that normally sends 5 a
   week sends none for two weeks, something should shout.

The repo already has an `email_alerts` adapter as the landing point for this.

### Registration is a real business representation

Florida vendor registrations collect FEIN, W-9 data, and sometimes sworn
statements — public-entity-crimes affidavits, scrutinized-companies
certifications under §287.135, E-Verify attestations. Register the real
company with real details. Creating accounts in bulk, or with fabricated
business identities to work around a per-account limit, moves this from a
terms-of-service question to a false-attestation-to-a-government-agency
question. Not worth it, and not necessary — the free tiers plus $225 of
subscriptions get us there legitimately.

---

## 3. DemandStar: pay or skip, do not scrape

DemandStar's terms of use prohibit, in explicit language, using "any robot,
spider, data scraping, crawler or other extraction tool" against their pages.
Their public agency pages do expose a JSON endpoint that works without
authentication, and it would be easy to use. I have deliberately not built
against it.

The practical reason matters more than the legal one: this is the fact pattern
platforms actually enforce against, and the remedy is cheap for them (kill the
account, block the IP) and expensive for us — including losing the legitimate
free-tier notifications we would otherwise keep.

The alternatives, in order:

1. **Most DemandStar agencies double-post.** Cities post to their own CivicPlus
   board; counties post to their own portals. We scrape the agency, not the
   reseller.
2. **The free tier gives one agency's alerts.** Point it at whichever single
   agency matters most and route it to the bid mailbox.
3. **$60/yr per county** for the two or three counties where we actually bid.
   That is real money for real coverage, and it is a fraction of statewide.

## 4. What is worth buying

| What | Cost | Why |
|---|---|---|
| **VendorLink** statewide | **$175/yr** | Florida-native, and the cheapest statewide coverage that exists anywhere. If we buy one thing, this is it. |
| **Euna Supplier Network Pro** | **$50/yr** | AI matching across 3,000+ agencies, and it is the sanctioned way to get Bonfire coverage beyond what we probe. |
| DemandStar county plan | $60/yr each | Only for counties where we genuinely bid. |

Under $250 a year covers what DemandStar alone would charge roughly $4,000 for.

---

## 5. Where coverage stands

Statewide fetch, run today, all 62 live sources, zero failures:

- **366 open opportunities** from **55 agencies**
- **13 counties** with live bids, plus statewide
- **358 sources configured**, spanning **52 of 67 counties**

The 15 counties with no source yet are Florida's smallest and most rural —
Lafayette, Liberty, Union, Glades, Dixie, Calhoun, Franklin, Gulf, Hamilton,
Holmes, Levy, Madison, Washington, Bradford, Okeechobee. Between them they hold
roughly 1% of the state's population and buy very little competitively. They are
worth doing last, and probably by standing public-records request rather than by
building a scraper for a county that posts four bids a year.

### The phases

**Phase 1 — done.** MyFloridaMarketPlace, Bonfire statewide sweep, statewide
geography, agency discovery, 358 sources.

**Phase 2 — the bid mailbox.** Domain, catch-all, Gmail API reader, per-sender
parsers, liveness monitoring. This unlocks Public Purchase's 228 agencies and
BidNet in one move, and it is the highest-value next step by a distance.

**Phase 3 — the remaining platforms.** Jaggaer for the universities, FDOT's
letting pages for construction. OpenGov, VendorLink and Ionwave were all on
this list and are now done, and all three came off it the same way: the route
that had been checked was not the route that is public. OpenGov's list endpoint
is a POST on the API host, not a GET on the portal. Ionwave was filed here as
"needs a session-cookie handshake" — it needs no cookie at all; `/` redirects
to a login and `SourcingEvents.aspx?SourceType=1`, which the login page itself
links to, does not. Probe the whole surface before concluding a platform needs
a browser or an account.

Vendor Registry also came off this list, but the other way — it is **not worth
an adapter**, and that is a finding rather than a deferral. See below.

### Vendor Registry — checked, and deliberately not adapted

Its current list is not a live feed. `/Bids/View/BidsList?BuyerId=<guid>`
renders server-side and tells an anonymous caller *"Currently, <agency> has no
open solicitations."* Fifteen buyers were checked across five states on
7 Aug 2026, including Williamson County TN — one of the platform's own flagship
customers. Every one returned zero. Fifteen agencies do not simultaneously have
nothing out for bid.

The archives agree from the other side: every buyer's expired list stops
between October 2023 and January 2026, clustered at the recent end. That is a
platform-wide freeze, not fifteen coincidences. mdf commerce owns Vendor
Registry *and* BidNet Direct, and the Florida tenants have moved between them:

| Agency | Last posting on Vendor Registry | Posts now on |
|---|---|---|
| Santa Rosa County | Oct 2023 | OpenGov — 11 open today, fetched live here |
| Central Florida Expressway | Jan 2026 | OpenGov — 4 open today, fetched live here |
| Indian River County | Jun 2025 | Bonfire — fetched live here |
| City of Sebring | Jan 2026 | BidNet Direct — its own vendor page links there |
| Okeechobee County | Jul 2025 | unknown; the county's site refuses us (403) |

An adapter reading the current list would report every one of them healthy and
empty, forever, while their bids arrived elsewhere. That failure has already
cost this project three times — Solid Waste Authority moving to Bonfire, six
CivicPlus cities that had gone to OpenGov, Deerfield Beach moving to Ionwave —
and each time the tell was the same: a page that still resolves and still
returns nothing.

**What was built instead is archive-only.** The expired lists are public,
complete and unauthenticated — 1,098 past solicitations across the five Florida
buyers, each with a type, reference number, deadline and its own detail page.
`src/pipeline/history.py` joins past to open on agency name, so those years
back-fill recurrence for the OpenGov and Bonfire feeds that replaced them.
Measured: 10 of 22 currently open bids across Santa Rosa, CFX and Indian River
now carry prior cycles, one of them reaching back to 2020. `fetch` returns
nothing and declares why through `empty_note`, so the source reports `empty`
rather than pretending to be a feed.

**Phase 4 — the long tail.** The ~410 cities on CivicPlus and similar CMS bid
boards, driven off the Florida League of Cities directory, and the special
districts from the state's own registry (a downloadable spreadsheet of 2,088
districts with their websites).

---

## 6. One thing to fix regardless

**The copy of this project on your Mac is months out of date.** It is still the
old Streamlit app with 12 sources. The real project — React frontend, FastAPI,
Postgres, 358 sources — only exists on GitHub. Anything done against the local
folder will be thrown away. Worth deleting it and re-cloning so there is one
copy.
