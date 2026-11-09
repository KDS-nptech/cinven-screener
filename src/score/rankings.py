"""Stage 10: investability score (deterministic) and the ranked list.

Components (config.investability): founder ownership is a gate; size 0-30 on the p50
revenue estimate inside the target band; growth 0-25 on headcount CAGR; hiring intensity
0-15; leverage 0-15; data quality 0-15. Durability and investability are never blended.

Inputs: universe, classification, durability, revenue_estimates, accounts_wide, charges,
jobs_summary, websites, why_now_summary (timing signals, carried through, never scored). Output: rankings.parquet (every classified target-vertical company,
ranked or shown as comparable).

Run: python -m src.score.rankings
"""
from __future__ import annotations

import datetime as dt
import json
import sys

import polars as pl

from src.common import REPO, cfg, get_logger, now_iso, parquet_exists, read_parquet, write_parquet

log = get_logger("rankings")
INV = cfg()["investability"]
TGT = cfg()["target"]
RANK_MIN_STAFF = int(TGT.get("rank_employees_min", TGT.get("employees_min", 0)))


def size_points(p50) -> float:
    if p50 is None:
        return 0.0
    lo, hi, f = TGT["revenue_target_min_gbp"], TGT["revenue_target_max_gbp"], INV["size_falloff_factor"]
    if lo <= p50 <= hi:
        return INV["size_points"]
    if p50 < lo:
        floor = lo / f
        return INV["size_points"] * max(0.0, (p50 - floor) / (lo - floor))
    ceil = hi * f
    return INV["size_points"] * max(0.0, (ceil - p50) / (ceil - hi))


def growth_points(cagr) -> float:
    if cagr is None:
        return INV["growth_points"] * 0.4   # unknown: partial credit, flagged
    return INV["growth_points"] * min(1.0, max(0.0, cagr / INV["growth_full_cagr"]))


def hiring_points(open_roles, employees) -> float:
    if not employees or open_roles is None:
        return 0.0
    share = open_roles / employees
    return INV["hiring_points"] * min(1.0, share / INV["hiring_full_share"])


def leverage_points(charges: list[dict], cutoff: str) -> tuple[float, list[str]]:
    flags = []
    outstanding = [c for c in charges if not c.get("satisfied_on") and not (c.get("status") or "").lower().startswith("fully-satisfied")]
    if not outstanding:
        return INV["leverage_points"], flags
    recent = [c for c in outstanding if c.get("created_on") and str(c["created_on"])[:10] >= cutoff]
    if recent:
        flags.append("recent_charge")
        return 0.0, flags
    flags.append("charges_outstanding")
    return INV["leverage_points"] * 0.5, flags


def headcount_cagr(history: list[dict]) -> float | None:
    pts = [(dt.date.fromisoformat(str(h["period_end"])[:10]), float(h["employees"])) for h in history if h.get("employees")]
    pts = sorted(pts)[-3:]
    if len(pts) < 2 or pts[0][1] <= 0:
        return None
    years = (pts[-1][0] - pts[0][0]).days / 365.25
    if years < 0.5:
        return None
    return (pts[-1][1] / pts[0][1]) ** (1 / years) - 1


def load_bands() -> dict[str, dict]:
    """Measured entry-headcount bands from docs/bp_pattern.json (python -m src.bp_pattern), per cohort."""
    f = REPO / "docs" / "bp_pattern.json"
    if not f.exists():
        return {}
    d = json.loads(f.read_text())
    return {k: c["headcount_band"] for k, c in d.get("cohorts", {}).items() if c.get("headcount_band")}


def headcount_fit(staff, band: dict | None) -> str:
    """core: inside the p25 to p75 of the fund's entry headcounts; early: below that but not below the
    smallest entry; below: smaller than anything the fund has entered; upper/above: beyond p75 / the max."""
    if not band or staff is None:
        return "unknown"
    if staff < band["min"]:
        return "below"
    if staff < band["core_lo"]:
        return "early"
    if staff <= band["core_hi"]:
        return "core"
    if staff <= band["max"]:
        return "upper"
    return "above"


def main(argv=None):
    bands = load_bands()
    cls = read_parquet("classification").filter(pl.col("vertical").is_in(TGT["verticals"]))
    uni = read_parquet("universe")
    df = cls.select(["company_number", "vertical", "sub_vertical", "confidence", "evidence_quote", "evidence_url", "is_software_product"]) \
            .rename({"confidence": "vertical_confidence"}).join(uni, on="company_number", how="inner")
    dur = read_parquet("durability") if parquet_exists("durability") else pl.DataFrame({"company_number": [], "durability_score": [], "grey": [], "n_unscored": []})
    df = df.join(dur.select(["company_number", "durability_score", "grey", "n_unscored"]), on="company_number", how="left")
    rev = read_parquet("revenue_estimates") if parquet_exists("revenue_estimates") else None
    if rev is not None:
        df = df.join(rev.select(["company_number", "tier", "p10", "p50", "p90", "period_end", "display", "extrapolated"]).rename({"period_end": "revenue_period_end", "display": "revenue_display"}), on="company_number", how="left")
    else:
        df = df.with_columns([pl.lit(None).alias(c) for c in ["tier", "p10", "p50", "p90", "revenue_period_end", "revenue_display", "extrapolated"]])
    wcols = ["company_number", "domain", "discovery_method"] + [c for c in ("site_verified", "site_verify_source") if parquet_exists("websites") and c in read_parquet("websites").columns]
    web = read_parquet("websites").select(wcols).unique(subset=["company_number"]) if parquet_exists("websites") else pl.DataFrame({"company_number": [], "domain": [], "discovery_method": []})
    df = df.join(web, on="company_number", how="left")
    wn = read_parquet("why_now_summary").select(["company_number", "why_now_signals", "why_now_approach", "why_now_caution", "why_now_line"]) if parquet_exists("why_now_summary") \
        else pl.DataFrame({"company_number": [], "why_now_signals": [], "why_now_approach": [], "why_now_caution": [], "why_now_line": []})
    df = df.join(wn, on="company_number", how="left")
    from src.common import name_tokens
    jobs = read_parquet("jobs_summary") if parquet_exists("jobs_summary") else None
    jobs_by = {r["company_number"]: r for r in jobs.to_dicts()} if jobs is not None else {}
    charges_by = {}
    if parquet_exists("charges"):
        for n, g in read_parquet("charges").group_by("company_number"):
            charges_by[n[0] if isinstance(n, tuple) else n] = g.to_dicts()
    hist_by = {}
    aw = read_parquet("accounts_wide").filter(pl.col("company_number").is_in(df["company_number"].to_list()))
    # prior-year comparatives inside a filing are real headcount figures; keep them for the trend
    for n, g in aw.sort("period_end").group_by("company_number"):
        hist_by[n[0] if isinstance(n, tuple) else n] = g.to_dicts()
    cutoff = (dt.date.fromisoformat(cfg()["build"]["as_of_date"]) - dt.timedelta(days=int(30.44 * INV["leverage_recent_charge_months"]))).isoformat()

    out = []
    for r in df.to_dicts():
        n = r["company_number"]
        flags = list(r.get("flags") or [])
        # Gate: founder-led (founder-owned, or an individual at 25%+ passing the director test with prior capital
        # on the register), size verified, and inside the staff band the fund actually enters at.
        founder_owned = r.get("founder_flag") == "founder" and r.get("founder_confidence") in ("high", "medium")
        led_src = r.get("founder_led")
        founder_led = bool(led_src) if led_src is not None else (founder_owned or (
            (r.get("n_individual_pscs") or 0) >= 1 and (r.get("combined_pct_mid") or 0) >= 25
            and not any(f in (r.get("flags") or []) for f in ("director_test_failed", "director_test_unavailable"))))
        in_band = r.get("latest_employees") is not None and r.get("latest_employees") >= RANK_MIN_STAFF
        manual_exclusion = r.get("exclusion_reason") == "manual"      # reviewer decision (overrides.yaml) always wins
        gate = founder_led and not manual_exclusion and not r.get("provisional") and in_band   # size unverified stays a comparable
        if founder_led and not in_band and r.get("latest_employees") is not None:
            flags.append("below_staff_band")
        cagr = headcount_cagr(hist_by.get(n, []))
        j = jobs_by.get(n) or {}
        lev, lev_flags = leverage_points(charges_by.get(n, []), cutoff)
        flags += lev_flags
        if cagr is None:
            flags.append("growth_unknown")
        dq = 0
        if r.get("tier") in ("A", "A-rolled", "A-derived", "A-ocr"):
            dq += 5
        if r.get("domain"):
            dq += 5
        if r.get("founder_confidence") == "high":
            dq += 5
        comp = {"size": round(size_points(r.get("p50")), 1), "growth": round(growth_points(cagr), 1),
                "hiring": round(hiring_points(j.get("open_roles"), r.get("latest_employees")), 1), "leverage": round(lev, 1), "data_quality": dq}
        inv = round(sum(comp.values()), 1)
        if r.get("grey"):
            flags.append("durability_grey")
        if r.get("extrapolated"):
            flags.append("revenue_extrapolated")
        if r.get("is_software_product") is False:
            flags.append("services_heavy")
        if r.get("provisional"):
            flags.append("size_unverified")
        # Fit to the fund's cheque size: core = p50 inside the calibrated band; early = below the floor but
        # above the hard minimum (watch list, or a buyout structure); large = above the band.
        p50 = r.get("p50")
        if p50 is None:
            fit = "unknown"
        elif p50 < TGT.get("revenue_early_floor_gbp", 0):
            fit = "too small"
        elif p50 < TGT["revenue_target_min_gbp"]:
            fit = "early"
        elif p50 <= TGT["revenue_target_max_gbp"]:
            fit = "core"
        else:
            fit = "large"
        # A one-word name matched by a domain probe to a site that never mentions the company number,
        # postcode or town is the classic wrong-site case (Clarity, Vitesse, Symmetry): kept as a comparable.
        single_token = len([t for t in name_tokens(r.get("name") or "") if len(t) >= 3]) <= 1
        if r.get("domain") and r.get("site_verified") is False and (single_token and (r.get("discovery_method") or "").startswith("domain_probe")):
            flags.append("website_unverified")
            gate = False
        elif r.get("domain") and r.get("site_verified") is False:
            flags.append("site_not_verified")
        out.append({**{k: r.get(k) for k in ["company_number", "name", "post_town", "postcode", "sic1", "inc_date", "vertical", "sub_vertical",
                                                 "vertical_confidence", "evidence_quote", "evidence_url", "founder_flag", "founder_confidence",
                                                 "exclusion_reason", "investor_flag", "latest_employees", "latest_period_end", "provisional", "durability_score",
                                                 "grey", "n_unscored", "tier", "p10", "p50", "p90", "revenue_period_end", "revenue_display", "domain", "site_verified", "site_verify_source"]},
                    "ranked": gate, "founder_led": bool(founder_led), "gate": ("founder-owned" if founder_owned else ("founder-led, prior capital" if founder_led else "not founder-led")), "size_fit": fit, "fit_all": headcount_fit(r.get("latest_employees"), bands.get("all")), "fit_uk": headcount_fit(r.get("latest_employees"), bands.get("uk")),
                    "investability_score": inv, "investability_components_json": json.dumps(comp), "headcount_cagr": round(cagr, 3) if cagr is not None else None,
                    "open_roles": j.get("open_roles"), "engineering_share": j.get("engineering_share"), "ai_roles": j.get("ai_roles"),
                    "why_now_signals": r.get("why_now_signals"), "why_now_approach": r.get("why_now_approach"), "why_now_caution": r.get("why_now_caution"), "why_now_line": r.get("why_now_line"),
                    "flags": sorted(set(flags)), "computed_at": now_iso()})
    res = pl.DataFrame(out, infer_schema_length=None)
    ranked = res.filter(pl.col("ranked")).sort(["durability_score", "investability_score"], descending=[True, True], nulls_last=True) \
                .with_row_index("rank", offset=1)
    comparables = res.filter(~pl.col("ranked")).with_columns(pl.lit(None, dtype=pl.UInt32).alias("rank"))
    res = pl.concat([ranked, comparables.select(ranked.columns)])
    write_parquet(res, "rankings")
    summary = {"computed_at": now_iso(), "rows": res.height, "ranked": int(ranked.height), "comparables": int(comparables.height),
               "by_vertical_ranked": {k: int(v) for k, v in zip(*[c.to_list() for c in ranked.group_by("vertical").len().sort("vertical")])} if ranked.height else {},
               "tier_counts_ranked": {str(k): int(v) for k, v in zip(*[c.to_list() for c in ranked.group_by("tier").len().sort("tier")])} if ranked.height else {},
               "size_fit_ranked": {str(k): int(v) for k, v in zip(*[c.to_list() for c in ranked.group_by("size_fit").len().sort("size_fit")])} if ranked.height else {},
               "fit_all_ranked": {str(k): int(v) for k, v in zip(*[c.to_list() for c in ranked.group_by("fit_all").len().sort("fit_all")])} if ranked.height else {},
               "fit_uk_ranked": {str(k): int(v) for k, v in zip(*[c.to_list() for c in ranked.group_by("fit_uk").len().sort("fit_uk")])} if ranked.height else {},
               "headcount_bands": bands,
               "founder_led_in_band_all": int(res.filter(pl.col("founder_led") & pl.col("fit_all").is_in(["core", "early", "upper"])).height),
               "founder_led_in_band_uk": int(res.filter(pl.col("founder_led") & pl.col("fit_uk").is_in(["core", "early", "upper"])).height),
               "founder_led_not_ranked": int(res.filter(pl.col("founder_led") & ~pl.col("ranked")).height),
               "gate_ranked": {str(k): int(v) for k, v in zip(*[c.to_list() for c in ranked.group_by("gate").len().sort("gate")])} if ranked.height else {},
               "rank_employees_min": RANK_MIN_STAFF}
    (REPO / "docs" / "rankings_summary.json").write_text(json.dumps(summary, indent=2))
    log.info("done: %s", summary)


if __name__ == "__main__":
    main(sys.argv[1:])
