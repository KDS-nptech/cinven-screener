"""Regenerate the synthetic Stage 2 / Stage 3 fixtures in this directory.

    python tests/fixtures/ownership/build_fixtures.py

The CSVs are the checked-in inputs; tests/test_ownership.py converts them to
parquet in a temp dir and runs the real pipeline. natures_of_control is pipe
separated in psc.csv because CSV has no list type. Every company number is
synthetic (1xxxxxxx operating companies, 2xxxxxxx holding companies).
"""
from __future__ import annotations

import csv
import pathlib

HERE = pathlib.Path(__file__).parent
INC = "2015-01-01"

OWN_25 = "ownership-of-shares-25-to-50-percent"
OWN_50 = "ownership-of-shares-50-to-75-percent"
OWN_75 = "ownership-of-shares-75-to-100-percent"
VOTE_75 = "voting-rights-75-to-100-percent"
APPOINT = "right-to-appoint-and-remove-directors"
INFLUENCE = "significant-influence-or-control"

IND = "individual-person-with-significant-control"
CORP = "corporate-entity-person-with-significant-control"
SUPER = "super-secure-person-with-significant-control"
STMT = "persons-with-significant-control-statement"

companies: list[dict] = []
accounts: list[dict] = []
psc: list[dict] = []
officers: list[dict] = []
filings: list[dict] = []


def company(number, name, employees=60, inc_date=INC, category="SMALL", share_premium=0, in_software=True,
            with_accounts=True, sic1="62012"):
    companies.append({
        "company_number": number, "name": name, "status": "Active", "inc_date": inc_date,
        "account_category": category, "post_town": "LONDON", "postcode": "EC1A 1AA",
        "sic1": sic1, "sic2": "62012" if (sic1 != "62012" and in_software) else "", "sic3": "", "sic4": "",
        "is_software_sic": "true" if in_software else "false", "charges_outstanding": 0,
    })
    if not with_accounts:
        return
    # an older period that must lose to the latest one
    accounts.append({"company_number": number, "period_end": "2024-03-31", "employees": 10, "turnover": 1000000,
                     "share_capital": 100, "share_premium": 0, "accounts_type": "small", "latest_for_company": "false"})
    accounts.append({"company_number": number, "period_end": "2025-03-31", "employees": employees, "turnover": 6000000,
                     "share_capital": 100, "share_premium": share_premium, "accounts_type": "small", "latest_for_company": "true"})


def psc_row(number, kind, name="", natures=(), notified="2016-04-06", ceased="", statement="", reg="", country="", legal=""):
    psc.append({
        "company_number": number, "kind": kind, "name": name, "natures_of_control": "|".join(natures),
        "notified_on": notified, "ceased_on": ceased, "is_active": "false" if ceased else "true",
        "statement": statement, "corporate_reg_number": reg, "country_registered": country, "legal_form": legal,
        "dob_year": 1975 if kind == IND else "",
    })


def director(number, name, appointed=INC, resigned="", role="director"):
    officers.append({"company_number": number, "name": name, "role": role, "appointed_on": appointed,
                     "resigned_on": resigned, "officer_id": f"off-{len(officers) + 1:04d}"})


def sh01(number, date):
    filings.append({"company_number": number, "type": "SH01", "date": date,
                    "description": "Statement of capital following an allotment of shares", "category": "capital"})


# 1 dispersed statement (register typo spelling)
company("10000001", "DISPERSED LTD")
psc_row("10000001", STMT, statement="no-individual-or-entity-with-signficant-control")

# 2 Hg on the register directly, alongside a founder with a minority
company("10000002", "HG BACKED LTD")
psc_row("10000002", CORP, "HG CAPITAL LLP", [OWN_50], reg="OC123456", country="England", legal="Limited Liability Partnership")
psc_row("10000002", IND, "Mr Peter Parker", [OWN_25])
director("10000002", "PARKER, Peter")

# 3 fund token: ' LP'
company("10000003", "LP BACKED LTD")
psc_row("10000003", CORP, "XYZ FUND II LP", [OWN_75], reg="", country="Cayman Islands", legal="Limited Partnership")

# 4 HIGHGATE must not match Hg; it is a UK holdco owned by one founder
company("10000004", "HIGHGATE OWNED LTD")
psc_row("10000004", CORP, "HIGHGATE SOFTWARE LTD", [OWN_75, VOTE_75], reg="20000004", country="England", legal="Limited Company")
psc_row("20000004", IND, "Mr Bruce Wayne", [OWN_75, VOTE_75])
director("10000004", "WAYNE, Bruce")

# 5 holdco walk-up to two founders
company("10000005", "TWO FOUNDERS HOLDCO LTD")
psc_row("10000005", CORP, "TF HOLDINGS LTD", [OWN_75, VOTE_75], reg="20000005", country="United Kingdom", legal="Private Limited Company")
psc_row("20000005", IND, "Ms Alice Cooper", [OWN_50])
psc_row("20000005", IND, "Mr Bob Dylan", [OWN_25])
director("10000005", "COOPER, Alice", appointed="2015-06-01")
director("10000005", "DYLAN, Bob", appointed="2015-06-01")

# 6 holdco whose own PSCs include an investor
company("10000006", "HOLDCO WITH INVESTOR LTD")
psc_row("10000006", CORP, "HWI HOLDINGS LTD", [OWN_75], reg="20000006", country="England", legal="Limited Company")
psc_row("20000006", IND, "Mr Carl Sagan", [OWN_25])
psc_row("20000006", CORP, "LDC (MANAGERS) LIMITED", [OWN_50], reg="02495714", country="England", legal="Limited Company")

# 7 foreign corporate parent
company("10000007", "FOREIGN PARENT LTD")
psc_row("10000007", CORP, "ACME INC", [OWN_75], reg="1234567", country="United States", legal="Corporation")

# 8 high confidence: one founder, director from day one
company("10000008", "HIGH CONF LTD")
psc_row("10000008", IND, "Mr David Jones", [OWN_75, VOTE_75])
director("10000008", "JONES, David")
director("10000008", "BROWN, Sarah", appointed="2019-01-01", role="secretary")

# 9 medium confidence: 50-75 band, director present
company("10000009", "MEDIUM CONF LTD")
psc_row("10000009", IND, "Ms Emma Watson", [OWN_50])
director("10000009", "WATSON, Emma")

# 10 trust variant only
company("10000010", "TRUST LTD")
psc_row("10000010", IND, "Mr Thomas Trustee", [OWN_75 + "-as-trust", VOTE_75 + "-as-trust"])
director("10000010", "TRUSTEE, Thomas")

# 11 super-secure record alongside an individual
company("10000011", "SUPER SECURE LTD")
psc_row("10000011", SUPER)
psc_row("10000011", IND, "Ms Diana Prince", [OWN_25])
director("10000011", "PRINCE, Diana")

# 12 no PSC rows at all
company("10000012", "NO PSC LTD", inc_date="2010-05-05")

# 13 founder-owned on the register but SH01-heavy
company("10000013", "SH01 HEAVY LTD")
psc_row("10000013", IND, "Mr Frank Castle", [OWN_75])
director("10000013", "CASTLE, Frank")
for d in ("2014-12-01", "2018-03-01", "2020-06-01", "2022-09-01", "2024-01-15"):
    sh01("10000013", d)  # the 2014 one predates incorporation and must not count

# 14 founder-owned, large share premium
company("10000014", "SHARE PREMIUM LTD", share_premium=750000)
psc_row("10000014", IND, "Ms Grace Hopper", [OWN_75])
director("10000014", "HOPPER, Grace")
sh01("10000014", "2019-01-01")

# 15 high ownership but the director test fails (appointed five years after incorporation)
company("10000015", "DIRECTOR FAIL LTD")
psc_row("10000015", IND, "Mr Gary Oldman", [OWN_75])
director("10000015", "SMITH, John")
director("10000015", "OLDMAN, Gary", appointed="2020-02-01")

# 16 more individuals than max_individual_pscs
company("10000016", "TOO MANY LTD")
for n in ("Mr Ian One", "Mr Jack Two", "Ms Kate Three", "Mr Liam Four"):
    psc_row("10000016", IND, n, [OWN_25])
director("10000016", "ONE, Ian")

# 17 holdco with its own corporate PSC (one level only)
company("10000017", "HOLDCO CORPORATE LTD")
psc_row("10000017", CORP, "HC HOLDINGS LTD", [OWN_75], reg="20000017", country="England", legal="Limited Company")
psc_row("20000017", CORP, "HC TOPCO LTD", [OWN_75], reg="20000018", country="England", legal="Limited Company")
psc_row("20000018", IND, "Mr Mike Top", [OWN_75])

# 18 voting rights only, used as proxy
company("10000018", "VOTING PROXY LTD")
psc_row("10000018", IND, "Ms Nina Simone", [VOTE_75, APPOINT])
director("10000018", "SIMONE, Nina")

# 19 two holdcos, each walked up
company("10000019", "MULTI CORP LTD")
psc_row("10000019", CORP, "MC HOLDINGS A LTD", [OWN_50], reg="20000019", country="England", legal="Limited Company")
psc_row("10000019", CORP, "MC HOLDINGS B LTD", [OWN_25], reg="20000020", country="England", legal="Limited Company")
psc_row("20000019", IND, "Mr Henry Ford", [OWN_75])
psc_row("20000020", IND, "Ms Clara Ford", [OWN_75])
director("10000019", "FORD, Henry")

# 20 holdco whose only record is a dispersed statement
company("10000020", "HOLDCO DISPERSED LTD")
psc_row("10000020", CORP, "HD HOLDINGS LTD", [OWN_75], reg="20000021", country="England", legal="Limited Company")
psc_row("20000021", STMT, statement="no-individual-or-entity-with-significant-control")

# 21 ceased investor must be ignored
company("10000021", "CEASED INVESTOR LTD")
psc_row("10000021", CORP, "BGF INVESTMENTS LP", [OWN_25], notified="2017-01-01", ceased="2022-06-30", reg="", country="Scotland", legal="Limited Partnership")
psc_row("10000021", IND, "Mr Oscar Wilde", [OWN_75])
director("10000021", "WILDE, Oscar")

# 22 individual with no ownership or voting band
company("10000022", "NO BAND LTD")
psc_row("10000022", IND, "Mr Paul Simon", [INFLUENCE])
director("10000022", "SIMON, Paul")

# 23 single individual below the medium threshold
company("10000023", "BELOW MEDIUM LTD")
psc_row("10000023", IND, "Ms Rosa Parks", [OWN_25])
director("10000023", "PARKS, Rosa")

# 24 UK corporate PSC with no usable registration number
company("10000024", "UNRESOLVED CORP LTD")
psc_row("10000024", CORP, "SOME PARENT LIMITED", [OWN_75], reg="", country="England", legal="Limited")

# 25 officer-style names with title and hyphen
company("10000025", "OFFICER FORMAT LTD")
psc_row("10000025", IND, "Dr Anna Smith-Jones", [OWN_75])
director("10000025", "SMITH-JONES, Dr Anna", appointed="2015-07-01")

# 26 all PSC records ceased
company("10000026", "ALL CEASED LTD")
psc_row("10000026", IND, "Mr Sam Gone", [OWN_75], ceased="2023-01-01")

# 27 secondary software SIC only (passes Stage 2, software_sic_primary false)
company("10000027", "RETAIL FIRST LTD", sic1="47910")
psc_row("10000027", IND, "Ms Tara Shop", [OWN_75])
director("10000027", "SHOP, Tara")

# 28 corporate PSC without a registration number, resolved by exact name against companies
company("10000028", "NAME RESOLVED LTD")
psc_row("10000028", CORP, "NR HOLDINGS LIMITED", [OWN_75], reg="", country="England", legal="Private Limited")
company("20000028", "NR HOLDINGS LIMITED", in_software=False, with_accounts=False, sic1="64209")
psc_row("20000028", IND, "Mr Victor Hugo", [OWN_75])
director("10000028", "HUGO, Victor")

# Stage 2 failures that must never reach Stage 3
company("10000095", "SMALL AND YOUNG LTD", employees=5, inc_date="2023-02-01")   # size fails first
company("10000096", "NO ACCOUNTS LTD", with_accounts=False)
company("10000097", "TOO SMALL LTD", employees=5)
company("10000098", "TOO YOUNG LTD", inc_date="2023-02-01")
company("10000099", "MICRO LTD", category="MICRO ENTITY")
psc_row("10000097", IND, "Mr Tiny Owner", [OWN_75])


def write(name: str, rows: list[dict]) -> None:
    with open(HERE / name, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


if __name__ == "__main__":
    write("companies.csv", companies)
    write("accounts_wide.csv", accounts)
    write("psc.csv", psc)
    write("officers.csv", officers)
    write("filings.csv", filings)
    print(f"companies {len(companies)}, accounts {len(accounts)}, psc {len(psc)}, officers {len(officers)}, filings {len(filings)}")
