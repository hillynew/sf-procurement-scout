# Florida Procurement Aggregator — Data Files

Generated **2026-08-06**. All rows derive from a live fetch or an explicitly-labelled
hardcoded list. Nothing here is inferred or invented — where a source failed, the rows
were left out and the failure is documented below.

| File | Rows | What it is |
|---|---|---|
| `fl_agencies.csv` | **2,817** | Master roster of Florida buying entities |
| `fl_procurement_sources.csv` | **133** | Agency → portal → adapter mapping |
| `sources_seed.yaml` | **133** | Same 133 sources in `config/sources.yaml` schema |
| `README_DATA.md` | — | This file |

---

## 1. `fl_agencies.csv` — 2,817 rows

`entity_id,name,tier,county,website,email,phone,notes`

`entity_id` is a stable generated slug prefixed by tier (`sd-`, `mun-`, `co-`, `sch-`,
`he-`, `st-`, `cons-`). Uniqueness asserted at build time.

### Per-tier counts

| tier | rows |
|---|---|
| `special_district` | 2,089 |
| `municipality` | 414 |
| `school_district` | 76 |
| `county` | 67 |
| `constitutional_officer` | 67 |
| `state` | 63 |
| `higher_ed` | 41 |
| **total** | **2,817** |

Field fill rates: county 2,740 · website 2,724 · email 2,559 · phone 2,502.

### How each tier was obtained

**Special districts — 2,089** (2,088 from the official list + Treasure Coast Regional
Planning Council, which is MFMP-registered but not on the special-district list).

Live POST to the FloridaCommerce Special District Accountability Program:

```bash
curl 'https://specialdistrictreports.floridajobs.org/OfficialList/CustomList' \
  -H 'User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36' \
  -H 'Referer: https://specialdistrictreports.floridajobs.org/OfficialList/CustomList' \
  -H 'Origin: https://specialdistrictreports.floridajobs.org' \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  --data-urlencode 'StartDate=' --data-urlencode 'EndDate=' \
  --data 'customReportData.DependencyStatus=Dependent,Independent' \
  --data 'customReportData.ActiveStatus=Active' \
  --data 'customReportData.BondAuthority=Yes,No' \
  --data 'customReportData.CountyName=Multi' \
  # ... customReportData.CountyName repeated once per each of the 67 counties ...
  --data 'customReportData.ReportType=Detailed' \
  --data 'customReportData.FormatType=Excel' \
  --data 'customReportData.Sort=1' \
  --data 'Action=GenerateReport' \
  -o sd_detailed.xlsx
```

Returned **478,452 bytes**, XLSX, sheet `Customized List`, **2,093 rows × 29 columns**
(5 title/header rows + 2,088 districts) — exactly as expected. Columns used: District's
Name, County(ies), Email, Website, Telephone, Status (Dependent/Independent), Local
Governing Authority, Special Purpose (the last three are folded into `notes`).

The Detailed report only populates `Website` for 150 districts, so websites were merged
from the pre-existing `sdap_web.xlsx` (2,088 rows) by parsing the
`=HYPERLINK("url","label")` formulas with `openpyxl` (`data_only=False`) — **1,938
websites recovered**, joined on normalized district name. Final website coverage:
2,088 / 2,089. Email coverage 2,081.

**Municipalities — 414.** Florida League of Cities API (primary):

```bash
# 1. prime cookies (required — a cold POST returns 403 "Unauthorized page access")
curl -c jar 'https://www.flcities.com/directory/' -H 'User-Agent: <browser UA>'
# 2. token
curl -b jar 'https://www.flcities.com/wp-admin/admin-ajax.php' \
  -H 'Referer: https://www.flcities.com/directory/' -H 'Origin: https://www.flcities.com' \
  -H 'X-Requested-With: XMLHttpRequest' -H 'User-Agent: <browser UA>' \
  --data 'action=get_flcities_token'
# 3. list + per-city detail
curl 'https://partnerapi.flcities.com/api/Consensus/cities?lean=true' -H "Authorization: Bearer $TOK"
curl "https://partnerapi.flcities.com/api/Consensus/city/$ID"       -H "Authorization: Bearer $TOK"
```

Worked. 413 cities listed; **412/412 detail fetches succeeded** (6 workers, retries).
Gives county, email, phone and website per city. Two municipalities present in the
Census CoG but absent from the FLC directory (City of Weeki Wachee, City of Miami
Shores) were unioned in, giving 414.

**Counties — 67.** US Census 2022 Government Units file:

```bash
curl -O 'https://www2.census.gov/programs-surveys/gus/datasets/2022/govt_units_2022.ZIP'   # 11,459,763 bytes
unzip govt_units_2022.ZIP   # -> Govt_Units_2022_Final.xlsx
```

Sheet `General Purpose`, `STATE == 'FL'` → **478 rows = 66 `1 - COUNTY` + 412
`2 - MUNICIPAL`**. `WEB_ADDRESS` used for website. Duval County / City of Jacksonville
is a consolidated city-county and is absent from the Census county rows — added by hand,
marked in `notes`, giving 67.

**School districts — 76.** Scraped `https://web03.fldoe.org/Schools/schoolmap_text.asp`
(plain HTML, no WAF) with a browser UA; parsed `<td>` blocks for
`<strong>NAME</strong> <span class="small">(NN)</span>` plus the `Homepage` anchor.
76 districts, 74 with homepage URLs. 66 are county districts; the other 10 are
state-supported/lab districts (FL School for the Deaf & the Blind, FL Virtual School,
DJJ, FSU/FAMU/FAU/UF lab schools, etc.) and are flagged in `notes`.
FLDOE lists Miami-Dade as `"Dade"` — remapped to `Miami-Dade County School District`.

**Higher ed — 41.** 12 State University System universities + 28 Florida College System
colleges, **hardcoded with their .edu domains**, plus Edward Waters University (private,
MFMP-registered) from `vip_orgs.json`. Hardcoded because
`https://www.fldoe.org/schools/higher-ed/fl-college-system/about-us/colleges.stml`
returns **HTTP 403** from an Akamai WAF regardless of UA/header set (see Failures).
Every hardcoded row carries `hardcoded: fldoe.org WAF 403` in `notes`.

**State agencies — 63.** From the pre-existing `vip_orgs.json` (129 MFMP orgs). Ids
starting `30` → `state`; `40`/`50` ids classified by name (university/college →
`higher_ed`, water management district / RPC / airport / transit → `special_district`,
City/Town/Village of → `municipality`, BoCC → `county`, school board → `school_district`).
All 129 carry `MFMP-registered (VIP org id NNNNNNNN)` in `notes`. Of the 129, 66 merged
into rows already sourced from an authoritative list, leaving 63 in the `state` tier.

**Constitutional officers — 67.** All 67 Supervisors of Elections:

```bash
curl -L 'https://dos.fl.gov/media/711276/qrycountyinfo_excel.xls' -o soe.xls
# NOTE: -L is required — dos.fl.gov 307-redirects to files.floridados.gov
```

Real BIFF `.xls` (58,880 bytes), read with `pandas.read_excel` → 67 rows × 15 columns.
100% coverage of website, email, phone and county.

### Dedupe

Deduped on **normalized name + tier**. Normalization lowercases, strips accents,
drops `the/of/a`, expands abbreviations (`Dist`→District, `Fla`→Florida, `BoCC`→Board of
County Commissioners, `Assn`→Association, `St`→Saint …), applies a small explicit alias
map for legacy institution names (e.g. *Brevard Community College* → *Eastern Florida
State College*, *Okaloosa-Walton CC* → *Northwest Florida State College*, *Lake City CC*
→ *Florida Gateway College*), and for municipalities strips the City/Town/Village prefix
and all whitespace so `City of De Land` == `City of DeLand`.

**2,881 pre-dedupe → 2,817 post-dedupe (64 merged).** On merge, empty fields are filled
from the duplicate and `notes` are concatenated, so an MFMP registration flag is never
lost.

---

## 2. `fl_procurement_sources.csv` — 133 rows

`source_id,entity_id,name,tier,county,platform,portal_url,api_url,adapter,docs_anon,live_fetch,confidence,notes`

125 / 133 rows are linked to an `entity_id` in `fl_agencies.csv`. The 8 unlinked are
statewide/federal aggregators with no single owning entity (MFMP, FDOT lettings, FACTS,
SAM.gov, FL Sheriffs), a private university (Embry-Riddle), a sheriff's office and a
multi-CDD portal — none of which map to a single roster row.

| platform | rows | adapter | docs_anon |
|---|---|---|---|
| `opengov` | 91 | `opengov` | yes |
| `bonfire` | 28 | `bonfire` | yes |
| `vendor_registry` | 3 | `vendor_registry` | partial |
| `publicpurchase` | 3 | `publicpurchase` | partial |
| `mfmp_vip` | 1 | `vip` | yes |
| `peoplesoft` | 1 | `peoplesoft` | partial |
| `infor_fsm` | 1 | `infor` | no |
| `jaggaer` | 1 | `jaggaer` | yes |
| `fdot_letting` | 1 | `fdot_letting` | yes |
| `facts` | 1 | `facts` | yes |
| `sam_gov` | 1 | `sam_gov` | yes |
| `html_custom` | 1 | `flsheriffs_rss` | yes |

Confidence: **132 verified, 1 probable** (Coral Gables Infor). Zero unverified.

### OpenGov — 91 rows

Derived from `og_gov.json` filtered to `state == "FL" && isActive` → exactly 91.
Each tenant code was then **individually confirmed live**:

```bash
curl "https://api.procurement.opengov.com/api/v1/government/<code>"   # 200 = real, 404 = not a tenant
```

**91/91 returned HTTP 200.**

> **Correction to the original spec.** The documented feed
> `https://api.procurement.opengov.com/api/v1/government/<code>/project/public`
> returns **HTTP 404 `{"message":"Not Found"}`** for every tenant tested. Verified
> working routes on that host are:
> * `GET /api/v1/government/<code>` → tenant metadata (incl. numeric `id`) — **200**
> * `GET /api/v1/government` → full 561-tenant directory (this is where `og_gov.json` came from) — **200**
> * `GET /api/v1/project/<id>` → full project detail — **200**
> * `POST /api/v1/project/search` → **401 Unauthorized** (this is the list route; needs a token)
>
> `https://procurement.opengov.com/portal/<code>` is served behind a **Cloudflare managed
> challenge** and returns 403 to non-browser clients, so it cannot be used to validate codes.
>
> `api_url` in the CSV is therefore set to the **verified** `/api/v1/government/<code>`,
> and every OpenGov row carries this caveat in `notes`. The adapter will need either the
> authenticated search route or headless-browser access to the portal to list opportunities.

### Bonfire — 28 rows (discovered, not assumed)

675 candidate subdomain slugs were generated from: the seed list in the brief, all 67
county names × 5 suffix patterns (`x`, `xcounty`, `xcountyfl`, `xfl`, `x-fl`), ~150 large
city names, universities/colleges, airports, ports, transit agencies and school districts.

1. **DNS prefilter** (concurrent `gethostbyname`, 3 attempts each) — this puts **zero
   load** on Bonfire's servers and is a clean discriminator because `*.bonfirehub.com` has
   **no wildcard DNS**: a non-tenant fails to resolve. **30 / 675 resolved**, stable
   across two independent passes (0 new, 0 lost).
2. **HTTP probe** of the 30 survivors, 8 workers, 10 s timeout:
   `GET https://<slug>.bonfirehub.com/PublicPortal/getOpenPublicOpportunitiesSectionData`
   keeping HTTP 200 + JSON `"success":1`.
3. **Identity confirmation** — fetched each tenant's `/portal` and read the `<title>`,
   which contains the tenant's official name. This is what caught two **non-Florida**
   tenants that a slug-only method would have wrongly kept:
   `nsu` = **Norfolk State University (VA)** and `tsc` = **Texas Southmost College (TX)**.
   Both excluded.

**Result: 28 verified live Florida Bonfire tenants.** `open_opportunities` was read from
the probe response and is recorded in each row's `notes`.

| slug | tenant (from portal title) | open opps |
|---|---|---|
| `hillsboroughcounty` | Hillsborough County | 24 |
| `broward` | Broward County (BPRO Electronic Procurement System) | 16 |
| `marionfl` | Marion County, FL | 9 |
| `pascocountyfl` | Pasco County | 8 |
| `talgov` | City of Tallahassee | 8 |
| `indianriver` | Indian River County | 7 |
| `monroecounty-fl` | Monroe County, FL | 5 |
| `psta` | Pinellas Suncoast Transit Authority | 5 |
| `townofpalmbeach` | Town of Palm Beach | 3 |
| `ucf` | University of Central Florida | 3 |
| `famu` | Florida A&M University | 2 |
| `fgcu` | Florida Gulf Coast University | 2 |
| `leeschools` | The School District of Lee County | 2 |
| `ocoee` | City of Ocoee, Florida | 2 |
| `panamacity` | City of Panama City | 2 |
| `fau` | Florida Atlantic University | 1 |
| `gohart` | Hillsborough Transit Authority | 1 |
| `stlucieschools` | St. Lucie School District | 1 |
| `suwanneecountyfl` | Suwannee County | 1 |
| `tri-rail` | South Florida Regional Transportation Authority | 1 |
| `erau` | Embry-Riddle Aeronautical University | 0 |
| `floridapoly` | Florida Polytechnic University | 0 |
| `jaxport` | JAXPORT | 0 |
| `keybiscayne` | Village of Key Biscayne, FL | 0 |
| `plantation` | City of Plantation | 0 |
| `swa` | Solid Waste Authority of Palm Beach County | 0 |
| `dadeschools` | Miami-Dade County Public School District | unknown\* |
| `levycounty` | Levy County, FL | unknown\* |

\* These two run a newer portal build: the legacy
`getOpenPublicOpportunitiesSectionData` endpoint 307-redirects to `/portal` and, once a
portal session cookie is held, returns `{"success":0,"message":"Error"}`. Both portals
are confirmed live and correctly named, so they are kept as verified tenants with an
unknown count. **The Bonfire adapter must handle both portal generations.**

A count of `0` means the tenant is live with nothing currently open — still worth polling.

### Vendor Registry — 3 rows

FL buyer GUIDs found by web search and each confirmed by fetching
`https://vrapp.vendorregistry.com/Bids/View/BidsList?BuyerId=<guid>` and checking the
page `<title>` names the right agency (all HTTP 200). Note the parameter is **`BuyerId`**,
not `buyerGuid`.

* Central Florida Expressway Authority — `7fa678ed-767c-46f1-b88f-2fe8e4853ecc`
* Okeechobee County — `e0c9e138-531c-43ed-bb52-97aa049ceb72`
* Santa Rosa County — `2a63b069-a1a0-47e8-9417-6007f31792d0`

This is certainly a partial list; Vendor Registry publishes no tenant directory.

### One-offs

All fetched and checked at build time:

| source | URL | result |
|---|---|---|
| MFMP VIP | `https://vendor.myfloridamarketplace.com/mfmp/pub/search/bids` | 200 |
| Miami-Dade PeopleSoft | `https://supplier.miamidade.gov/psc/EXTSUPP/SUPPLIER/ERP/c/SCP_PUBLIC_MENU_FL.SCP_PUB_BID_CMP_FL.GBL` | 200, 89 KB |
| UNF JAGGAER | `https://bids.sciquest.com/apps/Router/PublicEvent?CustomerOrg=UNF` | 200 |
| FDOT lettings | `https://bidletting.fdot.gov/LettingResults?districtID=99` | 200 (districtID=99 = all districts) |
| FACTS | `https://facts.fldfs.com/Search/ContractSearch.aspx` | 200 |
| FL Sheriffs Assn | `https://flsheriffs.org/purchasingprogram/feed/` | 200 `application/rss+xml` |
| SAM.gov | `https://api.sam.gov/opportunities/v2/search` | 404 without `api_key` — **free API key required**, noted on the row |
| PublicPurchase — FLHSMV | `https://www.publicpurchase.com/gems/flhsmv,fl/buyer/public/home` | 200 |
| PublicPurchase — LYNX | `https://www.publicpurchase.com/gems/lynx,fl/buyer/public/home` | 200 |
| PublicPurchase — Coral Gables | `https://www.publicpurchase.com/gems/coralgables,fl/buyer/public/home` | 200 |
| Coral Gables Infor | `https://sms-coralgables-prd.inforcloudsuite.com/fsm/SupplyManagementSupplier/page/EventPage?csk_SupplierGroup=cocg&menu=XiSupplierHome.EventListings` | **302 → login** |

The Infor URL in the brief (`sms-coralgables-prd.inforcloudsuite.com` with a `/rss/...`
path) returns 404 on every path variant tried. The URL above is the one published on
coralgables.com's Supplier Services page; it 302-redirects to authentication, so the row
is `docs_anon=no`, `confidence=probable`. **Coral Gables also runs a PublicPurchase
portal**, which is anonymously browsable and is the better ingest target — both rows are
included.

---

## 3. `sources_seed.yaml` — 133 sources

Every row of `fl_procurement_sources.csv`, emitted in the existing `config/sources.yaml`
schema (`id, name, county, agency, live_fetch, adapter, portal_url, register_url,
platform, api_url`). `county` is a lowercase-hyphenated slug or `statewide`.
`register_url` is emitted only where a real vendor-registration URL is known.
Validated by round-tripping through `yaml.safe_load` → 133 sources parsed.

---

## What failed

1. **`fldoe.org` — HTTP 403.** The FL College System colleges page (and the whole
   `/schools/higher-ed/` tree) is behind an Akamai WAF that 403s regardless of
   User-Agent, `Sec-Fetch-*`, `Referer` or `Accept-Language`. `floridacollegesystem.com`
   is reachable but is the Foundation site and carries no college directory.
   **Mitigation:** the 28 FCS colleges + 12 SUS universities are hardcoded with their
   .edu domains and every such row is labelled in `notes`. Note `web03.fldoe.org`
   (school districts) is a *different* host and is **not** WAF'd — it worked fine.
2. **OpenGov public project-list API.** Documented path 404s; the real list route
   requires auth (401). Detailed above.
3. **Coral Gables Infor path.** 404 on all guessed paths; the working URL requires login.
4. **SAM.gov** returns 404 without a free `api_key`.
5. **Bonfire on the newer portal build** (`dadeschools`, `levycounty`) — legacy JSON
   endpoint no longer serves; opportunity counts unknown.
6. **Not attempted / out of scope:** sheriffs, tax collectors, clerks of court and
   property appraisers as a tier — only Supervisors of Elections were available as a
   clean 67-row authoritative list. `constitutional_officer` therefore = SOEs only.
   Vendor Registry has no public tenant directory, so its 3 rows are certainly incomplete.

## Refresh cadence

| Source | Cadence | Why |
|---|---|---|
| Bonfire tenant probe (`getOpenPublicOpportunitiesSectionData`) | **hourly–daily** | This is the live opportunity feed |
| MFMP VIP, OpenGov, Vendor Registry, PublicPurchase, FDOT, SAM.gov, FL Sheriffs RSS | **daily** | Live opportunity feeds |
| Bonfire tenant **discovery** (DNS sweep + title check) | **quarterly** | New tenants onboard slowly; re-run to catch them |
| OpenGov FL tenant list (`GET /api/v1/government`) | **monthly** | Tenants are added/deactivated occasionally |
| FL League of Cities directory | **quarterly** | Contact churn |
| FLDOE school districts, SUS/FCS lists | **annually** | Very stable |
| Special District Official List | **quarterly** | ~2,088 districts; CDDs are created/dissolved continuously |
| Census CoG Government Units | **every 5 years** | Next edition 2027 |
| FL Dept of State Supervisors of Elections | **annually**, plus after each general election | Officeholders change |

---

## Corrections applied when this registry was loaded into the repo (2026-08-06)

These are recorded rather than edited into the text above, so the original
provenance stays readable next to what was later found to be wrong.

**1. The OpenGov caveat in §2 is superseded — the list route works.**

The block under "Correction to the original spec" reports that
`/api/v1/government/<code>/project/public` returns HTTP 404 for every tenant,
that `POST /api/v1/project/search` (401) is the real list route, and that the
adapter would therefore need an authenticated route or a headless browser.

That is not the case, and `fl_procurement_sources.csv` already disagrees with
it: every OpenGov row's `api_url` points at `/project/public` and its `notes`
read `VERIFIED 2026-08-06: POST {...}`. The prose did not get the same update.

**The route is a POST.** A GET of that path 404s, which is what the earlier pass
saw. Re-verified live on 6 Aug 2026 while building `src/sources/opengov.py`:

* `GET /api/v1/government` → 561 tenants, 93 Florida, 91 active — matches.
* `POST /api/v1/government/alachuacounty/project/public` → HTTP 200, `count: 392`.
* `GET /api/v1/project/289714` → 147 fields.
* An Orange County project returned 21 attachments; one downloaded anonymously
  as 318 KB of `application/pdf`.

No auth, no cookie, no browser. The 91 tenants are live in
`config/sources.opengov.yaml`.

**2. Documents are in `documentAttachment`, not only `attachments[]`.**

§2 and the research report both describe the pre-signed S3 URLs as arriving in
`attachments[]`. On the projects tested, `attachments` was frequently **empty**
while the compiled packet sat in `documentAttachment.url`. An adapter reading
only `attachments` reports zero documents on projects that have them. Both keys
are read, plus `proposalDocuments` and the addendums endpoint.

**3. `success: 0` from Bonfire is ambiguous — it is also the rate-limit reply.**

§2 attributes `{"success":0,"message":"Error"}` to the newer portal build, and
for `dadeschools` and `levycounty` that holds: both fail reproducibly, across
repeated passes, with pacing. But `erau` and `jaxport` returned the *same*
response when probed in a tight loop and answer normally once the requests are
paced. So a single `success: 0` is not evidence that a tenant is unreadable, and
tenant-discovery sweeps that treat it that way will under-count.
`scripts/seed_from_registry.py --probe` paces and retries before dropping one.

**4. Levy County needs no Bonfire workaround.** It is already covered live
through OpenGov (`og_levycounty`), so the unreadable Bonfire portal costs
nothing. Miami-Dade County Public Schools is the one real gap from that pair,
and it already has a catalog pointer (`mdcps_demandstar`).
