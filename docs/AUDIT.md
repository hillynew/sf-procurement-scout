# Audit — every problem found, nothing fixed yet

Sources: full code read (three independent passes), live portal verification
(2026-08-09, see docs/SOURCES.md), and the 1,017-test offline suite (all passing —
these are defects the tests don't cover). Severity: **CRIT** = wrong data shown or data
lost · **HIGH** = silent failure / missed records · **MED** = inconsistency, degraded
UX · **LOW** = dead code, drift, cosmetics.

## A. Wrong data (CRIT)

1. **Bonfire due times are 4–5 hours late.** `src/sources/bonfire.py:190` feeds
   `DateClose` to `parse_dt`, which treats naive strings as Eastern wall clock
   (`src/dates.py:44`) — but Bonfire stores UTC (verified live: 18:00:00 renders 2:00 PM
   EDT on the portal). Every Bonfire deadline is displayed wrong; an early-UTC close
   lands on the wrong calendar day. **Fix**: in the adapter, attach UTC before parsing
   (`parse_dt(f"{value} UTC")` or equivalent) so `parse_dt` converts to Eastern.

2. **Untracked history is deleted on every fetch.** `src/db/store.py:145-149` —
   snapshot-replace deletes any untracked row that fell off the portals. Closed
   solicitations vanish, so award linkage (agency+title+date matching per SOURCES.md §1)
   has nothing to link against, and "what was open last month" survives only in file
   snapshots pruned to 10 (`src/pipeline/store.py:27`). Directly against the north star.
   **Fix**: flag vanished rows `present=False` universally; never delete captured
   records (user rule). Add a status view filter instead.

3. **Awards misfiled as closed, portal-wide.** `src/sources/opengov.py` collapses every
   non-open status (`closeOutReason` "awarded" vs "canceled" ignored);
   `src/sources/civicplus.py` `_STATUS_MAP` maps `awarded`→`closed`;
   `src/sources/bonfire.py` ignores `IsPublicAward` (224 awarded vs 37 cancelled on
   Broward alone, verified); `src/sources/vendorlink.py` `_STATUS` flattens `awarded` /
   `under evaluation` / `all bids rejected`. The system's own award concept
   (`status="award"`) is starved by its four biggest platforms. **Fix**: map the
   verified status signals per SOURCES.md §3.

4. **Email alerts mislabel every record.** `src/sources/email_alerts.py` stamps
   config-level `county: broward`, `agency: "Email subscriptions"` on every mail
   regardless of sender; the From header is never read. Any non-Broward subscription
   produces records with a wrong county. **Fix**: parse From/sender domain → city/agency
   map; fall back to `unknown`, never a fixed county.

## B. Silent failures (HIGH)

5. **`miami_dade_informs` cannot look broken.** `src/sources/miami_dade_informs.py` —
   heuristic table pick with a "any table with >2 rows" fallback, `status` hardcoded
   `"open"`, never sets `degraded_reason`, `allows_empty` inherits True. A markup change
   yields junk or empty forever while health reads OK. The sibling adapter
   (`miami_dade_construction.py`) documents having been burned by exactly this and was
   fixed alone. **Fix**: `allows_empty=False`, strict table signature, degraded on miss.

6. **Two Jaggaer tenants are permanently empty by the module's own probe.**
   `config/sources.yaml` configures `jaggaer_uf` (`CustomerOrg=Florida`) and
   `jaggaer_usf` (`USFlorida`) while `src/sources/jaggaer.py`'s docstring records USF
   0/0/0 and UNF departed. A source that can only return zero reads as a quiet agency —
   the failure mode this project has hit three times. **Fix**: remove or convert to
   catalog pointers; verify UF's tenant identity first (probe table says "not tenants at
   all").

7. **CivicPlus tenant drift, live-verified.** Hollywood (`hollywoodfl.org`) board is
   abandoned — the city moved to BidSync — yet is configured `live_fetch: true` and
   reports healthy-empty. Boca Raton 302s its whole board to CivicPlus PublicLogin.
   `web/services/maintenance.py` platform check exists but is off by default and didn't
   flag either. **Fix**: recheck all 99 CivicPlus entries with the fingerprinter; move
   walled/dead boards to catalog; consider making the platform check opt-out.

8. **AI briefs silently lose the bid package.** `src/ai/summarizer.py:205-214`
   `_package_text` (a) never passes `document_headers`, so MFMP attachments return the
   SPA shell (the exact trap `src/sources/base.py:49` documents), and (b) matches
   `.endswith(".pdf")` without stripping the query string, unlike
   `src/pipeline/runner.py:166`. Result: briefs quietly summarize listings without the
   package on the sources where the package matters most. **Fix**: share
   `runner._primary_package`'s selection and pass headers.

9. **Notification badge undercounts.** `web/api/misc.py` `list_notifications` computes
   `unread` over the newest-50 slice only. **Fix**: `COUNT(*) WHERE read=false`.

10. **Deadline notifications duplicate daily.** `web/services/scheduler.py`
    `_deadline_scan` re-notifies every day for every bid inside the window (~6 copies per
    bid at the default 5-day window); `add_notification` has no dedupe. **Fix**: dedupe
    on (kind, opportunity_id, due-date).

11. **In-memory AI job state strands the UI.** `web/api/bids.py` module-level
    `_deep_running`/`_research_*`/`_match_*` dicts — a restart mid-run leaves the
    frontend polling `state:"running"` forever; the dicts also grow unbounded.
    **Fix**: persist state transitions or add a staleness timeout.

## C. Capture defects (HIGH — the Phase 2 findings, fix list in SOURCES.md §5)

12. **OpenGov** (`src/sources/opengov.py`): `_contact` (:388) probes keys
    (`contact`, `contactInfo`, `projectContact`, `owner`) that don't exist in the live
    payload — the real fields are flat `contact*`/`procurement*`; detail contacts are
    effectively never captured. `:211` reads `questionDeadline` — the real key is
    `qaDeadline` — so `questions_due` is never set. `_addenda` documents all dropped
    (no `url` on that endpoint's attachments; stable URLs sit unread in the detail
    payload's own `addendums[]`). NIGP `categories[]`, pre-bid fields, estimated cost,
    planholders: ignored. `raw` keeps 2 of ~148 fields.
13. **MFMP** (`src/sources/mfmp_vbs.py`): drops UNSPSC `commodityCodes[]`,
    `responseDate` (question deadline), the five indicator flags, and — critically —
    `linkedAdNumber`, the award↔solicitation linkage key.
14. **VendorLink** (`src/sources/vendorlink.py`): `supports_detail=False` on a
    disproven premise; the public detail flow + `/external/contracts` (vendor + amount)
    are unread. Gate: read VendorLink's ToS first (`src/terms.py` GRANDFATHERED).
15. **SAM.gov** (`src/sources/sam_gov.py`): `resourceLinks` (documents), NAICS/PSC,
    full contacts, and `ptype=a` structured awards all unrequested.
16. **FACTS** (`src/sources/facts.py`): 42 of 52 columns unread (commodity code,
    execution date, justification, STC id, Agency Reference Number); grants and POs
    never pulled.
17. **CivicPlus** (`src/sources/civicplus.py`): raw `Category:` text missed —
    `_detail_fields` reads only the `BidListHeader` span family, Category lives in
    `BidDetail`/`BidDetailSpec`; award-recommendation PDFs collected as documents but
    never parsed for the vendor.
18. **Bonfire**: `posted_date` never set; contracts' `IsExtendable` unread.
19. **Workday** (`src/sources/workday_sourcing.py`): `description` and
    `attachments{nodes{fileName}}` confirmed valid in the schema, unqueried.
20. **FDOT** (`src/sources/fdot_ads.py`): work-type texts, prequalification
    (`ProjectThresholdTypeName`), `SelectionMethodText`, BDI flag → `raw` only.
21. **Jaggaer**: award rows get no `protest_deadline` (mfmp and ionwave set it);
    award-document attachments (verified to contain vendor + amount) never fetched.
22. **notice_links** (`src/sources/notice_links.py`): the notice PDF is the record's
    URL but never emitted as a `Document` nor parsed — dates/contacts inside it lost;
    `status` always `open`, so a stale page yields permanently-open rows.
23. **Model gaps** (`src/models/opportunity.py`): no `tier`, `raw_category`,
    commodity codes, `awarded_vendor`/`award_amount`/`award_date`, linkage fields,
    contract term. Prerequisite for all of the above (schema-additive).

## D. Misleading logic / inconsistencies (MED)

24. **Watchlist `include_statewide` silently erased.** Supported by the Pydantic
    `Rules` model and matcher, absent from the TS `WatchlistRules` and `RuleBuilder` —
    and `PUT /api/watchlists/{id}` replaces rules wholesale via `compact()`, so editing
    any watchlist in the UI destroys the flag (`web/api/watchlists.py`,
    `frontend/src/api/types.ts`).
25. **RuleBuilder live preview lies about counts.** It re-implements matching in TS but
    omits the statewide-county reconciliation `web/services/matching.py` documents at
    length (147-of-241 recovery on a live sample).
26. **Settings offers dead options.** `auto_fetch.mode="on_open"` + `stale_minutes` are
    presented in the UI and implemented nowhere (`web/services/scheduler.py` handles
    only `interval`); choosing them silently disables auto-fetch.
27. **Award status invisible in the UI.** No `STATUS_STYLE` entry
    (`frontend/src/components/ui.tsx:32` — falls through to grey "closed" style);
    default status filter excludes it; `protest_deadline` — "the tightest deadline in
    the system" — renders only in the email digest. (Phase 6 will fix the surface; the
    data fixes are §A3.)
28. **Workroom "Saving…" indicator** reflects any mutation on the bid, not notes
    (`frontend/src/screens/Workroom.tsx` reads shared `mutate.isPending`).
29. **New watchlists show every match as NEW** (`seen_ids` starts empty and
    `new_count == match_count` on creation).
30. **`get_deep_dive` merge order** (`web/api/bids.py`): `{"state":…} | envelope` lets
    a stored payload key clobber `state`/`error`. Same pattern in `get_matches`.
31. **`bid_opening` is free text nothing consumes** — set by one adapter, refused by
    `src/records.py:69` (uses `due_date` as the day-31 proxy).
32. **`ContractRow.contract_id`** embeds `source_id` with a `:` separator and splits it
    back (`src/db/store.py:981,1011`) — a contract id containing a colon round-trips
    wrong.
33. **Dedupe discards loser enrichment** (`src/pipeline/runner.py:513-523`) — only
    dates/contact/budget/categories merge; scope/documents/requirements are dropped
    (mostly mitigated by running before the detail pass).
34. **email digest / mailbox check duplicated subject regex** — `_BID_SUBJECT` filter
    means a city whose alert subject doesn't match silently drops mail
    (`src/sources/email_alerts.py`); acceptable but unmeasured — no counter of
    discarded messages.

## E. Data-loss and hygiene risks (MED)

35. **`data/pdf_cache/` grows without bound** — `purge("pdf_cache")`
    (`src/db/store.py:926`) clears the DB tier only; no disk pruning exists.
36. **Five purge buttons + demo-data loader sit one click deep in Settings** with
    irreversible server-side effects (`web/api/misc.py` purge targets). Confirm-dialog
    presence should be verified in Phase 6; `snapshot` purge deletes all untracked
    opportunities (compounding §A2).
37. **`datetime.utcnow()`** used in 23 places — deprecated in 3.12; mixed naive/aware
    comparisons are already being hand-patched (`src/pipeline/runner.py:67`).

## F. Dead code, drift, waste (LOW)

38. `src/scoring.py` — go/no-go meters: built, tested, never wired to any UI.
39. `GET /api/bids/{id}/summary` — endpoint no client calls.
40. `raw` serialized to the browser on every list row (`web/services/serialize.py` has
    no whitelist) — pure payload weight; TS interface silently drops 8 fields it does
    receive (`keywords`, `protest_deadline`, `personalized`…).
41. `stats.pipeline.stages` computed server-side, never consumed; `taxonomy.total_open`,
    `sources.last_run.status/opp_count`, `SourceInfo.agency/adapter/live_fetch`,
    `SourceHealth.ok` all served-unread; Recharts maps `by_county[].value`,
    `deadline_load[].value`, `results_by_month[].won` into series that never render,
    plus a tooltip formatter for a nonexistent "Est. value" series.
42. Unused helpers: `contracts.by_vendor`, `fl_geo.counties_in_region`,
    `taxonomy.label_for/offer_for` (tests only); `Document.is_addendum` property.
43. `web/server.py` SPA guard's redundant `startswith(("api/", "api"))` condition.
44. Sample data documents use `url="#"` — every demo document link is a no-op.
45. README says 223 catalog pointers; config yields 226 effective. Cosmetic drift.
46. `web/sample_data.py` and screens: `/calendar` route redirects to `/bids` (screen
    removed) — harmless remnant.

## G. Security & credentials

47. **No committed secrets found** (scanned for key/token/password patterns; `.env` not
    tracked; `render.yaml` uses `sync: false` correctly; `auth-status` prints env names
    only). CI runs pyflakes + tests, no secret scanning — acceptable for a private
    repo.
48. `SF_SCOUT_BONFIRE_COOKIE` is a raw session cookie in env — documented, expiring,
    never logged. OK as designed.
49. Fetch-log (`SF_SCOUT_FETCH_LOG`) off by default — the "defense file" the crawl
    policy describes only exists if enabled. **Recommend on-by-default** with rotation.

## Order of work for Phase 4

Critical first: A1 (Bonfire UTC), A2 (history retention), A3 (award statuses),
A4 (mailbox attribution) → B5–B11 (silent failures) → C12–C23 (capture, in the
SOURCES.md §5 ranking, schema first) → D/E as they intersect touched files → F only
where a touched file makes it free. G49 as a one-line default change.

---

## Phase 4 resolution log (2026-08-09)

**Fixed** — A1 Bonfire UTC · A2 retention (nothing deleted; vanished untracked
rows age to closed) · A3 award statuses (opengov/civicplus/bonfire/wpb; SAM
awards added) · A4 email attribution · B5 INFORMS hardening · B8 summarizer
package headers+selection · B9 whole-table unread count · B10 deadline dedupe ·
C12 OpenGov capture (codes, qaDeadline, contacts, pre-bid, est. cost, addenda,
full raw) · C13 MFMP capture (+`linkedAdNumber` linkage, award notices join the
detail pass) · C15 SAM full capture + `ptype=a` awards · C16 FACTS width ·
C17 CivicPlus raw category + awarded status + award-rec vendor parse ·
C18 Bonfire posted-date note stands, `IsExtendable` captured · C19 Workday
description+codes · C20 FDOT work types/prequal/BDI · C21 Jaggaer protest
clock · C22 notice-links document · C23 schema (tier, raw_category,
commodity_codes, awarded_vendor/amount/date, linked_ref/award_linkage,
contract_term) · G49 fetch log on by default with rotation. Plus, beyond the
audit: an award↔solicitation linkage pass (`src/pipeline/linkage.py`), source
drop detection against each source's own norm, per-run field-coverage stamps,
a `/api/quality` + `run.py quality` report, and three new award sources
(Legistar ×6 bodies, FDOT bidletting, Miami-Dade award recommendations).

**Withdrawn** — B6: `jaggaer_uf`/`jaggaer_usf` use tenant keys (`Florida`,
`USFlorida`) the universities' own pages link, verified live answering with UF
branding; the module docstring's probe table describes the *wrong* keys and
should be read with that in mind. D32: `split(":", 1)` keeps everything after
the first colon, so a contract id containing a colon round-trips correctly.
D/B11: the in-memory AI job state self-heals — sets clear in a `finally`, a
restart empties them, and the UI's "none" state invites a re-run.

**Resolved differently** — C14 VendorLink: the detail pass was never built.
Reading the terms it required (the gate the audit set) found §5(H) forbidding
"any robot, spider, other automatic device, or manual process to monitor or
copy" their pages — a browse-wrap binding on use. Recorded PROHIBITED in
`src/terms.py`; the existing 66-source list adapter was removed per the
repo's own rule and every agency converted to a catalog pointer. The
sanctioned restore path is VendorLink's statewide subscription (~$175/yr) —
an owner decision.

**Open (deferred, tracked for later phases)** — D24 `include_statewide`
watchlist flag (frontend, Phase 6) · D25 preview-count divergence (Phase 6) ·
D26 dead auto-fetch options (Phase 6 settings rework) · D27 award status
invisible in UI (Phase 6, now with real award data to show) · D28-D31 UI
niceties (Phase 6) · E35 pdf-cache disk pruning · E37 `datetime.utcnow()`
deprecation sweep · F38-F46 dead code (removed opportunistically as files are
touched).

---

## B7 recheck (2026-08-10) — the drift hypothesis was wrong; a narrower gap is real

`scripts/fingerprint_agencies.py --recheck` swept the 222 entities already
placed on a platform: **220 unchanged, 0 moved, 2 no longer readable**
(Broward Solid Waste Disposal District — HTTPError; Town of Redington Shores —
no platform signature; both read as a slow host or a WAF, not a move). No
tenant has migrated. B7 as written — "CivicPlus tenant drift" — is **not
happening**, and is closed on that evidence.

What the sweep did surface is a different, narrower gap. Against production's
own `/api/sources`, **108 of 281 live sources (38%) return zero rows** —
including `hollywood`, the abandoned board B7 named. The bulk are CivicPlus
(≈55) and OpenGov (≈23), plus `jaggaer_usf`, `plantation`, `swa_pbc`, four
Legistar bodies, and two Workday tenants.

To be precise about what was and was not wrong here — an earlier draft of this
entry said the system "reports both as healthy", and that is false. These
sources carry `status: "empty"`, not `ok`; `SourceHealth.healthy` already
excludes them, and the Sources screen already renders them as "No listings"
in faint grey, sorted below `ok`, with their own stat card and filter chip.
The distinction between a clean fetch and a useful one exists and works.

The real gap is one level down. `empty` cannot separate:

* a small town with nothing open **this week** — an honest zero that will
  yield later, and
* a board the agency **abandoned** — which will never yield again.

Both fetch cleanly, both return zero, both render "No listings". And the
Phase 4 drop detector is blind to the second by construction: it judges a
source against *its own recent norm*, and for a board that has never returned
a row the norm is zero, so `_flag_source_drops` returns early. Nothing in the
build could ever escalate a permanently dead source. That is the structural
part, and it is real.

**Fixed (2026-08-10)** — `HealthStatus.UNVERIFIED`, set by
`_flag_never_verified` in `src/db/store.py`: a source fetched cleanly in at
least 6 runs spanning at least 7 days that has never once yielded a record
reads `unverified` rather than `empty`. The lookback is 120 runs, deliberately
wider than the drop window — at a four-hour cadence 8 runs is barely a day,
and a day of silence is what a normal weekend looks like. The state is not
sticky: one listing clears it on the next run. It raises no notification —
108 sources would arrive as 108 alerts — and instead surfaces on the Sources
screen as "Never verified" with its own stat card and filter. It deliberately
does not join the "needs attention" filter, which stays reserved for
`degraded`/`error`, i.e. things that were working and stopped.

Note this asserts the weaker, true thing. `unverified` does not claim a board
is dead; it claims nothing has ever demonstrated it is alive. Deciding which
of the 108 to demote to catalog pointers is a separate judgement, and still
an owner's call.
