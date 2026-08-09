# Feature proposals — ranked by value per unit of effort

Everything below builds on what Phase 4 landed: award records with vendors and
amounts (Legistar, FDOT lettings, SAM, Miami-Dade, MFMP-linked), the
award↔solicitation linkage, per-source health norms, and the quality report.
Effort: **S** = hours · **M** = a day or two · **L** = a week. Nothing is built
until you pick. Items needing your action or money say so in bold.

| # | Feature | What you get | Effort | Depends on |
|---|---|---|---:|---|
| 1 | **Awards & rebid screen** | The missing half of the north star, visible: recent awards with vendor + amount, protest windows still open, incumbent contracts expiring (the register already collects them — no screen shows it), and "likely rebids" from recurrence + contract end dates | M | Phase 6 does the styling; this makes the screen exist |
| 2 | **Protest-clock surfacing** | Award notices with a live 72-hour window on the dashboard, hours remaining, loudest thing on the page while open. Data exists; today it renders only in email | S | none |
| 3 | **Bid mailbox** | Public Purchase's 228 otherwise-dark agencies via their own alert emails. Parser hardening + per-sender liveness (a dead subscription must not look like a quiet agency) | M | **You: register the business per agency/platform, dedicate a mailbox** (you said yes) |
| 4 | **VendorLink statewide subscription** | The 66 agencies lost to their terms, back — plus the detail fields (bonds, estimates, tabulations, contracts grid with amounts) verified in Phase 2. As a paying subscriber, reading is sanctioned; their alerts feed the mailbox above | S–M after purchase | **You: ~$175/yr purchase decision** |
| 5 | **Legistar roster sweep** | More local award feeds: probe every FL municipality/county name against the API once, auto-configure hits (Brevard, Clearwater, Pensacola, Ocala, Deltona are known-likely) | S | none |
| 6 | **Quality + coverage cards** | The `/api/quality` report and per-source coverage trends on the Sources screen — the honesty meter where you'll see it | S | Phase 6 overlap |
| 7 | **Price intelligence** | "What does janitorial go for in Broward" — median award amount by category/county/tier from accumulated awards + 12k FACTS contracts + FDOT bid tabs; shown on matching open bids | M | grows more useful as award data accumulates |
| 8 | **Competitor/vendor profiles** | Who wins what: per-vendor award history from awards + both contract registers, linked from every awarded row. The groundwork for "who am I bidding against" | M | #7 shares its data layer |
| 9 | **Ch. 119 request scheduler** | The day-31 tabulation letters `src/records.py` already writes, actually managed: a queue of ripe requests, sent/received tracking, per-agency contact book. The only path to award data for BoardDocs school districts and rural counties | M | **You: sending the emails** (or approve a send-from-mailbox flow) |
| 10 | **Fingerprint recheck in-app** | The platform-watch job promoted: monthly recheck on by default, CivicPlus drift (Hollywood-style silent deaths) surfaced as notifications with a one-click "convert to catalog" | S–M | none |
| 11 | **Jaggaer award-doc parsing** | University award vendors + amounts out of the tabulation XLSX/PDFs (verified present; ephemeral links need same-session download) | M | heterogeneous files; best-effort |
| 12 | **Miami-Dade govaction awards** | BCC award history (1996–present, with costs) via the Legislative Information Center HTML — the county its dead Legistar mirror can't serve | M | none |
| 13 | **FDOT letting backfill** | One-time walk of ~2 years of letting archives per district for price history feeding #7 | S | #7 to display it |
| 14 | **Digest v2** | Awards with amounts in the daily email; protest windows first; a weekly "what closed, what it went for" section | S | #1's data shaping |

## Suggested first picks

**2 + 5 + 6** are a day of high-visibility wins on data already flowing.
**1** is the biggest single step toward the north star and pairs naturally
with Phase 6. **3 and 4** are the two coverage unlocks — both gated on you.
**7/8** are the compounding long game: every week of collected awards makes
them smarter.

Not proposed: anything touching DemandStar or BidNet (terms), scraping
VendorLink without the subscription (terms, see `src/terms.py`), BoardDocs
automation (bot-walled; #9 is the honest route), and the contractor network
(parked per your instruction — untouched, still working).
