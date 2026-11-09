# Back-tests on Cinven's UK entries

Computed 2026-11-09T19:48:33+00:00 from docs/research/03_uk_deals_companies_house.json.

**Conclusion:** 11 entries could be tested on the PSC register as it stood the month before announcement; 8 of them sat on a route the screener acts on. Pre-deal size bands: {"unknown": 7, "flagship band": 5, "strategic fund band (turnover only)": 2, "strategic fund band": 2, "too small (turnover only)": 3, "flagship band (turnover only)": 1}. Today the screener reads Cinven as owner for 4 of the entries still held.

| Company | Announced | Deal type | Pre-deal size band | Point-in-time route | Today | Verdict |
|---|---|---|---|---|---|---|
| Enserve (formerly Spice plc) | 2010-09 | public-to-private | unknown | before the PSC register (April 2016) | not a FULL, GROUP or MEDIUM filer on the snapshot | size unknown; exited 2016, today route None |
| Guardian Financial Services | 2011-08 | carve-out | unknown | before the PSC register (April 2016) | not a FULL, GROUP or MEDIUM filer on the snapshot | size unknown; exited 2016, today route None |
| CPA Global | 2012-02 | primary (founding IP law firms, with ICG minority) | unknown |  |  | no Companies House number (registered outside England and Wales) |
| AMCo (Mercury Pharma + Amdipharm) | 2012-08 | secondary buyout (Mercury Pharma from HgCapital, £465M) plus primary from founding family (Amdipharm, Patel brothers, £367M) | unknown | before the PSC register (April 2016) | uk_group | size unknown; exited 2015, today route uk_group |
| HEG (Host Europe Group) | 2013-07 | secondary buyout | unknown | before the PSC register (April 2016) | foreign_parent | size unknown; exited 2017, today route foreign_parent |
| Northgate Public Services | 2014-12 | carve-out | flagship band | before the PSC register (April 2016) | foreign_parent | size flagship band; exited 2018, today route foreign_parent |
| Premium Credit | 2015-01 | secondary buyout | strategic fund band (turnover only) | before the PSC register (April 2016) | uncertain | size strategic fund band (turnover only); exited 2022, today route uncertain |
| Kurt Geiger | 2015-12 | secondary buyout | strategic fund band | before the PSC register (April 2016) | not a FULL, GROUP or MEDIUM filer on the snapshot | size strategic fund band; exited 2025, today route None |
| NewDay | 2016-10 | secondary buyout | too small (turnover only) | uncertain | candidate but failed a universe rule | route not actionable (uncertain); size too small (turnover only) |
| JLA | 2018-05 | secondary buyout | flagship band | sponsor | not a FULL, GROUP or MEDIUM filer on the snapshot | route actionable (sponsor); size flagship band |
| LGC | 2019-11 | secondary buyout | flagship band | foreign_parent | not a FULL, GROUP or MEDIUM filer on the snapshot | route actionable (foreign_parent); size flagship band |
| Compre | 2020-11 | secondary buyout | too small (turnover only) | sponsor | candidate but failed a universe rule | route actionable (sponsor); size too small (turnover only) |
| Miller | 2020-11 | carve-out (from Willis Towers Watson and the partners) | strategic fund band (turnover only) | uncertain | sponsor | route not actionable (uncertain); size strategic fund band (turnover only); exited 2024, today route sponsor |
| True Potential | 2021-09 | primary (founder family and FTV Capital minority sell a majority) | flagship band | founder_family | sponsor | route actionable (founder_family); size flagship band; today reads Cinven as owner |
| IFGL | 2022-02 | secondary buyout | unknown |  |  | no Companies House number (registered outside England and Wales) |
| Policy Expert (QMetric Group) | 2024-09 | secondary (50% stake from Abu Dhabi Investment Authority, which had bought the founder out in Nov 2023) | strategic fund band | foreign_parent | sponsor (group head sponsor) | route actionable (foreign_parent); size strategic fund band; today reads Cinven as owner |
| Grant Thornton UK | 2024-11 | primary (partnership sells its advisory and tax practice to a PE-backed platform; audit stays in the LLP) | flagship band (turnover only) | uk_group | founder_family | route actionable (uk_group); size flagship band (turnover only); today route founder_family (Cinven not detected) |
| Smart Communications | 2025-08 | secondary buyout (majority; Accel-KKR retains a minority) | flagship band | uncertain | sponsor (group head sponsor) | route not actionable (uncertain); size flagship band; today reads Cinven as owner |
| Objectway | 2025 | primary (founder-led company) | unknown | foreign_parent | sponsor | route actionable (foreign_parent); size unknown; today reads Cinven as owner |
| Flint Global | 2025-12 | primary (majority investment from founders and partners; buys out Growth Capital Partners' 2021 minority) | too small (turnover only) | sponsor | candidate but failed a universe rule | route actionable (sponsor); size too small (turnover only) |
