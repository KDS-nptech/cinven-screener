"""Stage 2: size filter for the buyout universe.

    python -m src.filter.universe                 # real data under data/parquet
    python -m src.filter.universe --parquet-dir tests/tmp/x   # any other directory

Reads candidate_companies (Stage 1a) and accounts_wide (Stage 1b), executes
universe.sql with the thresholds from config.target, and writes:

    <parquet_dir>/size_age.parquet   one row per candidate company with the latest
                                     accounts, growth, EBITDA proxy, rule booleans and
                                     exclusion_reason
    <docs_dir>/funnel_stage2.json    the funnel counts printed on stdout

Nothing here is hard-coded: employees band, incorporation cut-off and the
excluded account categories all come from config.yaml.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys

import duckdb
import polars as pl

from src.common import REPO, cfg, get_logger, now_iso, path

log = get_logger("universe")

SQL_PATH = pathlib.Path(__file__).with_name("universe.sql")


# ------------------------------------------------------------------ helpers
def source(parquet_dir: pathlib.Path, table: str) -> str | None:
    """DuckDB-readable path for a stage table: a single file or a directory of parts."""
    f = parquet_dir / f"{table}.parquet"
    if f.is_file():
        return str(f)
    d = parquet_dir / table
    if d.is_dir() and any(d.glob("*.parquet")):
        return str(d / "*.parquet")
    return None


def register_view(con: duckdb.DuckDBPyConnection, name: str, src: str) -> None:
    con.execute(f'CREATE OR REPLACE VIEW "{name}" AS SELECT * FROM read_parquet(\'{src}\', union_by_name=true)')


def fetch_frame(con: duckdb.DuckDBPyConnection, sql: str, params: dict | None = None) -> pl.DataFrame:
    """Run a query and return a polars DataFrame, keeping the schema even for zero rows."""
    res = con.execute(sql, params) if params is not None else con.execute(sql)
    to_table = getattr(res, "to_arrow_table", None) or res.fetch_arrow_table
    df = pl.from_arrow(to_table())
    return df.to_frame() if isinstance(df, pl.Series) else df


def write_table(df: pl.DataFrame, parquet_dir: pathlib.Path, table: str) -> pathlib.Path:
    """Atomic parquet write mirroring src.common.write_parquet for any directory."""
    parquet_dir.mkdir(parents=True, exist_ok=True)
    p = parquet_dir / f"{table}.parquet"
    tmp = p.with_suffix(".parquet.tmp")
    df.write_parquet(str(tmp), compression="zstd")
    os.replace(tmp, p)
    return p


def resolve_dirs(parquet_dir: str | os.PathLike | None, docs_dir: str | os.PathLike | None):
    pq = pathlib.Path(parquet_dir) if parquet_dir is not None else path("parquet")
    docs = pathlib.Path(docs_dir) if docs_dir is not None else (REPO / cfg()["paths"]["docs"])
    return pq, docs


def _candidate_view(con: duckdb.DuckDBPyConnection, pq: pathlib.Path) -> None:
    """candidate_companies.parquet plus any config.target.force_include companies from companies.parquet."""
    src = source(pq, "candidate_companies")
    if not src:
        raise FileNotFoundError(f"candidate_companies not found under {pq}")
    forced = [str(n) for n in cfg()["target"].get("force_include", []) if n]
    comp = source(pq, "companies")
    if forced and comp:
        register_view(con, "companies_all", comp)
        lst = ", ".join("'" + n.replace("'", "''") + "'" for n in forced)
        con.execute(f"""
            CREATE OR REPLACE VIEW candidate_companies AS
            SELECT * FROM read_parquet('{src}')
            UNION ALL
            SELECT c.* FROM companies_all c
            WHERE c.company_number IN ({lst})
              AND c.company_number NOT IN (SELECT company_number FROM read_parquet('{src}'))
        """)
        return
    register_view(con, "candidate_companies", src)


def _empty_accounts_view(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(
        """
        CREATE OR REPLACE VIEW accounts_wide AS
        SELECT
            NULL::VARCHAR AS company_number, NULL::DATE AS period_end, NULL::BIGINT AS employees,
            NULL::DOUBLE AS turnover, NULL::DOUBLE AS share_capital, NULL::DOUBLE AS share_premium,
            NULL::VARCHAR AS accounts_type, NULL::BOOLEAN AS latest_for_company
        WHERE FALSE
        """
    )


# ------------------------------------------------------------------ main
def run(parquet_dir: str | os.PathLike | None = None, docs_dir: str | os.PathLike | None = None) -> dict:
    """Execute Stage 2 and return the funnel dict. Writes size_age.parquet and funnel_stage2.json."""
    pq, docs = resolve_dirs(parquet_dir, docs_dir)
    target = cfg()["target"]
    con = duckdb.connect()

    _candidate_view(con, pq)
    acc = source(pq, "accounts_wide")
    if acc:
        register_view(con, "accounts_wide", acc)
    else:
        log.warning("accounts_wide not found under %s; every company will fail has_accounts", pq)
        _empty_accounts_view(con)

    params = {
        "universe_turnover_min_gbp": float(target["universe_turnover_min_gbp"]),
        "universe_employees_min": int(target["universe_employees_min"]),
        "universe_employees_max": int(target["universe_employees_max"]),
        "rank_turnover_min_gbp": float(target["rank_turnover_min_gbp"]),
        "ebitda_early_floor_gbp": float(target["ebitda_early_floor_gbp"]),
        "exclude_account_categories": [str(c).upper().strip() for c in target["exclude_account_categories"]],
        "exclude_sic": [str(c).strip() for c in target["exclude_sic"]],
        "computed_at": now_iso(),
    }
    df = fetch_frame(con, SQL_PATH.read_text(), params)
    out = write_table(df, pq, "size_age")

    funnel = compute_funnel(df, params)
    print_funnel(funnel)
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "funnel_stage2.json").write_text(json.dumps(funnel, indent=2))
    log.info("wrote %s (%s rows) and %s", out, f"{len(df):,}", docs / "funnel_stage2.json")
    return funnel


def compute_funnel(df: pl.DataFrame, params: dict) -> dict:
    """Cumulative funnel in rule order plus independent pass counts for each rule."""
    n = len(df)
    sic = df.filter(pl.col("passes_legal_form") & pl.col("passes_sic"))
    cat = sic.filter(pl.col("passes_category"))
    disc = cat.filter(pl.col("passes_disclosure"))
    acc = disc.filter(pl.col("has_accounts"))
    size = disc.filter(pl.col("passes_size"))
    all_ = df.filter(pl.col("passes_all"))
    reasons = (
        df.group_by("exclusion_reason").len().sort("exclusion_reason", nulls_last=True)
        if n else pl.DataFrame({"exclusion_reason": [], "len": []})
    )
    return {
        "computed_at": params["computed_at"],
        "thresholds": {k: v for k, v in params.items() if k != "computed_at"},
        "funnel": {
            "candidates": n,
            "passes_legal_form_and_sic": len(sic),
            "passes_category": len(cat),
            "passes_disclosure": len(disc),
            "with_parsed_accounts": len(acc),
            "passes_size_or_provisional": len(size),
            "passes_all": len(all_),
            "passes_all_verified": len(all_.filter(~pl.col("provisional"))) if n else 0,
            "passes_all_provisional": len(all_.filter(pl.col("provisional"))) if n else 0,
            "at_scale": len(all_.filter(pl.col("at_scale"))) if n else 0,
        },
        "exclusion_reasons": {
            (r if r is not None else "none"): int(c) for r, c in reasons.iter_rows()
        },
    }


def print_funnel(funnel: dict) -> None:
    f = funnel["funnel"]
    width = max(len(k) for k in f)
    print("Stage 2 funnel")
    for k, v in f.items():
        print(f"  {k.ljust(width)}  {v:>10,}")
    reasons = funnel.get("exclusion_reasons") or {}
    if reasons:
        rw = max(len(k) for k in reasons)
        print("  exclusion reasons:")
        for k, v in reasons.items():
            print(f"    {k.ljust(rw)}  {v:>8,}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--parquet-dir", default=None, help="override data/parquet (used by tests)")
    ap.add_argument("--docs-dir", default=None, help="override docs/ for funnel_stage2.json")
    a = ap.parse_args(argv)
    try:
        run(a.parquet_dir, a.docs_dir)
    except FileNotFoundError as e:
        log.error("%s; Stage 1 outputs are not there yet, nothing written", e)
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
