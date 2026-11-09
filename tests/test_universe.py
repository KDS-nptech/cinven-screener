"""Stage 2 tests on the synthetic fixtures in tests/fixtures/ownership/.

Run: pytest tests/test_universe.py -q
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import subprocess
import sys

import polars as pl
import pytest

from src.common import REPO, cfg
from src.filter import universe

FIXTURES = REPO / "tests" / "fixtures" / "ownership"


def _loader():
    spec = importlib.util.spec_from_file_location("ownership_fixture_loader", FIXTURES / "loader.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def stage2(tmp_path_factory):
    d = tmp_path_factory.mktemp("stage2")
    _loader().build_parquet(d)
    funnel = universe.run(d, d / "docs")
    df = pl.read_parquet(d / "size_age.parquet")
    return d, funnel, df


def _row(df: pl.DataFrame, cn: str) -> dict:
    rows = df.filter(pl.col("company_number") == cn).to_dicts()
    assert len(rows) == 1, f"{cn} should appear exactly once"
    return rows[0]


def test_every_software_company_kept_with_rule_columns(stage2):
    _, _, df = stage2
    assert len(df) == 33  # software companies only; the non-software holdco 20000028 is excluded
    for col in ("passes_size", "passes_age", "passes_category", "passes_all", "has_accounts",
                "latest_employees", "latest_period_end", "latest_turnover", "exclusion_reason",
                "software_sic_primary", "computed_at"):
        assert col in df.columns, col
    assert df["company_number"].is_unique().all()


def test_latest_accounts_row_wins(stage2):
    _, _, df = stage2
    r = _row(df, "10000008")
    assert r["has_accounts"] is True
    assert r["latest_employees"] == 60          # not the older 10-employee period
    assert str(r["latest_period_end"]) == "2025-03-31"
    assert r["latest_turnover"] == 6000000.0
    assert r["passes_all"] is True and r["exclusion_reason"] is None


@pytest.mark.parametrize("cn,reason,size,age,cat", [
    ("10000097", "employees_below_min", False, True, True),
    ("10000098", "incorporated_too_recently", True, False, True),
    ("10000099", "account_category_excluded", True, True, False),
    ("10000096", "no_accounts", False, True, True),
    ("10000095", "employees_below_min", False, False, True),  # size is reported before age
])
def test_exclusion_reasons(stage2, cn, reason, size, age, cat):
    _, _, df = stage2
    r = _row(df, cn)
    assert r["exclusion_reason"] == reason
    assert (r["passes_size"], r["passes_age"], r["passes_category"]) == (size, age, cat)
    assert r["passes_all"] is False


def test_no_accounts_company(stage2):
    _, _, df = stage2
    r = _row(df, "10000096")
    assert r["has_accounts"] is False
    assert r["latest_employees"] is None and r["latest_period_end"] is None


def test_primary_sic_flag_is_informational(stage2):
    _, _, df = stage2
    r = _row(df, "10000027")
    assert r["software_sic_primary"] is False
    assert r["passes_all"] is True
    assert _row(df, "10000008")["software_sic_primary"] is True


def test_funnel_counts_and_thresholds(stage2):
    d, funnel, df = stage2
    f = funnel["funnel"]
    # 33 software companies; 10000096 has no accounts; 95 and 97 fail size; 98 fails age; 99 fails category
    assert f == {
        "active_software": 33, "with_accounts": 32, "passes_size": 30, "passes_age": 29,
        "passes_category": 28, "passes_all": 28,
    }
    assert f["passes_all"] == int(df["passes_all"].sum())
    t = cfg()["target"]
    assert funnel["thresholds"]["employees_min"] == t["employees_min"]
    assert funnel["thresholds"]["employees_max"] == t["employees_max"]
    assert funnel["thresholds"]["incorporated_on_or_before"] == str(t["incorporated_on_or_before"])
    assert funnel["thresholds"]["exclude_account_categories"] == [c.upper() for c in t["exclude_account_categories"]]
    on_disk = json.loads((d / "docs" / "funnel_stage2.json").read_text())
    assert on_disk["funnel"] == f
    assert on_disk["exclusion_reasons"]["none"] == 28


def test_derives_software_companies_when_missing(tmp_path):
    _loader().build_parquet(tmp_path)
    (tmp_path / "software_companies.parquet").unlink()
    funnel = universe.run(tmp_path, tmp_path / "docs")
    assert funnel["funnel"]["active_software"] == 33
    assert funnel["funnel"]["passes_all"] == 28


def test_module_is_runnable(tmp_path):
    _loader().build_parquet(tmp_path)
    proc = subprocess.run(
        [sys.executable, "-m", "src.filter.universe", "--parquet-dir", str(tmp_path), "--docs-dir", str(tmp_path / "docs")],
        cwd=REPO, capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    assert "passes_all" in proc.stdout
    assert (tmp_path / "size_age.parquet").exists()
    assert (tmp_path / "docs" / "funnel_stage2.json").exists()


def test_missing_inputs_exit_cleanly(tmp_path):
    proc = subprocess.run(
        [sys.executable, "-m", "src.filter.universe", "--parquet-dir", str(tmp_path / "empty"), "--docs-dir", str(tmp_path / "docs")],
        cwd=REPO, capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 0
    assert not (tmp_path / "empty" / "size_age.parquet").exists()
