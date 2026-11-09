"""Export the screener's tables to one JSON bundle for the static site (site/index.html).

Everything the site shows for the classified companies, plus the funnel, methods, calibration
and theme maps, read straight from data/parquet. Run after the scoring stages:

    python -m src.site.export        # writes site/data.json
    python -m src.site.build         # writes site/index.html (data inlined)
"""
from __future__ import annotations

import re

import json
import math

import polars as pl
import yaml

from src.common import REPO, get_logger, now_iso, parquet_exists, path, read_parquet

log = get_logger("site_export")
DOCS = REPO / "docs"
SITE = REPO / "site"


def _clean(v):
    if v is None:
        return None
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    if isinstance(v, (list, tuple)):
        return [_clean(x) for x in v]
    if isinstance(v, dict):
        return {k: _clean(x) for k, x in v.items()}
    if hasattr(v, "isoformat"):
        return v.isoformat()[:10]
    return v


def dicts(df):
    return [{k: _clean(x) for k, x in r.items()} for r in df.to_dicts()]


SMALL_WORDS = {"a", "an", "and", "as", "at", "by", "for", "from", "in", "of", "on", "or", "the", "to", "with"}


def _title(s: str) -> str:
    """Title case for labels: 'Founder-market fit' becomes 'Founder-Market Fit'; small words stay lower."""
    words = str(s).split(" ")
    out = []
    for i, w in enumerate(words):
        parts = w.split("-")
        out.append("-".join(p if (p.lower() in SMALL_WORDS and i > 0) else (p[:1].upper() + p[1:]) for p in parts))
    return " ".join(out)


FACT_FIXES = [(r"^FACT:\s*", ""), (r"\b1 executive officers\b", "1 executive officer"), (r"\b1 outside directors\b", "1 outside director"), (r"founder-led True", "founder-led"),
              (r"founder-led False", "not founder-led"), (r"founder-led None", "founder test not run"), (r"\bfrom 1 investors\b", "from 1 investor"), (r"\b1 equity rounds filed\b", "1 equity round filed"),
              (r"\(([\w -]+?) sized\)", r"(\1-sized)"), (r"pricing page True", "pricing page yes"), (r"pricing page False", "pricing page no"), (r"customer logos hint True", "customer logos yes"),
              (r"customer logos hint False", "customer logos no"), (r"public ATS (job )?board", "public job board"), (r"\bATS none\b", "job board none"), (r"\bapi docs\b", "API docs"), (r"\bgithub\b", "GitHub")]


def _fact_display(t: str) -> str:
    for a, b in FACT_FIXES:
        t = re.sub(a, b, t)
    return t


def doc(name):
    f = DOCS / name
    return json.loads(f.read_text()) if f.exists() else None


def main():
    cfg = yaml.safe_load((REPO / "config.yaml").read_text())
    rk = read_parquet("rankings")
    # Site scope: every classified target-vertical company (ranked or comparable) plus Greycroft seats.
    scope = rk.filter(pl.col("vertical").is_in(cfg["target"]["verticals"]) | pl.col("greycroft_board").fill_null(False) | pl.col("ranked"))
    scope = scope.sort(["ranked", "durability_score", "investability_score"], descending=[True, True, True], nulls_last=True)
    numbers = scope["company_number"].to_list()
    # Columns the page never reads (checked against the template); keeps the bundle under the 16 MB artifact limit.
    drop = {"rounds_json", "computed_at", "previous_names", "street1", "zip", "round_key", "inc_timespan", "fund_type",
            "is_option", "is_pooled_fund", "is_business_combination", "first_filing_date", "last_filing_date", "n_filings_in_round",
            "has_non_accredited", "age_at_round", "total_raised_filed", "first_sale_date", "age_years", "post_town", "n_executives",
            "executive_names", "n_directors", "n_investor_directors", "investor_director_names", "first_institutional_likely", "n_persons",
            "class_method", "n_unscored", "revenue_display", "homepage_url", "fit_all"}
    rankings = [{k: v for k, v in r.items() if k not in drop} for r in dicts(scope)]

    def group(table, cols=None, order=None, limit=None):
        if not parquet_exists(table):
            return {}
        df = read_parquet(table).filter(pl.col("company_number").is_in(numbers))
        if cols:
            df = df.select([c for c in cols if c in df.columns])
        out = {}
        for r in dicts(df):
            out.setdefault(r["company_number"], []).append(r)
        if limit:
            out = {k: v[:limit] for k, v in out.items()}
        return out

    scores = group("scores", ["company_number", "dimension", "score", "rationale", "evidence_quote", "evidence_url", "confidence", "status"])
    for k in scores:
        scores[k].sort(key=lambda x: x["dimension"])
        for x in scores[k]:  # the page restores dimension_name from config and status "scored" by default
            x.pop("company_number", None)
            if x.get("evidence_quote") and str(x["evidence_quote"]).startswith(("Form D", "last Form D", "FACT", "no public ATS", "website signals", "incorporated")) or "open roles on the public ATS board" in str(x.get("evidence_quote") or ""):
                x["evidence_quote"] = _fact_display(x["evidence_quote"])  # the screener's own fact lines, in plain wording
            if x.get("rationale"):  # model-written text follows the site style; quotes stay verbatim
                x["rationale"] = re.sub(r"\s*—\s*", ", ", x["rationale"])
            if x.get("status") == "scored":
                x.pop("status")
    why = group("why_now")
    for k in why:
        why[k].sort(key=lambda x: ({"approach": 0, "caution": 1}.get(x["direction"], 2), str(x.get("date") or "")))
    jobs = group("jobs", ["company_number", "title", "function", "location", "country_guess", "posted_at", "url"], limit=30)
    rev = {r["company_number"]: r for r in dicts(read_parquet("revenue_estimates").filter(pl.col("company_number").is_in(numbers)))} if parquet_exists("revenue_estimates") else {}
    web = {r["company_number"]: r for r in dicts(read_parquet("websites").filter(pl.col("company_number").is_in(numbers)).select(["company_number", "domain", "homepage_url", "discovery_method", "pages_fetched", "ats", "ats_token", "careers_url", "api_docs_url", "github_org", "integrations_count", "pricing_hint", "customer_logos_hint", "name_match", "site_verified"] if "site_verified" in read_parquet("websites").columns else ["company_number", "domain", "homepage_url", "discovery_method", "pages_fetched", "ats", "ats_token", "careers_url", "api_docs_url", "github_org", "integrations_count", "pricing_hint", "customer_logos_hint", "name_match"]))} if parquet_exists("websites") else {}
    # Form D history per company (every filing, with persons on the latest round).
    fil = read_parquet("formd_filings").filter(pl.col("cik").is_in(scope["cik"].to_list())).with_columns(pl.col("cik").alias("company_number"))
    filings = {}
    for r in dicts(fil.select(["company_number", "accession", "filing_date", "sale_date", "submission_type", "is_amendment", "total_offering", "total_sold", "n_investors", "revenue_range", "is_equity", "is_debt", "industry_group", "exemptions"]).sort("filing_date", descending=True)):
        filings.setdefault(r["company_number"], []).append(r)
    per = read_parquet("formd_persons").join(fil.select(["accession", "company_number", "filing_date"]), on="accession", how="inner")
    per = per.sort("filing_date", descending=True)
    persons = {}
    seen = set()
    for r in dicts(per.select(["company_number", "first_name", "last_name", "city", "state", "roles", "clarification", "filing_date"])):
        key = (r["company_number"], r["first_name"].lower(), r["last_name"].lower())
        if key in seen:
            continue
        seen.add(key)
        persons.setdefault(r["company_number"], []).append(r)
    companies = {}
    for r in rankings:
        n = r["company_number"]
        # ranking is re-attached by the page from D.rankings (saves ~4 MB in the bundle)
        companies[n] = {"ranking": None, "scores": scores.get(n, []), "why_now": why.get(n, []), "jobs": jobs.get(n, []), "revenue": rev.get(n, {}), "website": web.get(n, {}),
                        "filings": filings.get(n, []), "persons": persons.get(n, [])}

    themes = []
    if parquet_exists("themes"):
        t = read_parquet("themes").filter(pl.col("candidate"))
        t = t.join(rk.select(["company_number", "name", "city", "state", "vertical", "founder_led", "gate", "last_round_usd_m", "round_label", "durability_score", "ranked", "domain", "greycroft_board"]), on="company_number", how="left")
        themes = dicts(t.sort(["theme", "total_hits"], descending=[False, True]))

    s1, s2, s3 = doc("funnel_stage1.json") or {}, doc("funnel_stage2.json") or {}, doc("funnel_stage3.json") or {}
    cs = doc("classification_summary.json") or {}
    rs = doc("rankings_summary.json") or {}
    funnel = [
        ["Form D filings, 2024 Q1–2026 Q3", s1.get("filings", 0), "SEC Form D structured data sets: every Regulation D sale filed in 11 quarters"],
        ["Rounds", s2.get("rounds", 0), "A filing and its amendments count as one round; the largest amount sold is the round size"],
        ["Operating companies", s2.get("operating_company_rounds", 0), "Pooled investment funds and business combinations removed"],
        ["Equity rounds", s2.get("equity_rounds", 0), "Equity ticked in Item 9; debt and option rounds stay in the history"],
        ["US headquarters", s2.get("us", 0), "Issuer address in the 50 states, Washington, DC or Puerto Rico"],
        ["Companies on their latest round", s2.get("companies_us", s2.get("us", 0)), "One row per company on its most recent equity round; a company that has since raised past the range drops out below"],
        ["Five years old or less at the round", s2.get("within_five_years", 0), "Year of incorporation (Item 1) within five years of the sale"],
        ["Target industry groups", s2.get("target_industry_groups", 0), "Technology, health care, business services, consumer, financial services and climate; real estate, oil and gas, banking and biotech removed"],
        ["$1M–$50M latest round (the universe)", s2.get("companies", 0), "Total amount sold on the most recent equity round, amendments included"],
        ["Founder-led", s3.get("founder_led", 0), "An executive officer who is also a director or promoter on the filing; earlier investors allowed"],
        ["Founder-led with a website found", rk.filter(pl.col("founder_led") & pl.col("domain").is_not_null()).height, "Domain found by name search and the company name checked on the page; companies without a website stay on the Look Up page"],
        ["In the target verticals", rk.filter(pl.col("founder_led") & pl.col("vertical").is_in(cfg["target"]["verticals"])).height, "Classified by a language model from the company website, with a verbatim quote as evidence; sites with no target vocabulary are labeled other"],
        ["Ranked", rs.get("ranked", 0), f"Latest round $2M–$25M, $50M or less raised in total, recent filing, website verified, product company, platform score; {s3.get('greycroft_board', 0)} companies with a Greycroft board seat shown as comparables"],
    ]
    score_stats = []
    if parquet_exists("scores"):
        sc = read_parquet("scores")
        score_stats = dicts(sc.group_by(["dimension", "dimension_name"]).agg([pl.col("score").mean().round(2).alias("mean_score"), (pl.col("status") == "scored").sum().alias("scored"), (pl.col("status") != "scored").sum().alias("unscored"), (pl.col("confidence") == "high").sum().alias("high_conf")]).sort("dimension"))
    model_mix = {}
    if parquet_exists("scores"):
        m = read_parquet("scores")["model"].fill_null("").to_list()
        llm = [x for x in m if x and not x.startswith("rule:")]
        model_mix["subscores_by_model"] = len(llm)
        model_mix["subscores_batch_pct"] = round(100 * sum(1 for x in llm if x.startswith("batch")) / max(1, len(llm)), 1)
    if parquet_exists("classification"):
        m = read_parquet("classification")["model"].fill_null("").to_list()
        llm = [x for x in m if x and x != "None"]
        model_mix["labels_by_model"] = len(llm)
        model_mix["labels_batch_pct"] = round(100 * sum(1 for x in llm if x.startswith("batch")) / max(1, len(llm)), 1)
    why_stats = dicts(read_parquet("why_now").group_by(["signal", "direction"]).agg([pl.len().alias("n"), pl.col("company_number").n_unique().alias("companies")]).sort(["signal", "direction"])) if parquet_exists("why_now") else []
    index = [[r["company_number"], r["name"], r.get("city"), r.get("state"), r.get("last_round_usd_m"), r.get("round_label"), bool(r.get("founder_led")), r.get("vertical"), bool(r.get("ranked")), r.get("durability_score")] for r in dicts(rk.select(["company_number", "name", "city", "state", "last_round_usd_m", "round_label", "founder_led", "vertical", "ranked", "durability_score"]))]

    bundle = {
        "built_at": now_iso(),
        "index": index,
        "config": {"target": {k: v for k, v in cfg["target"].items() if k not in ("greycroft_people",)}, "rubric": {"weights": cfg["rubric"]["weights"], "dimension_names": {k: _title(v) for k, v in cfg["rubric"]["dimension_names"].items()}, "source_label": cfg["rubric"]["source_label"], "source_url": cfg["rubric"]["source_url"]},
                   "fit": {k: v for k, v in cfg["fit"].items() if k != "core_metros"}, "themes": {k: {"label": v["label"], "keywords": v["keywords"]} for k, v in cfg.get("themes", {}).get("list", {}).items()},
                   "build": {"as_of_date": cfg["build"]["as_of_date"], "formd_quarters": cfg["build"]["formd_quarters"]}},
        "rankings": rankings, "companies": companies, "themes": themes, "funnel": funnel, "score_stats": score_stats, "why_stats": why_stats,
        "docs": {k: doc(f) for k, f in [("gc_pattern", "gc_pattern.json"), ("gc_entries_formd", "gc_entries_formd.json"), ("rankings_summary", "rankings_summary.json"), ("classification_summary", "classification_summary.json"),
                                        ("qa", "qa_results.json"), ("usefulness", "usefulness.json"), ("backtests", "backtests.json"), ("benchmarks", "benchmarks.json"), ("aum", "research/aum.json"), ("ownership", "research/ownership.json"), ("backtest_pit", "backtest_pit.json"), ("top40_review", "qa/review2/top40_review.json")]} | {"model_mix": model_mix},
        "diligence_questions": ["Net new ARR by quarter since the last round, and the pipeline for the next two", "Who led the last round, what board seat they hold, and whether they have reserves for the next round",
                                "Gross margin after model and inference costs, and how it has moved as usage grew", "Logo and net revenue retention by cohort; share of customers who expanded",
                                "Shipping cadence: releases in the last 90 days and what is on the roadmap for the next 90", "How the product expands beyond the first customer type and the first wedge",
                                "Which parts of the product break if the underlying model provider changes", "Hiring plan to the next round and the senior commercial hires in it"],
    }
    SITE.mkdir(exist_ok=True)
    out = SITE / "data.json"
    out.write_text(json.dumps(bundle, default=str, separators=(",", ":")))
    log.info("wrote %s (%.1f MB): %d companies in scope, %d ranked, %d theme rows", out, out.stat().st_size / 1e6, len(companies), sum(1 for r in rankings if r.get("ranked")), len(themes))


if __name__ == "__main__":
    main()
