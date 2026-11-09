"""Turn the CSV fixtures in this directory into the parquet layout Stages 2 and 3 read.

    from loader import build_parquet
    build_parquet(tmp_dir, officers=True, filings=True)

Writes companies.parquet, software_companies.parquet, accounts_wide.parquet,
psc/part-00.parquet and, when asked, officers.parquet and filings.parquet.
"""
from __future__ import annotations

import pathlib

import polars as pl

HERE = pathlib.Path(__file__).parent


def _csv(name: str) -> pl.DataFrame:
    return pl.read_csv(HERE / name, infer_schema=False)


def _date(col: str) -> pl.Expr:
    return pl.col(col).str.to_date("%Y-%m-%d", strict=False).alias(col)


def _bool(col: str) -> pl.Expr:
    return (pl.col(col).str.to_lowercase() == "true").alias(col)


def _num(col: str, dtype) -> pl.Expr:
    return pl.col(col).cast(dtype, strict=False).alias(col)


def companies_frame() -> pl.DataFrame:
    return _csv("companies.csv").with_columns(
        _date("inc_date"), _bool("is_software_sic"), _num("charges_outstanding", pl.Int64),
    )


def accounts_frame() -> pl.DataFrame:
    return _csv("accounts_wide.csv").with_columns(
        _date("period_end"), _num("employees", pl.Int64), _num("turnover", pl.Float64),
        _num("share_capital", pl.Float64), _num("share_premium", pl.Float64), _bool("latest_for_company"),
    )


def psc_frame() -> pl.DataFrame:
    df = _csv("psc.csv")
    return df.with_columns(
        pl.when(pl.col("natures_of_control").is_null() | (pl.col("natures_of_control") == ""))
        .then(None).otherwise(pl.col("natures_of_control").str.split("|")).alias("natures_of_control"),
        _date("notified_on"), _date("ceased_on"), _bool("is_active"), _num("dob_year", pl.Int64),
    )


def officers_frame() -> pl.DataFrame:
    return _csv("officers.csv").with_columns(_date("appointed_on"), _date("resigned_on"))


def filings_frame() -> pl.DataFrame:
    return _csv("filings.csv").with_columns(_date("date"))


def build_parquet(out: pathlib.Path, officers: bool = True, filings: bool = True) -> pathlib.Path:
    out = pathlib.Path(out)
    out.mkdir(parents=True, exist_ok=True)
    comp = companies_frame()
    comp.write_parquet(out / "companies.parquet")
    comp.filter((pl.col("status") == "Active") & pl.col("is_software_sic")).write_parquet(out / "software_companies.parquet")
    accounts_frame().write_parquet(out / "accounts_wide.parquet")
    (out / "psc").mkdir(exist_ok=True)
    psc_frame().write_parquet(out / "psc" / "part-00.parquet")
    if officers:
        officers_frame().write_parquet(out / "officers.parquet")
    if filings:
        filings_frame().write_parquet(out / "filings.parquet")
    return out
