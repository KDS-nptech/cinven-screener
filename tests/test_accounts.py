"""Stage 1b tests: lean iXBRL parser and the accounts pipeline helpers, on fixtures only."""
from __future__ import annotations

import json
import pathlib
import zipfile

import pytest

from src.ingest import accounts, ixbrl

FIX = pathlib.Path(__file__).parent / "fixtures" / "accounts"
SYN = FIX / "synthetic_edge_cases_12345678_20251231.html"
PLAIN = FIX / "synthetic_plain_xbrl_87654321_20250630.xml"
CCH = FIX / "Prod223_4326_00037545_20260331.html"       # CCH scale="-2" on employees
MEDIUM = FIX / "Prod223_4326_03896652_20260430.html"    # medium entity with turnover
SCALE3 = FIX / "Prod223_4326_02135788_20260331.html"    # scale="3" on CostSales
MICRO = FIX / "Prod223_4326_01171856_20260623.html"
DORMANT = FIX / "Prod223_4326_00892901_20260331.html"
SCOTTISH = FIX / "Prod223_4326_SC631364_20250531.html"


def facts(parsed, concept):
    return [f for f in parsed["facts"] if f["concept"] == concept]


def current(parsed, concept, undimensioned=True):
    pe = parsed["period_end"]
    out = [f for f in facts(parsed, concept) if (f["end"] or f["instant"]) == pe
           and (not undimensioned or not f["dims"])]
    assert out, f"no current fact for {concept}"
    return out[0]


# ---------------------------------------------------------------- real fixtures
def test_all_fixtures_parse_and_match_filename():
    for f in sorted(FIX.glob("Prod*.html")):
        p = ixbrl.parse_file(str(f))
        num, end = accounts.parse_member_name(f.name)
        assert p["company_number"] == num
        assert p["period_end"] == end
        assert p["period_start"] and p["period_start"] < p["period_end"]
        assert p["kind"] == "ixbrl"
        assert p["facts"]


def test_period_end_and_employees_medium_entity():
    p = ixbrl.parse_file(str(MEDIUM))
    assert p["period_end"] == "2026-04-30"
    assert p["period_start"] == "2025-05-01"
    assert p["balance_sheet_date"] == "2026-04-30"
    emp = current(p, "AverageNumberEmployeesDuringPeriod")
    assert emp["value"] == 72 and emp["period_type"] == "duration"
    turn = current(p, "TurnoverRevenue")
    assert turn["value"] == 14066007
    assert ixbrl.accounting_standard(p) == "MediumEntities"
    assert ixbrl.accounts_type(p) == "FullAccounts"
    assert ixbrl.is_dormant(p) is False


def test_cch_negative_scale_on_employees_is_ignored():
    p = ixbrl.parse_file(str(CCH))
    emp = current(p, "AverageNumberEmployeesDuringPeriod")
    assert emp["scale"] == "-2"
    assert emp["value"] == 84          # corrected count
    assert abs(emp["value_literal"] - 0.84) < 1e-9   # what the spec-literal reading gives
    # a money fact in the same file keeps its sign attribute
    loss = current(p, "ProfitLossOnOrdinaryActivitiesBeforeTax")
    assert loss["sign"] == "-" and loss["value"] == -758412


def test_positive_scale_is_applied():
    p = ixbrl.parse_file(str(SCALE3))
    cs = [f for f in facts(p, "CostSales") if f["scale"] == "3"]
    assert cs and cs[0]["value"] == 4601000


def test_micro_entity_dormant_and_scottish_prefix():
    micro = ixbrl.parse_file(str(MICRO))
    assert ixbrl.accounting_standard(micro) == "Micro-entities"
    assert ixbrl.accounts_type(micro) == "FilletedAccounts"
    dorm = ixbrl.parse_file(str(DORMANT))
    assert ixbrl.is_dormant(dorm) is True
    sc = ixbrl.parse_file(str(SCOTTISH))
    assert sc["company_number"] == "SC631364"
    cred = [f for f in facts(sc, "Creditors") if f["instant"] == sc["period_end"]]
    assert any(f["is_within_one_year"] for f in cred)


# ---------------------------------------------------------------- synthetic edge cases
def test_synthetic_scale_sign_formats_and_nesting():
    p = ixbrl.parse_file(str(SYN))
    assert p["company_number"] == "12345678"
    assert p["period_start"] == "2025-01-01"       # ixt:datedaymonthyear 01/01/2025
    assert p["period_end"] == "2025-12-31"         # ixt:datelonguk with ordinal suffix
    assert p["entity_name"] == "Synthetic Software Limited"  # ix:exclude dropped
    assert current(p, "TurnoverRevenue")["value"] == 12_345_000        # scale 3
    assert current(p, "ProfitLoss")["value"] == -1500                  # sign="-"
    assert current(p, "GrossProfitLoss")["value"] == 7500.75           # ixt:numcomma
    emp = current(p, "AverageNumberEmployeesDuringPeriod")
    assert emp["value"] == 42 and abs(emp["value_literal"] - 0.42) < 1e-9
    assert current(p, "FixedAssets")["value"] == 2000                  # outer of nested pair
    assert current(p, "IntangibleAssets")["value"] == 2000             # inner of nested pair
    by_ctx = {(f["concept"], f["context_id"]): f["value"] for f in p["facts"]}
    assert by_ctx[("CashBankOnHand", "pye")] == 0                      # ixt2:zerodash
    assert by_ctx[("TradeDebtorsTradeReceivables", "pye")] == 0        # ixt:numdash
    assert by_ctx[("OtherCreditors", "pye")] == 0                      # ixt:fixed-zero
    assert by_ctx[("NetCurrentAssetsLiabilities", "cye")] == -250      # (250) no format
    assert ("Dividends", "cy") not in by_ctx                           # xsi:nil skipped
    within = [f for f in facts(p, "Creditors") if f["is_within_one_year"]]
    after = [f for f in facts(p, "Creditors") if f["is_after_one_year"]]
    assert within[0]["value"] == 4000 and after[0]["value"] == 1000
    assert within[0]["dims"] == {"MaturitiesOrExpirationPeriodsDimension": "WithinOneYear"}
    sc = [f for f in facts(p, "Equity") if f["dims"].get("EquityClassesDimension") == "ShareCapital"]
    assert sc[0]["value"] == 100
    assert ixbrl.is_dormant(p) is False                                # ixt2:booleanfalse
    assert ixbrl.accounts_type(p) == "FullAccounts"
    assert ixbrl.accounting_standard(p) == "FRS102"
    assert p["officers"] == ["A Director"]


def test_plain_xbrl_instance():
    p = ixbrl.parse_file(str(PLAIN))
    assert p["kind"] == "xbrl"
    assert p["company_number"] == "87654321"
    assert p["period_end"] == "2025-06-30" and p["period_start"] == "2024-07-01"
    assert p["entity_name"] == "Legacy Plain XBRL Ltd"
    assert current(p, "TurnoverGrossOperatingRevenue")["value"] == 3_500_000
    assert current(p, "AverageNumberEmployeesDuringPeriod")["value"] == 31
    assert current(p, "CashBankInHand")["value"] == -1200
    assert current(p, "CashBankInHand")["unit"] == "GBP"


def test_parse_number_rules():
    pn = ixbrl.parse_number
    assert pn("1,234.5", "ixt:numcommadot", None, None) == (1234.5, 1234.5)
    assert pn("1.234,5", "ixt:numdotcomma", None, None) == (1234.5, 1234.5)
    assert pn("-", "ixt:zerodash", None, None) == (0.0, 0.0)
    assert pn("", None, None, None) == (0.0, 0.0)
    assert pn("12", None, "3", "-", "Turnover") == (-12000.0, -12000.0)
    assert pn("84", None, "-2", None, "AverageNumberEmployeesDuringPeriod") == (84.0, 0.84)
    assert pn("84", None, "-2", None, "ApplicableTaxRate") == (0.84, 0.84)
    assert pn("x", "ixt:nocontent", None, None) == (None, None)
    with pytest.raises(ixbrl.IxbrlParseError):
        pn("abc", None, None, None)


def test_parse_date_variants():
    pd = ixbrl.parse_date
    assert pd("31 January 2026") == "2026-01-31"
    assert pd("31st Jan 26") == "2026-01-31"
    assert pd("January 31, 2026") == "2026-01-31"
    assert pd("31/01/2026") == "2026-01-31"
    assert pd("31.01.2026") == "2026-01-31"
    assert pd("2026-01-31") == "2026-01-31"
    assert pd("not a date") is None


# ---------------------------------------------------------------- pipeline helpers
def test_member_name_parsing_and_selection(tmp_path):
    assert accounts.parse_member_name("Prod223_3456_00123456_20250331.html") == ("00123456", "2025-03-31")
    assert accounts.parse_member_name("Prod223_4326_SC631364_20250531.html") == ("SC631364", "2025-05-31")
    assert accounts.parse_member_name("Prod223_4326_11441116_20260630_CIC.zip") is None
    assert accounts.parse_member_name("readme.txt") is None
    z = tmp_path / "t.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.write(MEDIUM, "Prod223_4326_03896652_20260430.html")
        zf.write(MICRO, "Prod223_4326_01171856_20260623.html")
        zf.writestr("Prod223_4326_11441116_20260630_CIC.zip", b"PK")
    with zipfile.ZipFile(z) as zf:
        picked, stats = accounts.select_members(zf, {"03896652"})
    assert [p.filename for p in picked] == ["Prod223_4326_03896652_20260430.html"]
    assert stats["members"] == 3 and stats["nested_zip"] == 1 and stats["matched"] == 1


def test_parse_one_rows_and_meta():
    res = accounts.parse_one((str(MEDIUM), "test.zip", "2026-10-12T00:00:00+00:00"))
    assert not res.get("error")
    meta = res["meta"]
    assert meta["company_number"] == "03896652" and meta["period_end"] == "2026-04-30"
    assert meta["has_turnover"] and meta["has_employees"] and meta["parser"] == "lean"
    assert meta["accounting_standard"] == "MediumEntities"
    concepts = {r["concept"] for r in res["facts"]}
    assert {"TurnoverRevenue", "AverageNumberEmployeesDuringPeriod", "Creditors"} <= concepts
    row = next(r for r in res["facts"] if r["concept"] == "TurnoverRevenue" and r["dims_json"] == "{}"
               and r["end"] == "2026-04-30")
    assert row["value"] == 14066007 and row["period_type"] == "duration"
    assert json.loads(row["dims_json"]) == {}
    # keep rule: config lists, extras and substrings
    keep = accounts.keep_concepts()
    assert accounts._keep("TurnoverRevenue", keep) and accounts._keep("CorporationTaxPayable", keep)
    assert accounts._keep("SomethingDeferredThing", keep) and not accounts._keep("ParValueShareX", keep)


def test_archive_plan_offline():
    monthly = accounts.monthly_archives()
    assert monthly[0] == "Accounts_Monthly_Data-September2026.zip"
    assert monthly[-1] == "Accounts_Monthly_Data-October2025.zip"
    dailies = accounts.daily_archives(use_network=False)
    assert dailies[0] == "Accounts_Bulk_Data-2026-10-01.zip"
    assert all("2026-10-" in d for d in dailies)
    assert accounts.zip_sort_key("Accounts_Monthly_Data-September2026.zip") == "2026-09-30"
    assert accounts.zip_sort_key("Accounts_Bulk_Data-2026-10-10.zip") == "2026-10-10"
