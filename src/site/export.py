"""Export the screener's tables to one JSON bundle for the static site (site/index.html).

Everything the site shows for the companies in scope (every company classified into one of the six
sectors, ranked or comparable), plus the funnel, methods, calibration and theme maps, read straight from
data/parquet and docs/. Run after the scoring stages:

    python -m src.site.export        # writes site/data.json
    python -m src.site.build         # writes site/index.html (data inlined)

Bundle (site/data.json):
  built_at, index, config, rankings, companies{n: {scores, why_now, jobs, website, accounts, psc, chain}},
  themes, funnel, score_stats, why_stats, docs{...}, diligence_questions
"""
from __future__ import annotations

import json
import math
import re

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
    words = str(s).split(" ")
    out = []
    for i, w in enumerate(words):
        parts = w.split("-")
        out.append("-".join(p if (p.lower() in SMALL_WORDS and i > 0) else (p[:1].upper() + p[1:]) for p in parts))
    return " ".join(out)


def _fact_display(t: str) -> str:
    t = re.sub(r"^FACT:\s*", "", t or "")
    return t


def doc(name):
    f = DOCS / name
    return json.loads(f.read_text()) if f.exists() else None


def main():
    cfg = yaml.safe_load((REPO / "config.yaml").read_text())
    rk = read_parquet("rankings")
    scope = rk.sort(["ranked", "durability_score", "fit_score"], descending=[True, True, True], nulls_last=True)
    numbers = scope["company_number"].to_list()
    drop = {"computed_at"}
    rankings = [{k: v for k, v in r.items() if k not in drop} for r in dicts(scope)]

    def group(table, cols=None, limit=None, key="company_number"):
        if not parquet_exists(table):
            return {}
        df = read_parquet(table).filter(pl.col(key).is_in(numbers))
        if cols:
            df = df.select([c for c in cols if c in df.columns])
        out = {}
        for r in dicts(df):
            out.setdefault(r[key], []).append(r)
        if limit:
            out = {k: v[:limit] for k, v in out.items()}
        return out

    scores = group("scores", ["company_number", "dimension", "score", "rationale", "evidence_quote", "evidence_url", "confidence", "status", "model"])
    for k in scores:
        scores[k].sort(key=lambda x: x["dimension"])
        for x in scores[k]:
            x.pop("company_number", None)
            if x.get("evidence_quote") and str(x["evidence_quote"]).startswith("FACT"):
                x["evidence_quote"] = _fact_display(x["evidence_quote"])
                x["fact"] = True
            if x.get("rationale"):
                x["rationale"] = re.sub(r"\s*—\s*", ", ", x["rationale"])
            if x.get("status") == "scored":
                x.pop("status")
            if x.get("model") and not str(x["model"]).startswith("rule:"):
                x.pop("model")
    why = group("why_now", ["company_number", "signal", "label", "date", "detail", "source", "direction"])
    for k in why:
        why[k].sort(key=lambda x: ({"approach": 0, "caution": 1}.get(x["direction"], 2), str(x.get("date") or "")))
    jobs = group("jobs", ["company_number", "title", "function", "location", "country_guess", "posted_at", "url"], limit=30)
    web = {}
    if parquet_exists("websites"):
        wdf = read_parquet("websites")
        wcols = [c for c in ("company_number", "domain", "homepage_url", "discovery_method", "pages_fetched", "ats", "careers_url", "name_match", "uk_signal") if c in wdf.columns]
        web = {r["company_number"]: r for r in dicts(wdf.filter(pl.col("company_number").is_in(numbers)).select(wcols))}
    # accounts history: every period on file, consolidated preferred, newest first
    accounts = {}
    if parquet_exists("accounts_wide"):
        aw = read_parquet("accounts_wide").filter(pl.col("company_number").is_in(numbers))
        acols = [c for c in ("company_number", "period_end", "comparative", "consolidated", "employees", "turnover", "gross_profit", "operating_profit", "pbt", "profit",
                             "depreciation", "amortisation", "net_assets", "cash", "bank_borrowings", "creditors_within_one_year", "creditors_after_one_year", "dividends",
                             "net_cash_from_ops", "accounts_type", "ebitda_stated") if c in aw.columns]
        aw = aw.select(acols).with_columns(pl.when(pl.col("employees") > 50000).then(pl.col("employees") / 1000).otherwise(pl.col("employees")).alias("employees"))
        aw = aw.sort(["company_number", "period_end", "consolidated"], descending=[False, True, True]).unique(subset=["company_number", "period_end"], keep="first")
        for r in dicts(aw.sort(["company_number", "period_end"], descending=[False, True])):
            accounts.setdefault(r.pop("company_number"), []).append(r)
    # PSC register rows for the company itself (active and ceased, with dates) and the chain companies
    psc = {}
    chain_numbers = set()
    for r in rankings:
        for hop in (r.get("walkup_path") or "").split("; "):
            if " -> " in hop:
                chain_numbers.add(hop.split(" -> ")[1])
    if parquet_exists("psc"):
        pdf = read_parquet("psc").filter(pl.col("company_number").is_in(numbers)).select(["company_number", "kind", "name", "natures_of_control", "notified_on", "ceased_on", "is_active",
                                                                                                "corporate_reg_number", "country_registered", "legal_form", "nationality", "country_of_residence", "dob_year", "statement"])
        for r in dicts(pdf.sort(["company_number", "is_active", "notified_on"], descending=[False, True, True])):
            n = r.pop("company_number")
            r["natures_of_control"] = [str(x).replace("ownership-of-shares-", "shares ").replace("voting-rights-", "votes ").replace("-percent", "%").replace("-", " ") for x in (r.get("natures_of_control") or [])]
            psc.setdefault(n, []).append(r)
    chain = {}
    if chain_numbers and parquet_exists("companies"):
        cdf = read_parquet("companies").filter(pl.col("company_number").is_in(list(chain_numbers))).select(["company_number", "name", "inc_date", "account_category", "status", "category"])
        chain = {r["company_number"]: r for r in dicts(cdf)}
    companies = {}
    for r in rankings:
        n = r["company_number"]
        companies[n] = {"scores": scores.get(n, []), "why_now": why.get(n, []), "jobs": jobs.get(n, []), "website": web.get(n, {}),
                        "accounts": accounts.get(n, []), "psc": psc.get(n, [])}

    themes = []
    if parquet_exists("themes"):
        t = read_parquet("themes").filter(pl.col("candidate"))
        t = t.join(rk.select(["company_number", "name", "post_town", "vertical", "route", "latest_turnover", "ebitda_proxy", "durability_score", "ranked", "domain"]), on="company_number", how="left")
        themes = dicts(t.sort(["theme", "total_hits"], descending=[False, True]))

    fc, s2, s3 = doc("funnel_counts.json") or {}, doc("funnel_stage2.json") or {}, doc("funnel_stage3.json") or {}
    f2 = s2.get("funnel", {})
    rs = doc("rankings_summary.json") or {}
    cs = doc("classification_summary.json") or {}
    route_counts = s3.get("route", {})
    actionable = sum(route_counts.get(k, 0) for k in ("founder_family", "sponsor", "sponsor_offshore", "plc_dispersed", "employee_owned"))
    funnel = [
        ["Companies on the register", fc.get("companies_total", 0), "Companies House basic company data, 1 November 2026 snapshot"],
        ["Active", fc.get("companies_active", 0), "Company status Active"],
        ["Last accounts FULL, GROUP or MEDIUM", fc.get("active_candidates", 0), "Small, micro, dormant and abridged filers cannot be at the fund's scale and are not read"],
        ["Share-capital companies in operating SIC codes", f2.get("passes_legal_form_and_sic", 0), "Guarantee companies, CICs, overseas branches, banks, insurers' carriers, pension funds, public bodies and household codes removed"],
        ["Accounts parsed (iXBRL bulk plus document API)", f2.get("with_parsed_accounts", 0), "Twelve months of Companies House iXBRL bulk data, then the document API for PDF filers, read by OCR and a model"],
        ["Universe: at or above the size floor, or size unverified", f2.get("passes_all", 0), f"Head count {cfg['target']['universe_employees_min']}+ or turnover £{cfg['target']['universe_turnover_min_gbp'] / 1e6:.0f}M+ on the latest accounts; FULL and GROUP filers with no parsed accounts yet are carried as size-unverified"],
        ["Ownership route a buyout fund can act on", actionable, "Founder or family, sponsor-owned, widely held PLC or employee-owned, read from the PSC register; foreign and UK group subsidiaries kept as carve-out comparables"],
        ["Group heads", s3.get("group_heads", 0), "Acquisition vehicles and subsidiaries collapse onto the top UK company that files group accounts"],
        ["In the six sectors", sum(v for k, v in (cs.get("vertical_counts") or {}).items() if k in cfg["target"]["sectors"]), "Classified by a language model from the company website, with a verbatim quote as evidence"],
        ["Ranked", rs.get("ranked", 0), f"Size verified at scale, website found, fit {rs.get('rank_min_fit', 40)} or more, scored on the rubric; the rest stay as comparables"],
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
        model_mix["subscores_rule_pct"] = round(100 * sum(1 for x in m if x.startswith("rule:")) / max(1, len(m)), 1)
    if parquet_exists("classification"):
        m = read_parquet("classification")["model"].fill_null("").to_list()
        model_mix["labels_by_model"] = len([x for x in m if x and x != "None"])
    why_stats = dicts(read_parquet("why_now").group_by(["signal", "direction"]).agg([pl.len().alias("n"), pl.col("company_number").n_unique().alias("companies")]).sort(["signal", "direction"])) if parquet_exists("why_now") else []
    # Look-up index: every universe company, so a name can be checked even when it never reached the scope
    uni = read_parquet("universe").select(["company_number", "name", "post_town", "route", "latest_turnover", "latest_employees", "ebitda_proxy", "provisional", "account_category", "exclusion_reason"])
    in_scope = set(numbers)
    index = [[r["company_number"], r["name"], r.get("post_town"), r.get("route"), r.get("latest_turnover"), r.get("latest_employees"), r.get("ebitda_proxy"), bool(r.get("provisional")), r["company_number"] in in_scope, r.get("exclusion_reason")]
             for r in dicts(uni)]

    bundle = {
        "built_at": now_iso(),
        "index": index,
        "config": {"target": cfg["target"], "rubric": {"weights": cfg["rubric"]["weights"], "dimension_names": {k: _title(v) for k, v in cfg["rubric"]["dimension_names"].items()}, "source_label": cfg["rubric"]["source_label"], "source_url": cfg["rubric"]["source_url"]},
                   "fit": cfg["fit"], "themes": {k: {"label": v["label"], "keywords": v["keywords"]} for k, v in cfg.get("themes", {}).get("list", {}).items()},
                   "build": {"as_of_date": cfg["build"]["as_of_date"], "snapshot_basic": cfg["build"]["snapshot_basic"], "snapshot_psc_date": cfg["build"]["snapshot_psc_date"], "accounts_months": cfg["build"]["accounts_monthly"]}},
        "rankings": rankings, "companies": companies, "chain": chain, "themes": themes, "funnel": funnel, "score_stats": score_stats, "why_stats": why_stats,
        "docs": {k: doc(f) for k, f in [("cv_pattern", "cv_pattern.json"), ("rankings_summary", "rankings_summary.json"), ("classification_summary", "classification_summary.json"),
                                        ("funnel_stage3", "funnel_stage3.json"), ("qa", "qa_results.json"), ("usefulness", "usefulness.json"), ("backtests", "backtests.json"),
                                        ("accounts_coverage", "accounts_coverage.json")]} | {"model_mix": model_mix},
        "diligence_questions": ["Revenue and EBITDA by segment and geography for the last three years, with the bridge from reported to adjusted EBITDA",
                                "Customer concentration: top ten customers' share of revenue and contract terms, and churn or renewal rates",
                                "Shareholder intentions: who owns what through the chain, any shareholder agreement, and the owners' timing",
                                "Management depth below the owner or sponsor appointee, and incentive arrangements in place",
                                "Acquisitions made in the last five years, integration status and the pipeline of targets",
                                "Debt facilities, covenants and maturities; pension scheme position; any contingent liabilities in the notes",
                                "Capex and working-capital needs against the cash conversion the accounts show",
                                "Regulatory position: licences, accreditations and any investigations or disputes disclosed"],
    }
    SITE.mkdir(exist_ok=True)
    out = SITE / "data.json"
    out.write_text(json.dumps(bundle, default=str, separators=(",", ":")))
    log.info("wrote %s (%.1f MB): %d companies in scope, %d ranked, %d theme rows, %d index rows", out, out.stat().st_size / 1e6, len(companies), sum(1 for r in rankings if r.get("ranked")), len(themes), len(index))


if __name__ == "__main__":
    main()
