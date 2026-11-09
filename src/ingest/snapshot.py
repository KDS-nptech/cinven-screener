"""Stage 1a: Companies House basic company snapshot.

Run from the repo root:
    python -m src.ingest.snapshot

Downloads config.build.snapshot_basic (BasicCompanyDataAsOneFile-YYYY-MM-DD.zip)
to data/raw/, extracts the single CSV, and writes:
    data/parquet/companies.parquet            every company on the register
    data/parquet/candidate_companies.parquet  Active companies whose last accounts were FULL, GROUP or MEDIUM
    data/raw/candidate_company_numbers.txt    one company_number per line, sorted (drives the accounts filter)
    docs/funnel_counts.json                   universe funnel counts

Downloading is resume-safe (HTTP Range) and skipped when the local file already
matches the server's Content-Length. The CSV is read by DuckDB straight from disk
so nothing larger than a DuckDB buffer ever sits in Python memory.
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import time
import zipfile

import duckdb
import requests

from src.common import REPO, cfg, get_logger, normalise_company_number, now_iso, parquet_path, path

log = get_logger("snapshot")

CH_DOWNLOAD_BASE = "https://download.companieshouse.gov.uk"


# ---------------------------------------------------------------- download
def remote_size(url: str, timeout: int = 60) -> int:
    r = requests.head(url, timeout=timeout, allow_redirects=True)
    r.raise_for_status()
    return int(r.headers["Content-Length"])


def download_file(url: str, dest: pathlib.Path, logger=None, retries: int = 6,
                  chunk_size: int = 1 << 20) -> pathlib.Path:
    """Stream url to dest, resuming a partial .part file. Skips when dest is complete.

    Shared by the basic snapshot and the PSC snapshot downloaders.
    """
    logger = logger or log
    dest = pathlib.Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    total = remote_size(url)
    if dest.exists():
        if dest.stat().st_size == total:
            logger.info("skip %s (complete, %d bytes)", dest.name, total)
            return dest
        logger.warning("%s exists with %d bytes, server says %d; re-downloading",
                       dest.name, dest.stat().st_size, total)
        dest.unlink()
    part = dest.with_name(dest.name + ".part")
    last_err: Exception | None = None
    for attempt in range(1, retries + 1):
        have = part.stat().st_size if part.exists() else 0
        if have > total:
            logger.warning("%s.part larger than remote; restarting", dest.name)
            part.unlink()
            have = 0
        if have == total:
            break
        headers = {"Range": f"bytes={have}-"} if have else {}
        t0 = time.time()
        try:
            with requests.get(url, headers=headers, stream=True, timeout=(30, 180)) as r:
                if r.status_code == 206:
                    mode = "ab"
                elif r.status_code == 200:
                    mode = "wb"
                    have = 0
                else:
                    r.raise_for_status()
                    raise RuntimeError(f"unexpected status {r.status_code} for {url}")
                logger.info("download %s from byte %d of %d (attempt %d)", dest.name, have, total, attempt)
                with open(part, mode) as f:
                    for chunk in r.iter_content(chunk_size=chunk_size):
                        if chunk:
                            f.write(chunk)
            got = part.stat().st_size
            if got == total:
                mb = (got - have) / 1e6
                dt_ = max(time.time() - t0, 1e-6)
                logger.info("done %s: %.0f MB in %.0fs (%.1f MB/s)", dest.name, mb, dt_, mb / dt_)
                break
            logger.warning("%s short after attempt %d: %d of %d", dest.name, attempt, got, total)
        except (requests.RequestException, OSError) as e:  # noqa: PERF203
            last_err = e
            logger.warning("%s attempt %d failed: %s", dest.name, attempt, e)
            time.sleep(min(60, 5 * attempt))
    if not part.exists() or part.stat().st_size != total:
        raise RuntimeError(f"failed to download {url}: {last_err}")
    os.replace(part, dest)
    return dest


# ---------------------------------------------------------------- snapshot build
# CSV header -> snake_case output column. Headers are stripped of whitespace first.
RAW_COLUMNS = {
    "CompanyName": "name",
    "CompanyNumber": "company_number",
    "CompanyStatus": "status",
    "CompanyCategory": "category",
    "IncorporationDate": "inc_date",
    "Accounts.AccountCategory": "account_category",
    "Accounts.LastMadeUpDate": "last_made_up_date",
    "Accounts.NextDueDate": "next_due_date",
    "Accounts.AccountRefDay": "account_ref_day",
    "Accounts.AccountRefMonth": "account_ref_month",
    "Mortgages.NumMortOutstanding": "charges_outstanding",
    "Mortgages.NumMortCharges": "charges_total",
    "Mortgages.NumMortSatisfied": "charges_satisfied",
    "RegAddress.PostTown": "post_town",
    "RegAddress.PostCode": "postcode",
    "RegAddress.County": "county",
    "SICCode.SicText_1": "sic_text1",
    "SICCode.SicText_2": "sic_text2",
    "SICCode.SicText_3": "sic_text3",
    "SICCode.SicText_4": "sic_text4",
    "PreviousName_1.CompanyName": "previous_name",
    "URI": "uri",
}


def snapshot_date() -> str:
    m = re.search(r"(\d{4}-\d{2}-\d{2})", cfg()["build"]["snapshot_basic"])
    if not m:
        raise ValueError("config.build.snapshot_basic must contain a YYYY-MM-DD date")
    return m.group(1)


def fetch_zip() -> pathlib.Path:
    name = cfg()["build"]["snapshot_basic"]
    return download_file(f"{CH_DOWNLOAD_BASE}/{name}", path("raw") / name)


def extract_csv(zip_path: pathlib.Path) -> pathlib.Path:
    """Extract the single CSV member next to the zip; skip when already extracted in full."""
    with zipfile.ZipFile(zip_path) as z:
        members = [m for m in z.infolist() if m.filename.lower().endswith(".csv")]
        if len(members) != 1:
            raise RuntimeError(f"expected one CSV in {zip_path.name}, found {[m.filename for m in members]}")
        m = members[0]
        out = zip_path.parent / pathlib.Path(m.filename).name
        if out.exists() and out.stat().st_size == m.file_size:
            log.info("skip extract %s (complete, %d bytes)", out.name, m.file_size)
            return out
        log.info("extract %s (%d bytes) from %s", m.filename, m.file_size, zip_path.name)
        tmp = out.with_name(out.name + ".tmp")
        with z.open(m) as src, open(tmp, "wb") as dst:
            while True:
                buf = src.read(8 << 20)
                if not buf:
                    break
                dst.write(buf)
        os.replace(tmp, out)
        return out


def csv_header(csv_path: pathlib.Path) -> list[str]:
    with open(csv_path, "r", encoding="utf-8", errors="replace") as f:
        line = f.readline().rstrip("\r\n")
    return [h.strip().strip('"') for h in line.split(",")]


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


def build_companies(csv_path: pathlib.Path) -> pathlib.Path:
    """Read the CSV with DuckDB and write data/parquet/companies.parquet."""
    header = csv_header(csv_path)  # stripped names; some raw headers carry a leading space
    missing = [c for c in RAW_COLUMNS if c not in header]
    if missing:
        raise RuntimeError(f"CSV is missing expected columns: {missing}")
    # Pass the stripped names to read_csv so SQL can address columns without the stray spaces.
    names_sql = "[" + ", ".join(f"'{_q(h)}'" for h in header) + "]"

    cand_cats = cfg()["target"]["candidate_account_categories"]
    cat_list = ", ".join(f"'{_q(c.upper())}'" for c in cand_cats)
    snap = snapshot_date()
    fetched = now_iso()

    def col(raw: str) -> str:
        return f'"{_q(raw)}"'

    def sic(i: int) -> str:
        # Leading 5-digit code in "62012 - Business and domestic software development"; NULL otherwise.
        return f"regexp_extract(trim({col(f'SICCode.SicText_{i}')}), '^(\\d{{5}})', 1)"

    def ddate(raw: str) -> str:
        return f"try_strptime(nullif(trim({col(raw)}), ''), '%d/%m/%Y')::DATE"

    def dint(raw: str) -> str:
        return f"try_cast(nullif(trim({col(raw)}), '') AS INTEGER)"

    def dtext(raw: str) -> str:
        return f"nullif(trim({col(raw)}), '')"

    sic_exprs = [f"nullif({sic(i)}, '')" for i in range(1, 5)]
    out = parquet_path("companies")
    tmp = out.with_suffix(".parquet.tmp")
    sql = f"""
    COPY (
      SELECT
        CASE WHEN regexp_matches(trim({col('CompanyNumber')}), '^[0-9]+$')
             THEN lpad(trim({col('CompanyNumber')}), 8, '0')
             ELSE upper(trim({col('CompanyNumber')})) END        AS company_number,
        {dtext('CompanyName')}                                   AS name,
        {dtext('CompanyStatus')}                                 AS status,
        {dtext('CompanyCategory')}                               AS category,
        {ddate('IncorporationDate')}                             AS inc_date,
        {dtext('Accounts.AccountCategory')}                      AS account_category,
        {ddate('Accounts.LastMadeUpDate')}                       AS last_made_up_date,
        {ddate('Accounts.NextDueDate')}                          AS next_due_date,
        {dint('Accounts.AccountRefDay')}                         AS account_ref_day,
        {dint('Accounts.AccountRefMonth')}                       AS account_ref_month,
        {dint('Mortgages.NumMortOutstanding')}                   AS charges_outstanding,
        {dint('Mortgages.NumMortCharges')}                       AS charges_total,
        {dint('Mortgages.NumMortSatisfied')}                     AS charges_satisfied,
        {dtext('RegAddress.PostTown')}                           AS post_town,
        {dtext('RegAddress.PostCode')}                           AS postcode,
        {dtext('RegAddress.County')}                             AS county,
        {sic_exprs[0]}                                           AS sic1,
        {sic_exprs[1]}                                           AS sic2,
        {sic_exprs[2]}                                           AS sic3,
        {sic_exprs[3]}                                           AS sic4,
        {dtext('SICCode.SicText_1')}                             AS sic_text1,
        {dtext('SICCode.SicText_2')}                             AS sic_text2,
        {dtext('SICCode.SicText_3')}                             AS sic_text3,
        {dtext('SICCode.SicText_4')}                             AS sic_text4,
        {dtext('PreviousName_1.CompanyName')}                    AS previous_name,
        {dtext('URI')}                                           AS uri,
        (upper(trim(coalesce({col('Accounts.AccountCategory')}, ''))) IN ({cat_list})) AS is_candidate,
        '{snap}'                                                 AS source_snapshot_date,
        '{fetched}'                                              AS fetched_at
      FROM read_csv('{_q(str(csv_path))}', header=true, names={names_sql}, all_varchar=true,
                    delim=',', quote='"', escape='"', parallel=true)
    ) TO '{_q(str(tmp))}' (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 200000)
    """
    con = _con()
    t0 = time.time()
    log.info("building companies.parquet from %s", csv_path.name)
    con.execute(sql)
    os.replace(tmp, out)
    n = con.execute(f"SELECT count(*) FROM read_parquet('{_q(str(out))}')").fetchone()[0]
    log.info("companies.parquet: %s rows in %.0fs", f"{n:,}", time.time() - t0)
    con.close()
    return out


def build_software(companies: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path]:
    """Write candidate_companies.parquet and candidate_company_numbers.txt (tmp then rename).

    Candidates are Active companies whose last accounts were in a large-company category
    (config.target.candidate_account_categories); the accounts bulk filter reads this list.
    Back-test companies (config.target.force_include) are always kept."""
    con = _con()
    status = cfg()["target"]["status"].strip().lower()
    force = cfg()["target"].get("force_include") or []
    force_sql = ", ".join(f"'{_q(n)}'" for n in force) or "''"
    out = parquet_path("candidate_companies")
    tmp = out.with_suffix(".parquet.tmp")
    con.execute(f"""
      COPY (
        SELECT * FROM read_parquet('{_q(str(companies))}')
        WHERE (lower(trim(status)) = '{_q(status)}' AND is_candidate) OR company_number IN ({force_sql})
        ORDER BY company_number
      ) TO '{_q(str(tmp))}' (FORMAT PARQUET, COMPRESSION ZSTD)
    """)
    os.replace(tmp, out)
    numbers = [r[0] for r in con.execute(
        f"SELECT company_number FROM read_parquet('{_q(str(out))}') ORDER BY company_number").fetchall()]
    numbers = sorted({normalise_company_number(n) for n in numbers if n})
    txt = path("raw") / "candidate_company_numbers.txt"
    txt_tmp = txt.with_name(txt.name + ".tmp")
    txt_tmp.write_text("\n".join(numbers) + "\n")
    os.replace(txt_tmp, txt)
    log.info("candidate_companies.parquet: %s rows; wrote %s", f"{len(numbers):,}", txt)
    con.close()
    return out, txt


def funnel_counts(companies: pathlib.Path, software: pathlib.Path) -> pathlib.Path:
    con = _con()
    t = cfg()["target"]
    status = t["status"].strip().lower()
    excl = ", ".join(f"'{_q(c.upper())}'" for c in t["exclude_account_categories"])
    cutoff = t["incorporated_on_or_before"]
    c = f"read_parquet('{_q(str(companies))}')"
    s = f"read_parquet('{_q(str(software))}')"
    counts = {
        "snapshot_date": snapshot_date(),
        "computed_at": now_iso(),
        "companies_total": con.execute(f"SELECT count(*) FROM {c}").fetchone()[0],
        "companies_active": con.execute(
            f"SELECT count(*) FROM {c} WHERE lower(trim(status)) = '{_q(status)}'").fetchone()[0],
        "active_candidates": con.execute(f"SELECT count(*) FROM {s}").fetchone()[0],
        "active_candidates_by_sic1_top50": dict(con.execute(
            f"SELECT coalesce(sic1, 'NULL'), count(*) FROM {s} GROUP BY 1 ORDER BY 2 DESC LIMIT 50").fetchall()),
        "active_candidates_excluding_micro_dormant_none": con.execute(
            f"SELECT count(*) FROM {s} WHERE upper(trim(coalesce(account_category, ''))) NOT IN ({excl})"
        ).fetchone()[0],
        "active_candidates_incorporated_on_or_before_cutoff": con.execute(
            f"SELECT count(*) FROM {s} WHERE inc_date <= DATE '{cutoff}'").fetchone()[0],
        "active_candidates_excluding_and_cutoff": con.execute(
            f"SELECT count(*) FROM {s} WHERE upper(trim(coalesce(account_category, ''))) NOT IN ({excl}) "
            f"AND inc_date <= DATE '{cutoff}'").fetchone()[0],
        "account_category_distribution_all_active": dict(con.execute(
            f"SELECT coalesce(account_category, 'NULL'), count(*) FROM {c} WHERE lower(trim(status)) = '{_q(status)}' GROUP BY 1 ORDER BY 2 DESC"
        ).fetchall()),
        "status_distribution_all": dict(con.execute(
            f"SELECT coalesce(status, 'NULL'), count(*) FROM {c} GROUP BY 1 ORDER BY 2 DESC").fetchall()),
        "config": {
            "candidate_account_categories": t["candidate_account_categories"],
            "exclude_account_categories": t["exclude_account_categories"],
            "incorporated_on_or_before": cutoff,
        },
    }
    con.close()
    out = REPO / "docs" / "funnel_counts.json"
    tmp = out.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(counts, indent=2))
    os.replace(tmp, out)
    log.info("funnel: %s", json.dumps({k: v for k, v in counts.items() if isinstance(v, int)}))
    return out


def main() -> None:
    t0 = time.time()
    zip_path = fetch_zip()
    csv_path = extract_csv(zip_path)
    header = csv_header(csv_path)
    log.info("CSV columns (%d): %s", len(header), header)
    companies = build_companies(csv_path)
    software, txt = build_software(companies)
    fc = funnel_counts(companies, software)
    log.info("snapshot stage done in %.0fs; wrote %s, %s, %s, %s", time.time() - t0, companies, software, txt, fc)


if __name__ == "__main__":
    main()
