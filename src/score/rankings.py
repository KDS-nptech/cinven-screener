"""Stage 10: entry fit (deterministic) and the ranked list.

Entry fit (config.fit, 0 to 100): size 30 (EBITDA proxy inside the measured core band, turnover as the
fallback), ownership route 25 (founder or family primary, sponsor secondary rising with hold years, PLC
dispersed for a take-private, carve-out routes lower), growth 15, margin 10, sector 10 (gate), data quality
10. The rubric score and the fit are never blended: the ranked list is sorted on the rubric score and the fit
gates it and breaks ties.

Gates for the ranked list: classified into one of the six sectors, operating business, group head, route in
the actionable set, size verified (not provisional) and at scale (EBITDA proxy at or above the early floor or
turnover at or above the ranking floor), website found, fit at or above config.fit.rank_min_fit, no manual
exclusion in overrides.yaml. Everything else classified into the six sectors stays as a comparable.

Inputs: universe, classification, durability, websites, jobs_summary, why_now_summary, overrides.yaml.
Output: rankings.parquet, docs/rankings_summary.json

Run: python -m src.score.rankings
"""
from __future__ import annotations

import datetime as dt
import json
import sys

import polars as pl
import yaml

from src.common import REPO, cfg, get_logger, name_tokens, now_iso, parquet_exists, read_parquet, write_parquet

log = get_logger("rankings")
FIT = cfg()["fit"]
TGT = cfg()["target"]
SECTORS = set(TGT["sectors"])
ROUTES = set(cfg()["classifier"].get("rank_routes") or cfg()["classifier"].get("routes", []))


def band_points(value, lo, hi, points) -> float:
    if value is None:
        return 0.0
    f = FIT["size_falloff_factor"]
    if lo <= value <= hi:
        return float(points)
    if value < lo:
        floor = lo / f
        return points * max(0.0, (value - floor) / (lo - floor))
    ceil = hi * f
    return points * max(0.0, (ceil - value) / (ceil - hi))


def size_points(ebitda, turnover) -> tuple[float, str]:
    if ebitda is not None and ebitda > 0:
        return round(band_points(ebitda, FIT["ebitda_core_min_gbp"], FIT["ebitda_core_max_gbp"], FIT["size_points"]), 1), "ebitda"
    if turnover is not None:
        return round(band_points(turnover, FIT["turnover_core_min_gbp"], FIT["turnover_core_max_gbp"], FIT["size_points"]), 1), "turnover"
    return 0.0, "unknown"


def route_points(route, hold_years) -> float:
    base = float(FIT["route_scores"].get(route or "uncertain", 0))
    if route in ("sponsor", "sponsor_offshore"):
        if hold_years is None:
            return round(base * 0.6, 1)
        lo, full = FIT["sponsor_hold_min_years"], FIT["sponsor_hold_full_years"]
        if hold_years >= full:
            return base
        if hold_years <= lo:
            return round(base * 0.25, 1)
        return round(base * (0.25 + 0.75 * (hold_years - lo) / (full - lo)), 1)
    return base


def growth_points(g) -> float:
    if g is None:
        return round(FIT["growth_points"] * 0.4, 1)   # unknown: partial credit, flagged
    return round(FIT["growth_points"] * min(1.0, max(0.0, g / FIT["growth_full"])), 1)


def margin_points(m) -> float:
    if m is None:
        return round(FIT["margin_points"] * 0.4, 1)
    return round(FIT["margin_points"] * min(1.0, max(0.0, m / FIT["margin_full"])), 1)


def size_fit_label(ebitda, turnover) -> str:
    """Which measured band the company sits in: Strategic Fund (EBITDA GBP 8M to 40M), flagship (GBP 40M to 300M)."""
    if ebitda is None and turnover is None:
        return "unknown"
    if ebitda is not None and ebitda > 0:
        if ebitda < TGT["ebitda_early_floor_gbp"]:
            return "too small"
        if ebitda < TGT["ebitda_target_min_gbp"]:
            return "strategic fund band"
        if ebitda <= TGT["ebitda_target_max_gbp"]:
            return "flagship band"
        return "mega-cap"
    if ebitda is not None and ebitda <= 0:
        return "loss-making" if (turnover or 0) < TGT["rank_turnover_min_gbp"] else "loss-making (turnover at scale)"
    if turnover < TGT["rank_turnover_min_gbp"]:
        return "too small (turnover only)"
    if turnover < 300e6:
        return "strategic fund band (turnover only)"
    if turnover <= FIT["turnover_core_max_gbp"]:
        return "flagship band (turnover only)"
    return "mega-cap (turnover only)"


CORRECTIONS: dict = {}


def load_overrides() -> tuple[set[str], dict[str, str]]:
    f = REPO / "overrides.yaml"
    if not f.exists():
        return set(), {}
    o = yaml.safe_load(f.read_text()) or {}
    excl = set()
    notes = {}
    for item in o.get("exclude", []) or []:
        if isinstance(item, dict):
            excl.add(str(item.get("company_number")))
            notes[str(item.get("company_number"))] = str(item.get("reason") or "")
        else:
            excl.add(str(item))
    global CORRECTIONS
    CORRECTIONS = {str(k): v for k, v in (o.get("corrections") or {}).items()}
    return excl, notes


def main(argv=None):
    uni = read_parquet("universe")
    cls = read_parquet("classification")
    dur = read_parquet("durability") if parquet_exists("durability") else pl.DataFrame({"company_number": [], "durability_score": [], "grey": [], "n_unscored": []})
    web = read_parquet("websites").select([c for c in ("company_number", "domain", "homepage_url", "name_match", "site_verified", "discovery_method", "pages_fetched") if c in read_parquet("websites").columns]).unique(subset=["company_number"]) if parquet_exists("websites") else None
    jobs = read_parquet("jobs_summary") if parquet_exists("jobs_summary") else None
    why = read_parquet("why_now_summary") if parquet_exists("why_now_summary") else None
    excl, excl_notes = load_overrides()
    # Part of a larger group: the first hop of the walk-up names the immediate UK parent; when that parent
    # controls two or more universe companies, each one is a unit of a group and the group is the target.
    # The largest of them (by turnover, then EBITDA proxy) represents the group and can rank; the others
    # are comparables that point to it.
    hops = read_parquet("universe").select(["company_number", "name", "walkup_path", "latest_turnover", "ebitda_proxy"]).to_dicts()
    parent_of, size_of, uname = {}, {}, {}
    for h in hops:
        uname[h["company_number"]] = h["name"]
        size_of[h["company_number"]] = (h.get("latest_turnover") or 0, h.get("ebitda_proxy") or 0)
        first = str(h.get("walkup_path") or "").split(";")[0].strip()
        if "->" in first:
            a, b = [x.strip() for x in first.split("->", 1)]
            if a == h["company_number"]:
                parent_of[a] = b
    kids: dict[str, list] = {}
    for a, b in parent_of.items():
        kids.setdefault(b, []).append(a)
    rep_of = {b: max(v, key=lambda x: size_of.get(x, (0, 0))) for b, v in kids.items()}

    cls = cls.drop([c for c in ("computed_at", "flags", "model", "prompt_version", "raw_json", "keyword_hits_json") if c in cls.columns])
    uni = uni.drop([c for c in ("computed_at", "flags") if c in uni.columns])
    df = cls.filter(pl.col("vertical").is_in(SECTORS)).join(uni, on="company_number", how="inner")
    df = df.rename({"confidence": "vertical_confidence"}) if "confidence" in df.columns else df
    if dur.height:
        df = df.join(dur.select(["company_number", "durability_score", "grey", "n_unscored"]), on="company_number", how="left")
    else:
        df = df.with_columns(pl.lit(None).alias("durability_score"), pl.lit(None).alias("grey"), pl.lit(None).alias("n_unscored"))
    if web is not None:
        df = df.join(web, on="company_number", how="left")
    else:
        df = df.with_columns(pl.lit(None).alias("domain"))
    if jobs is not None:
        df = df.join(jobs.select([c for c in ("company_number", "open_roles", "international_roles", "senior_commercial_roles") if c in jobs.columns]), on="company_number", how="left")
    if why is not None:
        df = df.join(why.drop([c for c in ("computed_at",) if c in why.columns]), on="company_number", how="left")

    out = []
    for r in df.to_dicts():
        n = r["company_number"]
        flags = []
        corr = CORRECTIONS.get(n)
        if corr:
            for k, v in corr.items():
                if k != "note":
                    r[k] = v
            if r.get("hold_start"):
                r["hold_years"] = round((dt.date.today() - dt.date.fromisoformat(str(r["hold_start"]))).days / 365.25, 1)
            flags.append("corrected_after_review")
        ebitda = r.get("ebitda_proxy")
        turnover = r.get("latest_turnover")
        sp, size_basis = size_points(ebitda, turnover)
        rp = route_points(r.get("route"), r.get("hold_years"))
        gp = growth_points(r.get("turnover_growth") if r.get("turnover_growth") is not None else r.get("employees_growth"))
        mp = margin_points(r.get("operating_margin"))
        sec = FIT["sector_points"] if r.get("vertical") in SECTORS else 0
        dq = 0
        if not r.get("provisional") and r.get("latest_period_end"):
            dq += 4
        if r.get("domain") and r.get("name_match") is not False:
            dq += 3
        if r.get("vertical_confidence") == "high":
            dq += 2
        if r.get("route_confidence") == "high":
            dq += 1
        comp = {"size": sp, "route": rp, "growth": gp, "margin": mp, "sector": sec, "data_quality": dq}
        fit = round(sum(comp.values()), 1)

        if r.get("provisional") or not r.get("latest_period_end"):
            flags.append("size_unverified")
        if r.get("turnover_growth") is None and r.get("employees_growth") is None:
            flags.append("growth_unknown")
        if r.get("operating_margin") is None:
            flags.append("margin_unknown")
        if r.get("growth_annualised") and r.get("turnover_growth") is not None:
            flags.append("growth_annualised")
        if r.get("grey"):
            flags.append("rubric_grey")
        if r.get("is_software_product") is False:
            flags.append("not_operating_business")
        if r.get("uk_headquartered") is False:
            flags.append("site_says_foreign_hq")
        if r.get("employees_scale_fixed"):
            flags.append("headcount_scale_corrected")
        if str(r.get("latest_accounts_type") or "").startswith("PDF"):
            flags.append("accounts_read_from_pdf")
        single_token = len([t for t in name_tokens(r.get("name") or "") if len(t) >= 3]) <= 1
        if r.get("domain") and r.get("name_match") is False and single_token and (r.get("discovery_method") or "").startswith("domain_probe"):
            flags.append("website_unverified")
        manual = n in excl
        if manual:
            flags.append("manual_exclusion")
        par = parent_of.get(n, "")
        sib = len(kids.get(par, []))
        rep = rep_of.get(par)
        part_of_group = sib >= 2 and rep != n          # a smaller unit: the representative carries the group
        if sib >= 2:
            flags.append("group_unit" if rep == n else "smaller_group_unit")
        plc_pdf = r.get("route") == "plc_dispersed" and str(r.get("latest_accounts_type") or "").startswith("PDF")
        cinven_owned = any("cinven" in str(x).lower() for x in list(r.get("owner_names") or []) + list(r.get("sponsor_names") or []) + [r.get("parent_name") or ""])
        if cinven_owned:
            flags.append("cinven_owned")
        # at scale: EBITDA at or above the Strategic Fund floor when a profit line is on file, else turnover at the ranking floor
        at_scale = (ebitda >= TGT["ebitda_early_floor_gbp"]) if (ebitda is not None and ebitda > 0) else bool(r.get("at_scale")) if ebitda is None else False
        gate = (r.get("vertical") in SECTORS and r.get("is_software_product") is not False and bool(r.get("is_group_head", True))
                and (r.get("route") in ROUTES) and not r.get("provisional") and at_scale and bool(r.get("domain"))
                and "website_unverified" not in flags and fit >= FIT["rank_min_fit"] and not manual and not cinven_owned and not part_of_group and not plc_pdf and r.get("durability_score") is not None)
        reasons = []
        if r.get("vertical") not in SECTORS:
            reasons.append("sector other")
        if r.get("is_software_product") is False:
            reasons.append("not an operating business")
        if not r.get("is_group_head", True):
            reasons.append("subsidiary of a ranked group")
        if r.get("route") not in ROUTES:
            reasons.append(f"route {r.get('route')}")
        if r.get("provisional"):
            reasons.append("size unverified")
        elif not at_scale:
            reasons.append("below the ranking size floor")
        if not r.get("domain"):
            reasons.append("no website found")
        if "website_unverified" in flags:
            reasons.append("website unverified")
        if fit < FIT["rank_min_fit"]:
            reasons.append(f"fit {fit:.0f} under {FIT['rank_min_fit']}")
        if manual:
            reasons.append("excluded after review: " + (excl_notes.get(n) or ""))
        if cinven_owned:
            reasons.append("already in Cinven's portfolio")
        if part_of_group:
            reasons.append(f"a smaller unit of a group: {uname.get(rep) or rep} ({rep}) is the largest of the {sib} UK companies under the same parent")
        if plc_pdf:
            reasons.append("listed company whose figures were read from a long annual report PDF and need a manual check")
        if corr and corr.get("note"):
            pass
        if r.get("route") == "employee_owned":
            reasons.append("employee ownership trust")
        if r.get("durability_score") is None:
            reasons.append("not yet scored")
        keep = ["company_number", "name", "post_town", "postcode", "sic1", "sic_text1", "inc_date", "category", "account_category", "vertical", "sub_vertical",
                "vertical_confidence", "evidence_quote", "evidence_url", "business_model", "uk_headquartered", "route", "route_confidence", "route_reason", "owner_names",
                "sponsor_names", "hold_start", "hold_years", "parent_name", "parent_country", "individuals_pct_mid", "n_individuals", "oldest_owner_age",
                "founder_rollover", "walkup_path", "group_head", "is_group_head", "latest_period_end", "latest_turnover", "latest_operating_profit", "ebitda_proxy", "ebitda_basis",
                "latest_pbt", "latest_employees", "turnover_growth", "turnover_growth_raw", "growth_annualised", "latest_period_days", "employees_growth", "operating_margin", "gross_margin", "latest_net_cash_from_ops", "latest_dividends",
                "latest_bank_borrowings", "latest_cash", "latest_net_assets", "latest_consolidated", "latest_accounts_type", "prior_period_end", "prior_turnover",
                "charges_outstanding", "charges_total", "provisional", "at_scale", "durability_score", "grey", "n_unscored", "domain", "homepage_url", "name_match",
                "open_roles", "international_roles", "why_now_signals", "why_now_approach", "why_now_caution", "why_now_line"]
        out.append({**{k: r.get(k) for k in keep}, "ranked": gate, "not_ranked_reason": "; ".join(reasons) if reasons else None,
                    "size_fit": size_fit_label(ebitda, turnover), "size_basis": size_basis, "fit_score": fit, "fit_components_json": json.dumps(comp),
                    "flags": sorted(set(flags)), "group_parent": par if sib >= 2 else None, "group_parent_name": uname.get(par) if sib >= 2 else None,
                    "review_note": (corr or {}).get("note"), "group_units": sib if sib >= 2 else None, "group_rep": rep if sib >= 2 else None, "computed_at": now_iso()})
    res = pl.DataFrame(out, infer_schema_length=None)
    ranked = res.filter(pl.col("ranked")).sort(["durability_score", "fit_score"], descending=[True, True], nulls_last=True).with_row_index("rank", offset=1)
    comparables = res.filter(~pl.col("ranked")).with_columns(pl.lit(None, dtype=pl.UInt32).alias("rank"))
    res = pl.concat([ranked, comparables.select(ranked.columns)])
    write_parquet(res, "rankings")

    def counts(frame, col):
        return {str(k): int(v) for k, v in zip(*[c.to_list() for c in frame.group_by(col).len().sort(col, nulls_last=True)])} if frame.height else {}

    summary = {"computed_at": now_iso(), "rows": res.height, "ranked": int(ranked.height), "comparables": int(comparables.height),
               "by_sector_ranked": counts(ranked, "vertical"), "by_route_ranked": counts(ranked, "route"), "size_fit_ranked": counts(ranked, "size_fit"),
               "by_sector_all": counts(res, "vertical"), "by_route_all": counts(res, "route"), "size_fit_all": counts(res, "size_fit"),
               "size_unverified_in_scope": int(res.filter(pl.col("provisional")).height),
               "fit_quartiles_ranked": [round(x, 1) if x is not None else None for x in [ranked["fit_score"].quantile(q) for q in (0.25, 0.5, 0.75)]] if ranked.height else [],
               "rubric_quartiles_ranked": [round(x, 1) if x is not None else None for x in [ranked["durability_score"].quantile(q) for q in (0.25, 0.5, 0.75)]] if ranked.height else [],
               "rank_min_fit": FIT["rank_min_fit"]}
    (REPO / "docs" / "rankings_summary.json").write_text(json.dumps(summary, indent=2))
    log.info("done: ranked %d of %d in scope; %s", ranked.height, res.height, json.dumps(summary["by_sector_ranked"]))


if __name__ == "__main__":
    main(sys.argv[1:])
