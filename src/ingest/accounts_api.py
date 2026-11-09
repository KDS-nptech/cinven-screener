"""Stage 1c: accounts gap-fill through the Companies House document API.

The bulk accounts product only carries iXBRL filed in the last twelve months. Two groups of
software companies are missing from it: PDF filers (most audited FULL and GROUP accounts,
PortSwigger among them) and companies whose last filing fell before the window (Person
Centred Software filed in September 2025). For each candidate this script reads the latest
AA filing from the filing history, fetches the document (iXBRL when available, else PDF) and
turns it into accounts_facts / accounts_meta parts in the bulk schema, so `accounts --build-wide`
picks them up unchanged.

Candidates: universe companies (Stage 3 output) that are `provisional`, meaning a FULL or GROUP
filer with no iXBRL in the bulk product. Priority order: ownership routes a buyout fund can act
on first (founder_family, sponsor, sponsor_offshore, plc_dispersed, employee_owned), GROUP
accounts before FULL; then uk_group and foreign_parent; uncertain last.

PDF extraction is regex over the text layer (pdftotext): average number of employees, turnover,
operating profit, profit before tax and a stated EBITDA. Rows sourced that way carry
parser = 'pdf_regex' and accounts_type = 'PDF-GROUP' or 'PDF-FULL' so the UI can say so.

Run: python -m src.ingest.accounts_api [--categories FULL,GROUP,MEDIUM] [--limit N] [--numbers a,b]
Every API response is cached; the run is resumable.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys
import time
from pathlib import Path

import polars as pl
import requests

from src.common import REPO, cfg, env_key, get_logger, now_iso, parquet_exists, path, read_parquet
from src.ingest.accounts import FACT_SCHEMA, META_SCHEMA, _frame, _write_part, parse_one
from src.enrich.ch_api import CHClient

log = get_logger("accounts_api")
PRIORITY = ["FULL", "GROUP", "MEDIUM", "SMALL", "AUDIT EXEMPTION SUBSIDIARY", "AUDITED ABRIDGED", "UNAUDITED ABRIDGED", "TOTAL EXEMPTION FULL"]
DOC_DIR = path("raw") / "accounts_api"
PROGRESS = path("raw") / (f"accounts_api_progress_{os.environ['API_SHARD'].replace('/', '_')}.json" if os.environ.get("API_SHARD") else "accounts_api_progress.json")
SOURCE_ZIP = f"api-{cfg()['build']['as_of_date']}"

def _num(s: str) -> float | None:
    try:
        return float(s.replace(",", ""))
    except ValueError:
        return None


YEAR_RE = re.compile(r"^(19|20)\d\d$")
SCALE_PATTERNS = [(r"£\s*'?000|£000|in\s+thousands|\(£'000\)|£'000|£ ?'000", 1000), (r"£\s*m\b|£\s*million|in\s+millions", 1_000_000)]
EMP_PHRASES = [r"average\s+(?:monthly\s+)?number\s+of\s+(?:persons\s+)?(?:employees|people|staff|persons\s+employed)",
               r"average\s+number\s+of\s+employees", r"persons\s+employed\s+by\s+the\s+(?:company|group)",
               r"average\s+(?:monthly\s+)?(?:number\s+of\s+)?(?:employees|staff)\s+(?:during|employed)",
               r"\bnumber\s+of\s+employees\b", r"employees\s+during\s+the\s+(?:year|period)"]
TURNOVER_LINE = re.compile(r"^\s*(?:turnover|revenue|total\s+revenue|group\s+turnover|group\s+revenue)\b[^0-9\n]{0,40}?(?:\d{1,2}\s+)?[(£]?\s*(\d{1,3}(?:,\d{3})+|\d{4,})\)?", re.I | re.M)


def _ints_after(low: str, start: int, span: int = 400) -> list[int]:
    """Integers in the window after a phrase, skipping years and note references."""
    out = []
    window = low[start:start + span]
    for m in re.finditer(r"(?<![\d,.])(\d{1,3}(?:,\d{3})*|\d+)(?![\d,.%])", window):
        tok = m.group(1).replace(",", "")
        if YEAR_RE.match(tok):
            continue
        if re.search(r"\bnotes?\s*$", window[max(0, m.start() - 8):m.start()]):
            continue  # "see note 8", not a headcount
        v = int(tok)
        if 1 <= v <= 20000:
            out.append(v)
    return out


def extract_from_pdf_text(text: str) -> dict:
    low = text.lower()
    out = {"employees": None, "turnover": None, "scale": 1, "employees_match": None, "turnover_match": None}
    for pat, mult in SCALE_PATTERNS:
        if re.search(pat, low):
            out["scale"] = mult
            break
    # Employees: the first phrase whose following window holds a plausible integer. Prefer a
    # 'total' line when the note breaks staff down by category.
    for pat in EMP_PHRASES:
        for m in re.finditer(pat, low):
            window = low[m.end():m.end() + 700]
            if re.match(r"\s*(and related costs\s+)?(can be|is|are) (found|shown|given|set out|disclosed) in note", window):
                continue
            # cut the window at the next numbered note heading ("8. directors' remuneration")
            nxt = re.search(r"\n\s*\d{1,2}\.\s+[a-z]", window)
            if nxt and nxt.start() > 40:
                window = window[:nxt.start()]
            # a breakdown table ends with a numbers-only total line: take its first figure
            num_lines = [ln for ln in window.split("\n") if re.fullmatch(r"\s*\d{1,3}(?:,\d{3})?(?:\s+\d{1,3}(?:,\d{3})?){1,3}\s*", ln)
                         and not all(YEAR_RE.match(x.replace(",", "")) for x in ln.split())]
            label_lines = [ln for ln in window.split("\n") if re.search(r"[a-z]{3,}.*\s\d{1,3}(?:,\d{3})?\s*(\s\d{1,3}(?:,\d{3})?)*\s*$", ln) and "no." not in ln]
            if num_lines and label_lines:
                first = num_lines[-1].split()[0].replace(",", "")
                if not YEAR_RE.match(first) and 1 <= int(first) <= 20000:
                    out["employees"], out["employees_match"] = int(first), low[m.start():m.end() + 80]
                    break
            tot = re.search(r"\btotal\b[^0-9\n]{0,30}(\d{1,3}(?:,\d{3})*|\d+)", window)
            if tot and not YEAR_RE.match(tot.group(1).replace(",", "")) and 1 <= int(tot.group(1).replace(",", "")) <= 20000:
                out["employees"], out["employees_match"] = int(tot.group(1).replace(",", "")), low[m.start():m.end() + 80]
                break
            ints = _ints_after(low, m.end())
            if ints:
                out["employees"], out["employees_match"] = ints[0], low[m.start():m.end() + 80]
                break
        if out["employees"] is not None:
            break
    # Turnover: first 'Turnover'/'Revenue' line with a figure, preferring the P&L section.
    pl_idx = max(low.find("profit and loss account"), low.find("income statement"), low.find("statement of comprehensive income"))
    regions = [text[pl_idx:], text] if pl_idx > 0 else [text]
    for region in regions:
        for m in TURNOVER_LINE.finditer(region):
            tok = m.group(1).replace(",", "")
            if YEAR_RE.match(tok):
                continue
            v = _num(m.group(1))
            if v is not None and v * out["scale"] >= 20000:
                out["turnover"], out["turnover_match"] = v * out["scale"], m.group(0)[:160]
                break
        if out["turnover"] is not None:
            break
    _plausibility(out)
    return out


def _plausibility(out: dict) -> None:
    """A document-wide £'000 marker can scale a figure that was already in pounds. Revenue per head
    above £2.5M, or turnover above £5bn with no headcount, is treated as a mis-scale and divided back."""
    t, e = out.get("turnover"), out.get("employees")
    if t is None:
        return
    if (e and e > 0 and t / e > 2_500_000) or (not e and t > 5_000_000_000):
        if out.get("scale", 1) == 1000:
            out["turnover"] = t / 1000
            out["scale_corrected"] = True
    if e and e > 0 and out["turnover"] / e < 2_000 and out.get("scale", 1) == 1:
        # the opposite case: a £'000 table that the scale regex missed
        out["turnover"] = out["turnover"] * 1000
        out["scale_corrected"] = True


PL_LABELS = {
    "operating_profit": r"(?:group\s+)?operating\s+(?:profit|loss|profit\s*/\s*\(loss\)|\(loss\)\s*/\s*profit|profit\s*\(loss\))",
    "pbt": r"(?:group\s+)?(?:profit|loss)\s*(?:/\s*\(loss\)\s*)?(?:on\s+ordinary\s+activities\s+)?before\s+(?:income\s+)?tax(?:ation)?",
    "ebitda": r"(?:adjusted\s+|underlying\s+)?ebitda",
    "revenue": r"(?:group\s+)?(?:turnover|revenue|total\s+revenue)",
}
NUM_TOKEN = r"\(?\s*(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)\s*\)?"


def _line_figure(text_low: str, label_rx: str, scale: int, allow_decimal: bool) -> tuple[float | None, str | None]:
    """First money figure on a line that starts with the label (P&L table layout). A leading bare
    integer up to 60 is a note reference and is skipped; parentheses mean negative. Returns the figure
    in pounds and the matched line."""
    rx = re.compile(r"^[ \t]*" + label_rx + r"\b(?![a-z])([^\n]*)$", re.I | re.M)
    for m in rx.finditer(text_low):
        rest = m.group(1)
        if re.match(r"\s*(and|of|is|was|for|from|in|to|per|margin|growth|increased|decreased|rose|fell)\b", rest):
            continue
        toks = list(re.finditer(r"\(?\s*(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)\s*\)?%?", rest))
        toks = [t for t in toks if "%" not in t.group(0)]
        if not toks:
            continue
        # drop a leading note reference
        first = toks[0].group(1)
        if len(toks) > 1 and "," not in first and "." not in first and first.isdigit() and int(first) <= 60:
            toks = toks[1:]
        for t in toks:
            tok = t.group(1).replace(",", "")
            if YEAR_RE.match(tok) or (not allow_decimal and "." in tok):
                continue
            try:
                v = float(tok)
            except ValueError:
                continue
            if "(" in t.group(0):
                v = -v
            if abs(v) * scale < 1000:
                continue
            return v * scale, (m.group(0).strip())[:160]
    return None, None


def extract_pl_from_text(text: str, scale: int) -> dict:
    """Operating profit, PBT, stated EBITDA and revenue from the text layer, preferring the P&L region."""
    low = text.lower()
    pl_idx = max(low.find("profit and loss account"), low.find("income statement"), low.find("statement of comprehensive income"),
                 low.find("consolidated statement of profit"))
    regions = [low[pl_idx:], low] if pl_idx > 0 else [low]
    out = {}
    allow_dec = scale >= 1_000_000
    for key, rx in PL_LABELS.items():
        for region in regions:
            v, line = _line_figure(region, rx, scale, allow_dec)
            if v is not None:
                out[key], out[key + "_match"] = v, line
                break
    # a stated EBITDA in the strategic report ("EBITDA of £12.3m", "EBITDA increased to £45.2 million")
    if "ebitda" not in out:
        m = re.search(r"ebitda[^\n£]{0,80}£\s*(\d{1,3}(?:,\d{3})*(?:\.\d+)?)\s*(m|million|k|bn|billion)?", low)
        if m:
            v = float(m.group(1).replace(",", ""))
            unit = (m.group(2) or "").lower()
            mult = {"m": 1e6, "million": 1e6, "k": 1e3, "bn": 1e9, "billion": 1e9}.get(unit, 1)
            if mult == 1 and v < 10000:
                mult = scale
            out["ebitda"], out["ebitda_match"] = v * mult, m.group(0)[:160]
    return out


def has_text_layer(text: str) -> bool:
    return len(re.findall(r"[a-zA-Z]{3,}", text or "")) > 150


def ocr_pdf(pdf_path: Path, max_pages: int = 90, dpi: int = 110, stop_when_found: bool = True) -> str:
    """Render pages with pdftoppm and OCR them with tesseract. Pages are visited in the order most
    likely to carry the figures (front matter with the KPIs and P&L first, then the notes in the
    middle of the document, then the rest) and the loop stops once employees and turnover are found."""
    import subprocess
    import tempfile

    texts: dict[int, str] = {}
    with tempfile.TemporaryDirectory() as d:
        subprocess.run(["pdftoppm", "-r", str(dpi), "-gray", "-f", "1", "-l", str(max_pages), str(pdf_path), f"{d}/pg"],
                       check=True, capture_output=True)
        pages = sorted(Path(d).glob("pg-*.pgm")) + sorted(Path(d).glob("pg-*.ppm"))
        n = len(pages)
        front = list(range(min(8, n)))
        mid = [i for i in range(int(n * 0.35), int(n * 0.85)) if i not in front]
        rest = [i for i in range(n) if i not in front and i not in mid]
        for i in front + mid + rest:
            r = subprocess.run(["tesseract", str(pages[i]), "-", "--psm", "6", "-l", "eng"], capture_output=True, text=True)
            texts[i] = r.stdout
            if stop_when_found and len(texts) >= 3:
                ex = extract_from_pdf_text("\n".join(texts[k] for k in sorted(texts)))
                if ex["employees"] is not None and ex["turnover"] is not None:
                    break
    return "\n".join(texts[k] for k in sorted(texts))


ROUTE_PRIORITY = {"founder_family": 0, "sponsor": 0, "sponsor_offshore": 0, "plc_dispersed": 0, "employee_owned": 0,
                  "uk_group": 1, "foreign_parent": 1, "uncertain": 2, "public_sector": 3}


def candidates(categories: list[str], routes: list[str] | None = None) -> pl.DataFrame:
    """Provisional universe companies (no iXBRL) in priority order: actionable routes first, GROUP before FULL."""
    u = read_parquet("universe")
    have = set(read_parquet("accounts_wide")["company_number"].unique().to_list()) if parquet_exists("accounts_wide") else set()
    df = u.filter(pl.col("passes_all") & pl.col("account_category").is_in(categories) & ~pl.col("company_number").is_in(list(have)))
    if routes:
        df = df.filter(pl.col("route").is_in(routes))
    if "is_group_head" in df.columns:
        df = df.filter(pl.col("is_group_head").fill_null(True))   # subsidiaries wait for their group head
    cat_order = {c: i for i, c in enumerate(["GROUP", "FULL", "MEDIUM"])}
    return (df.with_columns(pl.col("route").replace_strict(ROUTE_PRIORITY, default=9).alias("rprio"),
                            pl.col("account_category").replace_strict(cat_order, default=9).alias("cprio"))
              .sort(["rprio", "cprio", "company_number"]).drop(["rprio", "cprio"]))


def latest_accounts_filing(client: CHClient, number: str) -> dict | None:
    # Same request shape as Stage 4a's first page, so the two stages share one cached response.
    fh = client.get(f"/company/{number}/filing-history", {"category": "accounts", "items_per_page": 5})
    if not fh:
        return None
    items = [i for i in fh.get("items", []) if i.get("type") == "AA"]
    items.sort(key=lambda i: i.get("date") or "", reverse=True)
    return items[0] if items else None


def fetch_document(client: CHClient, meta_url: str, number: str) -> tuple[str | None, Path | None]:
    """Return (kind, local_path): kind is 'xhtml' or 'pdf'. One call: ask the content endpoint for iXBRL
    first (406 when the filing has none), then PDF. Saves the metadata round trip."""
    doc_id = meta_url.rstrip("/").split("/")[-1]
    DOC_DIR.mkdir(parents=True, exist_ok=True)
    out_x = DOC_DIR / f"Prod000_0000_{number}_{doc_id[:8]}.html"
    out_p = DOC_DIR / f"{number}_{doc_id}.pdf"
    if out_x.exists():
        return "xhtml", out_x
    if out_p.exists():
        return "pdf", out_p
    content = client.get_document(f"{meta_url}/content", "application/xhtml+xml")
    if content and (b"<html" in content[:2000].lower() or b"<?xml" in content[:200].lower()):
        out_x.write_bytes(content)
        return "xhtml", out_x
    content = client.get_document(f"{meta_url}/content", "application/pdf")
    if content and content[:5] == b"%PDF-":
        out_p.write_bytes(content)
        return "pdf", out_p
    return None, None


def _made_up(meta: dict) -> str:
    d = (meta.get("significant_date") or meta.get("created_at") or "")[:10]
    return d.replace("-", "") if d else "00000000"


def pdf_text(pdf_path: Path, max_pages: int = 120) -> str:
    """Text layer via poppler's pdftotext (fast, keeps table layout); pypdf as the fallback."""
    import subprocess

    try:
        r = subprocess.run(["pdftotext", "-layout", "-l", str(max_pages), str(pdf_path), "-"],
                           capture_output=True, timeout=120)
        if r.returncode == 0 and r.stdout:
            return r.stdout.decode("utf-8", errors="replace")
    except (OSError, subprocess.TimeoutExpired):
        pass
    try:
        from pypdf import PdfReader

        rd = PdfReader(str(pdf_path))
        return "\n".join((pg.extract_text() or "") for pg in rd.pages[:max_pages])
    except Exception:
        return ""


def pdf_rows(number: str, filing: dict, pdf_path: Path, fetched_at: str, text: str | None = None, parser: str = "pdf_regex") -> tuple[list[dict], dict]:
    made_up = (filing.get("description_values") or {}).get("made_up_date") or filing.get("date")
    text = pdf_text(pdf_path) if text is None else text
    ex = extract_from_pdf_text(text) if has_text_layer(text) else {"employees": None, "turnover": None, "scale": 1}
    pl_ = extract_pl_from_text(text, ex.get("scale", 1)) if has_text_layer(text) else {}
    if pl_.get("revenue") is not None and (ex.get("turnover") is None or ex.get("scale", 1) >= 1_000_000):
        ex["turnover"], ex["turnover_match"] = pl_["revenue"], pl_.get("revenue_match")
    facts = []
    for concept, value in (("AverageNumberEmployeesDuringPeriod", ex.get("employees")), ("TurnoverRevenue", ex.get("turnover")),
                           ("OperatingProfitLoss", pl_.get("operating_profit")), ("ProfitLossOnOrdinaryActivitiesBeforeTax", pl_.get("pbt")),
                           ("EBITDAStated", pl_.get("ebitda"))):
        if value is None:
            continue
        facts.append({"company_number": number, "period_end": made_up, "concept": concept, "value": float(value), "value_literal": float(value),
                      "unit": "pure" if concept.startswith("Average") else "GBP", "context_id": "pdf-duration", "period_type": "duration",
                      "instant": None, "start": None, "end": made_up, "is_within_one_year": False, "is_after_one_year": False, "n_dims": 0,
                      "dims_json": "{}", "scale": str(ex.get("scale", 1)), "sign": None, "decimals": None, "source_file": pdf_path.name,
                      "source_zip": SOURCE_ZIP, "fetched_at": fetched_at})
    try:
        tdir = path("cache") / "accounts_text"
        tdir.mkdir(parents=True, exist_ok=True)
        (tdir / f"{number}.txt").write_text(text[:400000])
    except OSError:
        pass
    desc = filing.get("description") or ""
    acc_type = "GROUP" if "group" in desc else ("FULL" if "full" in desc else ("MEDIUM" if "medium" in desc else ("SMALL" if "small" in desc else None)))
    meta = {"company_number": number, "period_start": None, "period_end": made_up, "balance_sheet_date": made_up, "entity_name": None,
            "accounts_type": f"PDF-{acc_type}" if acc_type else "PDF", "accounting_standard": None, "audit_status": None, "is_dormant": None,
            "n_facts": len(facts), "n_numeric": len(facts), "has_turnover": ex.get("turnover") is not None, "has_employees": ex.get("employees") is not None,
            "pl_exempt": None, "software": None, "parser": parser, "kind": "pdf", "source_file": pdf_path.name, "source_zip": SOURCE_ZIP,
            "fetched_at": fetched_at}
    meta["_scanned"] = not has_text_layer(text)
    meta["_filing"] = filing
    return facts, meta


def scanned_rows(number: str, filing: dict, pdf_path: Path, fetched_at: str) -> tuple[list[dict], dict]:
    """Image-only PDF: targeted OCR plus the vision read of the P&L page (src.ingest.pdf_ocr)."""
    from src.ingest.pdf_ocr import read_report, read_report_vision, vision_to_pounds

    made_up = (filing.get("description_values") or {}).get("made_up_date") or filing.get("date")
    r = read_report_vision(pdf_path) if os.environ.get("PDF_READER", "vision") == "vision" else read_report(pdf_path)
    vals: dict = {}
    parser = "ocr_none"
    if r.get("vision"):
        v = vision_to_pounds(r["vision"])
        vals = {"turnover": v.get("revenue"), "operating_profit": v.get("operating_profit"), "pbt": v.get("profit_before_tax"),
                "ebitda": v.get("ebitda"), "employees": v.get("employees")}
        parser = "ocr_vision"
        if v.get("period_end") and re.match(r"^\d{4}-\d{2}-\d{2}$", str(v["period_end"])):
            made_up = v["period_end"]
    text = r.get("text") or ""
    if text:
        ex = extract_from_pdf_text(text) if has_text_layer(text) else {"scale": 1}
        pl_ = extract_pl_from_text(text, ex.get("scale", 1)) if has_text_layer(text) else {}
        hl = r.get("highlights") or {}
        for k, src in (("turnover", pl_.get("revenue") or ex.get("turnover") or hl.get("revenue")),
                       ("operating_profit", pl_.get("operating_profit") or hl.get("operating_profit")),
                       ("pbt", pl_.get("pbt")), ("ebitda", pl_.get("ebitda") or hl.get("ebitda")),
                       ("employees", ex.get("employees"))):
            if vals.get(k) is None and src is not None:
                vals[k] = src
                if parser == "ocr_none":
                    parser = "ocr_regex"
        try:
            tdir = path("cache") / "accounts_text"
            tdir.mkdir(parents=True, exist_ok=True)
            (tdir / f"{number}.ocr.txt").write_text(text[:200000])
        except OSError:
            pass
    facts = []
    for concept, value in (("AverageNumberEmployeesDuringPeriod", vals.get("employees")), ("TurnoverRevenue", vals.get("turnover")),
                           ("OperatingProfitLoss", vals.get("operating_profit")), ("ProfitLossOnOrdinaryActivitiesBeforeTax", vals.get("pbt")),
                           ("EBITDAStated", vals.get("ebitda"))):
        if value is None:
            continue
        facts.append({"company_number": number, "period_end": made_up, "concept": concept, "value": float(value), "value_literal": float(value),
                      "unit": "pure" if concept.startswith("Average") else "GBP", "context_id": "ocr-duration", "period_type": "duration",
                      "instant": None, "start": None, "end": made_up, "is_within_one_year": False, "is_after_one_year": False, "n_dims": 1 if (r.get("vision") or {}).get("consolidated") else 0,
                      "dims_json": json.dumps({"GroupCompanyDataDimension": "Consolidated"}) if (r.get("vision") or {}).get("consolidated") else "{}",
                      "scale": "1", "sign": None, "decimals": None, "source_file": pdf_path.name,
                      "source_zip": SOURCE_ZIP, "fetched_at": fetched_at})
    desc = filing.get("description") or ""
    acc_type = "GROUP" if "group" in desc else ("FULL" if "full" in desc else ("MEDIUM" if "medium" in desc else None))
    meta = {"company_number": number, "period_start": None, "period_end": made_up, "balance_sheet_date": made_up, "entity_name": None,
            "accounts_type": f"PDF-{acc_type}" if acc_type else "PDF", "accounting_standard": None, "audit_status": None, "is_dormant": None,
            "n_facts": len(facts), "n_numeric": len(facts), "has_turnover": vals.get("turnover") is not None, "has_employees": vals.get("employees") is not None,
            "pl_exempt": None, "software": f"ocr:{r.get('method')}:p{r.get('pl_page')}:calls{r.get('vision_calls')}", "parser": parser, "kind": "pdf",
            "source_file": pdf_path.name, "source_zip": SOURCE_ZIP, "fetched_at": fetched_at}
    return facts, meta


def load_progress() -> dict:
    if PROGRESS.exists():
        return json.loads(PROGRESS.read_text())
    return {"done": {}, "stats": {"xhtml": 0, "pdf": 0, "pdf_employees": 0, "pdf_turnover": 0, "no_filing": 0, "no_doc": 0, "errors": 0}}


def save_progress(p: dict) -> None:
    tmp = PROGRESS.with_suffix(".tmp")
    tmp.write_text(json.dumps(p))
    tmp.replace(PROGRESS)


def run_ocr(numbers: list[str] | None, limit: int | None, shortlist_only: bool = False, priority_names: bool = False) -> None:
    """OCR the parked scanned PDFs (optionally only some companies) and write their facts."""
    q = DOC_DIR / "scanned"
    if not q.exists():
        log.info("no scanned queue")
        return
    items = sorted(q.glob("*.json"))
    if numbers:
        items = [j for j in items if json.loads(j.read_text())["company_number"] in set(numbers)]
    elif priority_names:
        # Pre-classification pass while the CPU is idle: founder or uncertain provisional companies in
        # FULL/GROUP/MEDIUM, names carrying a vertical keyword first, excluded companies never.
        import polars as pl

        from src.common import parquet_exists, read_parquet

        kw = ["health", "care", "medic", "clinic", "pharm", "dental", "vet", "patient", "nhs", "complian", "risk", "pay", "financ",
              "fintech", "insur", "tax", "account", "legal", "regul", "secur", "cyber", "audit", "bank", "lend", "credit", "wealth",
              "pension", "invest", "fund", "mortgage", "claims", "fraud", "identity", "privacy", "governance", "treasury", "trading", "capital"]
        allowed, hinted = set(), set()
        if parquet_exists("universe"):
            uni = read_parquet("universe").filter((pl.col("founder_flag") != "excluded") | pl.col("founder_led").fill_null(False)) if "founder_led" in read_parquet("universe").columns else read_parquet("universe").filter(pl.col("founder_flag") != "excluded")
            allowed = set(uni["company_number"].to_list())
            hinted = {r["company_number"] for r in uni.select(["company_number", "name"]).to_dicts() if any(k in (r["name"] or "").lower() for k in kw)}
        infos = [(j, json.loads(j.read_text())) for j in items]
        prio = {"FULL": 0, "GROUP": 1, "MEDIUM": 2}
        infos = [(j, i) for j, i in infos if i["company_number"] in allowed and (i.get("account_category") or "") in prio]
        infos.sort(key=lambda t: (0 if t[1]["company_number"] in hinted else 1, prio.get(t[1].get("account_category") or "", 9)))
        items = [j for j, _ in infos]
    elif shortlist_only:
        # Only companies that classified into a target vertical and are not excluded by the
        # founder rules; FULL and GROUP filers first since they are the larger businesses.
        import polars as pl

        from src.common import parquet_exists, read_parquet

        keep: set[str] = set()
        if parquet_exists("classification") and parquet_exists("universe"):
            cls = read_parquet("classification").filter(pl.col("vertical").is_in(cfg()["target"]["verticals"]))
            uni = read_parquet("universe").filter((pl.col("founder_flag") != "excluded") | pl.col("founder_led").fill_null(False)) if "founder_led" in read_parquet("universe").columns else read_parquet("universe").filter(pl.col("founder_flag") != "excluded")
            keep = set(cls["company_number"].to_list()) & set(uni["company_number"].to_list())
        infos = [(j, json.loads(j.read_text())) for j in items]
        prio = {"FULL": 0, "GROUP": 1, "MEDIUM": 2}
        items = [j for j, info in sorted(infos, key=lambda t: prio.get((t[1].get("account_category") or ""), 9)) if info["company_number"] in keep]
    if limit:
        items = items[:limit]
    prog = load_progress()
    facts_dir = path("parquet") / "accounts_facts"
    meta_dir = path("parquet") / "accounts_meta"
    batch_no = len(list(facts_dir.glob("part-api-ocr-*.parquet")))
    rows_f, rows_m = [], []
    fetched_at = now_iso()
    log.info("OCR queue: %d files", len(items))
    for i, j in enumerate(items):
        if not j.exists():
            continue
        try:
            info = json.loads(j.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        pdf = j.with_suffix(".pdf")
        if not pdf.exists():
            j.unlink(missing_ok=True)
            continue
        # claim the file so a second worker skips it
        claimed = pdf.with_suffix(f".{__import__('os').getpid()}.pdf")
        try:
            pdf.rename(claimed)
        except OSError:
            continue
        pdf = claimed
        t0 = time.time()
        try:
            text = ocr_pdf(pdf)
            facts, meta = pdf_rows(info["company_number"], info["filing"] or {}, pdf, fetched_at, text=text, parser="pdf_ocr")
            meta.pop("_scanned", None)
            meta.pop("_filing", None)
            rows_f.extend(facts)
            rows_m.append(meta)
            prog["done"][info["company_number"]] = "pdf_ocr"
            prog["stats"]["pdf_ocr"] = prog["stats"].get("pdf_ocr", 0) + 1
            prog["stats"]["pdf_employees"] += int(meta["has_employees"])
            prog["stats"]["pdf_turnover"] += int(meta["has_turnover"])
            log.info("%s OCR %.0fs employees=%s turnover=%s", info["company_number"], time.time() - t0,
                     next((f["value"] for f in facts if f["concept"].startswith("Average")), None),
                     next((f["value"] for f in facts if f["concept"] == "TurnoverRevenue"), None))
            (DOC_DIR / "ocr_text").mkdir(exist_ok=True)
            (DOC_DIR / "ocr_text" / (pdf.stem + ".txt")).write_text(text)
            pdf.unlink(missing_ok=True)
            j.unlink(missing_ok=True)
        except Exception as e:
            log.error("OCR failed for %s: %s", info["company_number"], e)
        if (i + 1) % 10 == 0 or i == len(items) - 1:
            if rows_m:
                import os as _os

                tag = f"{_os.getpid()}-{int(time.time())}"
                _write_part(_frame(rows_f, FACT_SCHEMA), facts_dir / f"part-api-ocr-{tag}.parquet")
                _write_part(_frame(rows_m, META_SCHEMA), meta_dir / f"part-api-ocr-{tag}.parquet")
                rows_f, rows_m = [], []
            # merge with whatever another worker saved meanwhile
            latest = load_progress()
            latest["done"].update(prog["done"])
            for k, v in prog["stats"].items():
                latest["stats"][k] = max(latest["stats"].get(k, 0), v)
            prog = latest
            save_progress(prog)
    log.info("OCR done: %s", prog["stats"])


def fixup_ocr_parts() -> None:
    """Re-apply the plausibility rules to every OCR fact part (rows written before a rule existed,
    and OCR digit noise): employees above 20,000 dropped; turnover per head above £2.5M divided by
    1,000 once and dropped if still implausible; turnover above £5bn with no headcount dropped."""
    import polars as pl

    facts_dir = path("parquet") / "accounts_facts"
    meta_dir = path("parquet") / "accounts_meta"
    changed = dropped = 0
    for fp in sorted(facts_dir.glob("part-api-ocr-*.parquet")):
        df = pl.read_parquet(fp)
        if df.height == 0:
            continue
        rows = df.to_dicts()
        by = {}
        for r in rows:
            by.setdefault((r["company_number"], r["period_end"]), {})[r["concept"]] = r
        keep = []
        for key, d in by.items():
            e = d.get("AverageNumberEmployeesDuringPeriod")
            t = d.get("TurnoverRevenue")
            ev = e["value"] if e else None
            tv = t["value"] if t else None
            if ev is not None and ev > 20000:
                ev = None
                dropped += 1
            if tv is not None:
                if ev and tv / ev > 2_500_000:
                    tv = tv / 1000
                    changed += 1
                    if tv / ev > 2_500_000 or tv / ev < 2_000:
                        tv = None
                        dropped += 1
                elif not ev and tv > 5_000_000_000:
                    tv = None
                    dropped += 1
                elif ev and tv / ev < 2_000:
                    tv = tv * 1000 if tv * 1000 / ev < 2_500_000 else None
                    changed += 1
            if ev is not None and e:
                keep.append({**e, "value": float(ev), "value_literal": float(ev)})
            if tv is not None and t:
                keep.append({**t, "value": float(tv), "value_literal": float(tv)})
            for c, r in d.items():
                if c not in ("AverageNumberEmployeesDuringPeriod", "TurnoverRevenue"):
                    keep.append(r)
        _write_part(_frame(keep, FACT_SCHEMA), fp)
        mp = meta_dir / fp.name
        if mp.exists():
            m = pl.read_parquet(mp).to_dicts()
            present = {(r["company_number"], r["period_end"]) for r in keep}
            has_t = {(r["company_number"], r["period_end"]) for r in keep if r["concept"] == "TurnoverRevenue"}
            has_e = {(r["company_number"], r["period_end"]) for r in keep if r["concept"] == "AverageNumberEmployeesDuringPeriod"}
            for r in m:
                k = (r["company_number"], r["period_end"])
                r["has_turnover"] = k in has_t
                r["has_employees"] = k in has_e
                r["n_facts"] = sum(1 for x in keep if (x["company_number"], x["period_end"]) == k)
            _write_part(_frame(m, META_SCHEMA), mp)
    log.info("fix-up done: %d values rescaled, %d dropped", changed, dropped)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--fixup-ocr", action="store_true", help="re-apply plausibility rules to OCR parts")
    ap.add_argument("--ocr", action="store_true", help="process the scanned-PDF queue with tesseract")
    ap.add_argument("--shortlist", action="store_true", help="with --ocr: only target-vertical, non-excluded companies")
    ap.add_argument("--priority-names", action="store_true", help="with --ocr: non-excluded FULL/GROUP/MEDIUM, keyword names first")
    ap.add_argument("--categories", default="GROUP,FULL,MEDIUM")
    ap.add_argument("--routes", default=None, help="comma list of ownership routes to restrict to (default: all, in priority order)")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--numbers")
    ap.add_argument("--batch-size", type=int, default=200)
    ap.add_argument("--shard", default=None, help="i/n: process every n-th candidate starting at i (parallel workers)")
    args = ap.parse_args(argv)
    if args.fixup_ocr:
        fixup_ocr_parts()
        return
    if args.ocr:
        run_ocr(args.numbers.split(",") if args.numbers else None, args.limit, shortlist_only=args.shortlist, priority_names=args.priority_names)
        return
    key = env_key("companies_house_key_env")
    if not key:
        log.info("CH_API_KEY not set; nothing to do")
        return
    client = CHClient(key)
    if args.numbers:
        nums = args.numbers.split(",")
        cand = read_parquet("candidate_companies").filter(pl.col("company_number").is_in(nums)).select(["company_number", "name", "account_category"])
    else:
        cand = candidates([c.strip() for c in args.categories.split(",")],
                          [r.strip() for r in args.routes.split(",")] if args.routes else None).select(["company_number", "name", "account_category"])
    prog = load_progress()
    todo = [r for r in cand.to_dicts() if r["company_number"] not in prog["done"]]
    if args.shard:
        i, k = (int(x) for x in args.shard.split("/"))
        todo = todo[i::k]
    if args.limit:
        todo = todo[: args.limit]
    log.info("%d candidates (%d already done); categories %s", len(todo), len(prog["done"]), cand.group_by("account_category").len().sort("len", descending=True).to_dicts())
    facts_dir = path("parquet") / "accounts_facts"
    meta_dir = path("parquet") / "accounts_meta"
    facts_dir.mkdir(parents=True, exist_ok=True)
    meta_dir.mkdir(parents=True, exist_ok=True)
    batch_facts, batch_meta = [], []
    shard_tag = os.environ.get("API_SHARD", "").replace("/", "of") or "s"
    batch_no = len(list(facts_dir.glob(f"part-api-{shard_tag}-*.parquet")))
    fetched_at = now_iso()
    t0 = time.time()
    def one(r: dict) -> None:
        n = r["company_number"]
        filing = latest_accounts_filing(client, n)
        if not filing:
            prog["done"][n] = "no_filing"
            prog["stats"]["no_filing"] += 1
            return
        meta_url = (filing.get("links") or {}).get("document_metadata")
        if not meta_url:
            prog["done"][n] = "no_doc"
            prog["stats"]["no_doc"] += 1
            return
        kind, local = fetch_document(client, meta_url, n)
        if not kind:
            prog["done"][n] = "no_doc"
            prog["stats"]["no_doc"] += 1
            return
        if kind == "xhtml":
            res = parse_one((str(local), SOURCE_ZIP, fetched_at))
            if res.get("error"):
                prog["done"][n] = "parse_error"
                prog["stats"]["errors"] += 1
                return
            batch_facts.extend(res["facts"])
            batch_meta.append(res["meta"])
            prog["done"][n] = "xhtml"
            prog["stats"]["xhtml"] += 1
            return
        facts, meta = pdf_rows(n, filing, local, fetched_at)
        scanned = meta.pop("_scanned", False)
        meta.pop("_filing", None)
        if scanned:
            # image-only PDF (Companies House rasterises PDFs): targeted OCR plus a vision read, inline
            facts, meta = scanned_rows(n, filing, local, fetched_at)
            prog["stats"]["pdf_scanned"] = prog["stats"].get("pdf_scanned", 0) + 1
            prog["stats"][meta["parser"]] = prog["stats"].get(meta["parser"], 0) + 1
        batch_facts.extend(facts)
        batch_meta.append(meta)
        prog["done"][n] = "pdf" if not scanned else meta["parser"]
        prog["stats"]["pdf"] += 1
        prog["stats"]["pdf_employees"] += int(meta["has_employees"])
        prog["stats"]["pdf_turnover"] += int(meta["has_turnover"])
        local.unlink(missing_ok=True)

    for i, r in enumerate(todo):
        try:
            one(r)
        except Exception as e:
            log.error("%s %s: %s", r["company_number"], r["name"], e)
            prog["done"][r["company_number"]] = f"error:{type(e).__name__}"
            prog["stats"]["errors"] += 1
        if (i + 1) % args.batch_size == 0 or i == len(todo) - 1:
            if batch_meta:
                batch_no += 1
                _write_part(_frame(batch_facts, FACT_SCHEMA), facts_dir / f"part-api-{shard_tag}-{batch_no:04d}.parquet")
                _write_part(_frame(batch_meta, META_SCHEMA), meta_dir / f"part-api-{shard_tag}-{batch_no:04d}.parquet")
                batch_facts.clear()
                batch_meta.clear()
            save_progress(prog)
            log.info("%d/%d done in %.0fs; stats %s; api calls %d", i + 1, len(todo), time.time() - t0, prog["stats"], client.calls_made)
    save_progress(prog)
    log.info("finished: %s. Now run: python -m src.ingest.accounts --build-wide", prog["stats"])


if __name__ == "__main__":
    main(sys.argv[1:])
