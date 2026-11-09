"""Quality checks, each by a model the pipeline never uses for its own answers (Claude Sonnet 5.5).

  python -m src.qa pdf [--n 30]       re-read the P&L page of a sample of PDF-read filings -> docs/qa/pdf_check.json
  python -m src.qa labels [--n 30]    blind re-label a sample of classified companies      -> docs/qa/labels_check.json
  python -m src.qa scores [--n 10]    blind re-score a sample of rubric-scored companies   -> docs/qa/scores_check.json
  python -m src.qa review-pack        top 30 ranked with every fact a reviewer needs       -> docs/qa/top30_pack.md
  python -m src.qa record             fold the checks and overrides.yaml into docs/qa_results.json

The PDF check fetches the same document, renders the page the reader used and asks the checker model
the same question; it tests extraction (figures, unit, period) on the page the pipeline chose.
"""
from __future__ import annotations

import argparse
import json
import random
import re
import tempfile
from pathlib import Path

import polars as pl
import yaml

from src.common import REPO, cfg, get_logger, now_iso, parquet_exists, path, read_parquet

log = get_logger("qa")
QA_DIR = REPO / "docs" / "qa"
CHECKER = "claude-sonnet-5-5"
CHECKER_PROVIDER = "anthropic_sonnet55"
DOC_BASE = "https://document-api.company-information.service.gov.uk/document"


def _within(a, b, tol):
    if a is None or b is None:
        return None
    if b == 0:
        return a == 0
    return abs(a - b) / abs(b) <= tol


# ------------------------------------------------------------------ PDF re-read
def pdf_check(n: int):
    from src.enrich.ch_api import CHClient
    from src.ingest.pdf_ocr import render, vision_extract, vision_to_pounds

    QA_DIR.mkdir(parents=True, exist_ok=True)
    meta = pl.scan_parquet(str(path("parquet") / "accounts_meta" / "part-api-*.parquet")).filter(
        pl.col("parser") == "ocr_vision").select(["company_number", "period_end", "software", "source_file"]).collect()
    facts = pl.scan_parquet(str(path("parquet") / "accounts_facts" / "part-api-*.parquet")).filter(
        pl.col("context_id") == "ocr-duration").select(["company_number", "concept", "value"]).collect()
    fx = {}
    for r in facts.to_dicts():
        fx.setdefault(r["company_number"], {})[r["concept"]] = r["value"]
    rows = [r for r in meta.to_dicts() if re.search(r":p(\d+):", r["software"] or "") and fx.get(r["company_number"], {}).get("TurnoverRevenue") is not None]
    # weight the sample towards companies at scale: they are the ones that reach the ranked list
    big = [r for r in rows if (fx[r["company_number"]].get("TurnoverRevenue") or 0) >= 50e6]
    small = [r for r in rows if r not in big]
    random.seed(7)
    pick = random.sample(big, min(len(big), (2 * n) // 3)) + random.sample(small, min(len(small), n - min(len(big), (2 * n) // 3)))
    client = CHClient()
    out = []
    tmp = Path(tempfile.mkdtemp(prefix="qa_pdf_"))
    for r in pick:
        num = r["company_number"]
        page = int(re.search(r":p(\d+):", r["software"]).group(1))
        doc_id = Path(r["source_file"]).stem.split("_", 1)[1]
        pdf = tmp / f"{num}.pdf"
        try:
            content = client.get_document(f"{DOC_BASE}/{doc_id}/content", "application/pdf")
            if not content or content[:5] != b"%PDF-":
                out.append({"company_number": num, "status": "no_document"})
                continue
            pdf.write_bytes(content)
            imgs = render(pdf, page, page, tmp, dpi=130)
            v = vision_extract(imgs[0], model=CHECKER) if imgs else None
        finally:
            for f in tmp.glob("*"):
                f.unlink(missing_ok=True)
        if not v:
            out.append({"company_number": num, "status": "checker_no_answer", "page": page})
            continue
        c = vision_to_pounds(v)
        p = fx[num]
        row = {"company_number": num, "status": "checked", "page": page, "period_end_pipeline": r["period_end"], "period_end_checker": c.get("period_end"),
               "turnover_pipeline": p.get("TurnoverRevenue"), "turnover_checker": c.get("revenue"),
               "op_pipeline": p.get("OperatingProfitLoss"), "op_checker": c.get("operating_profit"),
               "pbt_pipeline": p.get("ProfitLossOnOrdinaryActivitiesBeforeTax"), "pbt_checker": c.get("profit_before_tax"),
               "unit_checker": c.get("unit"), "notes_checker": (v.get("notes") or "")[:200]}
        row["turnover_within_2pct"] = _within(row["turnover_checker"], row["turnover_pipeline"], 0.02)
        row["op_within_2pct"] = _within(row["op_checker"], row["op_pipeline"], 0.02)
        t1, t2 = row["turnover_pipeline"], row["turnover_checker"]
        row["unit_error"] = bool(t1 and t2 and min(abs(t1), abs(t2)) > 0 and 900 <= max(abs(t1), abs(t2)) / min(abs(t1), abs(t2)) <= 1100)
        out.append(row)
        log.info("%s p%d turnover %s vs %s op %s vs %s", num, page, t1, t2, row["op_pipeline"], row["op_checker"])
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)
    ok = [x for x in out if x["status"] == "checked"]
    tv = [x for x in ok if x["turnover_within_2pct"] is not None]
    ov = [x for x in ok if x["op_within_2pct"] is not None]
    summary = {"computed_at": now_iso(), "checker_model": CHECKER, "sampled": len(pick), "checked": len(ok),
               "turnover_compared": len(tv), "turnover_within_2pct": round(100 * sum(x["turnover_within_2pct"] for x in tv) / len(tv), 1) if tv else None,
               "op_compared": len(ov), "op_within_2pct": round(100 * sum(x["op_within_2pct"] for x in ov) / len(ov), 1) if ov else None,
               "unit_errors": sum(x["unit_error"] for x in ok),
               "period_end_agree": round(100 * sum(1 for x in ok if x["period_end_checker"] == x["period_end_pipeline"]) / len(ok), 1) if ok else None,
               "method": "same page re-rendered at 130 dpi and read by the checker model with the pipeline's prompt; two thirds of the sample at turnover of £50M or more"}
    (QA_DIR / "pdf_check.json").write_text(json.dumps({"summary": summary, "rows": out}, indent=1, default=str))
    log.info("pdf check: %s", summary)


# ------------------------------------------------------------------ blind labels
def labels(n: int):
    from src.score import classify as C
    from src.score.llm import LLM

    QA_DIR.mkdir(parents=True, exist_ok=True)
    cls = read_parquet("classification").filter(pl.col("method") == "llm")
    uni = read_parquet("universe").select(["company_number", "name"])
    comp = read_parquet("candidate_companies").select(["company_number", "sic_text1"])
    df = cls.join(uni, on="company_number", how="left").join(comp, on="company_number", how="left")
    in_six = df.filter(pl.col("vertical") != "other")
    other = df.filter(pl.col("vertical") == "other")
    k = min(in_six.height, (3 * n) // 4)
    pick = in_six.sample(k, seed=11).to_dicts() + other.sample(min(other.height, n - k), seed=11).to_dicts()
    llm = LLM(C.PROMPT_VERSION + "-qa", providers=[CHECKER_PROVIDER])
    rows = []
    for r in pick:
        web = C.load_web(r["company_number"])
        if not web or not web.get("pages"):
            continue
        user, body = C.build_user_prompt(r["name"], r.get("sic_text1"), web["pages"])
        res = llm.complete_json(C.SYSTEM, user)
        d = res.data or {}
        rows.append({"company_number": r["company_number"], "name": r["name"], "pipeline": r["vertical"], "checker": d.get("sector"),
                     "agree": r["vertical"] == d.get("sector"), "pipeline_operating": r.get("is_software_product"), "checker_operating": d.get("is_operating_business")})
    agree = [x for x in rows if x["checker"]]
    summary = {"computed_at": now_iso(), "checker_model": CHECKER, "checked": len(agree),
               "agreement_pct": round(100 * sum(x["agree"] for x in agree) / len(agree), 1) if agree else None,
               "disagreements": [f'{x["name"]}: {x["pipeline"]} vs {x["checker"]}' for x in agree if not x["agree"]],
               "method": "same website extract and prompt, answered blind by the checker model; three quarters of the sample from the six sectors"}
    (QA_DIR / "labels_check.json").write_text(json.dumps({"summary": summary, "rows": rows}, indent=1, default=str))
    log.info("labels: %s", summary)


# ------------------------------------------------------------------ blind rubric
def scores(n: int):
    from src.score import rubric as R
    from src.score.llm import LLM

    QA_DIR.mkdir(parents=True, exist_ok=True)
    sc = read_parquet("scores_raw") if parquet_exists("scores_raw") else read_parquet("scores")
    sc = sc.filter(pl.col("status") == "scored")
    rk = read_parquet("rankings").select(["company_number", "name", "ranked", "durability_score"])
    pool_ranked = rk.filter(pl.col("ranked")).sort("durability_score", descending=True)["company_number"].to_list()
    pool_rest = [c for c in rk.filter(~pl.col("ranked") & pl.col("durability_score").is_not_null())["company_number"].to_list()]
    random.seed(13)
    pick = pool_ranked[: (2 * n) // 3] + random.sample(pool_rest, min(len(pool_rest), n - min(len(pool_ranked), (2 * n) // 3)))
    names = dict(zip(rk["company_number"].to_list(), rk["name"].to_list()))
    ctx = R.load_context(set(pick))
    llm = LLM(R.PROMPT_VERSION + "-qa", providers=[CHECKER_PROVIDER])
    W = {int(k): v for k, v in cfg()["rubric"]["weights"].items()}
    pairs, gaps, comps = [], [], []
    for num in pick:
        f = path("cache") / "web" / f"{num}.json"
        pages = json.loads(f.read_text()).get("pages", []) if f.exists() else []
        if not pages:
            continue
        rows, status = R.score_company(llm, num, names.get(num) or num, pages, R.structured_facts(num, ctx))
        if status != "scored":
            continue
        mine = {r["dimension"]: r["score"] for r in sc.filter(pl.col("company_number") == num).to_dicts()}
        theirs = {r["dimension"]: r["score"] for r in rows if r["score"] is not None}
        both = [k for k in range(1, 11) if k in mine and k in theirs and k not in (4, 5)]  # 4 and 5 are rule-scored
        for k in both:
            pairs.append((num, k, mine[k], theirs[k]))
        if both:
            m = sum(W[k] * mine[k] for k in both) / sum(W[k] for k in both)
            t = sum(W[k] * theirs[k] for k in both) / sum(W[k] for k in both)
            gaps.append((m - t) * 25)
            comps.append({"company_number": num, "name": names.get(num), "pipeline_mean": round(m, 2), "checker_mean": round(t, 2), "dims": len(both)})
    within = sum(abs(a - b) <= 1 for _, _, a, b in pairs)
    exact = sum(a == b for _, _, a, b in pairs)
    summary = {"computed_at": now_iso(), "checker_model": CHECKER, "companies": len(comps), "subscores": len(pairs),
               "within_one_pct": round(100 * within / len(pairs), 1) if pairs else None, "exact_pct": round(100 * exact / len(pairs), 1) if pairs else None,
               "iq_gap_mean": round(sum(gaps) / len(gaps), 1) if gaps else None,
               "method": "the eight website-read dimensions re-scored blind by the checker model from the same pages and facts; rule-scored dimensions excluded; IQ gap on the 0 to 100 scale"}
    (QA_DIR / "scores_check.json").write_text(json.dumps({"summary": summary, "companies": comps, "pairs": pairs}, indent=1, default=str))
    log.info("scores: %s", summary)


# ------------------------------------------------------------------ review pack
def review_pack(top: int = 30):
    QA_DIR.mkdir(parents=True, exist_ok=True)
    rk = read_parquet("rankings").filter(pl.col("ranked")).sort("durability_score", descending=True).head(top)
    lines = [f"# Top {top} review pack", "", f"Built {now_iso()}. One block per company; decide keep or exclude with a reason.", ""]
    for i, r in enumerate(rk.to_dicts(), 1):
        g = lambda k: r.get(k)
        lines += [f"## {i}. {g('name')} ({g('company_number')})",
                  f"- Sector: {g('vertical')} / {g('sub_vertical')}; route {g('route')} ({g('route_confidence')}); owners {g('owner_names')}; sponsor {g('sponsor_names')} hold {g('hold_years')}",
                  f"- Size: turnover {g('latest_turnover')}, EBITDA proxy {g('ebitda_proxy')} ({g('ebitda_basis')}), employees {g('latest_employees')}, period {g('latest_period_end')}, type {g('latest_accounts_type')}",
                  f"- Growth {g('turnover_growth')} (annualised {g('growth_annualised')}), margin {g('operating_margin')}; IQ {g('durability_score')}, fit {g('fit_score')}; flags {g('flags')}",
                  f"- Site {g('domain')} name_match {g('name_match')}; SIC {g('sic_text1')}; town {g('post_town')}",
                  f"- Quote: {g('evidence_quote')}", ""]
    (QA_DIR / "top30_pack.md").write_text("\n".join(lines))
    log.info("wrote %s", QA_DIR / "top30_pack.md")


# ------------------------------------------------------------------ record
def record():
    out = {"computed_at": now_iso(), "checker_model": CHECKER}
    f = QA_DIR / "pdf_check.json"
    if f.exists():
        s = json.loads(f.read_text())["summary"]
        out.update(pdf_checked=s["turnover_compared"], pdf_turnover_within_2pct=s["turnover_within_2pct"], pdf_op_within_2pct=s["op_within_2pct"],
                   pdf_unit_errors=s["unit_errors"], pdf_period_agree=s["period_end_agree"], pdf_method=s["method"])
    f = QA_DIR / "labels_check.json"
    if f.exists():
        s = json.loads(f.read_text())["summary"]
        out.update(labels_checked=s["checked"], label_agreement_pct=s["agreement_pct"], label_method=s["method"])
    f = QA_DIR / "scores_check.json"
    if f.exists():
        s = json.loads(f.read_text())["summary"]
        out.update(subscores_checked=s["subscores"], subscore_within_one_pct=s["within_one_pct"], subscore_exact_pct=s["exact_pct"],
                   iq_gap_mean=s["iq_gap_mean"], subscore_method=s["method"])
    ov = REPO / "overrides.yaml"
    if ov.exists():
        o = yaml.safe_load(ov.read_text()) or {}
        ex = o.get("exclude", []) or []
        out["top30_reviewed"] = o.get("top30_reviewed")
        out["exclusions"] = len(ex)
        reasons = {}
        for e in ex:
            k = (e.get("category") if isinstance(e, dict) else None) or "other"
            reasons[k] = reasons.get(k, 0) + 1
        out["exclusion_reasons"] = reasons
    (REPO / "docs" / "qa_results.json").write_text(json.dumps(out, indent=1))
    log.info("wrote docs/qa_results.json: %s", out)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["pdf", "labels", "scores", "review-pack", "record"])
    ap.add_argument("--n", type=int)
    a = ap.parse_args(argv)
    if a.cmd == "pdf":
        pdf_check(a.n or 30)
    elif a.cmd == "labels":
        labels(a.n or 30)
    elif a.cmd == "scores":
        scores(a.n or 10)
    elif a.cmd == "review-pack":
        review_pack(a.n or 30)
    else:
        record()


if __name__ == "__main__":
    main()
