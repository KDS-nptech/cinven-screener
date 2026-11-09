"""Fast checks on the Stage 1a snapshot outputs. Skipped when the parquet files are absent.

Run: python -m pytest tests/test_snapshot.py -q
"""
from __future__ import annotations

import duckdb
import pytest

from src.common import cfg, parquet_path

COMPANIES = parquet_path("companies")
SOFTWARE = parquet_path("software_companies")


def _con() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute("SET threads TO 1")
    return con


def _needs(p) -> None:
    if not p.exists():
        pytest.skip(f"{p} not built yet")


def test_company_numbers_are_zero_padded_8_chars():
    _needs(COMPANIES)
    con = _con()
    bad, total = con.execute(
        f"SELECT count(*) FILTER (WHERE company_number IS NULL OR length(company_number) <> 8 "
        f"OR company_number <> upper(company_number) OR company_number <> trim(company_number)), count(*) "
        f"FROM read_parquet('{COMPANIES}')"
    ).fetchone()
    assert total > 0
    assert bad == 0
    # Numeric company numbers keep their leading zeros ("00686734", never "686734").
    short = con.execute(
        f"SELECT count(*) FROM read_parquet('{COMPANIES}') "
        f"WHERE regexp_matches(company_number, '^[0-9]+$') AND length(ltrim(company_number, '0')) < 8 "
        f"AND NOT starts_with(company_number, '0')"
    ).fetchone()[0]
    assert short == 0


def test_sic1_is_five_digits_or_null():
    _needs(COMPANIES)
    con = _con()
    bad = con.execute(
        f"SELECT count(*) FROM read_parquet('{COMPANIES}') "
        f"WHERE sic1 IS NOT NULL AND NOT regexp_matches(sic1, '^[0-9]{{5}}$')"
    ).fetchone()[0]
    assert bad == 0
    # 'None Supplied' rows carry no code.
    none_supplied_with_code = con.execute(
        f"SELECT count(*) FROM read_parquet('{COMPANIES}') "
        f"WHERE sic_text1 = 'None Supplied' AND sic1 IS NOT NULL"
    ).fetchone()[0]
    assert none_supplied_with_code == 0


def test_software_companies_are_active_with_software_sic():
    _needs(SOFTWARE)
    con = _con()
    target = cfg()["target"]["status"].strip().lower()
    sics = cfg()["target"]["software_sic"]
    sic_list = ", ".join(f"'{s}'" for s in sics)
    non_active, not_software, total = con.execute(
        f"SELECT count(*) FILTER (WHERE lower(trim(status)) <> '{target}'), "
        f"count(*) FILTER (WHERE NOT (coalesce(sic1 IN ({sic_list}), false) OR coalesce(sic2 IN ({sic_list}), false) "
        f"OR coalesce(sic3 IN ({sic_list}), false) OR coalesce(sic4 IN ({sic_list}), false))), "
        f"count(*) FROM read_parquet('{SOFTWARE}')"
    ).fetchone()
    assert total > 0
    assert non_active == 0
    assert not_software == 0
    assert con.execute(f"SELECT bool_and(is_software_sic) FROM read_parquet('{SOFTWARE}')").fetchone()[0] is True
