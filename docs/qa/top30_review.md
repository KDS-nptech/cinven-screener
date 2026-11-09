# Hand review of the ranked list

9 November 2026. All 49 companies ranked at 21:22 were read against their Companies House record, PSC chain and website. Outcome across three rounds: 32 excluded by hand, 2 corrected, six rules added. 91 companies remain ranked. Reasons live in overrides.yaml and show on each company page.

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

## Second round after the Financial Services read (22:10)

The four readers were moved to the 905 FS-coded actionable companies (610 gave a turnover line). Twelve FS companies entered the ranking; all twelve were read and two remain.

- **Excluded by hand:** NewDay Cards (a Cinven and CVC company until KKR bought the consumer credit business in September 2025), XTX Markets and XTX Markets Trading (proprietary market maker), Winton and Arini (hedge fund managers), Jupiter Asset Management Limited (subsidiary of a listed company; the word Fund in the parent's name was a false sponsor match), Lucus Wealth (£359M turnover read for a small advice firm; implausible).
- **Removed by rule:** a website that does not carry the company's name now blocks ranking (Canaccord Genuity Wealth, J Rothschild Capital Management and Porterbrook Leasing had another firm's site); a company whose own name matches a sponsor (BlackRock, CVC Advisers, Ares, Partners Group, Tikehau, Antin, Octopus Investments) is an investment firm and never ranks.
- **Corrected:** Woodthorpe Hall Garden Centres trades as British Garden Centres; website match set by hand.
- **Left ranked:** Evolution Lending (Evolution Money, second-charge lender, founder-owned). Lindsell Train was left in at this round and excluded in the third.

## Third round after the wide-table fix (22:36)

Fixing the dropped consolidated PDF figures took the at-scale set from 180 to 412 and the ranked list to 112. All 112 were read; 19 more were excluded by hand and one rule was added.

- **Rule:** turnover above £5B read from a PDF never ranks (Hampden Holdings at £210B and Everards at £37B were unit errors).
- **Excluded by hand:** AirTanker and Onpath Energy (infrastructure concessions); AllianceBernstein, Hearst Networks UK and Vice Studios (UK arms of foreign groups); Love Productions (majority-owned by Sky); Lindsell Train, Egerton and Silchester (founder-controlled asset managers, treated the same way as Winton and Arini); MAPP Holdings, GlobalData, Imperial London Hotels, Quartzinvest, PGI Group, DCS, MCG, The Little Group and Newarthill (wrong or doubtful website); Whitworths (implausible turnover and wrong label).
- **Left ranked with a caveat:** A.E.S. Engineering shows a stray 3i label beside its founder owner; FD London and Harris Holdings sit near the bottom on websites that need checking; Moto and Welcome Break are sponsor-owned at flagship size with generic sponsor labels (Ventures, LP).

## Finding for the reader

Financial Services stays the thinnest sector: 2 of 91 ranked (Mattioli Woods under Pollen Street, and Evolution Money). The FS companies a buyout fund wants (brokers, wealth platforms, fund administrators) sit in holding-company SIC codes or inside groups whose PDF accounts are still unread, and the FS-coded population is dominated by asset managers' UK arms, lenders and trading firms.
