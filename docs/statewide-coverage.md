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

> **This decision was re-made, wrongly, on 7 Aug 2026, and reverted the same
> day.** An adapter was built against exactly that endpoint
> (`api.demandstar.com/contents/agency/search?id=<guid>`), shipped 14 agencies,
> and was merged as PR #43 before anyone noticed this section existed. The
> mistake was procedural, not technical: the reasoning started from
> `research/FL_PROCUREMENT_RESEARCH.md`, which frames DemandStar as a *coverage*
> question — "useful as fingerprinting oracles, not as data sources" — and that
> reads like a judgement about value, which new evidence can overturn. This
> file, where it is recorded as a **terms** decision already taken, was never
> opened.
>
> The clause is still live; verified verbatim against
> `network.demandstar.com/terms-of-use/` on 7 Aug 2026, at (I) in the
> prohibited-conduct list. Robots.txt is not the test here and never was:
> DemandStar serves `User-agent: *` with no rules at all, so a robots check
> returns "allowed" and means nothing. **An open endpoint is not permission.**
>
> If a future change wants to revisit this, the bar is a change in *their*
> terms or a paid plan — not a fresh reading of how easy the endpoint is.

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

### 3a. BidNet Direct: same answer, arrived at differently

11 Florida agencies fingerprint strong on BidNet, 10 of them covered nowhere
else — Palm Beach and Hernando school districts, Highlands County, five
colleges, Bal Harbour, Medley. Its `/florida` page lists 85 open solicitations
without a login. Not building against it is a real cost, and it is still the
right call.

Three things decide it, in order of weight:

1. **Their terms are unreadable to us.** `robots.txt` disallows
   `/public/info/`, which is where the terms of use live. So the one document
   that settles the question cannot be fetched without breaking the rule the
   fetch would be relying on. After §3, the test is the terms, not the
   endpoint — and here the test cannot be run.
2. **They block AI crawlers by name**, including `anthropic-ai`, `ClaudeBot`
   and `Claude-Web`, alongside GPTBot, CCBot, PerplexityBot and
   Google-Extended, each with `Disallow: /`. This crawler is none of those: its
   product token is `sf-procurement-scout`, so under RFC 9309 the `*` group
   governs it, and that group permits `/florida/...` at `Crawl-delay: 5` while
   forbidding paging. The letter allows it. The intent is not ambiguous.
3. **BidNet sells subscriptions.** The free surface is deliberately bounded,
   which is the fact pattern platforms enforce against — the same reasoning
   that governs DemandStar in §3.

Point 1 alone would be enough. A judgement call made on evidence one cannot
read, in favour of the party that gains from reading it that way, is not a
judgement call.

What is recorded instead: the 10 uncovered agencies are **catalog entries**, so
the gap shows in the app as "this agency posts here, go look" rather than as
silence. That is what the catalog is for.

Note the contrast with Bonfire, Ionwave and Jaggaer in `ROBOTS_OVERRIDES`. Those
serve a blanket `Disallow: /` and are crawled anyway, under a documented
exception. The difference is not how permissive robots.txt is — it is that for
those three the *terms* were read and bind on registration rather than on
reading. Here they could not be read at all.

### 3b. Vendor Registry: found by the guardrail, on its first use

Building the terms table in `src/terms.py` meant reading the terms of every
platform this build fetches, which nobody had done in one pass. Vendor
Registry's §1.1 says:

> You may not copy or download any content from the Site or Services except
> with the prior written approval of Vendor Registry.

under a browse-wrap that opens *"YOUR USE OF THIS SITE SHALL BE DEEMED TO BE
YOUR AGREEMENT TO ABIDE BY EACH OF THE TERMS."* It binds on reading. Note the
contrast with Ionwave, whose terms are in `ROBOTS_OVERRIDES` precisely because
they bind on *registration* and say nothing about automated access — the same
question, opposite answers, and the difference is only visible if you read both.

The archive-only adapter downloaded 1,098 past solicitations across five
Florida buyers. That is squarely inside the clause. The adapter, its tests and
its five configured sources are removed.

It cost something. Those years back-filled recurrence for the OpenGov and
Bonfire feeds that replaced Vendor Registry at those agencies — 10 of 22
currently open bids there carried a prior cycle because of it. The agencies
themselves are not lost: all five post on platforms this build already reads.

### 3c. Catalog recovery: asking the agency instead of the platform

§3, §3a and §3b each end the same way — the platform is off limits, the agencies
become catalog pointers, the gap stays visible. What none of them did was ask
the obvious follow-up: **do these agencies post anywhere else?** Most public
buyers advertise the same solicitation in more than one place, and the answer
was never looked for.

It could not have been, as it happens. `fingerprint_agency` stops at the first
strong signature, because the question it was built for is "what does this
agency run". The moment a purchasing page said VendorLink, the question was
answered and the CivicPlus board at `/Bids.aspx` one URL away was never
fetched. `scripts/recover_catalog_coverage.py` asks the narrower question —
"does this agency *also* run something we may read" — by passing `avoid` to the
fingerprinter, which makes a forbidden platform a match that does not stop the
search. The forbidden platform is kept in `also`, never dropped: an agency that
double-posts is a fact worth recording.

Nothing in it reads a forbidden platform. Every fetch goes to the agency's own
website, which is `AGENCY_SITE` in `src/terms.py`.

**Run over all 120 catalog pointers (2026-08-10).** First, what the pointers
turned out to be:

| Triage | pointers | What it means |
|---|---:|---|
| already read live by a bid adapter | 26 | the pointer is redundant — we cover this agency today |
| no roster entity | 23 | co-ops, chambers, sheriffs, clerks: no website on file to read |
| worth re-reading | 71 | resolving to **65** distinct agencies — a few platforms list one buyer as two boards |

Coverage is checked twice, on two different keys, because one key was not
enough. Matching the platform's agency name against a configured source's name
finds 23. The other 3 are found only by *identity*: take what the entity's
fingerprint says it runs, turn it into the tenant the generator would use, and
look for that. `og_pcsb` reads Pinellas County School District and says so
nowhere a string match can see — the OpenGov discoverer names its sources after
the tenant, not the buyer. Central Florida Expressway (`cfxway`) and Hernando
County (`hernandocounty`) hid the same way.

Then what re-reading those 65 agency websites found:

| Outcome | agencies | What it means |
|---|---:|---|
| named a platform we may read | 2 | **1** of them new: New Smyrna Beach |
| a lead — no adapter for it | 3 | 2× BidSync, 1× a self-hosted board needing a page reader |
| confirmed nowhere but the forbidden platform | 20 | the irreducible gap: 9 VendorLink, 10 BidNet, 1 DemandStar |
| site unreadable today | 40 | 15 no procurement link, 11 no signature, 7 WAF, 4 JS shell, 3 network |

**New Smyrna Beach** — its own CivicPlus board — is the single new live source
out of 65 agencies. The other of the 2 is Flagler County School District, a
weak match on OpenGov: a lead, not a tenant.

The honest headline is the first table, not the second. **The gap was never 120
agencies; a fifth of it was already covered and nobody had checked.** One new
source is a fair measure of how much double-posting actually survives once the
already-covered agencies are excluded: most of the rest are small bodies whose
only board is the one we cannot read, and 40 sites this build could not read at
all on the day.

That last row is a queue, not a verdict. A WAF-blocked homepage today is
readable next month, so this is worth re-running with the quarterly
fingerprint sweep rather than treating as settled.

**The embed bug, and what it was actually hiding.** Two recoveries pointed at
`procurement.opengov.com/portal/embed` — the iframe an agency drops into its
own page. The `/portal/(...)` pattern read `embed` as the tenant, minted a
source whose board 404s, and — the part that mattered — *claimed* the `embed`
identity, so every later agency whose fingerprint landed on an embed URL was
skipped as "already configured" with nothing in the report to say so. Five
were. Same shape as the match-on-host-alone bug already recorded in
`sources_from_fingerprints.py`, one level down, and guarded by `NON_TENANTS`.

Reading those five properly was the obvious follow-up, and it is worth writing
down that **it recovered nothing.** The tenant is in the URL after all, one
segment deeper — `/portal/embed/pcsb/project-list` — and `portal_url_for` was
truncating it before anything downstream could see it. Both patterns now accept
the embed form. All five tenants (`bartowfl`, `districtgov`, `cityoftampa`,
`cfxway`, `pcsb`) turned out to be **already configured live**, found earlier by
`scripts/discover_opengov_tenants.py`, which reads OpenGov's own tenant list and
never needed a fingerprint.

So the fix buys no coverage. What it buys is a report that says "already
configured" rather than "the URL does not name the tenant" — a closed question
instead of an open one, and five fewer agencies that look like unfinished work.
That is the same lesson as the section above, one more time: the gap was
smaller than the pointer count, and most of what looked missing was already
covered by a route nobody had cross-checked.

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

**Phase 3 — done.** FACTS, FDOT and Jaggaer all have their own sections below;
the Florida Sheriffs Association co-op came off this list without an adapter,
also below. What is left of the original plan is the bid mailbox, which needs
platform registrations and a real inbox rather than code.
OpenGov, VendorLink and Ionwave were all on this list and are now done, and all three came off it the same way: the route
that had been checked was not the route that is public. OpenGov's list endpoint
is a POST on the API host, not a GET on the portal. Ionwave was filed here as
"needs a session-cookie handshake" — it needs no cookie at all; `/` redirects
to a login and `SourcingEvents.aspx?SourceType=1`, which the login page itself
links to, does not. Probe the whole surface before concluding a platform needs
a browser or an account.

Vendor Registry also came off this list, but the other way — it is **not worth
an adapter**, and that is a finding rather than a deferral. See below.

### FACTS — the state contract register

`src/sources/facts.py`. Every executed state contract, posted under
**s. 215.985(14)** within 30 days of execution with its parties, dates,
procurement method and total compensation. The same statute at s. 215.985(2)(d)
requires the site be "easily accessible to the public at no cost" and not
"require the user to provide information" — an anti-registration wall written
into law. No robots.txt; the search page's own terms are a scope note with
nothing about access.

**12,377 contracts with a live end date, 10,192 expiring within a year**, across
31 agencies. The whole local register — every Bonfire tenant combined — is 4,403.

Three things about getting it:

- **The search pages ten rows at a time**, which for 63,515 matching contracts
  would be 6,352 requests. There is a **Download Results** postback that returns
  the entire result set as CSV: 52 columns, ~53 MB, about fifty seconds. So a
  refresh is two POSTs. It runs from `python -m src.cli contracts --refresh`, on
  a weekly cadence, never from the scheduler.
- **The date fields are begin ≥ B and end ≤ E**, not a window on the end date —
  asking for the next twelve months returns 17 contracts statewide, which is the
  number that both start and finish inside a year. There is no way to ask the
  server for "ending after today", so the already-expired rows are dropped
  locally and `DEFAULT_BEGIN_YEAR` bounds the download. 2020 was picked by
  measuring: it loses one contract in ten thousand against 2016 and halves the
  transfer.
- **`New End Date` supersedes `Original End Date`, on 21% of rows.** An
  amendment writes the new column and leaves the old one alone, so reading the
  original raises a rebid alert for a date already renegotiated.

Two data-quality facts worth knowing: 516 contract ids are used by more than one
agency, so the key has to carry the agency; and 177 agency/id pairs appear twice
under a truncated FLAIR id, 148 of them differing, usually with one copy missing
the vendor and sometimes carrying an older end date. The more complete record
wins — a named vendor first, then the later end date.

`Total Amount` and `Method of Procurement` are both carried, and they are what
make ten thousand expiries usable: the digest leads with the $7.1B Medicaid
managed-care contract ending 30 September rather than a $4,000 canine agreement
ending the same week. 82% of rows carry an amount; 100% carry a method, and the
method is the second half of the signal — "Agency Request For Proposals" is an
opening, "Non-competitively awarded grants" mostly is not.

Storing them needed the schema to become additive in fact rather than in
comment. `create_all` makes missing *tables* and ignores missing *columns*, so
adding one to `contracts` would have raised `no such column` on every database
that already existed. `src/db/engine.py` now runs a guarded
`ALTER TABLE ... ADD COLUMN` for nullable columns the models declare and the
live tables lack — additive only, idempotent, and it refuses a NOT NULL column
with no default rather than half-applying one.

### Florida Sheriffs Association — already covered, by VendorLink

The research scores the FSA co-op as an RSS feed worth two hours. The feed at
`flsheriffs.org/purchasingprogram/feed/` is real and returns
`application/rss+xml`, which is what got it verified — but it is a WordPress
*product* catalog of ten equipment categories, every one dated October 2024. It
is not a bid feed.

FSA's actual solicitations are bid through VendorLink, which its own
announcement letter says outright: *"All bidders must submit a complete bid
package online via the VendorLink bid system by September 1, 2026."* And
`vl_296` has been in this build since the VendorLink sweep — it returns
`FSA26-EQU24.0 Equipment` open, due 2 Sep 2026, questions closing 24 Jul, plus
13 archived. The duplicate `pp_flsheriffs` catalog pointer is already
suppressed. There is nothing to build.

### Watching for migrations

Re-running the fingerprint sweep does not find one. It is additive by design
and skips everything already swept, so a re-run prints `to do now 0`. Use:

```bash
python scripts/fingerprint_agencies.py --recheck
```

which re-reads only the entities already placed on a platform — 183 of 815 —
and diffs. First run, 7 Aug 2026: **178 unchanged, 2 moved, 3 no longer
readable**. Both moves were St. Johns County and its Anastasia Sanitary
District, off DemandStar and onto **Workday Strategic Sourcing** — the same
platform UNF left Jaggaer for. Three Florida agencies on a platform this
document had never heard of, now a fingerprint signature and two catalog
pointers.

Workday has two hosts one word apart and opposite in what they permit, and
that distinction is the whole story — see its section below. Both tenants are
now fetched live.

The mode reports "known → unknown" separately from a real move. Palm Coast and
Sanford went unreadable on that run and are almost certainly transient; folding
them in with migrations would cry wolf every sweep.

### Workday Strategic Sourcing — two hosts, one of them ours to read

Nothing in the research names this platform. It turned up twice in a week: UNF
left Jaggaer for it on 1 July 2026, and the first `--recheck` sweep caught
St. Johns County and its Anastasia Sanitary District leaving DemandStar for it.

**The two hosts matter more than anything else here.**

| host | what it is | robots | read? |
|---|---|---|---|
| `<tenant>.us.workdayspend.com` | authenticated supplier app | `Disallow: /` | **never** |
| `<tenant>.public-portal.us.workdayspend.com` | public opportunity portal | none at all | yes |

They are one word apart. Every row's `bidUrl` points at the *first* one, so it
is carried as a link for a person's browser and never fetched — handing someone
a URL is not the same act as crawling it. No override is needed or taken.

The portal is a Vite/React SPA on Apollo GraphQL, and the route took five steps
to work out and two requests to use: the shell names its entry bundle, a lazy
chunk holds `BidOpportunitiesQuery`, its AST gives the field set and a non-null
`input: EventInput!`, Apollo posts to `/graphql` on the same host — and **the
CSRF header is `X-XSRF-TOKEN`**. `X-CSRF-Token` and `X-Csrf-Token` both return
`422 Unprocessable Content` with an empty body, which reads as a malformed
query rather than a missing header. The token is the `_pp_xsrf` cookie,
URL-decoded, set by any page load. Introspection is disabled, so the field set
comes from the app's own query rather than the schema.

Two filters keep the board honest. `requestType: "TEST"` events are dropped —
St. Johns County's portal currently holds exactly one record, *"Testing
Solicitation for Suppliers"*, from their migration. And `restricted: true`
means invitation-only, which is not an opportunity. Both are counted, so a
tenant that published only a test says so rather than looking broken.

### Jaggaer — three universities, and the one the research named has left

The research gives `bids.sciquest.com/apps/Router/PublicEvent?CustomerOrg=UNF`
and says FIU is "at `bids.fiu.edu`". The URL template is right; the tenants
were not.

- **UNF has left.** Its own page carries a dated notice: *"Beginning July 1,
  2026, all University of North Florida solicitations will be posted through
  the University's new Bid Portal."* Both live tabs return no events. It moved
  to **Workday Strategic Sourcing** — a platform this document had never heard
  of, now a fingerprint signature so the next move is found by the sweep.
- **`bids.fiu.edu` is FIU's own procurement page**, not a Jaggaer portal. FIU
  does have a Jaggaer tenant, but it answers as "myFIUmarket System
  Administrator" and carries only an archive.
- **FSU is the live one, and the research never mentions it** — seven open
  solicitations on 7 Aug 2026, found by fingerprinting `procurement.fsu.edu`.

Probing all twelve state universities' tenant codes gives the real map. Seven
answer `400 System Error` and are not tenants at all (UF, UCF, FGCU, UWF, FAMU,
Florida Poly, New College).

| tenant | open | closed | awarded | |
|---|---:|---:|---:|---|
| FSU | 7 | 20 | 20 | configured |
| FAU | 0 | 20 | 20 | configured — between solicitations |
| FIU | 0 | 16 | 20 | configured |
| UNF | 0 | 20 | 20 | left the platform; **not** configured |
| USF | 0 | 0 | 0 | empty tenant; **not** configured |

UNF is deliberately absent. A source that can only ever return zero reads as a
quiet agency rather than a departed one — the mistake this project has made
three times.

`bids.sciquest.com` serves the same blanket `Disallow: /` Bonfire and Ionwave
do, and it is in `ROBOTS_OVERRIDES` with the same reasoning: these are Florida
public universities' competitive solicitations, and the records are the
university's.

### FDOT — the letting host was the wrong host

`bidletting.fdot.gov/LettingResults`, which the research names, is what its name
says: bid openings that have already happened, back to August 2024. No
advertisements.

Open work is at **`pdaexternal.fdot.gov/Pub/AdvertisementPublic/`**, split by
procurement path (`PS` professional services under the Consultants' Competitive
Negotiation Act, `D-B` design-build). Both hosts are crawlable — `bidletting`
serves `Allow: /`, `pdaexternal` serves no robots.txt.

`src/sources/fdot_ads.py` reads it. Live on 7 Aug 2026:

| | current | planned | in selection | all |
|---|---:|---:|---:|---:|
| Professional Services | 14 | 124 | 111 | 276 |
| Design-Build | 1 | 0 | 10 | 13 |

**The planned ads are the reason to bother.** FDOT publishes a Notice of
Planned Advertisement months before the advertisement itself — 124 of them for
professional services, with projected deadlines running into 2027. Nothing else
in this build sees work that early, and they arrive as `upcoming` so they never
sit on the open board as though they could be bid today.

Getting there takes four hops to find and two to use. `/Home/Config` publishes
`RestApiUrl: https://pdaextapi.fdot.gov/api/`; the Angular bundle builds
`AdvertisementPublic/GetAllNoticeDetails`; an HTTP interceptor copies a
page-scoped `akey` into an `Authentication` header — without it the API answers
**401 with an empty body**, which reads as a broken endpoint rather than a
missing header; and the page mints that `akey` into `window.AllAdInitParams`.
So a fetch is one page load for a fresh token and one API call. Empty
`DistrictCode` is statewide and `PageView=A` is every status, so one call does
the work of thirty-two.

One thing does not fit the schema. Every ad carries an FDOT district, and a
district is several counties — District 4 is Broward, Palm Beach, Martin,
St. Lucie, Indian River and Okeechobee. `county` holds one value, so it stays
`statewide`, the district goes in `department`, and the district's counties are
added to the keywords so a search for "broward" still finds its 24 ads.

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
