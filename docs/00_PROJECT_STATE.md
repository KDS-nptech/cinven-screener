# Project state: Cinven screener

Updated: 2026-11-10 13:35 London

## Goal
Build a sourcing screener for Cinven (London) on public data, the same architecture as the Greycroft screener (github.com/KDS-nptech/greycroft-screener) and the UK Software Screener for Brighton Park (github.com/KDS-nptech/uk-software-screener): universe from Companies House, ownership route from the PSC register, sector classification into Cinven's six sectors, size from filed accounts, rubric adapted from Cinven's published investment approach, entry fit calibrated to the fund's measured entry profile with outliers (US-led, club mega-deals, minority, fund-to-fund, Strategic Funds) measured and excluded, why-now signals, static site in Cinven's design system styled to cinven.com. Deliverables: the site (artifact plus GitHub Pages), the repo at github.com/KDS-nptech/cinven-screener, docs, a cold email draft to Samy Jazaerli (Senior Principal, Financial Services, London).

## Status
- 13:35 (10 Nov): 700 companies in the six sectors scored; 83 ranked (70 founder or family, 12 sponsor, 1 PLC; 67 Strategic Fund band, 16 flagship band; Consumer 26, Industrials 25, Business Services 13, Healthcare 8, TMT 6, Financial Services 5). overrides.yaml: 38 exclusions, 6 corrections, deal history for 11 sponsor-owned names, 2 trading-name fixes.
- Added 10 Nov: company page in four tabs; officers for all 700 from Companies House; website titles for 32 ranked companies; Overview landing view; Themes rebuilt; trading names; sub-sector exclusions (motor retail, forecourts, construction and housebuilding, energy supply, commodity trading); every ranked company re-scored with Claude Sonnet (comparables stay on Haiku, ~9 points higher); site/ folder ready for Cloudflare Pages.
- Data: 86 holding companies with FS subsidiaries read; general GROUP pass resumed and stopped when the session ended (~3,000 unread). 443 at-scale actionable heads, ~150 without a website.
- Repo private. Artifact https://claude.ai/artifact/7tEbHt4kox8Tc3viFCKUdo (private until Kyle shares it). steve98654 invited as collaborator.

## Next
1. Resume the general document pass (4 shards, GROUP then FULL), then `--build-wide`, universe, routes, discovery for new at-scale names, `src.enrich.suggest`, classify, rubric, `scripts/score_tail.sh`; review new ranked names before republishing.
2. Find sites by hand for the largest at-scale companies without one (DBI Holdings, WPG Finance, Family First Topco, Chesterfield Poultry).
3. FS: read accounts for holding-company-coded groups with FS subsidiaries (brokers, wealth, fund administration).
4. Re-run Seznam discovery for the smaller companies lost at 21:58 (cached).
5. Kyle: fill the bracketed fields in the email, share the artifact, send.

## Open questions
- Pre-2016 entries cannot be route-tested (PSC register starts April 2016); pre-deal accounts for them came from PDFs the research agent read.
- Smart Communications 2025: point-in-time route "uncertain" because Accel-KKR's partners appear as individual PSCs at 25 to 50%; a rule for named PE partners would need a people list.

## LAST SAFE CHECKPOINT (10 Nov 13:35)
Origin main holds code, config, overrides.yaml, research, docs and site/ (83 ranked). The artifact holds the same build. After new accounts land: build-wide, universe, routes, discovery, suggest, fetch, classify, rubric, rankings, `python -m src.score.rescore`, trading_names, team_pages, officers, `scripts/score_tail.sh`; review new ranked names before publishing.
