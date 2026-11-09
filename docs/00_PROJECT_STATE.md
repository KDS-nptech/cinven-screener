# Project state: Cinven screener

Updated: 2026-11-09 22:40 London

## Goal
Build a sourcing screener for Cinven (London) on public data, the same architecture as the Greycroft screener (github.com/KDS-nptech/greycroft-screener) and the UK Software Screener for Brighton Park (github.com/KDS-nptech/uk-software-screener): universe from Companies House, ownership route from the PSC register, sector classification into Cinven's six sectors, size from filed accounts, rubric adapted from Cinven's published investment approach, entry fit calibrated to the fund's measured entry profile with outliers (US-led, club mega-deals, minority, fund-to-fund, Strategic Funds) measured and excluded, why-now signals, static site in Cinven's design system styled to cinven.com. Deliverables: the site (artifact plus GitHub Pages), the repo at github.com/KDS-nptech/cinven-screener, docs, a cold email draft to Samy Jazaerli (Senior Principal, Financial Services, London).

## Status
- 22:40 (9 Nov): SITE PUBLISHED, THREE REVIEW ROUNDS DONE. 677 companies in the six sectors scored; 91 ranked (78 founder or family, 12 sponsor, 1 PLC; 75 Strategic Fund band, 16 flagship band; sectors: Industrials 30, Consumer 29, Business Services 18, Healthcare 7, TMT 5, Financial Services 2). overrides.yaml: 32 exclusions and 2 corrections with reasons; review record docs/qa/top30_review.md.
- Bug fixed 22:15: consolidated PDF figures were dropped in the wide build; at-scale actionable heads went 180 to 412.
- QA (checker Claude Sonnet 5.5): PDF reader 28 of 28 on turnover, 26 of 28 on operating profit; labels 80% agree on 40; rubric 85% within one point on 98 sub-scores, pipeline ~9 points more generous.
- Data: document API ~4,500 documents read (2,400 general GROUP pass, 905 FS-coded, plus the resumed general pass); ~3,300 GROUP-account actionable heads unread. Websites: 1,783 searched, model-suggested pass verified 58 at-scale sites; 114 at-scale companies still have none.
- Artifact: https://claude.ai/artifact/7tEbHt4kox8Tc3viFCKUdo (private). Email draft: docs/outreach/cinven_cold_email.md.

## Next
1. Resume the general document pass (4 shards, GROUP then FULL), then `--build-wide`, universe, routes, discovery for new at-scale names, `src.enrich.suggest`, classify, rubric, `scripts/score_tail.sh`; review new ranked names before republishing.
2. Find sites by hand for the largest at-scale companies without one (DBI Holdings, WPG Finance, Family First Topco, Chesterfield Poultry).
3. FS: read accounts for holding-company-coded groups with FS subsidiaries (brokers, wealth, fund administration).
4. Re-run Seznam discovery for the smaller companies lost at 21:58 (cached).
5. Kyle: fill the bracketed fields in the email, share the artifact, send.

## Open questions
- Pre-2016 entries cannot be route-tested (PSC register starts April 2016); pre-deal accounts for them came from PDFs the research agent read.
- Smart Communications 2025: point-in-time route "uncertain" because Accel-KKR's partners appear as individual PSCs at 25 to 50%; a rule for named PE partners would need a people list.

## LAST SAFE CHECKPOINT (9 Nov 22:40)
Origin main holds code, config, overrides.yaml, research, docs, QA records and site/index.html (91 ranked). The artifact holds the same build. On disk and gitignored: register tables, accounts parts, caches.
