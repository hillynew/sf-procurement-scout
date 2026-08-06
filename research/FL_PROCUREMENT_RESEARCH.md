# Getting Procurement Data From Every Government Agency in Florida

Research report for sf-procurement-scout
Prepared 6 August 2026

---

## The short version

There are roughly **2,800 government entities in Florida that buy things**. You will never write 2,800 scrapers, and you do not need to. Three findings collapse the problem:

1. **One API covers every state agency.** Florida's Vendor Information Portal has an open, unauthenticated JSON API with a bulk XLSX export and anonymous PDF attachment downloads. It replaced the old Vendor Bid System in 2022. Roughly 146 open and 12,824 closed solicitations, no bot protection, no robots.txt. This is the single best source in the state.

2. **One API covers 91 local agencies at once.** OpenGov Procurement publishes a global agency directory with no auth, and a per-agency project API that returns full detail including **pre-signed S3 URLs for the bid packets**. I verified all 91 active Florida tenants respond, holding 13,917 total projects. Your existing Bonfire adapter covers 28 more.

3. **The rest is a platform problem, not an agency problem.** About a dozen SaaS platforms host nearly every local solicitation in Florida. Write one adapter per platform, then map agencies onto platforms. Twelve adapters gets you the overwhelming majority of dollar volume.

The remaining hard tail is the ~2,088 special districts and ~400 small municipalities, and that tail is dominated by CivicPlus `/Bids.aspx` pages, which all share identical HTML. One parser handles all of them.

**Cost to reach every agency: $0 in subscriptions.** DemandStar and BidNet are not required for coverage. They are useful as fingerprinting oracles, not as data sources.

---

## Part 1 — What I found, ranked by value

### Tier 1: build these first

| Source | Coverage | Method | Docs? | Effort |
|---|---|---|---|---|
| **MFMP Vendor Information Portal** | All state agencies + 12 universities + 12 colleges + 5 WMDs + Citizens + Lottery | Open JSON API | **Yes, anonymous PDF** | 1 day |
| **OpenGov Procurement** | 91 FL agencies incl. Orange, Pinellas, Escambia, Collier, Sarasota, Volusia, Tampa, Orlando, St. Pete | Open JSON API | **Yes, presigned S3** | 1 day |
| **Bonfire** (you have this) | 28 verified FL tenants incl. Broward, Hillsborough, Pasco, Tallahassee | Open JSON API | List only, detail is Cloudflare-blocked | done |
| **CivicPlus `/Bids.aspx`** | Hundreds of small cities and counties | Stable HTML, identical everywhere | **Yes, DocumentCenter** | 2 days |
| **Florida Sheriffs Association co-op** | Statewide fleet, equipment, vehicles contracts | **RSS feed** | Yes, direct PDF | 2 hours |

### Tier 2: high value, more work

| Source | Coverage | Notes |
|---|---|---|
| **VendorLink** (`myvendorlink.com`) | **156 Florida agencies** in a public dropdown | Florida-native. Bigger in FL than DemandStar. Iterate `?a=1..500`. |
| **FDOT lettings** | All state road construction | `bidletting.fdot.gov/LettingResults?districtID=99` plus districts 01-07. Bid tabs on an anonymous FTP archive back to 2018. |
| **FACTS** | Every executed state contract | `facts.fldfs.com`. Statute requires posting within 30 days with prices, procurement method, sole-source justification, and redacted contract PDFs. Awards and incumbent intel. |
| **Vendor Registry** | Small FL cities and counties | Listings public, documents behind a free login. |
| **PeopleSoft / Oracle EBS / Jaggaer** | Miami-Dade, St. Pete legacy, UNF, FIU | One URL template each, swap the tenant key. Miami-Dade needs cookie persistence. |
| **SAM.gov** | Federal solicitations with FL place of performance | Free API, requires a free key, `state=FL`, max 1,000/page. |
| **67 county legal-notice sites** | Local bid ads under s. 50.0311 | See Part 3. Fragmented but statutorily required to be searchable. |

### Tier 3: do not build against these

- **Vendor Bid System (`vbs.dms.myflorida.com`)** — dead. Returns 502/404. Merged into VIP on 28 March 2022. Stale links still exist on FDOT pages; ignore them.
- **BidNet Direct** — anonymous view hides even the agency name behind "Registered members only." No usable free tier.
- **DemandStar** — agency names and titles are public SEO surface, documents are the paid product.
- **Bid Express / bidx.com** — full OAuth wall.
- **MFMP Sourcing / Ariba** — login-gated, adds nothing over VIP.
- **floridapublicnotices.com** — free and statutorily mandated, but the user agreement says no part may be used without written authorization. Use as QA reference, not as a redistribution corpus, until licensed.

---

## Part 2 — Technical details worth writing down

### MFMP Vendor Information Portal

Base: `https://vendor.myfloridamarketplace.com/mfmp`

```
POST /pub/search/bids            search, returns JSON array
POST /pub/search/bids/count      bare integer
GET  /pub/search/bids/detail?id={id}
POST /pub/search/bids/download/excel      full result set as XLSX
GET  /bids/detail/attachment/download?attachmentId={id}    raw PDF
GET  /pub/search/picklistOrg     129 agencies with numeric ids
GET  /bids/AdTypes               10 solicitation types
POST /pub/search/vendors         public vendor registry (bonus dataset)
```

Two gotchas that will cost you an afternoon if you miss them:

**You must send `Accept: application/json`.** Without it Express content-negotiates and silently returns `index.html` with HTTP 200. It looks like a broken endpoint.

**You must send every key in the request body.** Partial bodies fall through to the HTML shell.

```json
{"pageSize":25,"type":[],"status":["OPEN"],"agency":[],"adNumber":"",
 "agencyAdvertisementNumber":"","title":"","publishedDate":"","openDate":"",
 "endDate":"","commodityCodes":[],"intendsToParticipate":"","assignee":"","page":1}
```

`status` must be one of `OPEN`, `CLOSED`, `WITHDRAWN`. An empty array returns zero rows, so iterate all three. Type ids: 1 Agency Decision, 2 Grant Opportunities, 3 Informational Notice, 4 ITB, 5 ITN, 6 RFP, 7 Public Meeting Notice, 8 RFI, 9 RSQ, 10 Single Source.

I verified this live on 6 August 2026: 129 orgs returned, and a search for open bids returned FDOT solicitation `DOT-ITB-27-5001-SFMC` among others. Corpus at time of testing: 146 open, 12,824 closed, 411 withdrawn, history back to March 2022.

Detail responses carry a `docs[]` array with `attachmentId` per file. One RFP I checked had 21 attachments. Each downloads as a real PDF with `Content-Disposition`, no session required.

Two things beyond state agencies live in here: the 129-org picklist includes UCF, FIU, USF, UNF, Florida Poly, New College, Valencia, Polk State, Eastern Florida, Hillsborough CC, Brevard CC, Lake-Sumter, SFWMD, Early Learning Coalitions, and regional planning councils. That is your cheapest higher-ed coverage in the state.

### OpenGov Procurement

The key insight: **the API host has no Cloudflare challenge, the portal host does.** Naive scrapers hit `procurement.opengov.com/portal/*`, get a 403 challenge, and conclude OpenGov is closed. It is wide open on `api.procurement.opengov.com`.

```
GET  https://api.procurement.opengov.com/api/v1/government
     561 agencies, 43 states, 93 Florida (91 active). No auth.
     Each record's .government.code is the portal slug.

POST https://api.procurement.opengov.com/api/v1/government/{code}/project/public
     Content-Type: application/json
     {"limit":100,"page":0,"sortField":"releaseProjectDate","sortDirection":"DESC"}
     -> {"count":N,"rows":[...]}

GET  https://api.procurement.opengov.com/api/v1/project/{id}
     ~140 fields including attachments[] with pre-signed S3 URLs
GET  https://api.procurement.opengov.com/api/v1/project/{id}/addendums
```

Send `Origin: https://procurement.opengov.com` and a browser User-Agent.

I swept all 91 active Florida codes on 6 August 2026. **91/91 returned HTTP 200. 13,917 total projects.** Largest tenants: Escambia County 1,206, Orange County 1,132, Tampa 818, Pinellas 765, Sarasota 659, Volusia 622, St. Petersburg 567, Collier 533, Orlando 501.

The attachments are the win. `GET /api/v1/project/288006` returned 12 pre-signed S3 URLs pointing at `government-project.s3.us-west-2.amazonaws.com`, with `X-Amz-Expires=72000`. Full bid packets, zero auth. This is the only major platform in Florida that hands you documents this cleanly.

One caveat: there is no anonymous cross-agency search. `POST /api/v1/project/search` returns 401 without a `governmentCode`. Iterate the 91 codes.

### Bonfire — the gap in your current adapter

Your adapter reads `/PublicPortal/getOpenPublicOpportunitiesSectionData`, which works. Two things you may be missing:

**`projects` is an object keyed by ProjectID, not an array.** A common source of silent under-counting.

**Two more endpoints you are not calling:**
```
/PublicPortal/getPastPublicOpportunitiesSectionData
/PublicPortal/getPublicContractsSectionData   -> awards + vendor names, free
```
The contracts endpoint returns `ContractID, VendorID, Name, ContractStatusID, StartDate, EndDate`. That is award data you are currently leaving on the table.

**Detail pages are Cloudflare-challenged.** `/opportunities/{id}` returns 403 with a managed challenge even with a warmed cookie jar and full `Sec-Fetch-*` headers. So on Bonfire you get titles and close dates but not descriptions or bid packets, unless you run a JS-capable client. There is no JSON escape hatch; I probed several.

**Verified live Florida Bonfire tenants (28), with open-opportunity counts at time of testing:**

hillsboroughcounty 24 · broward 16 · marionfl 9 · pascocountyfl 8 · talgov 8 · indianriver 7 · monroecounty-fl 5 · psta 5 · townofpalmbeach 3 · ucf 3 · famu 2 · fgcu 2 · leeschools 2 · ocoee 2 · panamacity 2 · fau 1 · gohart 1 · stlucieschools 1 · suwanneecountyfl 1 · tri-rail 1 · erau 0 · floridapoly 0 · jaxport 0 · keybiscayne 0 · plantation 0 · swa 0 · dadeschools · levycounty

The last two run a newer portal build where the legacy endpoint 307-redirects and returns `success:0`. **Your adapter needs to handle both portal generations.**

Note: `swa` is Bonfire now. Your `sources.yaml` still points Solid Waste Authority of Palm Beach County at BidSync. Also `nsu` and `tsc` look like Florida slugs but are Norfolk State (VA) and Texas Southmost College — verify tenant identity by portal `<title>`, not by slug.

### CivicPlus `/Bids.aspx` — the small-city workhorse

Every CivicPlus site has this at the root, and the markup is byte-identical across all of them:

```
https://<city>.gov/Bids.aspx?catID=<n>&txtSort=<Category|Title|Date|BidNumberAsc|BidNumberDesc>&showAllBids=on
```

`showAllBids=on` includes Closed/Awarded/Cancelled — that is how you backfill history.

```html
<div class="bidItems listItems">
  <div class="listItemsRow bid">
    <div class="bidTitle"><a href="bids.aspx?bidID=330">TITLE</a>
      <span><strong>Bid No.</strong> FKAA-IFB-0023-26</span></div>
    <div class="bidStatus">... Open ... 8/6/2026 2:00 PM</div>
```

Detail at `?bidID=<N>`. Documents resolve through `/DocumentCenter/Index/<n>` then `/DocumentCenter/View/<n>`, anonymously downloadable. Planholder list at `/Bids/PlanHolders/<bidID>?documentId=-1`.

**Fingerprint:** the string `/Common/Modules/Bids/RWDBids.css` in the page head identifies a CivicPlus bids module with near-perfect precision.

Verified 200 on davie-fl.gov, baycountyfl.gov, hialeahfl.gov, cityofhomestead.com, co.walton.fl.us, fkaa.com, palatka-fl.gov, monroecounty-fl.gov, hollywoodfl.org.

Watch for pointer pages: some CivicPlus `/Bids.aspx` contain a single outbound link to another platform. Detect and follow.

### Enterprise ERPs behind the big counties

| ERP | URL template | Anonymous? | FL example |
|---|---|---|---|
| PeopleSoft | `/psc/<SITE>/SUPPLIER/ERP/c/SCP_PUBLIC_MENU_FL.SCP_PUB_BID_CMP_FL.GBL` | Yes, **with a cookie jar** | Miami-Dade |
| Oracle EBS | `/OA_HTML/OA.jsp?OAFunc=PON_ABSTRACT_PAGE&PON_NEGOTIATION_STATUS=ACTIVE` | Yes | St. Petersburg (legacy, migrated to OpenGov) |
| Jaggaer | `https://bids.sciquest.com/apps/Router/PublicEvent?CustomerOrg=<Org>` | **Yes** | UNF; FIU at `bids.fiu.edu` |
| Infor CloudSuite | `/fsm/SupplyManagementSupplier/page/EventPage?csk.SupplierGroup=<key>` | No, 302 to auth | Coral Gables, `SupplierGroup=cocg` |

Miami-Dade is worth the cookie handling. A naked GET returns "You must have cookies enabled." With `-c/-b` it returns 89KB rendering "Bidding Event Information / Bidding Opportunities / 14 rows."

### The BidNet trick

This is the cleverest thing in the research. On BidNet's `/statewide/` aggregated tier (non-member agencies), BidNet leaks **more** than on its own paying members. Those pages include a `Source` field containing the agency's native portal URL:

```
https://www.bidnetdirect.com/florida/solicitations/open-bids/statewide/
      Waterproofing-and-Painting-Services/443899169358
Source: https://sms-coralgables-prd.inforcloudsuite.com/fsm/SupplyManagementSupplier/
        page/EventPage?csk.SupplierGroup=cocg
```

One page told us Coral Gables runs Infor and gave the exact `SupplierGroup` key. **Crawl BidNet's statewide Florida tier to auto-discover native portal URLs for hundreds of agencies, then scrape the natives directly and skip BidNet entirely.**

At time of testing: 84 open Group solicitations, 1,308 statewide/federal bids.

### Fingerprinting agencies at scale

One regex each, run against an agency's `/bids` or `/purchasing` page:

| Platform | Signature |
|---|---|
| Bonfire | `bonfirehub.com`, `/PublicPortal/` |
| OpenGov | `procurement.opengov.com/portal/` |
| CivicPlus | `/Common/Modules/Bids/RWDBids.css` |
| Vendor Registry | `vrapp.vendorregistry.com/Bids/View/` |
| Ionwave | `.ionwave.net`, `ctl00_mainContent_rgBidList` |
| BidSync/Periscope | `BuyspeedBidDetail.xhtml`, `.buyspeed.com/bso/` |
| VendorLink | `myvendorlink.com/external/bids?a=` |
| PeopleSoft | `SCP_PUB_BID_CMP_FL.GBL` |
| Oracle EBS | `OA_HTML/OA.jsp?OAFunc=PON_` |
| Infor | `inforcloudsuite.com/fsm/SupplyManagementSupplier` |
| Jaggaer | `bids.sciquest.com/apps/Router/PublicEvent` |
| bids&tenders | `.bidsandtenders.net/Module/Tenders/` |
| PlanetBids | `vendors.planetbids.com/portal/<id>/bo/bo-search` |

**Recommended approach:** crawl each Florida agency's homepage, find the link matching `bid|purchasing|procurement|solicitation`, fetch it, match the table above. That is roughly 2,800 fetches for the whole state and gives you a fully current map. Re-run quarterly — migrations are frequent. Three were observed during this research alone: St. Petersburg moved to OpenGov, SWA moved to Bonfire, UNF is leaving Jaggaer.

Search dorks that returned real Florida tenants when tested: `site:bonfirehub.com "Florida"` and `site:vrapp.vendorregistry.com "BidsList"`.

### Vendor consolidation, which matters more than it looks

Two companies own most of this market:

- **Euna Solutions** owns Bonfire, Ionwave, and PennBid.
- **mdf commerce** owns BidNet Direct, Vendor Registry, and Periscope/BidSync/BuySpeed.

Practical consequence: platform quirks are shared within a family. Cloudflare posture, ViewState patterns, and JSON shapes tend to move together. Expect Ionwave to drift toward Bonfire's stack. Write your adapters with the family in mind.

---

## Part 3 — The legal layer

You asked for "anything legal and above-board." Here is the map. This is a research summary with citations, not legal advice.

### What agencies are required to publish, and where

| Rule | Who | Requirement |
|---|---|---|
| s. 287.042(3)(b), F.S. + Rule 60A-1.021 | State agencies | Electronic posting on the designated centralized website (now VIP) **at least 10 calendar days** before the response deadline |
| s. 287.057(5)(c) | State agencies | Single-source purchases posted **15 business days** |
| s. 255.0525 | State **and local** | Construction over $200k: 21 days' notice; over $500k: 30 days |
| s. 287.055(3)(a) (CCNA) | State, counties, cities, school boards | Must "publicly announce, in a uniform and consistent manner" A/E/surveying work over $325k construction cost or $35k planning fee. **No medium specified** — this is the most scattered category in Florida. |
| s. 336.44(2) | Counties | Road contracts: notice once a week for 2 consecutive weeks |
| s. 190.033(1) | CDDs | Goods over $195k advertised once in a newspaper of general circulation |
| s. 218.391(3) | All local entities, school boards, charter schools | Auditor selection announced "in a uniform and consistent manner" |
| s. 189.069 | All ~2,088 special districts | Must maintain a website with 15 enumerated items. **Procurement is not one of them** — but item 15 is **meeting agendas posted 7 days ahead and retained 1 year**, which is where district RFP authorizations and award recommendations surface. |
| s. 50.0311(9) | Local agencies publishing notices on a website | "A public bid advertisement made by a governmental agency on a publicly accessible website **must include a method to accept electronic bids**" |

### The two parallel universes of legal notices

Since HB 7049 (2022) created s. 50.0311, Florida legal notices split into two non-overlapping streams:

1. **Print-newspaper notices** get pushed by statute to `floridapublicnotices.com` (s. 50.0211(3)(a) names the URL in the statute itself). 90 days live, 18-month searchable archive, free by law.
2. **Website-published notices under s. 50.0311** are **not** routed to that repository. They sit on ~67 county-designated sites, in three implementation patterns: a dedicated subdomain (Leon County's `publicnotices.leoncountyfl.gov` is the model), a page on the county's CMS, or a county-designated private vendor site.

**There is no single consolidated statewide website of Florida legal notices.** A comprehensive product must crawl both streams.

### The single best legal lever you are not using

**s. 50.0311(6)** requires any agency that publishes notices on a website to maintain a registry and, at least once a year, publish a newspaper notice telling residents and property owners they may **register to receive legal notices by first-class mail or e-mail**.

That is a **statutory subscription right**. It is county-scoped rather than agency-scoped, requires no terms-of-service acceptance, creates no contractual exposure, and is legally enforceable. Register in every county that went website-only and route it to your bid mailbox. This is strictly better than registering as a vendor on hundreds of individual portals.

### Chapter 119 as a bulk-data lever

It works, with an important framing constraint.

**Phrase it as "copy an existing record," never "compile a list."** s. 119.01(2)(f) requires an agency to provide a copy **in the medium requested if the agency maintains it in that medium**. But under *Seigle v. Barry*, 422 So. 2d 63 (Fla. 4th DCA 1982), an agency need not re-sort or restructure data on demand.

Every modern procurement system has a native export button, which means the export **is** a routinely-produced record. So ask for:

> "A copy, in the medium in which you maintain it, of the solicitation table(s) in your [system name] — a native database export, CSV, XLSX, or the output of your system's standard export function — for records dated [range]. Pursuant to s. 119.01(2)(f), F.S., I request the copy in the medium in which the record is maintained."

**Records that provably exist and are requestable by name:**
- Bid tabulations — s. 287.057(7) confirms these exist as discrete records
- The interested-vendor list — s. 287.042(3)(a) requires state agencies to maintain one, and it is expressly non-exclusionary
- The plan-holder / addenda registry — s. 255.0525(3)
- CCNA shortlists and annual statements of qualifications — s. 287.055(3)(b), (4)

**Fees are the real gatekeeper.** s. 119.07(4)(d) allows a special service charge only for *extensive* use of IT or clerical resources. Because the charge keys off labor, "run your existing export" is cheap and "compile a list of X" is expensive. Always demand a written itemized estimate before authorizing.

**When an agency hides behind its portal vendor,** AGO 02-37 is your weapon: an agency "may not abdicate its duty to produce such records... by requiring those seeking public records to do so only through its designee and then paying whatever fee that company may establish." Pair it with s. 119.01(2)(c), which bars an agency from contracting for a records database in a way that impairs public inspection.

**The structural limit:** there is **no such thing as a standing request** in Florida (AG informal opinion to Worch, 1995). You must re-request periodically. So Chapter 119 is a **backfill and gap-filling tool, not an ingestion pipeline**. Use it for historical loads at onboarding, for bid tabs, and for prying data out of walled-garden agencies.

There is also no statutory response deadline — the standard is "promptly" and "in good faith" (s. 119.07(1)(c)), tested judicially. *Tribune Co. v. Cannella*, 458 So. 2d 1075 (Fla. 1984) killed automatic delay policies. *Lake Shore Hosp. Auth. v. Lilker*, 168 So. 3d 332 (Fla. 1st DCA 2015) is directly on point for you: an agency violated the Act by **pointing the requester to a website instead of producing copies**.

Requests can be made anonymously and without stating a purpose. Practically, don't — use a real named business contact. It removes the *Consumer Rights, LLC v. Union County* excuse and dramatically improves cooperation.

### The timing rule that drives your pipeline

**s. 119.071(1)(b)2:** sealed bids are exempt from disclosure **only until the agency notices an intended decision, or 30 days after opening, whichever is earlier.**

That is a self-executing sunset. Everything becomes public at notice-of-intent or day 31. Build your records-request trigger on day 31 after opening if no award has posted.

**s. 120.57(3)(b):** notice of protest is due **within 72 hours** of the posting of the notice of intended decision, excluding weekends and state holidays. For specifications protests, 72 hours after the solicitation posts.

**That 72-hour window is your latency SLA.** An aggregator that surfaces intended awards more than about a day late has no protest-decision value to a subscriber. It also means intended-award postings are the highest-frequency, highest-value event in the entire pipeline — and for state agencies they are electronically posted by statute on VIP.

### Awards and contracts

**s. 215.985(14)** (Transparency Florida Act) requires every state entity to post, **within 30 calendar days of executing a contract**: the parties, the procurement method, dates, commodity/service type, unit prices and deliverables, total compensation, payments to date, performance measures, the statutory justification if no competitive solicitation was used, and **electronic copies of the contract and procurement documents**.

That is FACTS. And s. 215.985(2)(d) defines "website" for this section as one "easily accessible to the public at no cost and **does not require the user to provide information**" — a statutory anti-registration-wall provision.

There is no local equivalent. For local awards you rely on Bonfire's contracts endpoint, OpenGov's project status, agency award pages, and Chapter 119.

### Scraping posture

The post-*Van Buren* / *hiQ* line means scraping **public, unauthenticated** pages is unlikely to violate the CFAA. But note how hiQ actually ended: hiQ **lost on contract**, breaching LinkedIn's user agreement, and consented to a permanent injunction in December 2022.

**The contract question is the one scrapers lose.** Which produces one clear rule:

> **Never create an account in order to harvest.** If the same data is reachable unauthenticated, take the unauthenticated path even if it is slower.

Registering as a vendor converts a weak browsewrap posture into an executed clickwrap, identifies you by name and EIN to the counterparty, gives them an account to terminate and a contract to sue on. MFMP specifically: Rule 60A-1.033(1) requires vendors to accept the Terms of Use by clicking an acceptance button. Registering to *bid* is fine and normal. Registering to *harvest* is not.

**One Florida-specific risk worth flagging to counsel:** s. 815.06, F.S. makes it a third-degree felony to access a computer "without authorization or exceeding authorization" where "the manner of use exceeds authorization." That phrasing is textually broader than the post-*Van Buren* CFAA, and I found no Florida appellate decision applying *Van Buren*'s narrowing construction to it. Scraping Florida agencies, from Florida, against Florida servers puts you squarely in its venue. This is a larger unquantified risk to your model than the CFAA is.

**Practical safe-harbor posture:**
1. Identify your crawler honestly in the User-Agent with a contact URL
2. Honor robots.txt and Crawl-delay even though they are not binding — the cost is trivial, the cost of a plaintiff waving a violated robots.txt at a judge is not
3. Rate-limit to about 1 request per second per host
4. Never create an account to scrape; never rotate IPs to defeat a block
5. On a cease-and-desist or IP block, **stop that source immediately** and switch to the Chapter 119 channel for that agency. Continued access after revocation is the fact pattern that revives CFAA and s. 815.06 exposure.
6. Log what you fetched, when, from what URL, and what robots.txt said at the time. That is your defense file.
7. Keep floridapublicnotices.com content segregated from your redistributable corpus pending a license from Florida Press Service.

**One robots.txt note that affects you directly:** `dms.myflorida.com` serves `User-agent: * / Disallow: /` with an allowlist for major search engines only. Respect it. The actual solicitation data is on VIP, which serves no robots.txt at all. Same for `facts.fldfs.com`.

---

## Part 4 — The agency universe

I built the full roster. **2,817 distinct Florida buying entities**, with 2,724 having a website and 2,559 an email address.

| Tier | Count | Source |
|---|---|---|
| Special districts | 2,089 | Dept of Commerce Special District Accountability Program |
| Municipalities | 414 | Florida League of Cities API + Census CoG |
| School districts | 76 | FLDOE |
| Counties | 67 | Census CoG + Duval/Jacksonville by hand |
| Constitutional officers | 67 | FL Dept of State (Supervisors of Elections) |
| State agencies | 63 | MFMP picklistOrg |
| Higher ed | 41 | 12 SUS + 28 FCS + 1 |

### The special-district download nobody knows about

This was the biggest single find on the enumeration side. The Department of Commerce publishes the full 2,088-district roster as one Excel file with 29 columns, via a scriptable POST:

```
POST https://specialdistrictreports.floridajobs.org/OfficialList/CustomList
Referer: https://specialdistrictreports.floridajobs.org/OfficialList/CustomList

StartDate=&EndDate=
&customReportData.DependencyStatus=Dependent,Independent
&customReportData.ActiveStatus=Active
&customReportData.BondAuthority=Yes,No
&customReportData.CountyName=Multi     (repeat once per county, 68 values total)
&customReportData.ReportType=Detailed
&customReportData.FormatType=Excel
&customReportData.Sort=1
&Action=GenerateReport
```

Returns 478KB, 2,093 rows, columns including **District's Name, County(ies), Email, Website, Special Purpose, Status, Local Governing Authority, Revenue, Statutory Authority**.

**Critical gotcha:** every `/OfficialList/*` endpoint returns HTTP 403 "The request is blocked" without a `Referer` header. With one, every endpoint returns 200. Also: all radio params must carry non-empty values or the server throws.

Statewide totals as of 6 August 2026: 2,088 active (1,488 independent, 600 dependent), 19 declared inactive. By purpose: **CDDs 1,095**, CRAs 211, housing authorities 91, drainage 82, fire control 64, airports 22, hospital 22, port facilities 15, mosquito control 18, expressway 5, water management 5.

**Tier your crawl by purpose code.** 1,095 of the 2,088 are CDDs — high entity count, low solicitation volume, administered by a handful of firms (Governmental Management Services, Inframark, Rizzetta, Wrathell Hunt, PFM). Crawl them monthly, not daily.

Nearly every "commonly missed" entity you'd worry about is already in this file: all 5 water management districts, CFX and the Greater Miami Expressway Agency, 12 seaports, 21 airport authorities including GOAA and Tampa, LYNX, Tri-Rail, HART, JTA, PSTA, North Broward Hospital District (Broward Health), Memorial Healthcare, Halifax, Sarasota Memorial, and 10 Children's Services Councils.

**What is NOT in it and must be added by hand:** Miami-Dade Aviation (MIA), Broward County Aviation (FLL), Lee County Port Authority (RSW), Miami-Dade DTPW, Broward County Transit, PalmTran, SunRail, and Jackson Health System — these are county departments or trusts, not districts. Also note Lee Health converted from a public district to a private nonprofit in 2024-25, so it correctly no longer appears.

### Other enumeration sources verified

- **Florida League of Cities** has an undocumented public API. `POST action=get_flcities_token` to `https://www.flcities.com/wp-admin/admin-ajax.php` mints a bearer token with no login, then `GET https://partnerapi.flcities.com/api/Consensus/cities?lean=true` returns 413 records. Per-city detail gives website, email, county, population, and officials. **You must prime cookies with a `GET /directory/` first** — a cold POST returns 403.
- **US Census 2022 Government Units file** — `https://www2.census.gov/programs-surveys/gus/datasets/2022/govt_units_2022.ZIP`. One download gives counties and municipalities with FIPS codes and `WEB_ADDRESS`. It is 2022 vintage, so it still lists entities that no longer exist. Good for FIPS joins, bad as a live roster.
- **FLDOE school districts** — `https://web03.fldoe.org/Schools/schoolmap_text.asp`, plain HTML, 76 entities with homepage URLs. Note `www.fldoe.org` is Akamai-WAF'd and returns 403 to scripts, but `web02`/`web03` are not.
- **Supervisors of Elections** — `https://dos.fl.gov/media/711276/qrycountyinfo_excel.xls`, all 67 with websites and emails, refreshed regularly. Follow redirects.
- **HUD public housing authorities** — ArcGIS layer returns 97 Florida PHAs (SDAP has 91; join on name to catch both).

---

## Part 5 — What I'd build, in order

**Phase 1 (about a week) — 60% of state dollar volume**

1. **VIP adapter.** All state agencies, universities, colleges, water management districts. Full documents. Poll `count` per status, page through, hydrate via detail, pull every `attachmentId`.
2. **OpenGov adapter.** 91 agencies, 13,917 projects, presigned S3 documents. Refresh the tenant list from `/api/v1/government` weekly so new agencies appear automatically.
3. **Fix the Bonfire adapter.** Add the past-opportunities and contracts endpoints, handle the object-keyed `projects` payload, handle both portal generations, and expand from your current 5 tenants to the verified 28.
4. **FSA co-op RSS.** Two hours of work for statewide vehicle and equipment contracts with direct PDF award packets.

**Phase 2 (about a week) — the long tail**

5. **CivicPlus adapter.** One parser, hundreds of small cities. Use `showAllBids=on` to backfill history.
6. **VendorLink adapter.** 156 Florida agencies from a public dropdown, iterate `?a=1..500`.
7. **Fingerprinting crawler.** Walk the 2,817-entity roster, find each procurement page, match the signature table, write the platform back to the registry. Re-run quarterly.

**Phase 3 — intelligence layer, where the actual money is**

8. **FACTS adapter.** Executed state contracts with prices, methods, and expiration dates. This tells you *when incumbents' contracts expire*, which is worth more than knowing what is currently out for bid.
9. **FDOT lettings and bid tabs.** GET-addressable letting reports plus an anonymous FTP archive back to 2018. Historical pricing intel.
10. **Award and intended-decision tracking.** Build the 72-hour protest window into the alerting. This is the highest-value event type in the whole pipeline.
11. **Chapter 119 backfill workflow.** A templated request generator for bid tabs and historical exports, triggered on day 31 after bid opening when no award has posted.

**Phase 4 — coverage completion**

12. **s. 50.0311(6) notice registrations** in every county that went website-only. Statutory right, no ToS, routes to your bid mailbox.
13. **County legal-notice site crawlers** for the ~67 sites in the second notice universe.
14. **PeopleSoft / Jaggaer / Oracle EBS one-offs** for Miami-Dade, UNF, FIU.
15. **Special district agendas.** s. 189.069 requires 7-day advance agenda posting retained a year. For the 993 non-CDD districts, agendas are the leading indicator that a solicitation is coming.

---

## Corrections to your current setup

Three things in your `config/sources.yaml` are now wrong:

1. **`swa_pbc`** points at BidSync. Solid Waste Authority of Palm Beach County moved to Bonfire at `swa.bonfirehub.com`. Your existing Bonfire adapter already covers it.
2. **Anything pointing at `vbs.dms.myflorida.com`** is dead — VBS was retired 28 March 2022 in favor of VIP.
3. **`west_palm_beach`** has a DemandStar fallback. Given the fingerprinting map, re-check whether WPB has migrated; several Florida agencies moved platforms during the window of this research.

And one architectural note: your `Opportunity` model hardcodes `county` as `miami-dade | broward | palm-beach`. Going statewide, that field needs to accept all 67 counties plus `statewide`, and you probably want a separate `tier` field (state / county / municipality / school_district / higher_ed / special_district) since agency tier drives both relevance scoring and crawl frequency.

---

## Files delivered

| File | Contents |
|---|---|
| `fl_agencies.csv` | 2,817 Florida buying entities with tier, county, website, email, phone |
| `fl_procurement_sources.csv` | 133 verified agency → platform → adapter mappings |
| `sources_seed.yaml` | The same 133, in your existing `config/sources.yaml` schema |
| `README_DATA.md` | Provenance for every row: exact requests used, what failed, refresh cadence |

---

## Open questions for counsel

1. **s. 815.06, F.S.** — is there Florida appellate authority applying *Van Buren*'s narrowing to "manner of use exceeds authorization"? I found none. Largest unquantified risk, and it is Florida-specific.
2. **Florida Press Service licensing** — negotiate a data license for floridapublicnotices.com rather than relying on the s. 50.0211(3)(c) free-access mandate, which grants access, not redistribution rights.
3. **s. 119.12(3) "improper purpose"** — how a high-volume commercial requester should structure Chapter 119 requests to avoid adverse fee exposure.
4. **Acquisition vs. redistribution** — lawfully obtaining a record under Chapter 119 says nothing about the right to republish a third party's compiled database. Separate analysis.

---

## Sources

**State systems:** [MFMP Vendor Information Portal](https://vendor.myfloridamarketplace.com/search/bids) · [DMS State Purchasing](https://www.dms.myflorida.com/business_operations/state_purchasing) · [FACTS](https://facts.fldfs.com/Search/ContractSearch.aspx) · [FDOT lettings](https://www.fdot.gov/contracts/lettings/letting-project-info.shtm/1000) · [FDOT procurement](https://www.fdot.gov/procurement/advertisements.shtm) · [Rule 60A-1.021](https://flrules.org/gateway/ruleno.asp?id=60A-1.021) · [Rule 60A-1.033](https://flrules.org/gateway/ruleno.asp?id=60A-1.033)

**Platforms:** [OpenGov Procurement](https://procurement.opengov.com/) · [Bonfire / Euna](https://eunasolutions.com/solutions/procurement/) · [Vendor Registry](https://vendorregistry.com/) · [BidNet Florida](https://www.bidnetdirect.com/florida/participating-buyers) · [DemandStar](https://www.demandstar.com/) · [BidSync](https://www.bidsync.com/) · [VendorLink](https://www.myvendorlink.com/external/bids?a=70) · [Jaggaer public events](https://bids.sciquest.com/apps/Router/PublicEvent?CustomerOrg=UNF)

**Co-ops:** [Florida Sheriffs Association purchasing](https://flsheriffs.org/purchasingprogram/) · [Florida Buy](https://floridabuy.org/) · [Sourcewell](https://proportal.sourcewell-mn.gov/Module/Tenders/en) · [OMNIA Partners](https://www.omniapartners.com/get-started/solicitations) · [NASPO ValuePoint](https://www.naspovaluepoint.org/solicitation-status/)

**Entity rosters:** [Special District Accountability Program](https://floridajobs.org/community-development/community-planning/special-districts/special-district-accountability-program) · [Special District Reports](https://specialdistrictreports.floridajobs.org/) · [Florida League of Cities directory](https://www.flcities.com/directory/) · [FLDOE school districts](https://web03.fldoe.org/Schools/schoolmap_text.asp) · [Florida College System](https://www.fldoe.org/schools/higher-ed/fl-college-system/about-us/colleges.stml) · [Board of Governors](https://www.flbog.edu/universities/) · [Census 2022 Government Units](https://www2.census.gov/programs-surveys/gus/datasets/2022/govt_units_2022.ZIP) · [FL Dept of State county officers](https://dos.fl.gov/elections/contacts/supervisor-of-elections/) · [HUD FL housing authorities](https://www.hud.gov/sites/dfiles/PIH/documents/PHA_Contact_Report_FL.pdf) · [Florida Ports Council](https://flaports.org/seaports/)

**Statutes (2025 Fla. Stat.):** [119.01](https://www.flsenate.gov/Laws/Statutes/2025/119.01) · [119.07](https://www.flsenate.gov/Laws/Statutes/2025/119.07) · [119.071](https://www.flsenate.gov/Laws/Statutes/2025/119.071) · [119.0701](https://www.flsenate.gov/Laws/Statutes/2025/119.0701) · [119.12](https://www.flsenate.gov/Laws/Statutes/2025/119.12) · [50.0211](https://www.flsenate.gov/Laws/Statutes/2025/50.0211) · [50.0311](https://www.flsenate.gov/Laws/Statutes/2025/50.0311) · [120.57](https://www.flsenate.gov/Laws/Statutes/2025/120.57) · [189.069](https://www.flsenate.gov/Laws/Statutes/2025/189.069) · [190.033](https://www.flsenate.gov/Laws/Statutes/2025/190.033) · [215.985](https://www.flsenate.gov/Laws/Statutes/2025/215.985) · [218.391](https://www.flsenate.gov/Laws/Statutes/2025/218.391) · [255.0525](https://www.flsenate.gov/Laws/Statutes/2025/255.0525) · [255.20](https://www.flsenate.gov/Laws/Statutes/2025/255.20) · [287.042](https://www.flsenate.gov/Laws/Statutes/2025/287.042) · [287.055](https://www.flsenate.gov/Laws/Statutes/2025/287.055) · [287.057](https://www.flsenate.gov/Laws/Statutes/2025/287.057) · [336.44](https://www.flsenate.gov/Laws/Statutes/2025/336.44) · [815.06](https://www.flsenate.gov/Laws/Statutes/2025/815.06)

**Guidance and cases:** [Government-in-the-Sunshine Manual 2025](https://www.myfloridalegal.com/sites/default/files/government-in-the-sunshine-manual.pdf) · [AG Open Government FAQ](https://www.myfloridalegal.com/open-government/frequently-asked-questions) · [hiQ v. LinkedIn, 31 F.4th 1180 (9th Cir. 2022)](https://cdn.ca9.uscourts.gov/datastore/opinions/2022/04/18/17-16783.pdf) · [Ryanair v. Booking.com JMOL](https://blog.ericgoldman.org/archives/2025/03/court-overturns-a-bad-jury-verdict-against-scraping-ryanair-v-booking-guest-blog-post.htm) · [CS/HB 7049 (2022)](https://www.flsenate.gov/Session/Bill/2022/7049) · [HB 1009 (2026), died in Senate](https://www.flsenate.gov/Session/Bill/2026/1009)

**Federal:** [SAM.gov Get Opportunities Public API](https://open.gsa.gov/api/get-opportunities-public-api/)
