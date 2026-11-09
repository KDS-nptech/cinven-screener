# Hand review of the ranked list

9 November 2026. All 49 companies ranked at 21:22 were read against their Companies House record, PSC chain and website. Outcome: 6 excluded by hand, 5 removed by a new rule, 1 corrected, 2 rule fixes. Reasons live in overrides.yaml and show on each company page.

## Excluded by hand

- **Vantage Data Centers UK (06132144):** UK arm of a US data centre platform; PSC is DigitalBridge Group, Inc.; no UK employees in the accounts.
- **Quadrature Capital (09516131):** proprietary trading firm; turnover is trading income.
- **The Girls' Day School Trust (00006400):** registered charity; the website found was a recruitment portal.
- **Blick Rothenberg (10238654):** one firm inside Azets (Hg and PAI); accounts cover the firm only.
- **Walstead Bicester (06941589):** one plant of Walstead Group (Rutland Partners).
- **Seasalt Holdings (04512575):** wrong website (seasalt.com is a US food business), so the label and rubric read the wrong pages.

## Removed by rule

- **Listed companies read from a PDF annual report never rank:** London Stock Exchange Group, Genus, Hays, Dunelm and James Fisher. The reader took a parent-company or segment line from reports of 150 pages or more (LSEG at £724M turnover, Dunelm at £97M). They stay as comparables with the reason shown. iomart, read from iXBRL, stays ranked.
- **Employee ownership trusts never rank** (MAP Group and 11 others).

## Corrected

- **Wood Mackenzie (SC222302):** the register shows "Charterhouse Nadia 5 Limited", a holding company named in Charterhouse's 2009 to 2012 ownership. Sponsor set to Veritas Capital, hold from February 2023 (press).

## Rule fixes

- **Project-named vehicles:** "Apollo 2024 Bidco Limited" (HealthNet Homecare) matched the sponsor name Apollo. A name of the form word, year, Bidco now reads as an acquisition vehicle with the sponsor unnamed.
- **Sponsor tokens:** see docs/research-log.md (Trustees, Nominees, trading houses, "Partners Group" inside "Evelyn Partners Group").

## Left in, with a caveat

- **Lindar Media (08939139):** the classifier calls it data aggregation software; it operates the MrQ online gaming brand. Low rank, label unreliable.
- **Uniserve (01826635):** the largest of four companies under GB Global Management; figures cover Uniserve Limited only.
- **Platinum Retail, Pozitive Energy, Harron Homes:** in scope by the rules; forecourts, energy supply and housebuilding sit outside Cinven's themes and score at the bottom.

## Finding for the reader

No Financial Services company ranks in this build. FS groups at scale mostly file PDF group accounts and their size was unread at review time; a targeted read of 905 FS-coded companies started at 21:26.
