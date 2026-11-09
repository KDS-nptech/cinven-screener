"""Stage 1a: Companies House persons-with-significant-control (PSC) snapshot.

Run from the repo root:
    python -m src.ingest.psc              # download, flatten, verify
    python -m src.ingest.psc download     # download the 33 parts only (safe under nohup)
    python -m src.ingest.psc flatten      # flatten downloaded parts to parquet
    python -m src.ingest.psc verify       # print counts and the PortSwigger rows

Downloads psc-snapshot-<date>_{i}of<n>.zip (config.build.snapshot_psc_date, snapshot_psc_parts)
to data/raw/psc/, resume-safe and skipping complete files. Each zip holds one
newline-delimited JSON .txt, which is extracted one part at a time, flattened by
DuckDB read_ndjson into data/parquet/psc/part-{i:02d}.parquet, then deleted. Every
company is kept (the table drives the Stage 3 holdco walk-up), not just software ones.
"""
from __future__ import annotations

import json
import os
import pathlib
import sys
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed

import duckdb

from src.common import REPO, cfg, get_logger, normalise_company_number, now_iso, path
from src.ingest.snapshot import CH_DOWNLOAD_BASE, download_file

log = get_logger("psc")

PARALLEL_DOWNLOADS = 3


# ---------------------------------------------------------------- download
def psc_date() -> str:
    return cfg()["build"]["snapshot_psc_date"]


def n_parts() -> int:
    return int(cfg()["build"]["snapshot_psc_parts"])


def part_name(i: int) -> str:
    return f"psc-snapshot-{psc_date()}_{i}of{n_parts()}.zip"


def raw_dir() -> pathlib.Path:
    d = path("raw") / "psc"
    d.mkdir(parents=True, exist_ok=True)
    return d


def out_dir() -> pathlib.Path:
    """data/parquet/psc/ (a directory of parts, per docs/CONVENTIONS.md)."""
    d = path("parquet") / "psc"
    d.mkdir(parents=True, exist_ok=True)
    return d


def download_all() -> list[pathlib.Path]:
    dl_log = get_logger("psc_download")
    names = [part_name(i) for i in range(1, n_parts() + 1)]
    out: dict[str, pathlib.Path] = {}
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=PARALLEL_DOWNLOADS) as ex:
        futs = {ex.submit(download_file, f"{CH_DOWNLOAD_BASE}/{n}", raw_dir() / n, dl_log): n for n in names}
        for f in as_completed(futs):
            n = futs[f]
            out[n] = f.result()  # raises on a failed part so the run stops loudly
    dl_log.info("all %d parts present in %s (%.0fs)", len(out), raw_dir(), time.time() - t0)
    return [out[n] for n in names]


# ---------------------------------------------------------------- flatten
def _con() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute("SET threads TO 2")
    con.execute("SET memory_limit = '3GB'")
    con.execute(f"SET temp_directory = '{path('raw') / 'duckdb_tmp'}'")
    con.execute("SET preserve_insertion_order = false")
    con.execute("SET enable_progress_bar = false")
    return con


def _q(s: str) -> str:
    return s.replace("'", "''")


def extract_part(zip_path: pathlib.Path) -> pathlib.Path:
    with zipfile.ZipFile(zip_path) as z:
        members = [m for m in z.infolist() if not m.is_dir()]
        if len(members) != 1:
            raise RuntimeError(f"expected one member in {zip_path.name}, found {[m.filename for m in members]}")
        m = members[0]
        out = zip_path.parent / pathlib.Path(m.filename).name
        if out.exists() and out.stat().st_size == m.file_size:
            return out
        tmp = out.with_name(out.name + ".tmp")
        with z.open(m) as src, open(tmp, "wb") as dst:
            while True:
                buf = src.read(8 << 20)
                if not buf:
                    break
                dst.write(buf)
        os.replace(tmp, out)
        return out


# JSON paths read with ->> (string) or -> (json) from the raw `data` object. Reading the
# record as a JSON value, not a struct, keeps the query valid when a part lacks a key.
FLATTEN_SQL = """
SELECT
  CASE WHEN regexp_matches(trim(company_number), '^[0-9]+$')
       THEN lpad(trim(company_number), 8, '0') ELSE upper(trim(company_number)) END AS company_number,
  data->>'$.kind'                                        AS kind,
  data->>'$.name'                                        AS name,
  data->>'$.name_elements.forename'                      AS name_forename,
  data->>'$.name_elements.surname'                       AS name_surname,
  CAST(data->'$.natures_of_control' AS VARCHAR[])        AS natures_of_control,
  try_cast(data->>'$.notified_on' AS DATE)               AS notified_on,
  try_cast(data->>'$.ceased_on' AS DATE)                 AS ceased_on,
  -- super-secure records carry a boolean `ceased` instead of ceased_on
  (data->>'$.ceased_on') IS NULL
    AND coalesce(try_cast(data->>'$.ceased' AS BOOLEAN), false) = false AS is_active,
  data->>'$.statement'                                   AS statement,
  CASE WHEN regexp_matches(trim(data->>'$.identification.registration_number'), '^[0-9]{{1,8}}$')
         THEN lpad(trim(data->>'$.identification.registration_number'), 8, '0')
       WHEN regexp_matches(upper(trim(data->>'$.identification.registration_number')), '^(SC|NI|OC|SO|NC|SL|R|LP|SE|FC|GE|GS|IC|IP|NA|NF|NL|NO|NP|NR|NZ|RC|SA|SF|SG|SI|SP|SR|SZ|ZC|RS|CE|CS|ES|EW|NV|PC)[0-9A-Z]+$')
         THEN upper(trim(data->>'$.identification.registration_number'))
       ELSE trim(data->>'$.identification.registration_number') END AS corporate_reg_number,
  data->>'$.identification.registration_number'          AS corporate_reg_number_raw,
  data->>'$.identification.country_registered'           AS country_registered,
  data->>'$.identification.legal_form'                   AS legal_form,
  data->>'$.identification.place_registered'             AS place_registered,
  data->>'$.nationality'                                 AS nationality,
  data->>'$.country_of_residence'                        AS country_of_residence,
  try_cast(data->>'$.date_of_birth.year' AS INTEGER)     AS dob_year,
  try_cast(data->>'$.date_of_birth.month' AS INTEGER)    AS dob_month,
  data->>'$.address.locality'                            AS address_locality,
  data->>'$.address.postal_code'                         AS address_postal_code,
  try_cast(data->>'$.is_sanctioned' AS BOOLEAN)          AS is_sanctioned,
  data->>'$.description'                                 AS description,
  data->>'$.etag'                                        AS etag,
  '{fetched}'                                            AS fetched_at,
  '{snap}'                                               AS snapshot_date
FROM read_ndjson('{src}', columns={{'company_number': 'VARCHAR', 'data': 'JSON'}},
                 maximum_object_size=67108864, ignore_errors=true, format='newline_delimited')
WHERE company_number IS NOT NULL
"""

TRAILER_SQL = """
SELECT data::VARCHAR
FROM read_ndjson('{src}', columns={{'company_number': 'VARCHAR', 'data': 'JSON'}},
                 maximum_object_size=67108864, ignore_errors=true, format='newline_delimited')
WHERE company_number IS NULL
"""


def flatten_part(i: int, con: duckdb.DuckDBPyConnection | None = None) -> pathlib.Path:
    """Extract part i, flatten to data/parquet/psc/part-ii.parquet, delete the .txt."""
    own = con is None
    con = con or _con()
    out = out_dir() / f"part-{i:02d}.parquet"
    zip_path = raw_dir() / part_name(i)
    t0 = time.time()
    txt = extract_part(zip_path)
    trailers = [r[0] for r in con.execute(TRAILER_SQL.format(src=_q(str(txt)))).fetchall()]
    for t in trailers:
        log.info("part %d trailer (not loaded): %s", i, t)
    sql = FLATTEN_SQL.format(src=_q(str(txt)), fetched=now_iso(), snap=psc_date())
    tmp = out.with_suffix(".parquet.tmp")
    con.execute(f"COPY ({sql}) TO '{_q(str(tmp))}' (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 200000)")
    os.replace(tmp, out)
    n = con.execute(f"SELECT count(*) FROM read_parquet('{_q(str(out))}')").fetchone()[0]
    txt.unlink(missing_ok=True)
    log.info("part %02d: %s rows -> %s in %.0fs", i, f"{n:,}", out.name, time.time() - t0)
    if own:
        con.close()
    return out


def flatten_all(force: bool = False) -> list[pathlib.Path]:
    con = _con()
    outs = []
    for i in range(1, n_parts() + 1):
        out = out_dir() / f"part-{i:02d}.parquet"
        if out.exists() and not force:
            log.info("skip part %02d (exists)", i)
            outs.append(out)
            continue
        outs.append(flatten_part(i, con))
    con.close()
    return outs


# ---------------------------------------------------------------- verify
def resolve_backtest(con: duckdb.DuckDBPyConnection, bt: dict) -> list[str]:
    """Company numbers for a config.backtests entry.

    Uses the configured number when it is on the register snapshot; otherwise looks the
    name up in companies.parquet (name prefix plus town when given) so a stale number
    in config is reported rather than silently returning no rows.
    """
    companies = path("parquet") / "companies.parquet"
    found: list[str] = []
    cn = normalise_company_number(bt.get("company_number"))
    if cn:
        found.append(cn)
    if not companies.exists():
        return found
    c = f"read_parquet('{_q(str(companies))}')"
    if cn:
        on_register = con.execute(f"SELECT count(*) FROM {c} WHERE company_number = '{_q(cn)}'").fetchone()[0]
        if on_register:
            return found
        log.warning("backtest %s: configured number %s is not on the %s snapshot; resolving by name",
                    bt["name"], cn, cfg()["build"]["snapshot_basic"])
    name = bt["name"].upper()
    town = (bt.get("town") or "").upper()
    sql = f"SELECT company_number, name, post_town, status FROM {c} WHERE upper(name) LIKE '{_q(name)}%'"
    if town:
        sql += f" AND upper(coalesce(post_town, '')) = '{_q(town)}'"
    rows = con.execute(sql + " ORDER BY name LIMIT 10").fetchall()
    log.info("backtest %s resolved by name to %s", bt["name"], rows)
    return found + [r[0] for r in rows]


def verify() -> dict:
    con = _con()
    src = f"read_parquet('{_q(str(out_dir() / '*.parquet'))}')"
    res = {
        "rows": con.execute(f"SELECT count(*) FROM {src}").fetchone()[0],
        "distinct_companies": con.execute(f"SELECT count(DISTINCT company_number) FROM {src}").fetchone()[0],
        "by_kind": dict(con.execute(f"SELECT coalesce(kind, 'NULL'), count(*) FROM {src} GROUP BY 1 ORDER BY 2 DESC").fetchall()),
        "ceased_not_null": con.execute(f"SELECT count(*) FROM {src} WHERE ceased_on IS NOT NULL").fetchone()[0],
        "statement_values": dict(con.execute(
            f"SELECT statement, count(*) FROM {src} WHERE statement IS NOT NULL GROUP BY 1 ORDER BY 2 DESC").fetchall()),
        "company_number_lengths": dict(con.execute(
            f"SELECT length(company_number), count(*) FROM {src} GROUP BY 1 ORDER BY 1").fetchall()),
        "corporate_with_reg_number": con.execute(
            f"SELECT count(*) FROM {src} WHERE corporate_reg_number IS NOT NULL").fetchone()[0],
        "null_natures_of_control_non_statement": con.execute(
            f"SELECT count(*) FROM {src} WHERE natures_of_control IS NULL AND statement IS NULL").fetchone()[0],
    }
    typo = "no-individual-or-entity-with-signficant-control"
    res["register_typo_present"] = typo in res["statement_values"]
    res["backtests"] = {}
    for bt in cfg().get("backtests", []):
        numbers = resolve_backtest(con, bt)
        for cn in numbers:
            rows = con.execute(
                f"SELECT company_number, kind, name, natures_of_control, notified_on, ceased_on, statement, "
                f"corporate_reg_number, country_registered, legal_form, nationality, country_of_residence, "
                f"dob_year, dob_month, address_locality, address_postal_code "
                f"FROM {src} WHERE company_number = '{_q(cn)}' ORDER BY notified_on"
            ).fetchall()
            res["backtests"][f"{bt['name']}_{cn}"] = [list(map(str, r)) for r in rows]
    con.close()
    log.info("verify: %s", json.dumps({k: v for k, v in res.items() if k != "backtests"}, default=str))
    for k, v in res["backtests"].items():
        log.info("backtest %s: %d PSC rows", k, len(v))
        for r in v:
            log.info("  %s", r)
    return res


def main(argv: list[str]) -> None:
    mode = argv[0] if argv else "all"
    t0 = time.time()
    if mode in ("download", "all"):
        download_all()
    if mode in ("flatten", "all"):
        flatten_all(force="--force" in argv)
    if mode in ("verify", "all"):
        res = verify()
        out = REPO / "docs" / "logs" / "psc_verify.json"
        out.write_text(json.dumps(res, indent=2, default=str))
        log.info("wrote %s", out)
    log.info("psc %s done in %.0fs", mode, time.time() - t0)


if __name__ == "__main__":
    main(sys.argv[1:])
