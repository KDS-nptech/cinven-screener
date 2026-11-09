# Project state: Cinven screener

Updated: 2026-11-09 14:20 London

## Goal
Build a sourcing screener for Cinven (London) on public data, the same architecture as the Greycroft screener (github.com/KDS-nptech/greycroft-screener) and the UK Software Screener for Brighton Park (github.com/KDS-nptech/uk-software-screener): universe from Companies House, ownership classification, sector classification into Cinven's six sectors, size estimate, rubric adapted from Cinven's published investment approach, fit calibrated to the fund's measured entry profile with outliers (SFF, minority, mega, growth) measured and excluded, why-now signals, static site in Cinven's design system styled to cinven.com. Deliverables: the site (artifact plus GitHub Pages), the repo at github.com/KDS-nptech/cinven-screener, docs, a cold email draft.

## Status
- 14:20 (9 Nov): Prior builds recovered (both repos cloned to /home/claude). Skeleton created. Research wave 1 launching (firm profile, entry profile 2015 to 2020, entry profile 2021 to 2026, UK deals and Companies House numbers). Companies House network access confirmed (download.companieshouse.gov.uk 200, cinven.com 200, Gemini and Mistral endpoints reachable).

## Next
1. Research wave 1 outputs land in docs/research/01 to 04.
2. Ingest: Companies House basic snapshot, PSC snapshot, accounts bulk iXBRL (large companies across all sectors).
3. Pipeline adaptation, site, validation, delivery.

## Open questions
- (none yet)

## LAST SAFE CHECKPOINT
Nothing built yet. Prior repos cloned read-only at /home/claude/greycroft-screener and /home/claude/uk-software-screener.
