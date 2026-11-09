# Limitations, mitigations and what Cinven's own data would change

Each limit says what the screener does about it and what the fund's own data (deal log, passes, CRM, portfolio metrics) would change. The site carries the same list on the Methods page.

1. **PDF accounts:** Most large UK companies file PDF accounts, and Companies House rasterises them. Only 29k of the 112k FULL, GROUP and MEDIUM filers were in the twelve-month iXBRL bulk product; the rest have no text layer. Mitigation: the document API fetches the latest accounts, the contents page is read for the printed page of the income statement, and a vision model reads that page (revenue, operating profit, profit before tax, EBITDA where stated, period end, unit, consolidated flag); ~74% of documents yield a turnover line; every such figure is flagged "accounts read from a PDF" on the card and in the why-now panel. Figures from a PDF read should be checked against the document before they are quoted. Cinven's data room access or a paid financials feed would replace this step.

2. **Unread accounts:** Size is unverified for companies whose accounts were not yet read. They stay in the universe as "size unverified" comparables and are never ranked. The document API runs at ~1,750 documents an hour on four workers, GROUP-account heads in actionable routes first; the Methods page shows coverage by route at build time.

3. **EBITDA proxy:** The proxy is operating profit plus disclosed depreciation and amortisation. Many filers do not tag D&A, so the proxy is operating profit alone for them (the basis is shown on every card); exceptional items are not stripped out; IFRS 16 leases inflate EBITDA for lease-heavy businesses. A stated adjusted EBITDA is captured when the P&L page or highlights print one.

4. **PSC register:** The register shows 25% bands and the top of the UK chain only. Investors below 25% are invisible; a founder who kept 20% alongside a sponsor is not seen; sponsors behind Jersey, Guernsey, Luxembourg or Delaware vehicles are named only when the vehicle carries the sponsor's name, otherwise the route is "offshore vehicle". Named-partner holdings (Accel-KKR's partners as individual PSCs of Smart Communications) read as individuals. Hold years come from the sponsor's PSC notification date, which can lag or lead completion by months. A sponsor list of ~300 names drives detection; a name not on the list falls to "foreign parent" or "uncertain". Cinven's own secondary pipeline and relationship map would resolve most of this.

5. **Group heads:** Subsidiaries collapse onto the highest UK company filing group accounts. A UK sub-group inside a larger UK group collapses onto the parent; a division that would be a carve-out is not seen on its own. Foreign-headquartered groups show their UK arm, labelled "foreign parent", with the site's UK-headquarters flag as a second check.

6. **Website coverage:** Websites were found for part of the universe, by Seznam search and a name probe. Bing and DuckDuckGo block this egress; discovery runs at ~1,850 companies an hour, largest verified companies first. A short or generic company name can land on another company's site; the name-match and UK-signal checks mark suspects and the classifier skips them. Companies without a website are classified by nobody and stay on the Look Up page.

7. **Rubric source:** The rubric is a model's reading of marketing copy. Eight of ten dimensions are scored from the company website with a verbatim quote; the model is conservative when evidence is thin (score 3, low confidence) and dimensions without evidence are left out of the weighted mean. Two dimensions are rule-scored from the accounts. Sub-scores are double-scored on a sample by a second model and the agreement is reported on the Methods page. Weights are ours. The source pages describe Cinven's approach and deal rationales, and the site says so.

8. **Calibration sample:** The calibration rests on 35 flagship entries and 14 Strategic Fund entries, with 20 outliers measured and excluded (US-led deals, club mega-deals above EUR 5B, minority stakes, fund-to-fund transfers). EV is published for 25 of 35 core entries; EBITDA for 12; equity cheques are undisclosed beyond the Fund 6 LP memo range (EUR 150M to 500M) and a stated EUR 200M minimum. The bands are therefore inferred from EV and EBITDA medians and the UK operating deals, and the Calibration page shows every figure with its source.

9. **Back-tests:** The back-tests check the route mechanics; they do not measure a hit rate. Eleven UK entries fall after the PSC register began; the register was rolled back to the month before announcement and the route re-run (8 of 11 actionable). Pre-deal accounts for the earlier entries came from PDFs the research pass read. The screener today cannot be tested on whether it would have ranked these companies, because their websites and the rubric read today's pages.

10. **Timing signals:** The signals are hypotheses. Hold years, owner ages, register moves, new holding companies, dividends and leverage are facts with dates; whether they mean a sale is coming is a question for the call. They never enter either score.

11. **SIC codes:** The codes are coarse and self-declared. Holding-company codes (64209, 70100) are kept because PE Topcos carry them; a handful of excluded codes remove banks, carriers, pension funds and public bodies; everything else waits for the website classifier.

12. **LLM dependence:** Classification and rubric calls ran on Claude Haiku through the Anthropic API; Gemini was blocked from this session's network. Every answer is cached by prompt so a rebuild costs nothing; the batch path (packed prompts answered by subagents) remains as the fallback.

## What the reviews found and what changed

To be completed after the top-30 review (docs/qa/).
