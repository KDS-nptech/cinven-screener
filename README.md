# Cinven Screener

UK buyout candidates for Cinven (London), found on public filings and scored two ways: an Investment Quality rubric adapted from Cinven's published approach, and an Entry Fit score calibrated to the fund's measured entry profile with outliers excluded. Six sectors (Business Services, Consumer, Financial Services, Healthcare, Industrials, TMT), two size bands (Strategic Fund 2 and the Eighth Cinven Fund), and the ownership route to each company read from the PSC register. See `docs/methodology.md` for the method, `docs/limitations.md` for what it cannot do, and `docs/00_PROJECT_STATE.md` for build state.

## What is in the repo

- `site/index.html` is the self-contained page: Ranked, Company, Funnel, Themes, Calibration, Methods (with Limitations), Shortlist and Look Up, styled to cinven.com (`docs/brand/cinven_design_system.md`). `site/artifact.html` is the same page for the claude.ai artifact. `.github/workflows/pages.yml` deploys `site/` to GitHub Pages.
- `docs/research/` holds the research behind the calibration: `01_cinven_firm_profile.md` (firm, funds, criteria, sector views, London team, deal size evidence), `02a` and `02b` (69 platform entries 2015 to 2026 with EV, EBITDA, route and an outlier flag with reasons), `03_uk_deals_companies_house.md` (20 UK platforms traced to Companies House numbers and vehicle chains).
- `docs/cv_pattern.json` is the measured entry profile (core, core recent, UK core, Strategic Funds, outliers). `docs/backtests.md` tests the route rules on UK entries as the PSC register stood before each announcement.
- `config.yaml` holds every threshold, weight, band and prompt version. `overrides.yaml` lists hand exclusions with reasons.
- `data/` is gitignored except small summaries. A fresh clone rebuilds it from the commands below; the request caches make re-runs cheap.

## Rebuild from scratch

Keys in `.env` (never committed): `CH_API_KEY`, `FCA_API_KEY`, `FCA_API_EMAIL`, `ANTHROPIC_API_KEY`, `ANTHROPIC_WORKSPACE_ID`. `GEMINI_API_KEY` and `MISTRAL_API_KEY` are optional second providers.

```bash
pip install -r requirements.txt
python -m src.ingest.snapshot                       # Stage 1a: Companies House basic data, candidate account categories
python scripts/psc_single.py                        # Stage 1a: PSC register (single zip streamed into parts)
python -m src.ingest.accounts --all                 # Stage 1b: 12 months of iXBRL accounts for the candidates
python -m src.ingest.accounts --build-wide
python -m src.filter.universe                       # Stage 2: size, category, legal form, SIC, disclosure rules
python -m src.filter.routes                         # Stage 3: ownership route from the PSC walk-up
python -m src.ingest.accounts_api --categories GROUP --routes --shard 0/4   # Stage 1c: document API, vision read of PDF filers (run 4 shards)
python -m src.enrich.websites discover --from-universe --shard 0/3          # Stage 4: website discovery (run 3 shards), then:
python -m src.enrich.websites merge && python -m src.enrich.websites fetch
python -m src.score.classify --workers 4            # Stage 5: six sectors, with a verbatim quote from the site
python -m src.score.themes                          # Stage 6: Cinven's 16 sub-sector themes
python -m src.score.rubric --workers 4              # Stage 7: Investment Quality (10 dimensions, rule-set dims 4 and 5)
python -m src.score.why_now                         # Stage 8: dated timing signals (never scored)
python -m src.score.rankings                        # Stage 9: Entry Fit, gates, flags, ranking
python -m src.cv_pattern && python -m src.backtests # calibration and back-tests
python -m src.site.export && python -m src.site.build
```

`scripts/pipeline_tail.sh` re-runs everything downstream of the ingest; every stage is cached and resumable. `scripts/coverage.py` reports how many universe companies have a size read and from which source.

## Reading the scores

Investment Quality (0 to 100) is the rubric: ten dimensions from Cinven's published approach, weighted, with cash generation and growth set by rule from the accounts and the rest set by the model from the website with a verbatim quote. Entry Fit (0 to 100) is deterministic: size against the measured bands, ownership route, growth, margin, sector and data quality. The two are never blended. The ranked list sorts on Investment Quality among companies that pass the gates (sector, actionable route, size at or above the early EBITDA floor, Entry Fit at or above 40). Flags on every row say which figures came from a PDF read, which are turnover only, and which websites are unverified.
