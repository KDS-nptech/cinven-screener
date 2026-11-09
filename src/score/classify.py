"""Stage 5: vertical classifier.

Two passes:
1. Keyword pre-filter on the fetched website text (config.classifier.keywords) plus a SIC
   hint (66190 implies fintech). Companies with no hit in any target vertical are labelled
   `other` deterministically and never reach the LLM.
2. One LLM call per remaining company (JSON output, temperature 0). The evidence quote
   must appear verbatim in the fetched text and the URL must be a fetched page; a failed
   validation re-runs once with a stricter reminder, then the company is flagged
   `classifier_failed` and its confidence forced to low.

Input: data/parquet/universe.parquet, data/parquet/websites.parquet, data/cache/web/<n>.json
Output: data/parquet/classification.parquet

Run: python -m src.score.classify [--limit N] [--numbers a,b,c] [--prefilter-only]
"""
from __future__ import annotations

import argparse
import json
import re
import sys

import polars as pl

from src.common import REPO, cfg, get_logger, now_iso, parquet_exists, path, read_parquet, write_parquet
from src.score.llm import LLM, quote_in_text

log = get_logger("classify")
PROMPT_VERSION = cfg()["classifier"]["prompt_version"]
SYSTEM = (REPO / "src" / "score" / "prompts" / f"{PROMPT_VERSION.replace('classify-', 'classify_')}.md").read_text()
VERTICALS = {"compliance_grc", "fintech_financial", "healthcare", "other"}
TEXT_BUDGET = 7000      # chars sent to the model; homepage first, then product pages
SIC_HINTS = {"66190": "fintech_financial"}


def load_web(company_number: str) -> dict | None:
    f = path("cache") / "web" / f"{company_number}.json"
    if not f.exists():
        return None
    try:
        return json.loads(f.read_text())
    except json.JSONDecodeError:
        return None


def keyword_hits(text: str) -> dict[str, int]:
    low = text.lower()
    out = {}
    for vertical, kws in cfg()["classifier"]["keywords"].items():
        n = 0
        for kw in kws:
            kw = str(kw).lower()
            if len(kw) <= 3:
                n += len(re.findall(rf"\b{re.escape(kw)}\b", low))
            else:
                n += low.count(kw)
        out[vertical] = n
    return out


def build_user_prompt(name: str, sic_text: str | None, pages: list[dict], budget: int = TEXT_BUDGET) -> tuple[str, str]:
    parts, used, urls = [], 0, []
    for p in pages:
        txt = (p.get("text") or "").strip()
        if not txt:
            continue
        room = budget - used
        if room <= 200:
            break
        chunk = txt[:room]
        parts.append(f"--- PAGE: {p.get('url')}\nTITLE: {p.get('title') or ''}\n{chunk}")
        urls.append(p.get("url"))
        used += len(chunk)
    body = "\n\n".join(parts)
    user = (f"Company: {name}\nCompanies House SIC description: {sic_text or 'n/a'}\n"
            f"Page URLs supplied: {json.dumps(urls)}\n\nWEBSITE TEXT:\n{body}\n\n"
            "Return the JSON object now.")
    return user, body


def validate(data: dict | None, body: str, urls: set[str]) -> list[str]:
    problems = []
    if not isinstance(data, dict):
        return ["no_json"]
    if data.get("vertical") not in VERTICALS:
        problems.append("bad_vertical")
    if not quote_in_text(str(data.get("evidence_quote", "")), body):
        problems.append("quote_not_verbatim")
    if len(str(data.get("evidence_quote", "")).split()) > 45:
        problems.append("quote_too_long")
    if data.get("evidence_url") not in urls:
        problems.append("bad_url")
    if data.get("confidence") not in {"high", "medium", "low"}:
        problems.append("bad_confidence")
    return problems


def classify_one(llm: LLM, row: dict, web: dict) -> dict:
    pages = web.get("pages") or []
    user, body = build_user_prompt(row["name"], row.get("sic_text1"), pages)
    urls = {p.get("url") for p in pages}
    res = llm.complete_json(SYSTEM, user)
    out = {"company_number": row["company_number"], "method": "llm", "model": res.model, "prompt_version": PROMPT_VERSION,
           "flags": [], "computed_at": now_iso()}
    if res.error in ("pending_batch", "quota_exhausted"):
        out.update(vertical=None, confidence=None, method="pending_batch")
        out["flags"].append(res.error)
        return out
    problems = validate(res.data, body, urls)
    if problems and res.error not in ("pending_batch", "quota_exhausted"):
        reminder = (user + "\n\nYour previous answer failed validation: " + ", ".join(problems) +
                    ". The evidence_quote must be an exact, contiguous substring of the WEBSITE TEXT above and the evidence_url "
                    "must be one of the supplied page URLs. Try again.")
        res2 = llm.complete_json(SYSTEM, reminder)
        if res2.error == "quota_exhausted":
            out.update(vertical=None, confidence=None, method="pending_batch")
            out["flags"].append("quota_exhausted")
            return out
        problems2 = validate(res2.data, body, urls)
        if not problems2:
            res, problems = res2, []
        else:
            out["flags"].append("classifier_failed")
            out["flags"].extend(sorted(set(problems2)))
            if res2.data and res2.data.get("vertical") in VERTICALS:
                res = res2
    d = res.data or {}
    out.update(
        vertical=d.get("vertical") if d.get("vertical") in VERTICALS else "other",
        sub_vertical=(d.get("sub_vertical") or "")[:60],
        is_software_product=bool(d.get("is_software_product")) if d else None,
        evidence_quote=(d.get("evidence_quote") or "")[:400],
        evidence_url=d.get("evidence_url") if d.get("evidence_url") in urls else None,
        confidence="low" if "classifier_failed" in out["flags"] else (d.get("confidence") if d.get("confidence") in {"high", "medium", "low"} else "low"),
        raw_json=json.dumps(d)[:2000],
    )
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int)
    ap.add_argument("--numbers")
    ap.add_argument("--prefilter-only", action="store_true")
    ap.add_argument("--all-universe", action="store_true", help="classify every universe row, not just founder/uncertain")
    ap.add_argument("--workers", type=int, default=4, help="parallel model calls")
    args = ap.parse_args(argv)

    uni = read_parquet("universe")
    if args.numbers:
        uni = uni.filter(pl.col("company_number").is_in(args.numbers.split(",")))
    elif not args.all_universe and "founder_flag" in uni.columns:
        keep = pl.col("founder_flag") != "excluded"
        if "founder_led" in uni.columns:
            keep = keep | pl.col("founder_led").fill_null(False)
        uni = uni.filter(keep)
    if parquet_exists("websites"):
        wcols = ["company_number", "domain", "text_chars"] + [c for c in ("name_match", "uk_signal", "discovery_method") if c in read_parquet("websites").columns]
        web = read_parquet("websites").select(wcols).unique(subset=["company_number"])
        uni = uni.join(web, on="company_number", how="left")
    else:
        uni = uni.with_columns(pl.lit(None).alias("domain"), pl.lit(None).alias("text_chars"))
    if "sic_text1" not in uni.columns and parquet_exists("companies"):
        comp = read_parquet("software_companies").select(["company_number", "sic_text1"])
        uni = uni.join(comp, on="company_number", how="left")
    if args.limit:
        uni = uni.head(args.limit)

    existing = read_parquet("classification") if parquet_exists("classification") else None
    done = set(existing["company_number"].to_list()) if existing is not None else set()
    done_rows = existing.to_dicts() if existing is not None else []
    # pending_batch rows and failed rows are retried
    done_rows = [r for r in done_rows if r.get("method") not in ("pending_batch", "no_website", "pending_llm", "wrong_site_suspected")]
    done = {r["company_number"] for r in done_rows}

    llm = LLM(PROMPT_VERSION)
    log.info("provider=%s model=%s", llm.provider, llm.model)
    rows = list(done_rows)
    n_prefilter = n_llm = n_noweb = n_pending = 0
    todo = [r for r in uni.to_dicts() if r["company_number"] not in done]
    log.info("%d companies to classify (%d already done)", len(todo), len(done))
    min_hits = cfg()["classifier"]["prefilter_min_hits"]

    def prepare(r: dict):
        """Deterministic part: returns ('row', dict) or ('llm', (r, web, hits))."""
        web = load_web(r["company_number"])
        if not web or not web.get("pages"):
            return "row", {"company_number": r["company_number"], "vertical": None, "sub_vertical": None, "is_software_product": None,
                           "evidence_quote": None, "evidence_url": None, "confidence": None, "method": "no_website",
                           "keyword_hits_json": None, "model": None, "prompt_version": PROMPT_VERSION, "flags": ["no_website"],
                           "raw_json": None, "computed_at": now_iso()}
        if r.get("name_match") is False and r.get("uk_signal") is False:
            return "row", {"company_number": r["company_number"], "vertical": None, "sub_vertical": None, "is_software_product": None,
                           "evidence_quote": None, "evidence_url": None, "confidence": None, "method": "wrong_site_suspected",
                           "keyword_hits_json": None, "model": None, "prompt_version": PROMPT_VERSION, "flags": ["wrong_site_suspected"],
                           "raw_json": None, "computed_at": now_iso()}
        text = " ".join((p.get("text") or "") for p in web["pages"])
        hits = keyword_hits(text)
        sic_hint = SIC_HINTS.get(str(r.get("sic1") or ""))
        if sum(hits.values()) < min_hits and not sic_hint:
            return "row", {"company_number": r["company_number"], "vertical": "other", "sub_vertical": None, "is_software_product": None,
                           "evidence_quote": None, "evidence_url": None, "confidence": "low", "method": "keyword_prefilter",
                           "keyword_hits_json": json.dumps(hits), "model": None, "prompt_version": PROMPT_VERSION, "flags": [],
                           "raw_json": None, "computed_at": now_iso()}
        if args.prefilter_only:
            return "row", {"company_number": r["company_number"], "vertical": None, "sub_vertical": None, "is_software_product": None,
                           "evidence_quote": None, "evidence_url": None, "confidence": None, "method": "pending_llm",
                           "keyword_hits_json": json.dumps(hits), "model": None, "prompt_version": PROMPT_VERSION, "flags": [],
                           "raw_json": None, "computed_at": now_iso()}
        return "llm", (r, web, hits)

    llm_jobs = []
    for r in todo:
        kind, payload = prepare(r)
        if kind == "row":
            rows.append(payload)
            m = payload["method"]
            n_noweb += m in ("no_website", "wrong_site_suspected")
            n_prefilter += m == "keyword_prefilter"
            n_llm += m == "pending_llm"
        else:
            llm_jobs.append(payload)
    log.info("deterministic: %d rows; %d companies go to the model", len(rows) - len(done_rows), len(llm_jobs))
    write_parquet(_frame(rows), "classification")

    from concurrent.futures import ThreadPoolExecutor, as_completed

    def run_llm(job):
        r, web, hits = job
        out = classify_one(llm, r, web)
        out["keyword_hits_json"] = json.dumps(hits)
        for k in ("vertical", "sub_vertical", "is_software_product", "evidence_quote", "evidence_url", "confidence", "raw_json"):
            out.setdefault(k, None)
        return out

    done_llm = 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(run_llm, j) for j in llm_jobs]
        for fut in as_completed(futures):
            try:
                out = fut.result()
            except Exception as e:  # keep going; the company is retried next run
                log.error("classify failed: %s", e)
                continue
            rows.append(out)
            if out["method"] == "pending_batch":
                n_pending += 1
            else:
                n_llm += 1
            done_llm += 1
            if done_llm % 25 == 0:
                log.info("%d/%d model calls done (prefilter=%d noweb=%d pending=%d calls=%d cache_hits=%d)",
                         done_llm, len(llm_jobs), n_prefilter, n_noweb, n_pending, llm.calls, llm.cache_hits)
                write_parquet(_frame(rows), "classification")
    df = _frame(rows)
    write_parquet(df, "classification")
    summary = {
        "computed_at": now_iso(), "rows": df.height, "llm": n_llm, "keyword_prefilter_other": n_prefilter,
        "no_website": n_noweb, "pending_batch": n_pending, "provider": llm.provider, "model": llm.model,
        "vertical_counts": {k: v for k, v in zip(*[c.to_list() for c in df.group_by("vertical").len().sort("vertical")])},
        "confidence_counts": {k: v for k, v in zip(*[c.to_list() for c in df.group_by("confidence").len().sort("confidence")])},
        "classifier_failed": int(df.filter(pl.col("flags").list.contains("classifier_failed")).height),
    }
    (REPO / "docs" / "classification_summary.json").write_text(json.dumps(summary, indent=2, default=str))
    log.info("done: %s", summary)


def _frame(rows: list[dict]) -> pl.DataFrame:
    schema = {"company_number": pl.Utf8, "vertical": pl.Utf8, "sub_vertical": pl.Utf8, "is_software_product": pl.Boolean,
              "evidence_quote": pl.Utf8, "evidence_url": pl.Utf8, "confidence": pl.Utf8, "method": pl.Utf8,
              "keyword_hits_json": pl.Utf8, "model": pl.Utf8, "prompt_version": pl.Utf8, "flags": pl.List(pl.Utf8),
              "raw_json": pl.Utf8, "computed_at": pl.Utf8}
    clean = []
    for r in rows:
        clean.append({k: r.get(k) for k in schema})
        if clean[-1]["flags"] is None:
            clean[-1]["flags"] = []
    return pl.DataFrame(clean, schema=schema)


if __name__ == "__main__":
    main(sys.argv[1:])
