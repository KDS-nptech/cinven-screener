"""Stage 1b: Companies House accounts bulk data to accounts_facts, accounts_meta, accounts_wide.

    python -m src.ingest.accounts --list                  # show the archive plan
    python -m src.ingest.accounts --zip <archive name>    # process one archive
    python -m src.ingest.accounts --all                   # process every configured archive (resumable)
    python -m src.ingest.accounts --build-wide            # pivot facts into accounts_wide.parquet

One archive at a time: download to data/raw/accounts/, keep only members whose company
number is in data/raw/candidate_company_numbers.txt, extract those to
data/raw/accounts/<zip-stem>/, delete the ZIP, parse with a Pool(2), write
data/parquet/accounts_facts/part-<zip-stem>.parquet and
data/parquet/accounts_meta/part-<zip-stem>.parquet, delete the extracted files, append a
line to docs/logs/accounts.log and record the archive in data/raw/accounts_progress.json
so a re-run resumes. Never extracts a ZIP whole.

Archive order: monthly files from config build.accounts_monthly, most recent first, then
the daily files after the last monthly month (listed from en_accountsdata.html).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shutil
import sys
import time
import zipfile
from multiprocessing import Pool
from pathlib import Path

import polars as pl
import requests

from src.common import REPO, cfg, get_logger, normalise_company_number, now_iso, path

log = get_logger("accounts")

BASE_URL = "https://download.companieshouse.gov.uk/"
INDEX_URL = BASE_URL + "en_accountsdata.html"
NUMBERS_FILE = REPO / "data" / "raw" / "candidate_company_numbers.txt"
PROGRESS_FILE = REPO / "data" / "raw" / "accounts_progress.json"
MEMBER_RE = re.compile(r"^(?:.*/)?Prod\d+_\d+_([A-Z0-9]{6,8})_(\d{8})(?:_[A-Za-z]+)?\.(html|xml|htm)$", re.I)
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August",
          "September", "October", "November", "December"]

# Local names kept in accounts_facts beyond the config concept lists.
EXTRA_CONCEPTS = {
    "Creditors", "CreditorsDueWithinOneYear", "CreditorsDueAfterOneYear",
    "TotalAssetsLessCurrentLiabilities", "CurrentAssets", "Debtors", "FixedAssets",
    "IntangibleAssets", "IntangibleAssetsNetBook", "OtherCreditors", "BankBorrowings",
    "BankBorrowingsOverdrafts", "Dividends", "DividendsPaid", "DividendsPaidOnShares",
    "StaffCosts", "StaffCostsEmployeeBenefitsExpense", "WagesSalaries", "CostSales",
    "OperatingProfitLoss", "AdministrativeExpenses", "IncomeTaxExpenseCredit",
    "TaxTaxCreditOnProfitOrLossOnOrdinaryActivities", "ProfitLossOnOrdinaryActivitiesBeforeTax",
    "NetCurrentAssetsLiabilities", "PropertyPlantEquipment", "InvestmentsFixedAssets",
    "TradeCreditorsTradePayables", "OtherDebtors", "TotalInventories",
    "AmountsOwedToGroupUndertakings", "AmountsOwedByGroupUndertakings",
    "PrepaymentsAccruedIncome", "PrepaymentsAccruedIncomeNotExpressedWithinCurrentAssetSubtotal",
    "ProvisionsForLiabilitiesBalanceSheetSubtotal", "FinanceLeaseLiabilitiesPresentValueTotal",
    "ParValueShare", "NumberSharesAllotted", "NumberSharesIssuedFullyPaid",
    "InterestPayableSimilarChargesFinanceCosts", "DepreciationExpensePropertyPlantEquipment",
    "AmortisationExpenseIntangibleAssets", "NetCashFlowsFromUsedInOperatingActivities",
    "ResearchDevelopmentExpenseRecognisedInProfitOrLoss",
    "DepreciationAmortisationExpense", "DepreciationImpairmentExpensePropertyPlantEquipment",
    "AmortisationImpairmentExpenseIntangibleAssets", "FinanceCosts", "OtherOperatingIncomeFormat1",
    "ProfitLossOnOrdinaryActivitiesBeforeTax", "DistributionCosts", "OtherOperatingExpensesFormat2",
    "NetDebtFunds", "Borrowings", "OtherBorrowings", "LoansFromGroupUndertakings",
    "ExceptionalItems", "GainLossOnDisposalsPropertyPlantEquipment", "InterestReceivableSimilarIncome",
    "NetCashFlowsFromUsedInInvestingActivities", "NetCashFlowsFromUsedInFinancingActivities",
    "PurchasePropertyPlantEquipment", "IncreaseDecreaseInCashCashEquivalents", "EBITDAStated",
}
CONCEPT_SUBSTRINGS = ("Employee", "Turnover", "Revenue", "Deferred", "Accrual", "SharePremium",
                      "ShareCapital", "Taxation", "Tax")

FACT_SCHEMA = {
    "company_number": pl.Utf8, "period_end": pl.Utf8, "concept": pl.Utf8, "value": pl.Float64,
    "value_literal": pl.Float64, "unit": pl.Utf8, "context_id": pl.Utf8, "period_type": pl.Utf8,
    "instant": pl.Utf8, "start": pl.Utf8, "end": pl.Utf8, "is_within_one_year": pl.Boolean,
    "is_after_one_year": pl.Boolean, "n_dims": pl.Int32, "dims_json": pl.Utf8, "scale": pl.Utf8,
    "sign": pl.Utf8, "decimals": pl.Utf8, "source_file": pl.Utf8, "source_zip": pl.Utf8,
    "fetched_at": pl.Utf8,
}
META_SCHEMA = {
    "company_number": pl.Utf8, "period_start": pl.Utf8, "period_end": pl.Utf8,
    "balance_sheet_date": pl.Utf8, "entity_name": pl.Utf8, "accounts_type": pl.Utf8,
    "accounting_standard": pl.Utf8, "audit_status": pl.Utf8, "is_dormant": pl.Boolean,
    "n_facts": pl.Int32, "n_numeric": pl.Int32, "has_turnover": pl.Boolean,
    "has_employees": pl.Boolean, "pl_exempt": pl.Boolean, "software": pl.Utf8,
    "parser": pl.Utf8, "kind": pl.Utf8, "source_file": pl.Utf8, "source_zip": pl.Utf8,
    "fetched_at": pl.Utf8,
}


# ---------------------------------------------------------------- archive plan
def keep_concepts() -> set[str]:
    s = set(EXTRA_CONCEPTS)
    for names in cfg()["accounts"]["concepts"].values():
        s.update(names)
    return s


def _keep(concept: str, keep: set[str]) -> bool:
    return concept in keep or any(sub in concept for sub in CONCEPT_SUBSTRINGS)


def monthly_archives() -> list[str]:
    """Config months, most recent first."""
    months = list(cfg()["build"]["accounts_monthly"])
    months.sort(key=_month_key, reverse=True)
    return [f"Accounts_Monthly_Data-{m}.zip" for m in months]


def _month_key(label: str) -> tuple[int, int]:
    m = re.match(r"([A-Za-z]+)(\d{4})", label)
    return int(m[2]), MONTHS.index(m[1]) + 1


def daily_from_date() -> dt.date:
    """First day not covered by a monthly archive, bounded below by config accounts_daily_from."""
    last = max(cfg()["build"]["accounts_monthly"], key=_month_key)
    y, mth = _month_key(last)
    first_after = (dt.date(y, mth, 28) + dt.timedelta(days=4)).replace(day=1)
    cfg_from = dt.date.fromisoformat(cfg()["build"]["accounts_daily_from"])
    return max(first_after, cfg_from)


def daily_archives(use_network: bool = True) -> list[str]:
    """Daily archives from daily_from_date() to as_of_date, taken from the download index so
    weekends and bank holidays that do not exist are skipped. Falls back to weekdays."""
    start = daily_from_date()
    end = dt.date.fromisoformat(cfg()["build"]["as_of_date"])
    names: list[str] = []
    if use_network:
        try:
            r = requests.get(INDEX_URL, timeout=60)
            r.raise_for_status()
            found = sorted(set(re.findall(r"Accounts_Bulk_Data-(\d{4}-\d{2}-\d{2})\.zip", r.text)))
            names = [f"Accounts_Bulk_Data-{d}.zip" for d in found
                     if start <= dt.date.fromisoformat(d) <= end]
        except Exception as e:  # pragma: no cover
            log.warning("could not list %s (%s); falling back to weekdays", INDEX_URL, e)
    if not names:
        d = start
        while d <= end:
            if d.weekday() < 5:
                names.append(f"Accounts_Bulk_Data-{d.isoformat()}.zip")
            d += dt.timedelta(days=1)
    return names


def archive_plan(use_network: bool = True) -> list[str]:
    return monthly_archives() + daily_archives(use_network)


def zip_sort_key(zip_name: str) -> str:
    """ISO date that orders archives by recency: month end for monthly, the date for daily."""
    m = re.search(r"Monthly_Data-([A-Za-z]+)(\d{4})", zip_name)
    if m:
        y, mth = int(m[2]), MONTHS.index(m[1]) + 1
        last = (dt.date(y, mth, 28) + dt.timedelta(days=4)).replace(day=1) - dt.timedelta(days=1)
        return last.isoformat()
    m = re.search(r"(\d{4}-\d{2}-\d{2})", zip_name)
    return m[1] if m else "0000-00-00"


# ---------------------------------------------------------------- inputs and progress
def load_numbers(file: Path = NUMBERS_FILE) -> set[str]:
    nums = set()
    for line in file.read_text().splitlines():
        n = normalise_company_number(line.split(",")[0])
        if n:
            nums.add(n)
    return nums


def load_progress() -> dict:
    if PROGRESS_FILE.exists():
        try:
            return json.loads(PROGRESS_FILE.read_text())
        except json.JSONDecodeError:
            pass
    return {"done": [], "runs": []}


def save_progress(p: dict) -> None:
    PROGRESS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = PROGRESS_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(p, indent=1))
    os.replace(tmp, PROGRESS_FILE)


# ---------------------------------------------------------------- download
def download(name: str, dest: Path, retries: int = 3) -> Path:
    url = BASE_URL + name
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(".zip.part")
    for attempt in range(1, retries + 1):
        try:
            have = part.stat().st_size if part.exists() else 0
            headers = {"Range": f"bytes={have}-"} if have else {}
            with requests.get(url, stream=True, timeout=120, headers=headers) as r:
                if r.status_code == 416:  # already complete
                    break
                r.raise_for_status()
                mode = "ab" if (have and r.status_code == 206) else "wb"
                if mode == "wb":
                    have = 0
                total = int(r.headers.get("content-length", 0)) + have
                t0 = time.time()
                with open(part, mode) as fh:
                    for chunk in r.iter_content(chunk_size=4 << 20):
                        fh.write(chunk)
                        have += len(chunk)
                size = part.stat().st_size
                if total and size < total:
                    raise IOError(f"short download {size} < {total}")
                log.info("downloaded %s %.1f MB in %.0fs", name, size / 1e6, time.time() - t0)
            break
        except Exception as e:
            log.warning("download attempt %d for %s failed: %s", attempt, name, e)
            if attempt == retries:
                raise
            time.sleep(10 * attempt)
    os.replace(part, dest)
    return dest


# ---------------------------------------------------------------- member filter and extract
def parse_member_name(name: str) -> tuple[str, str] | None:
    m = MEMBER_RE.match(name)
    if not m:
        return None
    num = normalise_company_number(m[1])
    d = m[2]
    return num, f"{d[:4]}-{d[4:6]}-{d[6:]}"


def select_members(zf: zipfile.ZipFile, numbers: set[str]) -> tuple[list[zipfile.ZipInfo], dict]:
    stats = {"members": 0, "html": 0, "xml": 0, "nested_zip": 0, "unparsed_name": 0, "matched": 0,
             "matched_xml": 0}
    picked = []
    for info in zf.infolist():
        if info.is_dir():
            continue
        stats["members"] += 1
        nm = info.filename
        low = nm.lower()
        if low.endswith(".zip"):
            stats["nested_zip"] += 1
            continue
        if low.endswith(".xml"):
            stats["xml"] += 1
        elif low.endswith((".html", ".htm")):
            stats["html"] += 1
        parsed = parse_member_name(nm)
        if not parsed:
            stats["unparsed_name"] += 1
            continue
        if parsed[0] in numbers:
            picked.append(info)
            stats["matched"] += 1
            if low.endswith(".xml"):
                stats["matched_xml"] += 1
    return picked, stats


def extract_members(zf: zipfile.ZipFile, members: list[zipfile.ZipInfo], out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for info in members:
        target = out_dir / Path(info.filename).name
        with zf.open(info) as src, open(target, "wb") as dst:
            shutil.copyfileobj(src, dst, 1 << 20)
        paths.append(target)
    return paths


# ---------------------------------------------------------------- parse workers
_KEEP: set[str] | None = None


def _worker_init(keep: set[str]) -> None:
    global _KEEP
    _KEEP = keep


def parse_one(args: tuple[str, str, str]) -> dict:
    """Parse one file. Returns {"facts": [...], "meta": {...}} or {"error": str, "meta": {...}}."""
    from src.ingest import ixbrl

    file_path, source_zip, fetched_at = args
    keep = _KEEP if _KEEP is not None else keep_concepts()
    fname = Path(file_path).name
    parsed_name = parse_member_name(fname)
    num_from_name, end_from_name = parsed_name if parsed_name else (None, None)
    try:
        parsed, parser = ixbrl.parse_with_fallback(file_path)
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}", "facts": [], "meta": {
            "company_number": num_from_name, "period_start": None, "period_end": end_from_name,
            "balance_sheet_date": None, "entity_name": None, "accounts_type": None,
            "accounting_standard": None, "audit_status": None, "is_dormant": None,
            "n_facts": 0, "n_numeric": 0, "has_turnover": False, "has_employees": False,
            "pl_exempt": None, "software": None, "parser": "failed", "kind": None,
            "source_file": fname, "source_zip": source_zip, "fetched_at": fetched_at}}
    company = parsed["company_number"] or num_from_name
    period_end = parsed["period_end"] or end_from_name
    rows = []
    has_turnover = has_employees = False
    turnover_names = set(cfg()["accounts"]["concepts"]["turnover"])
    employee_names = set(cfg()["accounts"]["concepts"]["employees"])
    seen = set()
    for f in parsed["facts"]:
        c = f["concept"]
        if not _keep(c, keep):
            continue
        key = (c, f["context_id"], f["value"])
        if key in seen:
            continue
        seen.add(key)
        if c in turnover_names:
            has_turnover = True
        if c in employee_names:
            has_employees = True
        rows.append({
            "company_number": company, "period_end": period_end, "concept": c,
            "value": float(f["value"]), "value_literal": float(f["value_literal"]),
            "unit": f["unit"], "context_id": f["context_id"], "period_type": f["period_type"],
            "instant": f["instant"], "start": f["start"], "end": f["end"],
            "is_within_one_year": bool(f["is_within_one_year"]),
            "is_after_one_year": bool(f["is_after_one_year"]),
            "n_dims": len(f["dims"]), "dims_json": json.dumps(f["dims"], sort_keys=True),
            "scale": f["scale"], "sign": f["sign"], "decimals": f["decimals"],
            "source_file": fname, "source_zip": source_zip, "fetched_at": fetched_at,
        })
    nn = parsed["nonnumeric"]
    pl_exempt = nn.get("EntityHasTakenExemptionUnderCompaniesActInNotPublishingItsOwnProfitLossAccountTruefalse")
    meta = {
        "company_number": company, "period_start": parsed["period_start"], "period_end": period_end,
        "balance_sheet_date": parsed["balance_sheet_date"], "entity_name": parsed["entity_name"],
        "accounts_type": ixbrl.accounts_type(parsed),
        "accounting_standard": ixbrl.accounting_standard(parsed),
        "audit_status": ixbrl.audit_status(parsed), "is_dormant": ixbrl.is_dormant(parsed),
        "n_facts": len(rows), "n_numeric": parsed["n_numeric"], "has_turnover": has_turnover,
        "has_employees": has_employees,
        "pl_exempt": (pl_exempt.strip().lower() == "true") if pl_exempt else None,
        "software": nn.get("NameProductionSoftware"), "parser": parser, "kind": parsed["kind"],
        "source_file": fname, "source_zip": source_zip, "fetched_at": fetched_at,
    }
    return {"facts": rows, "meta": meta}


def parse_files(paths: list[Path], source_zip: str, workers: int = 2) -> tuple[pl.DataFrame, pl.DataFrame, dict]:
    fetched_at = now_iso()
    keep = keep_concepts()
    jobs = [(str(p), source_zip, fetched_at) for p in paths]
    facts: list[dict] = []
    metas: list[dict] = []
    stats = {"parsed": 0, "failed": 0, "fallback": 0, "xml": 0, "errors": []}
    if not jobs:
        return _frame(facts, FACT_SCHEMA), _frame(metas, META_SCHEMA), stats
    with Pool(workers, initializer=_worker_init, initargs=(keep,)) as pool:
        for res in pool.imap_unordered(parse_one, jobs, chunksize=32):
            metas.append(res["meta"])
            facts.extend(res["facts"])
            if res.get("error"):
                stats["failed"] += 1
                if len(stats["errors"]) < 20:
                    stats["errors"].append((res["meta"]["source_file"], res["error"]))
            else:
                stats["parsed"] += 1
                if res["meta"]["parser"] == "ixbrlparse":
                    stats["fallback"] += 1
                if res["meta"]["kind"] == "xbrl":
                    stats["xml"] += 1
    fdf = _frame(facts, FACT_SCHEMA).unique(
        subset=["company_number", "period_end", "concept", "context_id", "value"], keep="first")
    mdf = _frame(metas, META_SCHEMA)
    return fdf, mdf, stats


def _frame(rows: list[dict], schema: dict) -> pl.DataFrame:
    if not rows:
        return pl.DataFrame(schema=schema)
    return pl.DataFrame(rows, schema=schema)


# ---------------------------------------------------------------- one archive
def process_zip(name: str, numbers: set[str], keep_zip: bool = False, local_zip: Path | None = None) -> dict:
    """Download, filter, extract, parse, write, clean up. Returns the stats dict."""
    t_start = time.time()
    stem = name[:-4] if name.lower().endswith(".zip") else name
    raw = path("raw") / "accounts"
    raw.mkdir(parents=True, exist_ok=True)
    zip_path = local_zip if local_zip else raw / name
    extract_dir = raw / stem
    stats: dict = {"zip": name, "started_at": now_iso()}
    try:
        if not zip_path.exists():
            t0 = time.time()
            download(name, zip_path)
            stats["download_s"] = round(time.time() - t0, 1)
        stats["zip_mb"] = round(zip_path.stat().st_size / 1e6, 1)
        t0 = time.time()
        with zipfile.ZipFile(zip_path) as zf:
            members, sel = select_members(zf, numbers)
            stats.update(sel)
            if extract_dir.exists():
                shutil.rmtree(extract_dir)
            paths = extract_members(zf, members, extract_dir)
        stats["extract_s"] = round(time.time() - t0, 1)
        log.info("%s: %d members, %d matched (%d xml, %d nested zips skipped), extracted in %.0fs",
                 name, sel["members"], sel["matched"], sel["matched_xml"], sel["nested_zip"], stats["extract_s"])
    finally:
        if zip_path.exists() and not keep_zip and not local_zip:
            zip_path.unlink()
    t0 = time.time()
    fdf, mdf, pstats = parse_files(paths, name)
    stats["parse_s"] = round(time.time() - t0, 1)
    stats.update({k: v for k, v in pstats.items() if k != "errors"})
    stats["errors_sample"] = pstats["errors"]
    stats["facts_rows"] = fdf.height
    stats["meta_rows"] = mdf.height
    facts_dir = path("parquet") / "accounts_facts"
    meta_dir = path("parquet") / "accounts_meta"
    facts_dir.mkdir(parents=True, exist_ok=True)
    meta_dir.mkdir(parents=True, exist_ok=True)
    _write_part(fdf, facts_dir / f"part-{stem}.parquet")
    _write_part(mdf, meta_dir / f"part-{stem}.parquet")
    if extract_dir.exists():
        shutil.rmtree(extract_dir)
    stats["total_s"] = round(time.time() - t_start, 1)
    stats["finished_at"] = now_iso()
    log.info("%s done: %d files parsed (%d failed, %d ixbrlparse fallback), %d fact rows, "
             "download %ss extract %ss parse %ss total %ss",
             name, stats["parsed"], stats["failed"], stats["fallback"], stats["facts_rows"],
             stats.get("download_s", "-"), stats["extract_s"], stats["parse_s"], stats["total_s"])
    prog = load_progress()
    if name not in prog["done"]:
        prog["done"].append(name)
    prog["runs"] = [r for r in prog.get("runs", []) if r.get("zip") != name] + [stats]
    prog["updated_at"] = now_iso()
    save_progress(prog)
    return stats


def _write_part(df: pl.DataFrame, target: Path) -> None:
    tmp = target.with_suffix(".parquet.tmp")
    df.write_parquet(str(tmp), compression="zstd")
    os.replace(tmp, target)


# ---------------------------------------------------------------- wide table
# Columns of accounts_wide: (column, kind, concept list source, equity-dimension member regex)
# kind: "instant" = balance sheet (instant at period end), "duration" = P&L / employees.
WIDE_COLUMNS: list[tuple[str, str, list[str] | str, str | None]] = [
    ("employees", "duration", "employees", None),
    ("turnover", "duration", "turnover", None),
    ("gross_profit", "duration", "gross_profit", None),
    ("profit", "duration", "profit", None),
    ("operating_profit", "duration", ["OperatingProfitLoss"], None),
    ("staff_costs", "duration", ["StaffCostsEmployeeBenefitsExpense", "StaffCosts", "WagesSalaries"], None),
    ("dividends", "duration", ["DividendsPaid", "Dividends", "DividendsPaidOnShares"], None),
    ("trade_debtors", "instant", "trade_debtors", None),
    ("accrued_deferred_income", "instant", "accrued_deferred_income", None),
    ("tax_social_security", "instant", "tax_social_security", None),
    ("corp_tax", "instant", "corp_tax", None),
    ("cash", "instant", "cash", None),
    ("net_assets", "instant", "net_assets+Equity", None),
    ("equity", "instant", "equity", None),
    ("share_capital", "instant", "share_capital", "^ShareCapital"),
    ("share_premium", "instant", "share_premium", "^SharePremium"),
    ("retained_earnings", "instant", "retained_earnings", "^RetainedEarningsAccumulatedLosses"),
    ("creditors_within_one_year", "within", "creditors_within_one_year", None),
    ("creditors_after_one_year", "after", ["Creditors", "CreditorsDueAfterOneYear"], None),
    ("current_assets", "instant", ["CurrentAssets"], None),
    ("fixed_assets", "instant", ["FixedAssets"], None),
    ("intangible_assets", "instant", ["IntangibleAssets", "IntangibleAssetsNetBook"], None),
    ("bank_borrowings", "instant", ["BankBorrowingsOverdrafts", "BankBorrowings"], None),
    # Added for the buyout screener: the EBITDA bridge and leverage lines large companies disclose.
    ("pbt", "duration", ["ProfitLossOnOrdinaryActivitiesBeforeTax"], None),
    ("cost_of_sales", "duration", ["CostSales"], None),
    ("depreciation", "duration", ["DepreciationExpensePropertyPlantEquipment", "DepreciationAmortisationExpense", "DepreciationImpairmentExpensePropertyPlantEquipment"], None),
    ("amortisation", "duration", ["AmortisationExpenseIntangibleAssets", "AmortisationImpairmentExpenseIntangibleAssets"], None),
    ("interest_payable", "duration", ["InterestPayableSimilarChargesFinanceCosts", "FinanceCosts"], None),
    ("tax_charge", "duration", ["TaxTaxCreditOnProfitOrLossOnOrdinaryActivities", "IncomeTaxExpenseCredit"], None),
    ("net_cash_from_ops", "duration", ["NetCashFlowsFromUsedInOperatingActivities"], None),
    ("total_assets_less_current_liabilities", "instant", ["TotalAssetsLessCurrentLiabilities"], None),
    ("provisions", "instant", ["ProvisionsForLiabilitiesBalanceSheetSubtotal"], None),
    ("amounts_owed_to_group", "instant", ["AmountsOwedToGroupUndertakings"], None),
    ("other_creditors", "instant", ["OtherCreditors"], None),
    ("ppe", "instant", ["PropertyPlantEquipment"], None),
    ("inventories", "instant", ["TotalInventories"], None),
    ("ebitda_stated", "duration", ["EBITDAStated"], None),
]


def _concepts_for(spec: list[str] | str) -> list[str]:
    """A config key, optionally followed by '+Extra' fallbacks, or a literal list."""
    if isinstance(spec, str):
        key, *extras = spec.split("+")
        return list(cfg()["accounts"]["concepts"][key]) + extras
    return list(spec)


def _sql_list(names: list[str]) -> str:
    return ", ".join("'" + n.replace("'", "''") + "'" for n in names)


def _priority_case(names: list[str], col: str = "concept") -> str:
    parts = " ".join(f"WHEN {col} = '{n}' THEN {i * 10}" for i, n in enumerate(names))
    return f"CASE {parts} ELSE 999 END"


def _col_expr(column: str, kind: str, spec, eq_regex: str | None) -> str:
    """arg_min(value, rank) FILTER (WHERE ...) for one wide column, against the `cf` CTE.

    `cf` carries: pe (effective period end), extra_dims (dimension count ignoring the
    GroupCompanyDataDimension), grp_rank (0 when the fact is the Consolidated member, else 1),
    eq_member (EquityClassesDimension member) and the within/after maturity flags.
    Consolidated figures win over company-only ones when a group files both, because the
    consolidated line describes the business being screened."""
    names = _concepts_for(spec)
    pri = _priority_case(names)
    if kind == "duration":
        cond = f"concept IN ({_sql_list(names)}) AND period_type = 'duration' AND extra_dims = 0"
        rank = f"({pri} + grp_rank * 2 + CASE WHEN start IS NOT DISTINCT FROM period_start THEN 0 ELSE 1 END)"
    elif kind == "within":
        cond = (f"concept IN ({_sql_list(names + ['CreditorsDueWithinOneYear'])}) AND period_type = 'instant' "
                f"AND ((is_within_one_year AND NOT is_after_one_year AND extra_dims = mat_dims AND mat_dims >= 1) "
                f"OR extra_dims = 0)")
        rank = f"({pri} + grp_rank * 2 + CASE WHEN is_within_one_year THEN 0 ELSE 1 END)"
    elif kind == "after":
        cond = (f"concept IN ({_sql_list(names)}) AND period_type = 'instant' AND "
                f"((is_after_one_year AND NOT is_within_one_year AND extra_dims = mat_dims AND mat_dims >= 1) "
                f"OR (concept = 'CreditorsDueAfterOneYear' AND extra_dims = 0))")
        rank = f"({pri} + grp_rank)"
    else:  # instant: no dimensions, or only maturity dimensions pointing at within one year
        base = (f"(concept IN ({_sql_list(names)}) AND extra_dims = mat_dims AND NOT is_after_one_year)")
        if eq_regex:
            base = (f"({base} OR (concept = 'Equity' AND extra_dims = 1 AND eq_member IS NOT NULL "
                    f"AND regexp_matches(eq_member, '{eq_regex}')))")
            rank = (f"((CASE WHEN concept = 'Equity' THEN 500 ELSE {pri} END) + grp_rank "
                    f"+ CASE WHEN extra_dims = 0 THEN 0 ELSE 1 END)")
        else:
            rank = f"({pri} + grp_rank + CASE WHEN extra_dims = 0 THEN 0 ELSE 1 END)"
        cond = f"{base} AND period_type = 'instant'"
    return f"arg_min(value, {rank}) FILTER (WHERE {cond}) AS {column}"


def build_wide(verbose: bool = True) -> dict:
    """Pivot accounts_facts into data/parquet/accounts_wide.parquet. Returns sanity numbers."""
    import duckdb

    facts_glob = str(path("parquet") / "accounts_facts" / "*.parquet")
    meta_glob = str(path("parquet") / "accounts_meta" / "*.parquet")
    if not list((path("parquet") / "accounts_facts").glob("*.parquet")):
        log.info("no accounts_facts parts yet; nothing to build")
        return {}
    con = duckdb.connect()
    con.execute("SET memory_limit='3GB'; SET threads=2;")
    con.execute(f"CREATE VIEW facts_raw AS SELECT * FROM read_parquet('{facts_glob}', union_by_name=true)")
    con.execute(f"CREATE VIEW meta_raw AS SELECT * FROM read_parquet('{meta_glob}', union_by_name=true)")
    # zip recency so the latest filing wins when a company filed twice for one period end
    zips = [r[0] for r in con.execute("SELECT DISTINCT source_zip FROM meta_raw").fetchall()]
    zip_rank = " ".join(f"WHEN source_zip = '{z}' THEN '{zip_sort_key(z)}'" for z in zips)
    con.execute(f"""
        CREATE TABLE meta AS
        SELECT *, CASE {zip_rank} ELSE '0000' END AS zip_date,
               row_number() OVER (PARTITION BY company_number, period_end
                                  ORDER BY (CASE {zip_rank} ELSE '0000' END) DESC, source_file DESC) AS rn
        FROM meta_raw
        WHERE company_number IS NOT NULL AND period_end IS NOT NULL AND parser <> 'failed'
    """)
    con.execute("CREATE TABLE chosen AS SELECT * FROM meta WHERE rn = 1")
    col_exprs = ",\n      ".join(_col_expr(*c) for c in WIDE_COLUMNS)
    con.execute(f"""
        CREATE TABLE cf AS
        SELECT f.company_number, f.period_end AS file_period_end, m.period_start AS file_period_start,
               COALESCE(f.instant, f."end") AS pe, f.concept, f.value, f.period_type, f.start, f."end",
               f.instant, f.n_dims, f.is_within_one_year, f.is_after_one_year, f.source_file,
               json_extract_string(f.dims_json, '$.GroupCompanyDataDimension') AS grp_member,
               greatest(f.n_dims - CASE WHEN json_extract_string(f.dims_json, '$.GroupCompanyDataDimension') IS NOT NULL THEN 1 ELSE 0 END, 0) AS extra_dims,
               CASE WHEN json_extract_string(f.dims_json, '$.GroupCompanyDataDimension') = 'Consolidated' THEN 0 ELSE 1 END AS grp_rank,
               json_extract_string(f.dims_json, '$.EquityClassesDimension') AS eq_member,
               len(list_filter(json_keys(f.dims_json), lambda k: k IN ('MaturitiesOrExpirationPeriodsDimension',
                   'FinancialInstrumentCurrentNon-currentDimension'))) AS mat_dims,
               CASE WHEN COALESCE(f.instant, f."end") = f.period_end THEN m.period_start
                    WHEN f.period_type = 'duration' THEN f.start END AS period_start
        FROM facts_raw f
        JOIN chosen m ON m.source_file = f.source_file AND m.source_zip = f.source_zip
                     AND m.company_number = f.company_number
        WHERE COALESCE(f.instant, f."end") IS NOT NULL
    """)
    # current-period rows
    con.execute(f"""
        CREATE TABLE wide_main AS
        SELECT company_number, pe AS period_end, FALSE AS comparative, any_value(source_file) AS source_file,
          bool_or(grp_member = 'Consolidated') AS consolidated,
          {col_exprs}
        FROM cf WHERE pe = file_period_end
        GROUP BY company_number, pe
    """)
    # comparative rows: prior-period facts, only when no filing covers that period end
    con.execute(f"""
        CREATE TABLE wide_comp AS
        SELECT company_number, pe AS period_end, TRUE AS comparative, any_value(source_file) AS source_file,
          bool_or(grp_member = 'Consolidated') AS consolidated,
          {col_exprs}
        FROM cf c WHERE pe <> file_period_end
          AND NOT EXISTS (SELECT 1 FROM chosen m WHERE m.company_number = c.company_number AND m.period_end = c.pe)
        GROUP BY company_number, pe
    """)
    con.execute("""
        CREATE TABLE wide AS
        WITH u AS (SELECT * FROM wide_main UNION ALL SELECT * FROM wide_comp),
        ps AS (
          SELECT company_number, pe AS period_end, arg_max(period_start, period_type = 'duration') AS period_start
          FROM cf WHERE period_start IS NOT NULL GROUP BY company_number, pe)
        SELECT u.*, m.accounts_type, m.accounting_standard, m.audit_status, m.is_dormant, m.pl_exempt,
               m.entity_name,
               COALESCE(m.period_start, ps.period_start) AS period_start,
               date_diff('day', TRY_CAST(COALESCE(m.period_start, ps.period_start) AS DATE), TRY_CAST(u.period_end AS DATE)) + 1 AS period_days,
               u.period_end = max(u.period_end) OVER (PARTITION BY u.company_number) AS latest_for_company,
               u.period_end = max(CASE WHEN NOT u.comparative THEN u.period_end END) OVER (PARTITION BY u.company_number) AS latest_filing_for_company
        FROM u
        LEFT JOIN chosen m ON m.company_number = u.company_number AND m.period_end = u.period_end AND NOT u.comparative
        LEFT JOIN ps ON ps.company_number = u.company_number AND ps.period_end = u.period_end
    """)
    con.execute(f"ALTER TABLE wide ADD COLUMN computed_at VARCHAR DEFAULT '{now_iso()}'")
    cols = [c[0] for c in WIDE_COLUMNS]
    order = ["company_number", "period_end", "period_start", "period_days", "comparative", "consolidated", *cols,
             "accounts_type", "accounting_standard", "audit_status", "is_dormant", "pl_exempt",
             "entity_name", "source_file", "latest_for_company", "latest_filing_for_company", "computed_at"]
    out = path("parquet") / "accounts_wide.parquet"
    tmp = out.with_suffix(".parquet.tmp")
    con.execute(f"COPY (SELECT {', '.join(order)} FROM wide ORDER BY company_number, period_end) TO '{tmp}' (FORMAT PARQUET, COMPRESSION ZSTD)")
    os.replace(tmp, out)

    emp_min = cfg()["target"]["universe_employees_min"]
    emp_max = cfg()["target"]["universe_employees_max"]
    s = {}
    s["rows"] = con.execute("SELECT count(*) FROM wide").fetchone()[0]
    s["rows_current"] = con.execute("SELECT count(*) FROM wide WHERE NOT comparative").fetchone()[0]
    s["rows_comparative"] = s["rows"] - s["rows_current"]
    s["companies"] = con.execute("SELECT count(DISTINCT company_number) FROM wide").fetchone()[0]
    s["meta_files"] = con.execute("SELECT count(*) FROM meta_raw").fetchone()[0]
    s["facts_rows"] = con.execute("SELECT count(*) FROM facts_raw").fetchone()[0]
    s["share_employees"] = con.execute("SELECT round(avg(CASE WHEN employees IS NOT NULL THEN 1 ELSE 0 END), 3) FROM wide WHERE NOT comparative").fetchone()[0]
    s["share_turnover"] = con.execute("SELECT round(avg(CASE WHEN turnover IS NOT NULL THEN 1 ELSE 0 END), 3) FROM wide WHERE NOT comparative").fetchone()[0]
    s["employees_p10_p50_p90"] = con.execute("SELECT quantile_cont(employees, [0.1, 0.5, 0.9]) FROM wide WHERE NOT comparative AND employees IS NOT NULL").fetchone()[0]
    s["turnover_p10_p50_p90"] = con.execute("SELECT quantile_cont(turnover, [0.1, 0.5, 0.9]) FROM wide WHERE NOT comparative AND turnover IS NOT NULL").fetchone()[0]
    s["rows_employees_in_band"] = con.execute(f"SELECT count(*) FROM wide WHERE NOT comparative AND employees BETWEEN {emp_min} AND {emp_max}").fetchone()[0]
    s["rows_employees_in_band_with_turnover"] = con.execute(f"SELECT count(*) FROM wide WHERE NOT comparative AND employees BETWEEN {emp_min} AND {emp_max} AND turnover IS NOT NULL").fetchone()[0]
    s["companies_employees_in_band_latest"] = con.execute(f"SELECT count(*) FROM wide WHERE latest_filing_for_company AND NOT comparative AND employees BETWEEN {emp_min} AND {emp_max}").fetchone()[0]
    s["share_net_assets"] = con.execute("SELECT round(avg(CASE WHEN net_assets IS NOT NULL THEN 1 ELSE 0 END), 3) FROM wide WHERE NOT comparative").fetchone()[0]
    s["share_creditors_within"] = con.execute("SELECT round(avg(CASE WHEN creditors_within_one_year IS NOT NULL THEN 1 ELSE 0 END), 3) FROM wide WHERE NOT comparative").fetchone()[0]
    s["share_share_capital"] = con.execute("SELECT round(avg(CASE WHEN share_capital IS NOT NULL THEN 1 ELSE 0 END), 3) FROM wide WHERE NOT comparative").fetchone()[0]
    s["fractional_employees_rows"] = con.execute("SELECT count(*) FROM wide WHERE employees IS NOT NULL AND employees <> round(employees)").fetchone()[0]
    s["backtests"] = {}
    for label, num in _backtest_numbers(con).items():
        rows = con.execute(f"""SELECT period_end, period_start, period_days, comparative, consolidated, employees, turnover,
                                      gross_profit, profit, net_assets, cash, creditors_within_one_year, share_capital,
                                      share_premium, retained_earnings, accounts_type, accounting_standard, latest_for_company
                               FROM wide WHERE company_number = '{num}' ORDER BY period_end""").fetchall()
        s["backtests"][f"{label} ({num})"] = [list(r) for r in rows]
    con.close()
    if verbose:
        for k, v in s.items():
            if k == "backtests":
                for label, rows in v.items():
                    print(f"backtest {label}: {len(rows)} rows")
                    for r in rows:
                        print(f"    {r}")
            else:
                print(f"{k}: {v}")
    _append_sanity(s, out)
    return s


def _backtest_numbers(con) -> dict[str, str]:
    """Backtest companies from config plus any snapshot match on name, because the config
    number for PortSwigger (06452255) is not the registered PORTSWIGGER LTD (06719143)."""
    out: dict[str, str] = {}
    for b in cfg().get("backtests", []):
        if b.get("company_number"):
            out[f"{b['name']} config"] = normalise_company_number(b["company_number"])
    snap = path("parquet") / "software_companies.parquet"
    if snap.exists():
        for b in cfg().get("backtests", []):
            try:
                rows = con.execute(f"""SELECT company_number FROM read_parquet('{snap}')
                                       WHERE upper(name) LIKE '{b['name'].upper().replace("'", "''")}%' LIMIT 3""").fetchall()
            except Exception:
                rows = []
            for (num,) in rows:
                out[f"{b['name']} snapshot"] = num
    return out


def _append_sanity(s: dict, out: Path) -> None:
    doc = REPO / "docs" / "accounts_concepts.md"
    lines = [f"\n### Build at {now_iso()} ({out.name})\n"]
    for k, v in s.items():
        if k == "backtests":
            continue
        lines.append(f"- {k}: {v}")
    lines.append("- Backtest rows [period_end, period_start, days, comparative, consolidated, employees, turnover, "
                 "gross_profit, profit, net_assets, cash, creditors_within, share_capital, share_premium, "
                 "retained_earnings, type, standard, latest]:")
    for label, rows in s.get("backtests", {}).items():
        lines.append(f"    - {label}: {'not present in the parsed data' if not rows else ''}")
        for r in rows:
            lines.append(f"        - {r}")
    with open(doc, "a") as fh:
        fh.write("\n".join(lines) + "\n")


# ---------------------------------------------------------------- CLI
def wait_for_numbers(max_wait_s: int, poll_s: int = 60) -> bool:
    waited = 0
    while not NUMBERS_FILE.exists() or NUMBERS_FILE.stat().st_size == 0:
        if waited >= max_wait_s:
            return False
        log.info("waiting for %s (%ds so far)", NUMBERS_FILE, waited)
        time.sleep(poll_s)
        waited += poll_s
    return True


def run_all(plan: list[str], numbers: set[str], force: bool = False) -> None:
    prog = load_progress()
    for name in plan:
        if name in prog["done"] and not force:
            log.info("skip %s (done)", name)
            continue
        try:
            process_zip(name, numbers)
        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code == 404:
                log.warning("%s not on the server (404); skipping", name)
                prog = load_progress()
                prog.setdefault("missing", []).append(name)
                save_progress(prog)
                continue
            raise


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--zip", help="process one archive by name (e.g. Accounts_Monthly_Data-September2026.zip)")
    ap.add_argument("--local-zip", help="path to an already downloaded ZIP to process instead of downloading")
    ap.add_argument("--all", action="store_true", help="process every configured archive, resuming from progress")
    ap.add_argument("--build-wide", action="store_true", help="rebuild accounts_wide.parquet from facts parts")
    ap.add_argument("--list", action="store_true", help="print the archive plan")
    ap.add_argument("--force", action="store_true", help="reprocess archives already marked done")
    ap.add_argument("--numbers", help="override the company number file")
    ap.add_argument("--wait-minutes", type=int, default=0, help="poll for the numbers file this long before starting")
    ap.add_argument("--keep-zip", action="store_true", help="do not delete the ZIP after processing")
    a = ap.parse_args(argv)

    if a.list:
        for n in archive_plan():
            print(n)
        return 0
    if a.build_wide and not (a.zip or a.all):
        build_wide()
        return 0
    if not (a.zip or a.all or a.local_zip):
        ap.print_help()
        return 1
    numbers_file = Path(a.numbers) if a.numbers else NUMBERS_FILE
    if numbers_file == NUMBERS_FILE and a.wait_minutes:
        if not wait_for_numbers(a.wait_minutes * 60):
            log.error("numbers file %s never appeared; exiting 0", NUMBERS_FILE)
            return 0
    if not numbers_file.exists():
        log.error("numbers file %s missing; nothing to do", numbers_file)
        return 0
    numbers = load_numbers(numbers_file)
    log.info("%d company numbers loaded from %s", len(numbers), numbers_file)
    if a.local_zip:
        p = Path(a.local_zip)
        process_zip(a.zip or p.name, numbers, keep_zip=True, local_zip=p)
    elif a.zip:
        process_zip(a.zip, numbers, keep_zip=a.keep_zip)
    elif a.all:
        run_all(archive_plan(), numbers, force=a.force)
    if a.build_wide:
        build_wide()
    return 0


if __name__ == "__main__":
    sys.exit(main())
