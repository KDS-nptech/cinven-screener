"""Usefulness, measured: the numbers a sceptical reader asks for.

- evidence coverage: share of rubric sub-scores that carry a verbatim quote, and the confidence mix
- discovery uplift proxy: share of ranked companies with no funding announcement found (press names
  in the fetched site text or the LLM evidence); Form D is the only public record of their round
- completeness per stage: how many companies cleared each gate, and the honest gaps
- precision before review: filled in from overrides.yaml once the top of the list is hand-checked

    python -m src.usefulness   -> docs/usefulness.json
"""
from __future__ import annotations

import json
import re
import sys

import polars as pl
import yaml

from src.common import cfg, REPO, get_logger, now_iso, parquet_exists, path, read_parquet

log = get_logger("usefulness")
PRESS_RE = re.compile(r"\b(techcrunch|press release|announced (?:a|our|its) (?:\$|seed|series)|raises? \$|funding round|led by [A-Z][\w ]+ (?:Ventures|Capital|Partners)|businesswire|prnewswire)\b", re.I)


def main(argv=None):
    out = {"computed_at": now_iso()}
    if parquet_exists("scores"):
        sc = read_parquet("scores")
        scored = sc.filter(pl.col("status") == "scored")
        withq = scored.filter(pl.col("evidence_quote").is_not_null() & (pl.col("evidence_quote") != "FACT: no evidence found"))
        webq = withq.filter(~pl.col("evidence_quote").str.starts_with("FACT:"))  # a quote from the company's own pages, as opposed to a filing or job-board fact line
        out["evidence_coverage"] = {"subscores_scored": scored.height, "with_verbatim_quote": withq.height, "quote_pct": round(100 * withq.height / scored.height, 1) if scored.height else None,
                                    "with_website_quote": webq.height, "website_quote_pct": round(100 * webq.height / scored.height, 1) if scored.height else None,
                                    "with_fact_line": withq.height - webq.height, "fact_line_pct": round(100 * (withq.height - webq.height) / scored.height, 1) if scored.height else None,
                                    "high_confidence_pct": round(100 * scored.filter(pl.col("confidence") == "high").height / scored.height, 1) if scored.height else None,
                                    "no_evidence_fallback_pct": round(100 * (scored.height - withq.height) / scored.height, 1) if scored.height else None,
                                    "companies_scored": sc["company_number"].n_unique(), "unscored_dimensions": sc.filter(pl.col("status") != "scored").height}
    if parquet_exists("rankings"):
        rk = read_parquet("rankings")
        ranked = rk.filter(pl.col("ranked"))
        n_press = 0
        for n in ranked["company_number"].to_list():
            f = path("cache") / "web" / f"{n}.json"
            try:
                txt = " ".join((p.get("text") or "") for p in json.loads(f.read_text()).get("pages", [])) if f.exists() else ""
            except json.JSONDecodeError:
                txt = ""
            if PRESS_RE.search(txt):
                n_press += 1
        out["discovery_uplift_proxy"] = {"ranked": ranked.height, "press_language_on_site": n_press, "no_press_on_site": ranked.height - n_press,
                                         "no_press_pct": round(100 * (ranked.height - n_press) / ranked.height, 1) if ranked.height else None,
                                         "note": "Companies whose own fetched pages never mention a raise, a lead investor or a press release. A proxy for how many rounds a news-driven database would miss; it is not a check against a news source."}
        out["completeness"] = {"universe": rk.height if False else int(read_parquet("universe").height), "founder_led": int(rk["founder_led"].fill_null(False).sum()),
                               "with_domain": int(rk["domain"].is_not_null().sum()),
                               "classified_target_vertical": int(rk["vertical"].is_in(cfg()["target"]["verticals"]).sum()) if "vertical" in rk.columns else None,
                               "rubric_scored": int(rk["durability_score"].is_not_null().sum()), "ranked": ranked.height,
                               "revenue_tier_a": int((rk["tier"] == "A").sum()) if "tier" in rk.columns else None, "with_ats_board": int(rk["open_roles"].is_not_null().sum())}
        if parquet_exists("websites"):
            w = read_parquet("websites")
            out["completeness"]["universe_with_domain"] = int(w["domain"].is_not_null().sum())
            out["completeness"]["universe_with_domain_pct"] = round(100 * int(w["domain"].is_not_null().sum()) / w.height, 1)
    ov = REPO / "overrides.yaml"
    if ov.exists():
        o = yaml.safe_load(ov.read_text()) or {}
        comp = o.get("companies") or {}
        reviewed = o.get("top30_reviewed", 0)
        # only the corrections made during the top-30 hand review count against its precision;
        # the wrong-website control and the second scorers work the whole list
        top = {k: v for k, v in comp.items() if "top-30 hand review" in (v.get("note") or "").lower() and "second pass" not in (v.get("note") or "").lower()}
        excluded = sum(1 for v in top.values() if v.get("exclude"))
        relabel = sum(1 for v in top.values() if v.get("vertical"))
        if reviewed:
            out["precision_before_review"] = {"top30": {"reviewed": reviewed, "excluded": excluded, "relabelled": relabel, "kept": reviewed - excluded - relabel,
                                                        "precision_pct": round(100 * (reviewed - excluded - relabel) / reviewed, 1)}, "overrides": len(comp)}
    f = REPO / "docs" / "qa" / "independent_review.json"
    if f.exists():
        ir = json.loads(f.read_text())
        ir["credible_pct"] = round(100 * ir["credible"] / ir["n"], 1) if ir.get("n") else None
        out["independent_review"] = ir
    (REPO / "docs" / "usefulness.json").write_text(json.dumps(out, indent=1, default=str))
    log.info("%s", json.dumps(out)[:600])


if __name__ == "__main__":
    main(sys.argv[1:])
