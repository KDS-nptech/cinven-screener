"""Stage 3 tests: every founder-ownership rule on synthetic PSC fixtures.

Run: pytest tests/test_ownership.py -q

The CSV inputs live in tests/fixtures/ownership/ (regenerate with
build_fixtures.py). The loader converts them to parquet in a temp dir, then the
real pipeline runs with parquet_dir pointed at it.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys

import polars as pl
import pytest

from src.common import REPO, cfg
from src.filter import ownership

FIXTURES = REPO / "tests" / "fixtures" / "ownership"


def _loader():
    spec = importlib.util.spec_from_file_location("ownership_fixture_loader", FIXTURES / "loader.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def full(tmp_path_factory):
    """Pipeline with officers and filings present."""
    d = tmp_path_factory.mktemp("own_full")
    _loader().build_parquet(d, officers=True, filings=True)
    df = ownership.run(d, d / "docs")
    return d, df


@pytest.fixture(scope="module")
def bare(tmp_path_factory):
    """Pipeline without officers.parquet or filings.parquet."""
    d = tmp_path_factory.mktemp("own_bare")
    _loader().build_parquet(d, officers=False, filings=False)
    df = ownership.run(d, d / "docs")
    return d, df


def _row(df: pl.DataFrame, cn: str) -> dict:
    rows = df.filter(pl.col("company_number") == cn).to_dicts()
    assert len(rows) == 1, f"{cn} should appear exactly once in universe"
    return rows[0]


# (company, founder_flag, confidence, exclusion_reason, investor_flag, flags, investor_names, walkup_path)
CASES = [
    ("10000001", "excluded", None, "dispersed", "none", [], [], None),
    ("10000002", "excluded", None, "investor_present", "present", [], ["HG CAPITAL LLP"], None),
    ("10000003", "excluded", None, "investor_present", "present", [], ["XYZ FUND II LP"], None),
    ("10000004", "founder", "high", None, "none", ["holdco_walkup"], [], "10000004 -> 20000004"),
    ("10000005", "founder", "high", None, "none", ["holdco_walkup"], [], "10000005 -> 20000005"),
    ("10000006", "excluded", None, "investor_present", "present", [], ["LDC (MANAGERS) LIMITED"], None),
    ("10000007", "uncertain", "low", "foreign_corporate", "none", [], [], None),
    ("10000008", "founder", "high", None, "none", [], [], None),
    ("10000009", "founder", "medium", None, "none", ["check_share_premium"], [], None),
    ("10000010", "uncertain", "low", None, "none", ["nominee_or_trust"], [], None),
    ("10000011", "uncertain", "low", None, "none", ["super_secure"], [], None),
    ("10000012", "uncertain", "low", "no_psc", "none", [], [], None),
    ("10000013", "founder", "high", None, "possible", ["sh01_heavy"], [], None),
    ("10000014", "founder", "high", None, "possible", ["share_premium_high"], [], None),
    ("10000015", "founder", "medium", None, "none", ["director_test_failed", "check_share_premium"], [], None),
    ("10000016", "uncertain", "low", None, "none", [], [], None),
    # config.ownership.holdco_walkup_levels is 3, so the Bidco-style stack resolves to its founder
    ("10000017", "founder", "medium", None, "none", ["holdco_walkup", "director_test_unavailable", "check_share_premium"], [],
     "10000017 -> 20000017; 10000017 -> 20000017 -> 20000018"),
    ("10000018", "founder", "high", None, "none", ["voting_proxy"], [], None),
    ("10000019", "founder", "high", None, "none", ["multiple_corporate_pscs", "holdco_walkup"], [],
     "10000019 -> 20000019; 10000019 -> 20000020"),
    ("10000020", "excluded", None, "dispersed", "none", [], [], None),
    ("10000021", "founder", "high", None, "none", [], [], None),
    ("10000022", "uncertain", "low", None, "none", ["no_ownership_band"], [], None),
    ("10000023", "uncertain", "low", None, "none", [], [], None),
    ("10000024", "uncertain", "low", "corporate_unresolved", "none", [], [], None),
    ("10000025", "founder", "high", None, "none", [], [], None),
    ("10000026", "uncertain", "low", "no_psc", "none", ["all_pscs_ceased"], [], None),
    ("10000027", "founder", "high", None, "none", [], [], None),
    ("10000028", "founder", "high", None, "none", ["holdco_walkup", "holdco_name_resolved"], [], "10000028 -> 20000028"),
]


@pytest.mark.parametrize("cn,flag,conf,reason,inv_flag,flags,inv_names,path", CASES, ids=[c[0] for c in CASES])
def test_rule_outcomes(full, cn, flag, conf, reason, inv_flag, flags, inv_names, path):
    _, df = full
    r = _row(df, cn)
    assert r["founder_flag"] == flag
    assert r["founder_confidence"] == conf
    assert r["exclusion_reason"] == reason
    assert r["investor_flag"] == inv_flag
    assert r["flags"] == flags
    assert r["investor_names"] == inv_names
    assert r["walkup_path"] == path


def test_universe_only_holds_stage2_passers(full):
    _, df = full
    assert len(df) == 28
    for cn in ("10000095", "10000096", "10000097", "10000098", "10000099"):
        assert df.filter(pl.col("company_number") == cn).is_empty()


def test_output_schema(full):
    d, df = full
    expected = ["company_number", "name", "post_town", "postcode", "sic1", "inc_date", "latest_employees",
                "latest_period_end", "latest_turnover", "account_category", "passes_size", "passes_age", "provisional",
                "founder_flag", "founder_confidence", "exclusion_reason", "investor_flag", "investor_names",
                "flags", "individual_pscs_json", "walkup_path", "combined_pct_mid", "n_individual_pscs",
                "n_corporate_pscs", "n_statements", "sh01_count", "share_premium_latest", "computed_at"]
    assert df.columns == expected
    assert df.schema["investor_names"] == pl.List(pl.String)
    assert df.schema["flags"] == pl.List(pl.String)
    assert (d / "universe.parquet").exists()
    assert (d / "docs" / "funnel_stage3.json").exists()
    assert df["founder_flag"].is_in(["founder", "excluded", "uncertain"]).all()
    assert df["computed_at"].str.len_chars().min() >= 19


def test_holdco_walkup_individuals(full):
    _, df = full
    r = _row(df, "10000005")
    people = json.loads(r["individual_pscs_json"])
    assert [p["name"] for p in people] == ["Ms Alice Cooper", "Mr Bob Dylan"]
    assert all(p["via_holdco"] for p in people)
    assert all(p["holdco"] == "20000005" for p in people)
    # 62.5 + 37.5: a holdco in the 75-100 band is read as wholly owned, so no scaling
    assert r["combined_pct_mid"] == pytest.approx(100.0)
    assert [p["pct_mid"] for p in people] == [62.5, 37.5]
    assert r["n_individual_pscs"] == 2 and r["n_corporate_pscs"] == 1
    # minority holdcos scale the look-through stake: 87.5 x 62.5% + 87.5 x 37.5%
    multi = json.loads(_row(df, "10000019")["individual_pscs_json"])
    assert [p["pct_mid"] for p in multi] == [pytest.approx(54.69), pytest.approx(32.81)]
    assert _row(df, "10000019")["combined_pct_mid"] == pytest.approx(87.5)
    direct = _row(df, "10000008")
    p = json.loads(direct["individual_pscs_json"])[0]
    assert p["via_holdco"] is False and p["pct_mid"] == 87.5
    assert p["band"] == cfg()["ownership"]["high_confidence_band"]
    assert p["notified_on"] == "2016-04-06"


def test_investor_excluded_company_still_lists_direct_individuals(full):
    _, df = full
    people = json.loads(_row(df, "10000002")["individual_pscs_json"])
    assert [p["name"] for p in people] == ["Mr Peter Parker"]


def test_sh01_and_share_premium(full):
    _, df = full
    assert _row(df, "10000013")["sh01_count"] == 4          # the 2014 SH01 predates incorporation
    assert _row(df, "10000014")["sh01_count"] == 1
    assert _row(df, "10000014")["share_premium_latest"] == 750000.0
    assert _row(df, "10000012")["sh01_count"] == 0           # filings present, none for this company
    # excluded companies keep their register verdict; rule 8 is only for the kept
    assert _row(df, "10000001")["investor_flag"] == "none"


def test_counts_columns(full):
    _, df = full
    assert _row(df, "10000001")["n_statements"] == 1
    assert _row(df, "10000019")["n_corporate_pscs"] == 2
    assert _row(df, "10000016")["n_individual_pscs"] == 4
    assert _row(df, "10000021")["n_corporate_pscs"] == 0     # the ceased BGF record is not active


def test_without_officers_or_filings(bare):
    _, df = bare
    assert len(df) == 28
    r = _row(df, "10000008")
    assert (r["founder_flag"], r["founder_confidence"]) == ("founder", "medium")
    assert r["flags"] == ["director_test_unavailable", "check_share_premium"]
    assert df["sh01_count"].is_null().all()
    assert "sh01_heavy" not in _row(df, "10000013")["flags"]
    assert _row(df, "10000013")["investor_flag"] == "none"
    # share premium still works without filings
    assert _row(df, "10000014")["flags"] == ["director_test_unavailable", "check_share_premium", "share_premium_high"]
    assert _row(df, "10000014")["investor_flag"] == "possible"
    # exclusions do not depend on officers
    assert _row(df, "10000002")["exclusion_reason"] == "investor_present"
    # the director-fail case becomes plain medium because the test did not run
    assert _row(df, "10000015")["flags"] == ["director_test_unavailable", "check_share_premium"]


def test_summary_json(full):
    d, df = full
    s = json.loads((d / "docs" / "funnel_stage3.json").read_text())
    assert s["rows"] == 28
    assert s["inputs"] == {"officers_available": True, "filings_available": True}
    assert sum(s["founder_flag"].values()) == 28
    assert s["founder_flag"]["excluded"] == 5
    assert s["exclusion_reason"]["investor_present"] == 3


# ---------------------------------------------------------------- unit checks on the helpers
RULES = ownership.compile_rules()


@pytest.mark.parametrize("name,hit", [
    ("HG CAPITAL LLP", True),
    ("HGCAPITAL TRUST PLC", True),
    ("Hg Pooled Management Limited", True),
    ("HIGHGATE SOFTWARE LTD", False),
    ("XYZ FUND II LP", True),
    ("XYZ L.P.", True),
    ("ALPHA LPG LTD", False),
    ("LDC (MANAGERS) LIMITED", True),
    ("GOLDCREST HOLDINGS LTD", False),
    ("OCTOPUS INVESTMENTS NOMINEES LIMITED", True),
    ("ACCELERATE SOFTWARE LTD", False),
    ("NOTIONAL SOFTWARE LTD", False),
    ("RANDOM FUNDRAISING LTD", False),
    ("BLUE OCEAN CAPITAL PARTNERS LLP", True),
    ("EPISODE 1 VENTURES LLP", True),
    ("", False),
    (None, False),
])
def test_investor_match(name, hit):
    assert bool(ownership.investor_match(name, RULES)) is hit


def test_investor_match_labels_come_from_config():
    labels = ownership.investor_match("BGF INVESTMENTS LP", RULES)
    assert "BGF" in labels and "LP" in labels
    assert set(labels) <= set(cfg()["ownership"]["investor_names"]) | {t.strip() for t in cfg()["ownership"]["investor_name_tokens"]}


@pytest.mark.parametrize("a,b,same", [
    ("Mr John Michael Smith", "SMITH, John Michael", True),
    ("Dr Anna Smith-Jones", "SMITH-JONES, Dr Anna", True),
    ("Mr Jan Van Der Berg", "VAN DER BERG, Jan", True),
    ("Ms Jane O'Brien OBE", "O'BRIEN, Jane", True),
    ("Mr John Smith", "SMITH, Jonathan", False),
    ("Mr John Smith", "JONES, John", False),
])
def test_person_matching(a, b, same):
    assert ownership.same_person(ownership.person_key(a), ownership.person_key(b)) is same


@pytest.mark.parametrize("raw,expected", [
    ("12345678", "12345678"), ("1234567", "01234567"), ("SC123456", "SC123456"), ("No. 09876543", "09876543"),
    ("HRB 12345", None), ("1234567890", None), (None, None), ("", None),
])
def test_norm_reg_number(raw, expected):
    assert ownership.norm_reg_number(raw) == expected


@pytest.mark.parametrize("row,kind", [
    ({"corporate_reg_number": "12345678", "country_registered": "England", "legal_form": "Limited Company"}, "uk"),
    ({"corporate_reg_number": "12345678", "country_registered": "England & Wales", "legal_form": "Ltd"}, "uk"),
    ({"corporate_reg_number": "12345678", "country_registered": "Northern Ireland", "legal_form": "Limited"}, "uk"),
    ({"corporate_reg_number": "12345678", "country_registered": None, "legal_form": None}, "uk"),
    ({"corporate_reg_number": "1234567", "country_registered": "Delaware", "legal_form": "Corporation"}, "foreign"),
    ({"corporate_reg_number": "12345678", "country_registered": "Ireland", "legal_form": "Limited"}, "foreign"),
    ({"corporate_reg_number": None, "country_registered": "United Kingdom", "legal_form": "Limited"}, "unresolved"),
    ({"corporate_reg_number": None, "country_registered": None, "legal_form": None}, "unresolved"),
])
def test_classify_corporate(row, kind):
    assert ownership.classify_corporate(row)[0] == kind


def test_band_parsing_uses_config_midpoints():
    mids = cfg()["ownership"]["band_midpoints"]
    b = ownership.parse_bands(["ownership-of-shares-50-to-75-percent", "voting-rights-75-to-100-percent"], RULES)
    assert b["band"] == "ownership-of-shares-50-to-75-percent" and b["mid"] == mids["ownership-of-shares-50-to-75-percent"]
    v = ownership.parse_bands(["voting-rights-25-to-50-percent"], RULES)
    assert v["voting_proxy"] is True and v["mid"] == mids["ownership-of-shares-25-to-50-percent"]
    t = ownership.parse_bands(["ownership-of-shares-75-to-100-percent-as-trust"], RULES)
    assert t["trust_or_firm_only"] is True and t["mid"] == mids["ownership-of-shares-75-to-100-percent"]
    o = ownership.parse_bands(["ownership-of-shares-more-than-25-percent-registered-overseas-entity"], RULES)
    assert o["mid"] == mids["ownership-of-shares-more-than-25-percent-registered-overseas-entity"]
    assert ownership.parse_bands(["significant-influence-or-control"], RULES)["band"] is None


def test_empty_universe_survives(tmp_path):
    """No accounts means nobody passes Stage 2; Stage 3 must still write an empty, well-typed table."""
    _loader().build_parquet(tmp_path)
    (tmp_path / "accounts_wide.parquet").unlink()
    df = ownership.run(tmp_path, tmp_path / "docs")
    assert len(df) == 0
    assert df.schema["flags"] == pl.List(pl.String)
    assert pl.read_parquet(tmp_path / "universe.parquet").is_empty()


def test_walkup_levels_from_config(tmp_path, monkeypatch):
    """With two levels the Bidco-style stack (opco -> holdco -> topco -> founder) resolves."""
    _loader().build_parquet(tmp_path)
    monkeypatch.setitem(cfg()["ownership"], "holdco_walkup_levels", 2)
    try:
        df = ownership.run(tmp_path, tmp_path / "docs")
    finally:
        monkeypatch.undo()
    r = _row(df, "10000017")
    assert (r["founder_flag"], r["founder_confidence"], r["exclusion_reason"]) == ("founder", "medium", None)
    assert r["walkup_path"] == "10000017 -> 20000017; 10000017 -> 20000017 -> 20000018"
    assert "director_test_unavailable" in r["flags"]   # no officer rows for the opco in the fixture: unavailable, not failed


def test_module_is_runnable(tmp_path):
    _loader().build_parquet(tmp_path)
    proc = subprocess.run(
        [sys.executable, "-m", "src.filter.ownership", "--parquet-dir", str(tmp_path), "--docs-dir", str(tmp_path / "docs")],
        cwd=REPO, capture_output=True, text=True, timeout=180,
    )
    assert proc.returncode == 0, proc.stderr
    assert "Stage 3 universe: 28 companies" in proc.stdout
    assert (tmp_path / "universe.parquet").exists()
    assert (tmp_path / "size_age.parquet").exists()   # Stage 2 was run on demand
