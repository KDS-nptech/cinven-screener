# Project state: Cinven screener

Updated: 2026-11-09 19:55 London

## Goal
Build a sourcing screener for Cinven (London) on public data, the same architecture as the Greycroft screener (github.com/KDS-nptech/greycroft-screener) and the UK Software Screener for Brighton Park (github.com/KDS-nptech/uk-software-screener): universe from Companies House, ownership route from the PSC register, sector classification into Cinven's six sectors, size from filed accounts, rubric adapted from Cinven's published investment approach, entry fit calibrated to the fund's measured entry profile with outliers (US-led, club mega-deals, minority, fund-to-fund, Strategic Funds) measured and excluded, why-now signals, static site in Cinven's design system styled to cinven.com. Deliverables: the site (artifact plus GitHub Pages), the repo at github.com/KDS-nptech/cinven-screener, docs, a cold email draft to Samy Jazaerli (Senior Principal, Financial Services, London).

## Status
- 19:55 (9 Nov): RESEARCH COMPLETE, PIPELINE RUNNING END TO END, SITE IN BUILD. All four research files final (docs/research/01 firm profile v3 71KB; 02a 30 entries 2015 to 2020; 02b 39 entries 2021 to 2026; 03 20 UK platforms with Companies House numbers and vehicle chains). Measured pattern in docs/cv_pattern.json: 35 core flagship entries, EV median EUR 1.2B (p25 740, p75 2,345; 2024 onwards median EUR 2.3B), EBITDA median EUR 76M (p25 61, p75 145), headcount median 1,130, secondary buyouts 74%, founder or family involved 43%; Strategic Funds 14 entries, EV median ~EUR 490M; 20 outliers listed with reasons. UK flagship operating deals entered at turnover GBP 100M to 250M and EBITDA GBP 20M to 75M (docs/research/03). Bands set from this: Strategic Fund band EBITDA GBP 8M to 30M, flagship band GBP 30M to 300M, mega-cap above. Fit route points: founder or family 25, sponsor 22 (rising with hold years), offshore vehicle 16, PLC and foreign parent 14, UK group 12.
- First end-to-end run: 60 companies classified (Claude Haiku 4.5 through the Anthropic API; Gemini is blocked from this session's network), 45 rubric-scored (Haiku 5.5 and 4.5), why-now signals, rankings (22 ranked of 45 in scope), export (7 MB bundle). Back-tests (src/backtests.py, docs/backtests.md): 11 UK entries testable on the PSC register as it stood before announcement, 8 on an actionable route after three rule fixes (sovereign and pension funds read as sponsors, walk-up deepened to 7 levels for PE chains, individuals at 25 to 50% with nobody else on the register read as founder-led); today the screener reads Cinven as owner of True Potential, Smart Communications, Policy Expert and Objectway's UK entity.
- Data: Companies House basic snapshot 1 Nov 2026 (5.71M companies), PSC snapshot 9 Nov 2026 (16.1M rows), 12 months of all-sector iXBRL accounts (29,436 companies parsed), document API with a vision read of the P&L page for the PDF filers (800 read by 19:50; 74% yield a turnover line; 4 workers at ~1,750 documents an hour on the GROUP-account heads in actionable routes, 5,981 to do). Universe 66,256; actionable group heads 15,833 of which 2,500 size-verified so far and 351 at scale. Website discovery: Bing and DuckDuckGo blocked from this egress, Seznam works; 3 shards at ~1,850 an hour over the 14,539 actionable heads, largest verified first.
- Background workers die when the chat turn ends; every stage is resumable (scripts/pipeline_tail.sh re-runs the chain downstream of the ingest).
- Site: agent building src/site/template.html in Cinven's tokens (docs/brand/cinven_design_system.md) against site/data.json; views Ranked, Company, Funnel, Themes, Calibration, Methods (with Limitations tab), Shortlist, Look Up.

## Next
1. Let the document API workers and discovery shards run; re-run scripts/pipeline_tail.sh as data lands; rubric the new shortlist.
2. Site agent returns; screenshot pass; writing-standards pass on every string.
3. Hand review of the top 30 (overrides.yaml with reasons); blind re-score sample; QA record; usefulness tiles.
4. Docs: methodology.md, limitations.md, research-log.md, open-questions.md, README.md; cold email docs/outreach/cinven_cold_email.md.
5. Commit, push, publish the artifact.

## Open questions
- Pre-2016 entries cannot be route-tested (PSC register starts April 2016); pre-deal accounts for them came from PDFs the research agent read.
- Smart Communications 2025: point-in-time route "uncertain" because Accel-KKR's partners appear as individual PSCs at 25 to 50%; a rule for named PE partners would need a people list.
- Themes have one match each so far (few websites fetched); re-run after discovery.
- Quadrature Capital (proprietary trading, financial_services) ranks on the first list; review pass should exclude non-buyout financial institutions by rule (SIC 64999 with turnover from trading) or override.

## LAST SAFE CHECKPOINT (9 Nov 19:55)
Commit on origin main holds code, config, research outputs, cv_pattern.json, backtests, first site bundle. On disk and gitignored: data/parquet/companies.parquet, psc/, accounts_facts and accounts_meta parts (bulk plus API shards), data/cache (web pages, LLM answers, CH API responses, accounts text). A fresh clone rebuilds from the ingest commands in README.md; the LLM cache makes re-runs cheap.
