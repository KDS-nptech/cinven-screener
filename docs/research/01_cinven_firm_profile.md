# 01. Cinven firm profile (investor calibration)

Status: v3, substantially complete (agent 01). Last written 2026-11-09 19:27 GMT. All eight sections sourced; rubric, taxonomy and sources complete. Raw pages under docs/research/raw/01/ (cinven.com corporate pages; 95 news-insights articles under raw/01/news/; 96 team pages under raw/01/team/; SEC IAPD firm search JSON; Oregon OIC 2016 board book under raw/01/lp/). Queued for manual review: Wayback Machine snapshots (web.archive.org refused connections through the proxy), SEC IAPD firm summary API (blocked), PSERS 2016 resolution PDF (redirects to pa.gov search).

## Conclusion

Cinven is a partner-owned, London-headquartered European buyout firm that in 2026 deploys two vehicles side by side: the €13.2B Eighth Cinven Fund (flagship, closed January 2024; control buyouts with disclosed enterprise values of ~€1B to ~€5B) and the €2.3B Strategic Fund 2 (closed September 2026; control positions in founder-owned, asset-light European mid-market businesses in Financial Services, Business Services and TMT). The only published hard criteria are from a 2016 LP paper for Fund 6: "enterprise values above €300 million" and equity cheques of "€150 million to €500 million", control only. Scaling that by fund size (Fund 8 is 1.9x Fund 6) gives a flagship equity cheque of ~€300M to ~€1B and EV of ~€600M+ today (estimate, medium confidence), consistent with the 2024 to 2026 disclosed deals (Alter Domus €4.9B, idealista €2.9B, Vitamin Well ~€3B, Theramex ~€2.6B, UAX ~€2B, Grant Thornton UK ~£1.5B, Artefact ~€1B, Smart Communications >$1B). SF2 deals are undisclosed; the ~€2.3B fund and 16-person team imply ~€100M to ~€400M equity per platform (estimate, low confidence).

The published investment filter is stable across 2024 to 2026 deal announcements and strategy pages: a market-leading or scarce platform in a large, structurally growing market; recurring or repeat revenue with high retention; a track record of organic growth with margin expansion; cash generation and resilience; buy and build potential in a fragmented market; international expansion runway; a founder or management team that reinvests; and since 2025 an explicit "well positioned to drive value from AI" test. Deals are originated through a "Sector-Regional origination matrix" (six sector teams crossed with regional teams in seven offices), long pre-deal relationships with founders and corporates, and thematic sub-sector targeting; in Fund 8 "eight out of ten investments to date are primary or founder-led". Sources: https://www.cinven.com/approach/ ; https://www.cinven.com/news-insights/cinven-closes-second-strategic-fund/ ; https://www.cinven.com/news-insights/exits-to-strategics/ ; https://www.cinven.com/news-insights/cinven-raises-14-5-billion-for-the-eighth-cinven-fund/ ; raw/01/lp/oregon_oic_2016.txt.

Screener calibration implied: European HQ (or US business with a European growth angle), one of six sectors, control available from a founder, family, corporate parent or sponsor, EBITDA roughly €50M+ for the flagship (~€600M+ EV at typical sector multiples; estimate) or ~€10M to ~€40M for SF2 (estimate), and the attribute set in the Rubric candidates section. Outliers to exclude from the typical-entry calibration: SFF and SF2 deals (mid-market), minority positions (Fressnapf, Regenity, Policy Expert 50%, Envu post-GIC), mega-deals (TKE €17.2B, STADA, MasOrange), add-ons bought by portfolio companies, and US-office-led deals (Salsify, Archer, Smart Communications, Regenity, Taxwell).

## 1. Firm facts

| Item | Fact | Source |
|---|---|---|
| Founding | Founded 1977 as part of the British Coal pension scheme; name abbreviates "Coal Industry Nominees Ventures" | https://www.cinven.com/about/company/ |
| Independence | Management buyout from previous owner 1995; "entirely partner-owned since then" | https://www.cinven.com/about/company/ |
| Ownership | "Cinven is owned by and for the benefit of its Partners"; only business is management of PE funds | https://www.cinven.com/about/governance/ |
| HQ | Cinven Limited, 21 St. James's Square, London SW1Y 4JZ | https://www.cinven.com/contact-us/ |
| Offices (7 listed) | Frankfurt (Cinven GmbH, Omniturm), London, Luxembourg (Cinven Luxembourg S.à r.l), Madrid (Cinven Spain S.L.U.), Milan (Cinven S.r.l.), New York (Cinven, Inc., Tower 49), Paris (Cinven France SAS) | https://www.cinven.com/contact-us/ |
| Office count inconsistency | Approach page: "seven global offices" and also "eight regional offices across Europe and the US"; company page infographic "8 Offices"; Feb 2024 release lists eight including Guernsey | https://www.cinven.com/approach/ ; https://www.cinven.com/about/company/ ; https://www.cinven.com/news-insights/cinven-transitions-management-team/ |
| Headcount | ">250 Team members" (approach page); "employee numbers more than doubling to 260" (Feb 2024); "more than 170 people" (May 2019) | https://www.cinven.com/approach/ ; https://www.cinven.com/news-insights/cinven-transitions-management-team/ ; https://www.cinven.com/news-insights/cinven-raises-e10-billion-for-the-seventh-cinven-fund/ |
| Team page count | 263 named individuals on cinven.com/team as of 2026-11-09 (raw/01/team_list.tsv) | https://www.cinven.com/team/ |
| Total funds raised | ">€50bn" (approach page); "more than €55bn" (Feb 2024 release); "c. €37 billion" (May 2019) | https://www.cinven.com/approach/ ; https://www.cinven.com/news-insights/cinven-transitions-management-team/ ; https://www.cinven.com/news-insights/cinven-raises-e10-billion-for-the-seventh-cinven-fund/ |
| AUM (firm statement) | "AUM has increased from €11bn to €44bn" over 2016 to Feb 2024 (definition not stated) | https://www.cinven.com/news-insights/cinven-transitions-management-team/ |
| SEC RAUM | Cinven Limited (CRD 323818, SEC 801-137029) is an ACTIVE SEC registrant at 21 St James's Square; third-party Form ADV summaries show regulatory AUM $42.71B (discretionary $40.87B, non-discretionary $1.84B), 22 private funds with gross assets $40.81B, 150 employees, 23 accounts; the aggregator pages show no filing date (FINTRX shows "Registered since August 7, 2026", which may be a re-registration date) | raw/01/sec_iapd_firm_search.json ; https://privatefunddata.com/fund-companies/cinven-limited/ ; https://fintrx.com/firms/firm/cinven-limited-323818 |
| Other SEC entities | Cinven, Inc. (CRD 323534, SEC 801-127053) ACTIVE, New York; Cinven Limited (CRD 163484, Guernsey, 802-76366) INACTIVE; Cinven Capital Management (V) General Partner Limited (CRD 163481) INACTIVE | raw/01/sec_iapd_firm_search.json |
| Realised proceeds | "€52bn" (approach page); "c. €47 billion" at Jan 2024; "c. €11 billion of realised value in the last three years" (May 2019) | https://www.cinven.com/approach/ ; https://www.cinven.com/news-insights/cinven-raises-14-5-billion-for-the-eighth-cinven-fund/ ; https://www.cinven.com/news-insights/cinven-raises-e10-billion-for-the-seventh-cinven-fund/ |
| Realisations since Jan 2024 | "c. €12 billion of realisations while investing more than €6 billion" (Dec 2025); "nearly €11 billion in proceeds since January 2024 and distributing close to 30% of NAV over the past year" (Oct 2025); PEI: €6.7B realised in 2024, "signed 14 realisations last year and invested €4bn" | https://www.cinven.com/news-insights/cinven-announces-leadership-update/ ; https://www.cinven.com/news-insights/exits-to-strategics/ ; https://www.privateequityinternational.com/institution-profiles/cinven.html |
| Investments | "150+"; "realised or listed more than 115 investments"; "c. 135 companies" by May 2019 | https://www.cinven.com/approach/ ; https://www.cinven.com/news-insights/cinven-raises-14-5-billion-for-the-eighth-cinven-fund/ |
| Portfolio companies | "40+" (46 listed as Current on portfolio page, 2026-11-09) | https://www.cinven.com/about/company/ ; https://www.cinven.com/portfolio/ |
| Sectors | 6: Business Services, Consumer, Financial Services, Healthcare, Industrials, TMT | https://www.cinven.com/approach/ |
| Firsts claimed | "raised the first billion-plus Europe-focused fund in 1996, led the first €1bn European MBO in 1998" | https://www.cinven.com/news-insights/cinven-transitions-management-team/ |
| Add-on activity | "over the two most recent Funds, Cinven has completed more than 200 add-on acquisitions through its portfolio companies" (May 2019, Funds 5 and 6) | https://www.cinven.com/news-insights/cinven-raises-e10-billion-for-the-seventh-cinven-fund/ |
| LP base by type | Public pension 43%, SWF 23%, insurers 10%, family offices and private wealth 7%, endowments and others 6%, fund of funds 5%, corporate pensions 3%, banks 3% | https://www.cinven.com/about/company/ |
| LP base by geography | Americas 39%, Europe 28%, Asia-Pacific 24%, Middle East 10% | https://www.cinven.com/about/company/ |
| Leadership | Co-Managing Partners Bruno Schick (Frankfurt; Head of DACH and Emerging Europe; chairs Portfolio Review Committees; leads portfolio, value creation, exits) and Jorge Quemada (Madrid; Head of Iberia; chairs Investment Committee; leads investment activity) | https://www.cinven.com/about/governance/ ; https://www.cinven.com/news-insights/cinven-announces-leadership-update/ |
| Dec 2025 leadership change | Supraj Rajagopalan (Co-Managing Partner, CEO) and Alex Leslie (COO and CFO) stepped down; Alexandra Hess appointed President; Maxim Crewe appointed Head of Countries and Sectors; Mike Colato interim COO and CFO; Stuart McAlpine to Chairman Emeritus | https://www.cinven.com/news-insights/cinven-announces-leadership-update/ |
| Investment Committee (Dec 2025) | Chair Jorge Quemada; permanent members Bruno Schick, Pontus Pettersson, Thomas Railhac, David Barker | https://www.cinven.com/news-insights/cinven-announces-leadership-update/ |
| Executive Committee | Alexandra Hess, Bruno Schick, Jorge Quemada, Maxim Crewe, Pontus Pettersson, Thomas Railhac | https://www.cinven.com/about/governance/ |
| Operating Committee | Alexandra Hess, Alison Raymond (CCO), Babett Carrier (Partner and General Counsel), Caroline Rawes (Partner and CHRO), Dominic Smyth (CFO and COO, appointed 1 Sep 2026) | https://www.cinven.com/about/governance/ ; https://www.cinven.com/news-insights/cinven-appoints-dominic-smyth-as-chief-financial-officer-and-chief-operating-officer/ |
| UK regulation | Cinven Limited (Registered in England No. 2192937; FCA FRN 938064) authorised and regulated by the FCA; registered as investment adviser with US SEC | https://www.cinven.com/ifpr-disclosure/ ; site footer |
| Luxembourg AIFM | Cinven Fund Management S.à r.l., RCS B287169, 4 Rue Albert Borschette, L-1246, CSSF-regulated AIFM with MiFID top-up; Spanish branch in Madrid under CNMV | https://www.cinven.com/cinven-luxembourg-aifm/ |
| Guernsey | Cinven Capital Management (SFF) General Partner Limited regulated by Guernsey Financial Services Commission | https://www.cinven.com/about/governance/ |
| IFPR disclosure (Cinven Limited, YE 31 Dec 2025, dated 30 Sep 2026) | Own funds £50.4M; total remuneration £198.8M (fixed £26.3M, variable £172.5M); 13 material risk takers; Board: Quemada, Hess, Schick, Crewe, Pettersson, Railhac; revenue is advisory and management fees from group fund managers; strategies "do not employ the use of leverage on a substantial basis" | https://www.cinven.com/ifpr-disclosure/ |
| Walker Guidelines | Cinven commits to conform and promotes conformity by portfolio companies | https://www.cinven.com/about/governance/ |
| PRI | Signatory since 2009 | https://www.cinven.com/about/company/ |
| Track record (Fund 6 LP paper, Sep 2015) | Five prior funds: €16.8B invested since 1996, aggregate net IRR 14.8%, net TVPI 1.7x; all but Fund II first or second quartile per Cambridge Associates; 65 investment professionals and 21 partners | raw/01/lp/oregon_oic_2016.txt (https://www.oregon.gov/treasury/invested-for-oregon/Documents/oic-meeting-archives/2016/agendas/2016.03.29-OIC-Special%20Meeting-PUBLIC-BOOK.pdf) |
| Track record (May 2019) | Fund 5 net DPI c. 1.4x; nine of 17 Fund 5 investments exited at c. 3.2x aggregate; exits since Jan 2017 include CeramTec 3.2x, Medpace 3.5x, Ufinet 6.0x | https://www.cinven.com/news-insights/cinven-raises-e10-billion-for-the-seventh-cinven-fund/ |

## 2. Funds

| Fund | Vintage or close | Size | Notes | Source |
|---|---|---|---|---|
| Fund 1 | 1996 | €1.6B | "first billion-plus Europe-focused fund" | https://www.cinven.com/about/company/ ; https://www.cinven.com/news-insights/cinven-transitions-management-team/ |
| Fund 2 | 1998 | €2.4B | | https://www.cinven.com/about/company/ |
| Fund 3 | 2001 | €4.4B | | https://www.cinven.com/about/company/ |
| Fund 4 | 2006 | €6.6B | | https://www.cinven.com/about/company/ |
| Fund 5 | 2012 vintage | €5.3B | first close €3B; upsized to €5.3B; 17 investments | https://www.cinven.com/about/company/ ; https://www.unquote.com/uk/news/71694/fifth-cinven-fund-holds-first-close-at-eur3bn ; https://www.cinven.com/news-insights/cinven-raises-e10-billion-for-the-seventh-cinven-fund/ |
| Fund 6 | 2016 | €7B hard cap, raised in four months | 15 to 20 investments planned; 15 companies in 11 countries by May 2019 | https://www.cinven.com/about/company/ ; https://www.cinven.com/news-insights/cinven-raises-e10-billion-for-the-seventh-cinven-fund/ ; raw/01/lp/oregon_oic_2016.txt |
| Fund 7 | 2019 (closed 2 May 2019) | €10B hard cap (c. $11B), under four months, 180+ investors in 30+ countries | "European buyouts and selective North American investments" | https://www.cinven.com/news-insights/cinven-raises-e10-billion-for-the-seventh-cinven-fund/ |
| Strategic Financials Fund (SFF) | 2022 | €1.5B | financial services; GP regulated in Guernsey; deals Compre, Finaxy, IFGL, Policy Expert, Miller (realised), Säkra | https://www.cinven.com/about/company/ ; https://www.cinven.com/about/governance/ ; https://www.cinven.com/portfolio/ |
| Fund 8 (Eighth Cinven Fund) | 2023 vintage, final close 9 Jan 2024 | €13.2B ($14.5B) hard cap | "nearly 30% larger than" Fund 7; two investments by Feb 2024; "eight out of ten investments to date are primary or founder-led" (Oct 2025); still the active flagship in Nov 2026 releases | https://www.cinven.com/news-insights/cinven-raises-14-5-billion-for-the-eighth-cinven-fund/ ; https://www.cinven.com/news-insights/cinven-transitions-management-team/ ; https://www.cinven.com/news-insights/exits-to-strategics/ |
| Barentz Continuation Fund | Mar 2024 | ~€850M (Secondaries Investor, "understood to be") | single-asset CV for Barentz, led by Goldman Sachs and AlpInvest; "Barentz II" is the current portfolio entry; SEC list shows "Barley (no.1) LP" $537M gross | https://www.pei-secondariesinvestor.com/goldman-sachs-alpinvest-lead-cinvens-barentz-secondary/ ; https://www.privateequityinternational.com/institution-profiles/cinven.html ; https://privatefunddata.com/fund-companies/cinven-limited/ |
| Strategic Fund 2 (SF2) | final close 8 Sep 2026 | c. €2.3B, "exceeding its target fund size by c. 50%" (implies ~€1.5B target) and "c. 75% increase" on SFF | Bloomberg (Jun 2025) reported a €1.5B to €2B target; four investments signed at close: Objectway, Flint Global, Ongoing Warehouse, Optio; 16-person dedicated team co-led by Luigi Sbrozzi and Michael Weber | https://www.cinven.com/news-insights/cinven-closes-second-strategic-fund/ ; https://pe-insights.com/?p=342854 ; https://privateequitywire.com/news/cinven-closes-e2-3bn-strategic-fund-2 |
| "Cinven Anatole" | in market since Dec 2024 per PEI (size locked) | unknown | likely a co-invest or continuation vehicle; not referenced on cinven.com | https://www.privateequityinternational.com/institution-profiles/cinven.html |

SEC-reported fund vehicles (gross asset values from Form ADV as summarised by privatefunddata.com, no date given): Seventh Cinven Fund (no.1) LP $15.59B; Eighth Cinven Fund (no.1) $7.13B, (no.2) $3.65B, (no.3) $3.7B; Cinven Strategic Fund 2 (no.1) LP $2.4B; Sixth Cinven Fund (no.1) to (no.4) $1.72B, $1.39B, $815M, $1.47B; Barley (no.1) LP $537M. Source: https://privatefunddata.com/fund-companies/cinven-limited/.

Fund IX: no "Ninth Cinven Fund" or "Fund IX" announcement found on cinven.com or in web search as of 2026-11-09 (queries run: "Ninth Cinven Fund", "Cinven Fund IX", "Cinven fundraise 2025", "Cinven fundraise 2026"). The only 2025 to 2026 fundraising news is SF2. Co-invest: GIC minority in Envu (Mar 2026), La Caisse co-investment in Optio (Jul 2026), Mubadala in UAX (Oct 2025), Ontario Teachers' in group.One (2022); IR team "capital raising for numerous co-investments" (Jan 2025). Sources: https://www.cinven.com/news-insights/cinven-welcomes-strategic-minority-investment-in-envu-from-gic/ ; https://www.cinven.com/news-insights/optio-acquisition/ ; https://www.cinven.com/news-insights/cinven-announces-partner-promotions-5/.

## 3. Published investment criteria (cinven.com and LP papers)

| Criterion | What Cinven publishes | Source |
|---|---|---|
| Sector focus | Six sectors only; "we don't get distracted by anything else" | https://www.cinven.com/approach/ |
| Thematic | "We invest behind long-term, structural trends"; "we are micro investors and the structural micro trends we target" (Quemada, May 2025) | https://www.cinven.com/approach/ ; https://www.cinven.com/news-insights/investing-in-europe-six-reasons-to-be-cheerful/ |
| Target company (flagship) | "control positions in growth-oriented, market leading, cash generative companies with resilient characteristics" (McAlpine, Jan 2024) | https://www.cinven.com/news-insights/cinven-raises-14-5-billion-for-the-eighth-cinven-fund/ |
| Target company (SF2) | "control positions in high-growth, asset-light opportunities across Financial Services, Business Services and TMT" in the European mid-market; "high-quality, founder-owned businesses" | https://www.cinven.com/news-insights/cinven-closes-second-strategic-fund/ |
| EV and equity range (only published numbers) | Fund 6 (2016): "enterprise values above €300 million, via equity investments ranging in size from €150 million to €500 million"; "15-20 investments"; "The Firm only seeks control investments" | raw/01/lp/oregon_oic_2016.txt (Oregon OIC, 29 Mar 2016) |
| Control vs minority | Flagship and SF2 state control. Published minority exceptions: Fressnapf (2024), Regenity (alongside Linden, 2026), Policy Expert (50%, 2024); partial sell-downs to minority: SYNLAB stakes, Envu after GIC | https://www.cinven.com/news-insights/cinven-sale-of-arcaplanet-to-fressnapf-and-concurrent-minority-investment-in-fressnapf-group/ ; https://www.cinven.com/news-insights/regenity-biosciences-announcement/ ; https://www.cinven.com/news-insights/policy-expert-positioned-for-growth-as-cinven-acquires-50-shareholding/ |
| Deal types | "Europe remains a land of primary deals – carve-outs and founder-led divestments – which have been a sweet spot for our last three funds" (Quemada); founders: "18 portfolio companies led or owned by their founders" since Fund 6; secondary buyouts (UAX from CVC, Theramex from Carlyle and PAI, Nutrisens from Sagard, Smart Communications from Accel-KKR, Artefact from Ardian); P2P and IPO exits (Allegro, HBX, SYNLAB) | https://www.cinven.com/news-insights/investing-in-europe-six-reasons-to-be-cheerful/ ; https://www.cinven.com/news-insights/why-founders-choose-cinven/ |
| Sourcing model | "Sector-Regional origination matrix"; "sector-country matrix" | https://www.cinven.com/approach/ ; https://www.cinven.com/news-insights/cinven-closes-second-strategic-fund/ |
| Local presence | "people on the ground in all the markets in which we invest"; "Trust-based relationships are key to unlocking primary transactions"; "Some of Cinven's deals have been more than twenty years in the making" | https://www.cinven.com/approach/ ; https://www.cinven.com/news-insights/investing-in-europe-six-reasons-to-be-cheerful/ |
| Diligence | "forensic in our diligence"; growth strategy and management relationships built "long before we actually invest"; looks for "true transformation potential" | https://www.cinven.com/approach/ |
| Macro stance | Consumer: "we assess any potential investment against inflationary, deflationary and recessionary pressures"; "almost completely agnostic to the macro environment" | https://www.cinven.com/news-insights/active-investing-in-consumer-mega-trends/ |
| Hold period | Not stated as a target. Evidence: first sponsor round "often precedes another round of financial sponsorship after four to five years" (Nitel exited two years early); RBE 2021 to 2026; Arcaplanet 2022 to 2024; Viridium 2014 to 2025; Ufinet "10 years" | https://www.cinven.com/news-insights/exits-to-strategics/ ; https://www.cinven.com/news-insights/ufinet-10-years-of-transformation/ |
| Exit planning | "exit planning is prioritised from day one"; exit templates maintained through hold; PRC "hold/sell" analysis for every investment at annual "Super Days"; five strategic exits since Jan 2024 at "nearly 3x" weighted MOIC | https://www.cinven.com/news-insights/exits-to-strategics/ |
| ESG gate | Potential investments reviewed "against our ESG framework"; post-deal targets for decarbonisation, diversity, governance | https://www.cinven.com/approach/ |
| Value creation: top line | Buy and build, pricing models, sales acceleration, internationalisation | https://www.cinven.com/approach/ |
| Value creation: margin and cash | Cost optimisation, procurement, cash | https://www.cinven.com/approach/ |
| Value creation: strategic transformation | Digital commerce, investment data analytics, data and AI, ESG; in-house digital and AI team under Paul Vega; Head of AI and Technology Transformation Stuart Walker | https://www.cinven.com/approach/ ; https://www.cinven.com/team/paulvega/ ; https://www.cinven.com/team/stuart-walker/ |
| Governance of value creation | Deal team, Portfolio Review Committee, portfolio team, capital markets team, senior advisor bench; operating KPIs linked to value creation plan | https://www.cinven.com/approach/ |
| Value creation outcome claimed | Fund 8 "average earnings growth of 27% over the past twelve months" (Oct 2025); Fund 6 unrealised portfolio "double-digit EBITDA growth" (2018) | https://www.cinven.com/news-insights/exits-to-strategics/ ; https://www.cinven.com/news-insights/cinven-raises-e10-billion-for-the-seventh-cinven-fund/ |
| Geography | "European buyouts and selective North American investments" (2019); US office "supporting portfolio growth for European businesses expanding into the Americas" (2026); Europe preferred for "valuation gap with the US" and primary deal flow (Quemada) | https://www.cinven.com/news-insights/cinven-raises-e10-billion-for-the-seventh-cinven-fund/ ; https://www.cinven.com/news-insights/cinven-closes-second-strategic-fund/ ; https://www.cinven.com/news-insights/investing-in-europe-six-reasons-to-be-cheerful/ |
| US deals | North America regional team led by Julia Kahr (Partner, New York); US-headquartered investments include Salsify (Boston), Regenity, Smart Communications, Archer, National Seating & Mobility, BioAgilytix, Taxwell, Nitel (realised) | https://www.cinven.com/news-insights/regenity-biosciences-announcement/ ; https://www.cinven.com/news-insights/cinven-to-acquire-salsify/ |

## 4. Sector team views

### Business Services (Head: Rory Neeson, London)
| Theme | Evidence | Source |
|---|---|---|
| Fund services | "Fund services has been a priority subsector for Cinven's Business Services team"; attractions: structural growth of private capital, "increasing regulation", outsourcing, "strong revenue visibility and cashflow generation", fragmented market for buy and build | https://www.cinven.com/news-insights/cinven-agrees-to-make-significant-strategic-investment-in-alter-domus/ |
| People-based professional services | "extensive experience of successfully investing in people-based professional service providers such as Alter Domus, Miller and CPA Global"; Flint Global in a "fast-growing segment of the professional services industry" with "attractive recurring revenue model" | https://www.cinven.com/news-insights/cinven-news-grant-thornton/ ; https://www.cinven.com/news-insights/cinven-to-invest-in-flint-global/ |
| GRC and services-software overlap | Business Services team "identified GRC as a core investment theme" in 2020; found "a highly fragmented marketplace across Europe" then widened to the US with the New York team to find Archer | https://www.cinven.com/news-insights/living-in-the-matrix-hitting-the-bullseye-with-archer-through-cross-team-collaboration/ |
| Data and AI consulting | Artefact: "Large, high-growth data and AI consulting sector"; "repeatable revenue streams from blue-chip corporate customers"; "scarce global platform of scale"; "Buy and build track record in globally fragmented market" | https://www.cinven.com/news-insights/cinven-in-exclusive-negotiations-to-acquire-artefact/ |
| Private education | UAX: "structurally growing and resilient Spanish private higher education market"; demographics, international students, lifelong learning; founder reinvesting | https://www.cinven.com/news-insights/cinven-to-acquire-universidad-alfonso-x-el-sabio-group-from-cvc-funds/ |
| Pharma cold chain | Envirotainer: zero Swedish clients at entry, R&D nearly doubled 2017 to 2021, volumes tripled in India, Korea, China | https://www.cinven.com/news-insights/the-nordic-opportunity-five-elements-for-success/ |
| Energy and sustainability services | Amara NZero (majority from ProA Capital, Apr 2023) | https://www.cinven.com/news-insights/cinven-agrees-to-acquire-a-majority-stake-in-amara-nzero-from-proa-capital/ |

### Consumer (Head: Maxim Crewe, London)
| Theme | Evidence | Source |
|---|---|---|
| Published Consumer thesis (Oct 2024, PEI interview) | Mega-trends over sub-sectors: experience over goods, health and wellness, pet market, wealth polarisation, ageing, eco-conscious consumer. Favoured models: "Smaller-ticket consumer products or services with repeat-purchase models"; "Differentiated consumer propositions with robust pricing power"; "Companies down the value chain" one or more steps from the consumer. Playbook: talent, digitalisation and AI, buy and build, "Consolidating fragmented markets", internationalisation, ESG | https://www.cinven.com/news-insights/active-investing-in-consumer-mega-trends/ |
| Health and wellness | Vitamin Well: "structural shift away from less healthy snacks and drinks"; "track record of profitable organic growth"; US volumes "more than doubled" since entry | https://www.cinven.com/news-insights/cinven-to-become-lead-investor-in-vitamin-well/ ; https://www.cinven.com/news-insights/the-nordic-opportunity-five-elements-for-success/ |
| Pet care | PPF "growth through premiumisation, M&A and Sustainability"; Arcaplanet to Fressnapf with reinvestment | https://www.cinven.com/news-insights/ppf-a-story-of-growth/ ; https://www.cinven.com/news-insights/arcaplanet-preparation-learning-and-long-term-relationships-create-real-value/ |
| QSR and franchising | RBE exit: "thematic approach to investing behind consumer megatrends" (Corà); "partnering with strong founders and management teams" (Jönas) | https://www.cinven.com/news-insights/cinven-agrees-to-the-sale-of-restaurant-brands-europe/ |
| Consumer plus TMT crossover | Salsify brings "both our TMT and Consumer sector teams" | https://www.cinven.com/news-insights/cinven-to-acquire-salsify/ |

### Financial Services (Head: Maxim Crewe; Strategic Funds co-heads Luigi Sbrozzi and Michael Weber)
| Theme | Evidence | Source |
|---|---|---|
| Specialty underwriting and MGAs | Optio: "Specialty MGAs are expected to continue to outgrow the broader Property & Casualty insurance sector"; "capital-light business model"; fragmented market for M&A; prior Compre, Miller, Policy Expert | https://www.cinven.com/news-insights/optio-acquisition/ |
| Accounting and professional services | "Accounting Services has been a priority sector for Cinven's Financial Services team" (Jazaerli); Grant Thornton UK (2024) and Germany (2025) | https://www.cinven.com/news-insights/cinven-news-grant-thornton/ ; https://www.cinven.com/news-insights/grant-thornton-germany-and-cinven-enter-into-strategic-partnership/ |
| Wealth tech and financial software | Objectway: "mission-critical, modular, front-to-back office software"; "highly recurring revenues and earnings visibility and strong cash flow generation" | https://www.cinven.com/news-insights/objectway-investment/ |
| Life insurance consolidation and run-off | Viridium: "consolidation of the highly fragmented German life insurance sector" (2014 to 2025, €67B AUM at exit); Compre legacy P&C run-off | https://www.cinven.com/news-insights/exits-to-strategics/ ; https://www.cinven.com/news-insights/cinven-to-sell-viridium-group/ |
| Insurance distribution | Finaxy (France, from Ardian), Säkra (Sweden), Policy Expert (UK, 50%) | https://www.cinven.com/news-insights/cinven-enters-into-exclusive-negotiations-with-ardian-to-acquire-the-finaxy-group/ |
| Consumer credit and advice platforms | NewDay portfolio sold to KKR (Sep 2025); True Potential | https://www.cinven.com/news-insights/kkr-agrees-to-acquire-newdays-consumer-credit-portfolio-from-cinven-and-cvc/ |

### Healthcare (Head: Pontus Pettersson, London; Partner Philipp Meyer, Frankfurt)
| Theme | Evidence | Source |
|---|---|---|
| Specialty pharma, women's health | Theramex: "structurally growing segment of specialty pharma", "substantial unmet medical need", in-licensing track record, "resilient commercial model" | https://www.cinven.com/news-insights/cinven-to-acquire-theramex/ |
| Medical nutrition | Nutrisens: "Large and resilient medical nutrition market" driven by demographics; "double-digit organic growth while increasing its margins" | https://www.cinven.com/news-insights/cinven-in-exclusive-negotiations-with-sagard-to-acquire-nutrisens/ |
| Regenerative biomaterials and medtech manufacturing | Regenity (Feb 2026, with Linden, US) | https://www.cinven.com/news-insights/regenity-biosciences-announcement/ |
| Diagnostics, labs, life science tools, CROs | SYNLAB, LGC, BioAgilytix, Medpace and Clario (realised), Phadia | https://www.cinven.com/news-insights/philipp-meyer-joins-cinven/ |
| Generics and consumer health | STADA majority to CapVest (Sep 2025), "largest European LBO of the year to date" | https://www.cinven.com/news-insights/bain-capital-and-cinven-to-sell-majority-stake-in-stada-to-capvest/ |

### Industrials (Head: Pontus Pettersson)
| Theme | Evidence | Source |
|---|---|---|
| Corporate carve-outs ("corporate orphans") | "Cinven funds have a long track record of investing in ... corporate orphans"; targets are "fundamentally sound, but ... overlooked", with "great intellectual property"; TKE margin from ~13% to >17%; Envu €600M revenue, "just over 1%" of Bayer, "leading consolidator in a fragmented market with three acquisitions" | https://www.cinven.com/news-insights/the-rewards-of-a-corporate-carve-out/ ; https://www.cinven.com/news-insights/tk-elevator-a-compelling-carve-out/ |
| Specialty and construction chemicals | Arxada (from Lonza), MBS (from Sika via MBCC), "eight new production sites", six new countries | https://www.cinven.com/news-insights/the-rewards-of-a-corporate-carve-out/ ; https://www.cinven.com/news-insights/from-uncertainty-to-resurgence-cinven-x-master-builders-solutions/ |
| Distribution | Barentz (life science ingredients), Ahlsell (building materials, 2006 to 2012) | https://www.cinven.com/news-insights/the-nordic-opportunity-five-elements-for-success/ |

### TMT (Head: Thomas Railhac, London)
| Theme | Evidence | Source |
|---|---|---|
| Vertical and enterprise software | Smart Communications: "cloud-native SaaS", "recurring revenues and best-in-class retention rates"; Salsify: "Differentiated, business-critical platform", network effects, "high customer retention through the cycle", "Well positioned to drive value from AI"; Ongoing: "system of record" "defensively positioned against AI disintermediation"; repeat levers "sales force productivity, strategic accounts, customer success and pricing" | https://www.cinven.com/news-insights/cinven-to-acquire-smart-communications/ ; https://www.cinven.com/news-insights/cinven-to-acquire-salsify/ ; https://www.cinven.com/news-insights/cinven-to-invest-in-ongoing-warehouse-alongside-founders/ ; https://www.cinven.com/news-insights/living-in-the-matrix-hitting-the-bullseye-with-archer-through-cross-team-collaboration/ |
| Online classifieds and marketplaces | idealista: segment "an area of focus for Cinven's TMT team for several years"; Allegro precedent | https://www.cinven.com/news-insights/cinven-agrees-to-acquire-a-majority-stake-in-idealista/ |
| Digital infrastructure and telecoms | Ufinet (6.0x first exit), MasOrange stake sold for €4.25B, Netceed, Nitel to Comcast | https://www.cinven.com/news-insights/ufinet-10-years-of-transformation/ ; https://www.cinven.com/news-insights/cinven-sell-stake-in-masorange/ |
| Hosting, SMB and productivity software | group.One (one.com plus dogado), think-cell, Taxwell | https://www.cinven.com/news-insights/how-taxwell-is-using-ai-to-transform-the-tax-filing-experience/ |
| Adtech and GRC | RTB House, Archer | https://www.cinven.com/news-insights/archer-unlocking-value-with-ai/ |

### Regional theses
Nordics (Pettersson, Oct 2025): ">€2 billion in market leaders" invested; Nordic companies "more international in outlook", liquid equity markets for exit, English fluency, STEM workforce, start-up ecosystem. Europe (Quemada, May 2025): size of market, valuation gap with the US, dislocation creating carve-outs, local presence wins, catch-up sectors (digital, infrastructure, defence), incoming LP capital. Sources: https://www.cinven.com/news-insights/the-nordic-opportunity-five-elements-for-success/ ; https://www.cinven.com/news-insights/investing-in-europe-six-reasons-to-be-cheerful/.

## 5. London team

Source for every row: https://www.cinven.com/team/<slug>/ (saved under raw/01/team/), with promotions and hires from the press releases cited. The two Co-Managing Partners sit in Frankfurt (Schick) and Madrid (Quemada).

Firm leadership based in London: Alexandra Hess (President, Head of IR and Strategic Initiatives); Maxim Crewe (Partner, Head of Sectors and Countries; leads Consumer and Financial Services sector teams); Pontus Pettersson (Partner; leads Healthcare and Industrials sector teams and Nordic regional team; IC, PRC, ExCo); Thomas Railhac (Partner; leads TMT sector team; IC); David Barker (Partner; IC member; formerly led TMT; joined 1996); Stuart McAlpine (Chairman Emeritus); Stuart Walker (Partner, Head of AI and Technology Transformation); Paul Vega and Thilo Sautter (Partners leading the Portfolio team); Soren Christensen (Partner, leads Capital Markets) and Christopher Anderson (Partner, Capital Markets); Babett Carrier (General Counsel); Caroline Rawes (CHRO); Mike Colato (Partner and Senior Advisor; interim COO and CFO Dec 2025 to Sep 2026); Eleanor Mountain, Sarah Verity-Thomas, Tarek Bayazid (Partners, IR); Allegra Day (MD, Head of Sustainability); Parker Rhodes (MD, Capital Formation).

| Sector | London partners (selected deals) | London senior principals and principals (selected deals) |
|---|---|---|
| Business Services | Rory Neeson (Head; Accumin, Alter Domus, Amara NZero, Archer, Artefact, Barentz, Grant Thornton, HBX, JLA, OMNES, NewDay, Viridium; ex Bain), Ben Osnabrug (Benelux head; Accumin, Barentz, Envirotainer, One.com; ex Citi), Miguel Segura (Iberia; Alter Domus, Amara NZero, Domia, HBX, UAX, Ufinet; ex 3i), Anthony Cardona (TMT and BS; CPA Global, Flint Global, Visma, Accumin, MBS, Arxada, Envu; ex L.E.K.) | Karanvir Dhillon (Principal; Accumin, Alter Domus, Artefact), Nicholas Engels (Principal; Amara NZero, Barentz, JLA, True Potential, UAX) |
| Consumer | Maxim Crewe (Head; Alter Domus, Allegro, Arcaplanet, Fressnapf, Grant Thornton, Kurt Geiger, NewDay, PPF, Planasa, Salsify, True Potential, Viridium; ex Citi) | Rebecca Hunter (Senior Principal; Fressnapf, JLA, Miller, NewDay, PCL, Synlab, True Potential), Carol Yu (Principal; Arcaplanet, Kurt Geiger, RTB House, Salsify, Vitamin Well), Giulia Tieppo (Principal, promoted Jan 2025; Arcaplanet, Envu, Fressnapf, Planasa) |
| Financial Services | Maxim Crewe (Head), Juan Monge (FS and SFF; Miller, Säkra, Objectway; ex CVC, Actis/General Atlantic, McKinsey) | Samy Jazaerli (Senior Principal), Jodi Balfe (Principal; Compre, Grant Thornton, Miller, True Potential; ex Goldman FIG), Louis Deloz (Principal; Alter Domus, Grant Thornton; ex Bain) |
| Strategic Funds (SFF, SF2) | Luigi Sbrozzi (Partner, Co-Head; Miller, Compre, IFGL, Säkra, Finaxy, Flint Global, Policy Expert, Objectway; ex Centerbridge, CVC). Co-head Michael Weber (Partner, joined Oct 2024 from Riverside; DACH; Ongoing Warehouse) is Frankfurt-based | Balazs Lam (Senior Principal; Compre, IFGL, Säkra, Finaxy, Policy Expert; ex CVC) |
| Healthcare | Pontus Pettersson (Head; Arxada, CeramTec, Envirotainer, Envu, LGC, MBS, Ongoing, Nutrisens, Regenity, Theramex) | Anastasya Molodykh-McFarlane (Senior Principal; LGC, Medpace, Synlab, Theramex; joined 2015), Dominic Robinson (Principal; BioAgilytix, Nutrisens, PPF, Synlab) |
| Industrials | Pontus Pettersson (Head) | Jacopo Bruschi (Senior Principal; Arxada, MBS, TKE), Marco Strizzi (Senior Principal; Arxada, Envu; ex PSP, BC Partners), Tom Thomasson (Senior Principal; Arxada, Envirotainer, Ongoing, Vitamin Well), Joel Kaidesoja (Principal; Envirotainer, Envu, Vitamin Well) |
| TMT | Thomas Railhac (Head; Allegro, group.One, HEG, idealista, MasOrange, Netceed, Nitel, One.com, RTB House, Smart Communications, True Potential, Ufinet; ex Goldman PIA) | Letizia Bellucci (Senior Principal; group.One, One.com, Planasa, Ufinet), Anniek Joosten (Principal; Barentz, Jaggaer, MasOrange, Netceed, One.com, RTB House, Smart Communications), Begona Araujo Perez (Principal, promoted Jan 2024; Allegro, group.one, MasOrange, Smart Communications) |

Partners promoted or hired 2024 to 2026 (all offices): Adam Prindis (TMT, Emerging Europe), Daniel Garin (TMT, North America; Salsify, Archer, Taxwell), Eleanor Mountain (IR) promoted Jan 2025; Philipp Meyer (Healthcare and DACH, Frankfurt, ex Carlyle, where he worked on Carlyle's "£1.2bn acquisition of Theramex") hired Feb 2025; Jan Schönfeld (BS, TMT, DACH) promoted Jan 2026. Career path: "a defined eight-year path from Associate to Senior Principal". Sources: https://www.cinven.com/news-insights/cinven-announces-partner-promotions-5/ ; https://www.cinven.com/news-insights/philipp-meyer-joins-cinven/ ; https://www.cinven.com/news-insights/cinven-announces-partner-promotion-2/ ; https://www.cinven.com/news-insights/executing-excellence-inside-the-playbook-of-top-private-equity-dealmakers/.

Samy Jazaerli: Senior Principal, London, Financial Services sector team. Deals: Alter Domus, Compre, Grant Thornton, IFGL (current), Viridium Gruppe (realised). Background: Credit Suisse (M&A and LBO advisory), French Finance Ministry (Corps des Mines); Ecole Polytechnique (MSc Mathematics), Princeton (Master in Finance); joined Cinven 2017. Titled "Principal" in the Grant Thornton UK release of 21 Nov 2024, so promoted to Senior Principal between Nov 2024 and Nov 2026. Quote: "Accounting Services has been a priority sector for Cinven's Financial Services team". Wayback title history queued (web.archive.org unreachable through the proxy). Sources: https://www.cinven.com/team/samy-jazaerli/ ; https://www.cinven.com/news-insights/cinven-news-grant-thornton/.

## 6. Deal size evidence

Published statements of range:

| Statement | Fund | Source |
|---|---|---|
| "enterprise values above €300 million, via equity investments ranging in size from €150 million to €500 million"; "portfolio of 15-20 investments"; "only seeks control investments" | Fund 6 (€7B, 2016) | Oregon OIC staff memo, 29 Mar 2016, raw/01/lp/oregon_oic_2016.txt lines 73 to 75 (https://www.oregon.gov/treasury/invested-for-oregon/Documents/oic-meeting-archives/2016/agendas/2016.03.29-OIC-Special%20Meeting-PUBLIC-BOOK.pdf) |
| ~€300M to ~€1B equity, ~€600M+ EV | Fund 8 (€13.2B) | Estimate: Fund 6 range scaled by fund size ratio 13.2/7 = 1.9x; confidence medium; cross-checked against disclosed Fund 8 EVs below |
| ~€100M to ~€400M equity per platform | SF2 (€2.3B) | Estimate: fund size over 8 to 12 platforms after reserves, 16-person team; confidence low; no SF2 deal value disclosed |

Disclosed or press-reported deal values, 2020 to 2026 (flag column marks outliers for calibration):

| Deal | Date | Fund | Value | Flag | Source |
|---|---|---|---|---|---|
| Alter Domus | Mar 2024 | Fund 8 | EV €4.9B, majority (about half the shares) | typical flagship (upper) | https://www.mergersight.com/post/cinven-agrees-to-pay-4-9bn-for-a-majority-stake-in-alter-domus |
| Vitamin Well | Aug 2024 | Fund 8 | EV ~€3B, ~20x EBITDA (~€150M EBITDA), lead investor with Bridgepoint retaining a significant minority | typical flagship | https://www.mainsights.io/ma-news/cinven-becomes-lead-investor-in-vitamin-well-at-an-ev-of-eur-3bn-and-evebitda-of-20x |
| idealista | Jun 2024 | Fund 8 | "enterprise value of €2.9bn", majority | typical flagship | https://www.cinven.com/news-insights/cinven-agrees-to-acquire-a-majority-stake-in-idealista/ |
| Theramex | Nov 2026 | Fund 8 | ~€2.6B (press); ~£2.2B (pharmaphorum); Carlyle and PAI paid £1.2B in 2022 | typical flagship | https://femtechinsider.com/cinven-to-acquire-womens-health-drugmaker-theramex-for-2-6b/ ; https://pharmaphorum.com/news/uk-womens-health-firm-theramex-sold-around-ps22bn ; https://www.cinven.com/news-insights/philipp-meyer-joins-cinven/ |
| UAX | Oct 2025 | Fund 8 | "around €2B" ($2.2B), controlling stake with founder and Mubadala | typical flagship | https://inforcapital.com/news/cinven-seals-e2b-spain-education-deal-for-uax/ |
| Grant Thornton UK | Nov 2024 (closed Apr 2025) | Fund 8 | "up to £1.5bn"; net revenue £724M; majority with partners retaining stake | typical flagship (lower) | https://pe-insights.com/?p=337935 |
| Artefact | Jul 2025 | Fund 8 | "approximately €1 billion ($1.2 billion)" (Bloomberg) | typical flagship (lower) | https://ng.investing.com/news/economy-news/cinven-nears-1-billion-acquisition-of-french-data-firm-artefact--bloomberg-93CH-2024796 |
| Smart Communications | Aug 2025 | Fund 8 | "over $1 billion", from Accel-KKR | US-led, typical size | https://inforcapital.com/news/cinven-acquires-smart-communications-in-saas-mega-deal/ |
| Envu (Bayer Environmental Science) | Mar 2022 (closed Dec 2022) | Fund 7 | $2.6B; ~€600M revenue; Cinven later explored a ~€3.5B exit | carve-out, typical | https://www.leadersleague.com/pt/news/cinven-buys-bayer-s-environmental-science-business-for-2-6bn ; https://www.cinven.com/news-insights/the-rewards-of-a-corporate-carve-out/ ; https://www.privateequitywire.co.uk/cinven-explores-e3-5bn-exit-for-former-bayer-unit-envu/ |
| TK Elevator | Feb 2020 | Fund 7 | €17.2B with Advent and RAG foundation | mega-deal, consortium, exclude | https://www.cinven.com/news-insights/the-rewards-of-a-corporate-carve-out/ |
| Restaurant Brands Europe (exit) | Nov 2026 | Fund 7 | €2.33B for 100%; €1.4B acquisition loan; 2025 EBITDA €245M (~9.5x); 2025 sales €1.541B | exit value, typical | https://euroweeklynews.com/2026/11/06/major-burger-king-shake-up-in-spain-as-e2-3-billion-deal-changes-ownership/ |
| MasOrange (exit) | Dec 2025 | Fund 6/7 | stake sold for €4.25B with KKR and Providence | mega-deal, consortium, exclude | https://www.cinven.com/news-insights/cinven-sell-stake-in-masorange/ |
| Barentz continuation fund | Mar 2024 | CV | ~€850M vehicle | continuation vehicle, exclude | https://www.pei-secondariesinvestor.com/goldman-sachs-alpinvest-lead-cinvens-barentz-secondary/ |
| SF2 deals (Objectway, Flint Global, Ongoing Warehouse, Optio) | 2025 to 2026 | SF2 | undisclosed in all four releases | mid-market, exclude from flagship calibration | https://www.cinven.com/news-insights/cinven-closes-second-strategic-fund/ |
| Regenity, Policy Expert (50%), Fressnapf (minority), Envu GIC stake | 2024 to 2026 | various | undisclosed | minority or co-invest, exclude | section 3 sources |

Reading: Fund 8 platform deals with disclosed values cluster at ~€1B to ~€5B EV, with the lower bound (~€1B: Artefact, Smart Communications, Grant Thornton) set by equity cheques of roughly €400M to €600M at typical leverage, consistent with the scaled Fund 6 range. Confidence medium: based on eight disclosed values out of roughly 15 Fund 8 platform investments.

## 7. How Cinven sources

| Mechanism | Evidence | Source |
|---|---|---|
| Sector-Regional origination matrix | "combines the deep specialist expertise of its Sector teams with the local European networks of its Regional teams"; "All Cinven deals ... are staffed by a combination of regional and sector experts" | https://www.cinven.com/news-insights/cinven-closes-second-strategic-fund/ ; https://www.cinven.com/news-insights/living-in-the-matrix-hitting-the-bullseye-with-archer-through-cross-team-collaboration/ |
| How the matrix works | "Sector teams will dig into emerging themes and validate and share them with regional teams who can look for investment opportunities locally"; regional teams "use their networks of founders, executives, advisers and investors to make introductions"; remuneration "reward[s] collaboration" | https://www.cinven.com/news-insights/living-in-the-matrix-hitting-the-bullseye-with-archer-through-cross-team-collaboration/ |
| Matrix governance | Maxim Crewe appointed Head of Countries and Sectors "to oversee Cinven's sector and regional matrix, a longstanding differentiator" (Dec 2025) | https://www.cinven.com/news-insights/cinven-announces-leadership-update/ |
| Thematic sub-sector targeting with multi-year lead times | GRC theme identified 2020, Archer signed 2023 after "18 months" of US mapping; "spent significant time targeting investment opportunities in the fund services subsector" (Alter Domus); "health, wellbeing and fitness" (Vitamin Well); classifieds "area of focus for several years" (idealista); "Accounting Services has been a priority sector" (Grant Thornton) | deal releases cited in section 4 |
| Primary and founder-led deal flow | "In the Eighth Cinven Fund, eight out of ten investments to date are primary or founder-led"; "Europe remains a land of primary deals – carve-outs and founder-led divestments"; "18 portfolio companies led or owned by their founders" since Fund 6 | https://www.cinven.com/news-insights/exits-to-strategics/ ; https://www.cinven.com/news-insights/investing-in-europe-six-reasons-to-be-cheerful/ ; https://www.cinven.com/news-insights/why-founders-choose-cinven/ |
| Long relationship building | "confidential and intimate dialogues with founders, business owners, and corporates"; Fressnapf founder relationship "nearly 20 years ago"; "Some of Cinven's deals have been more than twenty years in the making"; Theramex followed "for many years"; Optio management known "more than two years" | https://www.cinven.com/news-insights/exits-to-strategics/ ; https://www.cinven.com/news-insights/investing-in-europe-six-reasons-to-be-cheerful/ ; https://www.cinven.com/news-insights/cinven-to-acquire-theramex/ ; https://www.cinven.com/news-insights/optio-acquisition/ |
| Off-market and valuation angle | Diversified investors "can target particularly interesting segments and originate well to generate even more attractive valuations through off-market deals" (Quemada) | https://www.cinven.com/news-insights/investing-in-europe-six-reasons-to-be-cheerful/ |
| Corporate carve-outs | Pettersson: "It's hard to find the right targets"; carve-outs "a trend we anticipate will continue"; TKE, Arxada, Envu, MBS | https://www.cinven.com/news-insights/the-rewards-of-a-corporate-carve-out/ |
| Winning auctions | Joint sector plus regional pitch "around resources to accelerate organic growth and boots on the ground in Europe to drive M&A-led growth" (Archer); Grant Thornton: "top of every non-commercial score, but second in the financial" and still won | https://www.cinven.com/news-insights/living-in-the-matrix-hitting-the-bullseye-with-archer-through-cross-team-collaboration/ ; https://www.cinven.com/news-insights/why-founders-choose-cinven/ |
| Mid-market extension | SF2 "to pursue a broader set of mid-market opportunities" with dedicated team; SF2 brings "increased connectivity with key stakeholders across Europe's sectors and regions" to the flagship | https://www.cinven.com/news-insights/cinven-closes-second-strategic-fund/ |
| Culture pitch to founders | Attention ("a portfolio of 400 companies" vs "40"), "here to support, not to steer", speed, regional cultural fit, founders keeping "a chunky minority interest" | https://www.cinven.com/news-insights/why-founders-choose-cinven/ |

## 8. Recent news 2025 to 2026 (cinven.com news listing, newest first)

| Date | Event | Type | Source |
|---|---|---|---|
| 06 Nov 2026 | Agreed sale of Restaurant Brands Europe stake to consortium led by founder Gregorio Jiménez; EBITDA "more than doubling" since 2021 | Exit (Consumer, Fund 7) | https://www.cinven.com/news-insights/cinven-agrees-to-the-sale-of-restaurant-brands-europe/ |
| 03 Nov 2026 | Agreed to acquire Theramex (women's health specialty pharma, London) from Carlyle and PAI | New investment (Healthcare) | https://www.cinven.com/news-insights/cinven-to-acquire-theramex/ |
| 08 Sep 2026 | SF2 final close c. €2.3B | Fundraising | https://www.cinven.com/news-insights/cinven-closes-second-strategic-fund/ |
| 01 Sep 2026 | Dominic Smyth appointed CFO and COO | Leadership | https://www.cinven.com/news-insights/cinven-appoints-dominic-smyth-as-chief-financial-officer-and-chief-operating-officer/ |
| 27 Jul 2026 | Cinven and La Caisse to acquire Optio Group (specialty MGA, UK) | New investment (FS, SF2) | https://www.cinven.com/news-insights/optio-acquisition/ |
| 22 Jul 2026 | Agreed to acquire Salsify (PXM software, Boston) | New investment (TMT and Consumer, US) | https://www.cinven.com/news-insights/cinven-to-acquire-salsify/ |
| 02 Jul 2026 | Vitamin Well Group to combine with EMPWR | Portfolio add-on | https://www.cinven.com/news-insights/vitamin-well-group-empwr/ |
| 06 May 2026 | Invest in Ongoing Warehouse (cloud WMS, Gothenburg) alongside founders; "third investment from Cinven's new mid-market strategy" | New investment (TMT, SF2) | https://www.cinven.com/news-insights/cinven-to-invest-in-ongoing-warehouse-alongside-founders/ |
| 29 Apr 2026 | KONE and TKE to combine | Exit path (Industrials) | https://www.cinven.com/news-insights/kone-and-tke/ |
| 25 Mar 2026 | GIC strategic minority investment in Envu | Partial realisation and co-invest | https://www.cinven.com/news-insights/cinven-welcomes-strategic-minority-investment-in-envu-from-gic/ |
| 12 Feb 2026 | Strategic investment in Regenity Biosciences alongside Linden | New investment (Healthcare, US) | https://www.cinven.com/news-insights/regenity-biosciences-announcement/ |
| 14 Jan 2026 | Jan Schönfeld promoted to Partner | People | https://www.cinven.com/news-insights/cinven-announces-partner-promotion-2/ |
| 17 Dec 2025 | Leadership update: Rajagopalan and Leslie leave; Hess President; Crewe Head of Countries and Sectors; IC broadened | Leadership | https://www.cinven.com/news-insights/cinven-announces-leadership-update/ |
| 12 Dec 2025 | Cinven, KKR and Providence sell stake in MasOrange for €4.25B | Exit (TMT) | https://www.cinven.com/news-insights/cinven-sell-stake-in-masorange/ |
| 08 Dec 2025 | Invest in Flint Global (regulatory and policy advisory, London) | New investment (BS, SF2) | https://www.cinven.com/news-insights/cinven-to-invest-in-flint-global/ |
| 28 Oct 2025 | Acquire majority of UAX from CVC with founder and Mubadala | New investment (BS, Iberia) | https://www.cinven.com/news-insights/cinven-to-acquire-universidad-alfonso-x-el-sabio-group-from-cvc-funds/ |
| 13 Oct 2025 | Grant Thornton Germany partnership approved | New investment (FS, DACH) | https://www.cinven.com/news-insights/grant-thornton-germany-and-cinven-enter-into-strategic-partnership/ |
| 12 Sep 2025 | KKR to acquire NewDay's consumer credit portfolio from Cinven and CVC | Exit (FS) | https://www.cinven.com/news-insights/kkr-agrees-to-acquire-newdays-consumer-credit-portfolio-from-cinven-and-cvc/ |
| 01 Sep 2025 | Bain Capital and Cinven to sell majority of STADA to CapVest | Exit (Healthcare) | https://www.cinven.com/news-insights/bain-capital-and-cinven-to-sell-majority-stake-in-stada-to-capvest/ |
| 07 Aug 2025 | Objectway majority investment with founder; "first investment from Cinven's new mid-market strategy" | New investment (FS, SF2) | https://www.cinven.com/news-insights/objectway-investment/ |
| 01 Aug 2025 | Acquire Smart Communications (CCM SaaS) from Accel-KKR | New investment (TMT, US) | https://www.cinven.com/news-insights/cinven-to-acquire-smart-communications/ |
| 28 Jul 2025 | Exclusive negotiations to acquire Artefact (data and AI consulting, Paris) from Ardian | New investment (BS, France) | https://www.cinven.com/news-insights/cinven-in-exclusive-negotiations-to-acquire-artefact/ |
| 01 Jul 2025 | CFO transition announced | Leadership | https://www.cinven.com/news-insights/cinven-announces-chief-financial-officer-transition/ |
| 20 May 2025 | Exclusive negotiations with Sagard to acquire Nutrisens (medical nutrition, France) | New investment (Healthcare) | https://www.cinven.com/news-insights/cinven-in-exclusive-negotiations-with-sagard-to-acquire-nutrisens/ |
| 24 Mar 2025 | Completed sale of SYNLAB minority to Labcorp | Exit (Healthcare) | https://www.cinven.com/news-insights/cinven-completes-sale-of-minority-stake-in-synlab-to-strategic-investor-labcorp/ |
| 19 Mar 2025 | Sale of Viridium Group to Allianz, BlackRock, T&D consortium | Exit (FS) | https://www.cinven.com/news-insights/cinven-to-sell-viridium-group/ |
| 14 Feb 2025 | HBX Group IPO on Spanish exchanges | Exit (BS) | https://www.cinven.com/news-insights/hbx-group-successfully-listed-and-commences-trading-on-spanish-stock-exchanges/ |
| 13 Feb 2025 | Sale of Kurt Geiger | Exit (Consumer) | https://www.cinven.com/news-insights/cinven-to-sell-kurt-geiger/ |
| 03 Feb 2025 | Philipp Meyer joins as Healthcare Partner (Frankfurt) | People | https://www.cinven.com/news-insights/philipp-meyer-joins-cinven/ |
| 10 Jan 2025 | Partner promotions (Prindis, Garin, Mountain) | People | https://www.cinven.com/news-insights/cinven-announces-partner-promotions-5/ |

Strategy shifts visible in 2025 to 2026: (1) the mid-market strategy formalised as SF2 with scope widened from FS to BS and TMT; (2) explicit AI value-creation thesis in deal rationales, a Head of AI and Technology Transformation and AI case studies (Alter Domus, Taxwell, Archer); (3) heavier US deployment from New York (Salsify, Regenity, Smart Communications); (4) exit emphasis to strategics with "nearly 3x" weighted MOIC on five strategic exits since Jan 2024; (5) leadership consolidation under two Co-Managing Partners after the Dec 2025 departures. Sources: https://www.cinven.com/news-insights/cinven-closes-second-strategic-fund/ ; https://www.cinven.com/news-insights/exits-to-strategics/ ; https://www.cinven.com/news-insights/cinven-announces-leadership-update/ ; https://www.cinven.com/team/stuart-walker/.

## Rubric candidates

Ranked by how often the attribute appears in Cinven's own deal rationales (2024 to 2026 press releases with stated "attractive characteristics": Alter Domus, idealista, Vitamin Well, Grant Thornton UK, Nutrisens, Artefact, Smart Communications, Objectway, UAX, Flint Global, Ongoing Warehouse, Salsify, Optio, Theramex) and strategy pages. Counts are a manual reading of the 14 rationales (saved under raw/01/news/, bullet extract in raw/01/news/deal_rationale_bullets.txt) and are approximate to plus or minus one. Quotes are under 15 words; the URL column gives the source of the quote.

| Rank | Attribute | Quote | Approximate count (of 14 deal rationales, plus strategy pages) | Quote source URL |
|---|---|---|---|---|
| 1 | Large, structurally growing end market with long-term tailwinds | "Exposure to a structurally growing end-market" | 14 of 14; approach page | https://www.cinven.com/news-insights/optio-acquisition/ ; https://www.cinven.com/approach/ |
| 2 | Strong, experienced management; founder or partners reinvesting | "Strong founder-led management team" | 13 of 14 | https://www.cinven.com/news-insights/objectway-investment/ |
| 3 | Market-leading or scarce, differentiated platform | "scarce, market-leading global fund services platform" | 12 of 14; Fund 8 release "market leading" | https://www.cinven.com/news-insights/cinven-agrees-to-make-significant-strategic-investment-in-alter-domus/ ; https://www.cinven.com/news-insights/cinven-raises-14-5-billion-for-the-eighth-cinven-fund/ |
| 4 | Track record of organic growth, ideally with margin expansion | "double-digit organic growth while increasing its margins" | 11 of 14 | https://www.cinven.com/news-insights/cinven-in-exclusive-negotiations-with-sagard-to-acquire-nutrisens/ |
| 5 | Organic plus inorganic growth runway, buy and build in a fragmented market | "value accretive M&A opportunities in a highly fragmented market" | 10 of 14; approach page; Consumer thesis "Consolidating fragmented markets" | https://www.cinven.com/news-insights/optio-acquisition/ ; https://www.cinven.com/news-insights/active-investing-in-consumer-mega-trends/ |
| 6 | International expansion potential (Europe to US, or local champion abroad) | "taking local champions and driving growth abroad" | 9 of 14; approach page | https://www.cinven.com/news-insights/active-investing-in-consumer-mega-trends/ ; https://www.cinven.com/news-insights/cinven-to-acquire-theramex/ |
| 7 | Recurring or repeat revenue with high retention and visibility | "recurring revenues and best-in-class retention rates" | 8 of 14; Consumer thesis "repeat-purchase models" | https://www.cinven.com/news-insights/cinven-to-acquire-smart-communications/ ; https://www.cinven.com/news-insights/active-investing-in-consumer-mega-trends/ |
| 8 | Resilience and downside protection through the cycle | "resilient characteristics"; "providing both visibility and downside protection" | 8 of 14; Fund 8 release | https://www.cinven.com/news-insights/cinven-raises-14-5-billion-for-the-eighth-cinven-fund/ ; https://www.cinven.com/news-insights/cinven-to-invest-in-ongoing-warehouse-alongside-founders/ |
| 9 | Blue-chip, diversified customer base with strong advocacy | "blue-chip and diversified client base" | 7 of 14 | https://www.cinven.com/news-insights/cinven-to-invest-in-flint-global/ |
| 10 | Regulatory, outsourcing or digitalisation tailwinds | "increasing regulation and a continued trend towards outsourcing" | 7 of 14 | https://www.cinven.com/news-insights/cinven-agrees-to-make-significant-strategic-investment-in-alter-domus/ |
| 11 | Cash generation | "cash generative companies"; "strong cash flow generation" | 4 of 14; Fund 8 release; exits article | https://www.cinven.com/news-insights/cinven-raises-14-5-billion-for-the-eighth-cinven-fund/ ; https://www.cinven.com/news-insights/objectway-investment/ |
| 12 | Mission-critical or business-critical, embedded product | "Business-critical solution with a deeply embedded customer base" | 4 of 14 | https://www.cinven.com/news-insights/cinven-to-invest-in-ongoing-warehouse-alongside-founders/ |
| 13 | Well positioned to benefit from AI (and defended against AI disintermediation) | "Well positioned to drive value from AI" | 3 of 14 (all 2026); AI case studies | https://www.cinven.com/news-insights/cinven-to-acquire-salsify/ |
| 14 | Pricing power from brand or differentiated proposition | "robust pricing power thanks to strong brands or high-value service models" | 4 of 14; Consumer thesis | https://www.cinven.com/news-insights/active-investing-in-consumer-mega-trends/ |
| 15 | Talent magnet and strong culture | "proven ability to attract, retain and grow high-quality talent" | 4 of 14 (people businesses) | https://www.cinven.com/news-insights/cinven-in-exclusive-negotiations-to-acquire-artefact/ |
| 16 | Asset-light, capital-light model (SF2 emphasis) | "high-growth, asset-light opportunities in the European mid-market" | 3 of 14; SF2 release | https://www.cinven.com/news-insights/cinven-closes-second-strategic-fund/ |
| 17 | Transformation potential and multiple value creation levers | "true transformation potential"; "Multiple further growth and value creation levers" | approach page; 5 of 14 | https://www.cinven.com/approach/ ; https://www.cinven.com/news-insights/objectway-investment/ |
| 18 | Primary situation: founder, family or corporate orphan | "primary or founder-led"; "corporate orphans" | sourcing pages | https://www.cinven.com/news-insights/exits-to-strategics/ ; https://www.cinven.com/news-insights/the-rewards-of-a-corporate-carve-out/ |

Suggested ten-dimension rubric from the ranking: (1) structural market growth, (2) market leadership and differentiation, (3) management quality and founder alignment, (4) growth and margin track record, (5) buy and build runway in fragmented market, (6) international expansion potential, (7) revenue quality (recurring, retention, blue-chip base), (8) resilience and cash generation, (9) mission-criticality and regulatory or outsourcing tailwinds, (10) AI and digital transformation upside. Deal size and sector fit are gating filters applied before scoring.

## Classifier taxonomy

Six sector pills used on cinven.com/portfolio: Business Services, Consumer, Financial Services, Healthcare, Industrials, TMT; plus a "Strategic Funds" pill for SFF and SF2 deals (Compre, Finaxy, IFGL, Policy Expert). Multi-pill companies: Alter Domus (BS, FS), Archer (BS, TMT), Envirotainer (BS, Healthcare, Industrials), Salsify (Consumer, TMT), TK Elevator (BS, Industrials), True Potential (FS, TMT). Source: https://www.cinven.com/portfolio/ (docs/cv_portfolio/cinven_portfolio_page.json).

Sub-sector labels Cinven itself uses (from press releases, thought pieces and team pages; portfolio examples in brackets):

| Sector | Sub-sector labels used by Cinven | Source examples |
|---|---|---|
| Business Services | fund administration and corporate services ("fund services") [Alter Domus]; professional services: audit, tax and advisory [Grant Thornton]; regulatory, policy and economic advisory [Flint Global]; data and AI consulting [Artefact]; governance, risk and compliance (GRC) [Archer]; private higher education [UAX, OMNES]; pharma cold chain and temperature-controlled logistics [Envirotainer]; travel technology and B2B travel distribution [HBX]; energy efficiency and sustainability services [Amara NZero]; commercial laundry and critical asset services [JLA]; home services [Domia]; property valuation and data [Accumin]; life science ingredients distribution [Barentz]; "tech-enabled services" (generic) | https://www.cinven.com/news-insights/cinven-agrees-to-make-significant-strategic-investment-in-alter-domus/ ; https://www.cinven.com/news-insights/living-in-the-matrix-hitting-the-bullseye-with-archer-through-cross-team-collaboration/ |
| Consumer | functional food and beverage, health and wellness [Vitamin Well]; pet care retail and pet food [Fressnapf, Arcaplanet, PPF]; quick-service restaurants and master franchising [RBE]; footwear and accessories [Kurt Geiger]; fresh produce genetics [Planasa]; consumer packaged goods (CPG) and e-commerce enablement [Salsify]; "smaller-ticket consumer products or services with repeat-purchase models" | https://www.cinven.com/news-insights/active-investing-in-consumer-mega-trends/ ; https://www.cinven.com/news-insights/cinven-agrees-to-the-sale-of-restaurant-brands-europe/ |
| Financial Services | specialty insurance MGAs and specialty underwriting [Optio, Compre, Miller]; insurance brokerage and distribution [Finaxy, Säkra, Policy Expert]; legacy and run-off insurance [Compre]; life insurance consolidation [Viridium]; wealth management technology and financial software [Objectway]; accounting services [Grant Thornton]; consumer credit [NewDay]; financial advice and wealth platforms [True Potential]; fund services (shared with BS) [Alter Domus, IFGL] | https://www.cinven.com/news-insights/optio-acquisition/ ; https://www.cinven.com/news-insights/objectway-investment/ |
| Healthcare | specialty pharma, women's health [Theramex]; generics, OTC and consumer health [STADA]; medical and clinical nutrition [Nutrisens]; clinical laboratories and diagnostics [SYNLAB]; life science tools, standards and genomics [LGC]; bioanalytical testing [BioAgilytix]; CRO and clinical trial technology [Medpace, Clario]; regenerative biomaterials and medtech CDMO [Regenity]; mobility and accessibility solutions [NSM] | https://www.cinven.com/news-insights/cinven-to-acquire-theramex/ ; https://www.cinven.com/news-insights/philipp-meyer-joins-cinven/ |
| Industrials | corporate carve-outs and "corporate orphans"; specialty chemicals and microbial control [Arxada]; concrete admixtures and construction chemicals [MBS]; environmental science and pest control [Envu]; elevators and escalators [TKE]; technical ceramics [CeramTec]; building materials distribution [Ahlsell] | https://www.cinven.com/news-insights/the-rewards-of-a-corporate-carve-out/ |
| TMT | vertical and enterprise SaaS: customer communications management [Smart Communications], product experience management [Salsify], warehouse management [Ongoing Warehouse], GRC [Archer], procurement software [Jaggaer]; online classifieds and marketplaces [idealista, Allegro]; digital infrastructure, fibre and telecoms [Ufinet, MasOrange, Netceed]; web hosting and SMB digital services [group.One]; productivity software [think-cell]; tax software [Taxwell]; adtech [RTB House]; "technology and tech-enabled services" (SF2 scope) | https://www.cinven.com/news-insights/cinven-to-acquire-smart-communications/ ; https://www.cinven.com/news-insights/cinven-closes-second-strategic-fund/ |

## Open items (queued for manual review)
- Wayback snapshots of https://www.cinven.com/team/samy-jazaerli/ for title history: web.archive.org connections were reset through the proxy on 2026-11-09; not retried.
- SEC IAPD firm summary for CRD 323818 (RAUM as-of date and Schedule D fund list): API blocked; the aggregator figures ($42.71B RAUM) carry no date.
- PSERS 2016 resolution PDF (Fund 6) redirects to pa.gov search; Oregon OIC 2016 covers the same strategy text.
- No LP paper found for Fund 7 or Fund 8 stating an EV or equity range; searches run against oregon.gov, psers.pa.gov and generic pension terms.

## Sources
- https://www.cinven.com/approach/ (raw/01/investment-approach.html)
- https://www.cinven.com/about/company/ (raw/01/company.html)
- https://www.cinven.com/about/governance/ (raw/01/governance.html)
- https://www.cinven.com/contact-us/ (raw/01/contact-us.html)
- https://www.cinven.com/cinven-luxembourg-aifm/ (raw/01/cinven-luxembourg-aifm.html)
- https://www.cinven.com/ifpr-disclosure/ (raw/01/www-cinven-com-ifpr-disclosure-ye2025.html)
- https://www.cinven.com/team/ and 96 individual team pages (raw/01/team/, index raw/01/team_list.tsv)
- https://www.cinven.com/portfolio/ (docs/cv_portfolio/cinven_portfolio_page.json)
- https://www.cinven.com/news-insights/ listing pages 1 to 8 and 95 articles (raw/01/news/, URL index raw/01/news/all_article_urls.txt), including:
  - https://www.cinven.com/news-insights/cinven-closes-second-strategic-fund/
  - https://www.cinven.com/news-insights/cinven-raises-14-5-billion-for-the-eighth-cinven-fund/
  - https://www.cinven.com/news-insights/cinven-raises-e10-billion-for-the-seventh-cinven-fund/
  - https://www.cinven.com/news-insights/cinven-transitions-management-team/
  - https://www.cinven.com/news-insights/cinven-announces-leadership-update/
  - https://www.cinven.com/news-insights/exits-to-strategics/
  - https://www.cinven.com/news-insights/why-founders-choose-cinven/
  - https://www.cinven.com/news-insights/investing-in-europe-six-reasons-to-be-cheerful/
  - https://www.cinven.com/news-insights/active-investing-in-consumer-mega-trends/
  - https://www.cinven.com/news-insights/the-nordic-opportunity-five-elements-for-success/
  - https://www.cinven.com/news-insights/the-rewards-of-a-corporate-carve-out/
  - https://www.cinven.com/news-insights/living-in-the-matrix-hitting-the-bullseye-with-archer-through-cross-team-collaboration/
  - https://www.cinven.com/news-insights/executing-excellence-inside-the-playbook-of-top-private-equity-dealmakers/
  - deal releases: Theramex, Salsify, Optio, Ongoing Warehouse, Flint Global, UAX, Objectway, Smart Communications, Artefact, Nutrisens, Alter Domus, idealista, Vitamin Well, Grant Thornton UK, Regenity, Envu GIC, RBE sale, MasOrange sale, STADA sale, Viridium sale
  - people releases: Michael Weber (Oct 2024), partner promotions (Jan 2025, Jan 2026), Philipp Meyer (Feb 2025), Dominic Smyth (Sep 2026)
- Oregon OIC Special Meeting public book, 29 Mar 2016, Cinven Fund VI staff memo (raw/01/lp/oregon_oic_2016-03-29_public_book.pdf and oregon_oic_2016.txt): https://www.oregon.gov/treasury/invested-for-oregon/Documents/oic-meeting-archives/2016/agendas/2016.03.29-OIC-Special%20Meeting-PUBLIC-BOOK.pdf
- SEC IAPD firm search API result (raw/01/sec_iapd_firm_search.json)
- https://privatefunddata.com/fund-companies/cinven-limited/
- https://fintrx.com/firms/firm/cinven-limited-323818
- https://www.privateequityinternational.com/institution-profiles/cinven.html
- https://privateequitywire.com/news/cinven-closes-e2-3bn-strategic-fund-2
- https://pe-insights.com/?p=342854 (Bloomberg, Jun 2025, mid-market fund target)
- https://www.pei-secondariesinvestor.com/goldman-sachs-alpinvest-lead-cinvens-barentz-secondary/
- https://www.mergersight.com/post/cinven-agrees-to-pay-4-9bn-for-a-majority-stake-in-alter-domus
- https://www.mainsights.io/ma-news/cinven-becomes-lead-investor-in-vitamin-well-at-an-ev-of-eur-3bn-and-evebitda-of-20x
- https://inforcapital.com/news/cinven-seals-e2b-spain-education-deal-for-uax/
- https://pe-insights.com/?p=337935 (Grant Thornton UK valuation)
- https://ng.investing.com/news/economy-news/cinven-nears-1-billion-acquisition-of-french-data-firm-artefact--bloomberg-93CH-2024796
- https://inforcapital.com/news/cinven-acquires-smart-communications-in-saas-mega-deal/
- https://www.leadersleague.com/pt/news/cinven-buys-bayer-s-environmental-science-business-for-2-6bn
- https://www.privateequitywire.co.uk/cinven-explores-e3-5bn-exit-for-former-bayer-unit-envu/
- https://euroweeklynews.com/2026/11/06/major-burger-king-shake-up-in-spain-as-e2-3-billion-deal-changes-ownership/
- https://femtechinsider.com/cinven-to-acquire-womens-health-drugmaker-theramex-for-2-6b/
- https://pharmaphorum.com/news/uk-womens-health-firm-theramex-sold-around-ps22bn
- https://www.unquote.com/uk/news/71694/fifth-cinven-fund-holds-first-close-at-eur3bn
