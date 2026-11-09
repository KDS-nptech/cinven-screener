"""Back-tests on Cinven's UK entries (docs/research/03_uk_deals_companies_house.json).

    python -m src.backtests        # writes docs/backtests.json and docs/backtests.md

Two questions per entry:
1. Point in time: with the PSC register rolled back to the month before Cinven's announcement (a PSC row
   counts when notified on or before that date and not ceased by it), which ownership route would the
   screener have assigned, and does it match the seller the research found? Was the pre-deal size inside
   one of the two bands?
2. Today: is the company (or its group head) in the universe, and does the screener read it as sponsor-owned
   by Cinven (current portfolio) or by the buyer (exited)?

The PSC register starts in April 2016, so entries before then can only be tested on size and sector.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import polars as pl

from src.common import REPO, cfg, get_logger, now_iso, parquet_exists, read_parquet, read_parquet_where
from src.filter.routes import compile_route_rules, evaluate

log = get_logger("backtests")
ACTIONABLE = {"founder_family", "sponsor", "sponsor_offshore", "plc_dispersed", "employee_owned"}


def _d(s) -> dt.date | None:
    try:
        return dt.date.fromisoformat(str(s)[:10]) if s else None
    except ValueError:
        return None


def psc_index_asof(seed: str, as_of: dt.date, levels: int = 4) -> dict[str, list[dict]]:
    """PSC rows as they stood on as_of for the seed company and the UK corporate PSCs reachable from it."""
    want = {seed}
    idx: dict[str, list[dict]] = {}
    frontier = {seed}
    for _ in range(levels + 1):
        if not frontier:
            break
        rows = read_parquet_where("psc", "company_number", frontier)
        nxt = set()
        for r in rows.to_dicts():
            n_on, c_on = _d(r.get("notified_on")), _d(r.get("ceased_on"))
            if n_on and n_on > as_of:
                continue
            if c_on and c_on <= as_of:
                continue
            r = dict(r)
            r["is_active"] = True
            r["ceased_on"] = None
            idx.setdefault(r["company_number"], []).append(r)
            reg = r.get("corporate_reg_number")
            if reg and len(str(reg)) == 8 and reg not in want:
                nxt.add(reg)
        want |= nxt
        frontier = nxt
    return idx


def size_band(ebitda_m, turnover_m) -> str:
    t = cfg()["target"]
    if ebitda_m is not None:
        e = ebitda_m * 1e6
        if e < t["ebitda_early_floor_gbp"]:
            return "too small"
        if e < t["ebitda_target_min_gbp"]:
            return "strategic fund band"
        if e <= t["ebitda_target_max_gbp"]:
            return "flagship band"
        return "mega-cap"
    if turnover_m is not None:
        tv = turnover_m * 1e6
        if tv < t["rank_turnover_min_gbp"]:
            return "too small (turnover only)"
        return "strategic fund band (turnover only)" if tv < 300e6 else "flagship band (turnover only)"
    return "unknown"


def main() -> None:
    src = REPO / "docs" / "research" / "03_uk_deals_companies_house.json"
    if not src.exists():
        log.error("research file missing: %s", src)
        return
    research = json.loads(src.read_text())
    entries = research.get("uk_platforms", [])
    rules = compile_route_rules()
    companies = read_parquet("companies") if parquet_exists("companies") else None
    uni = read_parquet("universe") if parquet_exists("universe") else None
    rk = read_parquet("rankings") if parquet_exists("rankings") else None
    results = []
    for e in entries:
        cn = (e.get("ch_number") or "").strip()
        ann = e.get("announced") or ""
        row = {"name": e.get("name"), "company_number": cn or None, "announced": ann, "deal_type": e.get("deal_type"), "sector": e.get("sector_cinven"),
               "outlier": bool(e.get("outlier")), "outlier_reason": e.get("outlier_reason") or None, "seller": e.get("seller"), "psc_before_deal_research": e.get("psc_before_deal")}
        pre = e.get("pre_deal_accounts") or {}
        row["pre_deal"] = {k: pre.get(k) for k in ("period_end", "turnover_gbp_m", "operating_profit_gbp_m", "ebitda_gbp_m", "employees", "accounts_type")}
        row["size_band_pre_deal"] = size_band(pre.get("ebitda_gbp_m"), pre.get("turnover_gbp_m"))
        if not cn:
            row["status"] = "no Companies House number (registered outside England and Wales)"
            results.append(row)
            continue
        comp = companies.filter(pl.col("company_number") == cn).to_dicts() if companies is not None else []
        c = comp[0] if comp else {}
        row["register"] = {"name": c.get("name"), "status": c.get("status"), "category": c.get("category"), "account_category": c.get("account_category"), "sic1": c.get("sic1")}
        # point in time
        try:
            y, m = int(ann[:4]), int(ann[5:7]) if len(ann) >= 7 else 1
            as_of = dt.date(y, m, 1) - dt.timedelta(days=1)
        except ValueError:
            as_of = None
        if as_of and as_of >= dt.date(2016, 4, 6):
            idx = psc_index_asof(cn, as_of)
            company = {"company_number": cn, "name": c.get("name"), "category": c.get("category"), "inc_date": c.get("inc_date")}
            r = evaluate(company, idx, rules, None, as_of)
            row["point_in_time"] = {"as_of": as_of.isoformat(), "route": r["route"], "confidence": r["route_confidence"], "reason": r["route_reason"],
                                    "owners": r["owner_names"][:4], "sponsors": r["sponsor_names"][:3], "hold_years": r["hold_years"], "walkup_path": r["walkup_path"],
                                    "psc_rows_seen": sum(len(v) for v in idx.values())}
            row["point_in_time"]["actionable"] = r["route"] in ACTIONABLE or r["route"] in ("foreign_parent", "uk_group")
        else:
            row["point_in_time"] = {"as_of": as_of.isoformat() if as_of else None, "route": None, "note": "before the PSC register (April 2016)"}
        # today
        today = {}
        if uni is not None:
            u = uni.filter(pl.col("company_number") == cn).to_dicts()
            if u:
                u = u[0]
                today = {"in_universe": bool(u.get("passes_all")), "route": u.get("route"), "sponsors": (u.get("sponsor_names") or [])[:3], "owners": (u.get("owner_names") or [])[:3],
                         "hold_years": u.get("hold_years"), "group_head": u.get("group_head"), "is_group_head": u.get("is_group_head"), "provisional": u.get("provisional"),
                         "latest_turnover": u.get("latest_turnover"), "ebitda_proxy": u.get("ebitda_proxy"), "exclusion_reason": u.get("exclusion_reason")}
                if u.get("group_head") and u["group_head"] != cn:
                    h = uni.filter(pl.col("company_number") == u["group_head"]).to_dicts()
                    if h:
                        today["group_head_name"] = h[0].get("name")
                        today["group_head_route"] = h[0].get("route")
                        today["group_head_sponsors"] = (h[0].get("sponsor_names") or [])[:3]
            else:
                cand = read_parquet("candidate_companies").filter(pl.col("company_number") == cn).height if parquet_exists("candidate_companies") else 0
                today = {"in_universe": False, "note": "candidate but failed a universe rule" if cand else "not a FULL, GROUP or MEDIUM filer on the snapshot"}
            if rk is not None:
                k = rk.filter(pl.col("company_number") == cn).to_dicts()
                if k:
                    today["in_scope"] = True
                    today["ranked"] = bool(k[0].get("ranked"))
                    today["sector"] = k[0].get("vertical")
        row["today"] = today
        cinven_now = any("cinven" in str(s).lower() for s in (today.get("sponsors") or []) + (today.get("group_head_sponsors") or []) + (today.get("owners") or []))
        exited = bool((e.get("exit") or {}).get("year"))
        row["today"]["reads_cinven_as_owner"] = cinven_now
        row["today"]["exited_per_research"] = exited
        pit = row["point_in_time"]
        verdict = []
        if pit.get("route"):
            verdict.append("route " + ("actionable" if pit.get("actionable") else "not actionable") + f" ({pit['route']})")
        verdict.append("size " + row["size_band_pre_deal"])
        if today:
            if cinven_now and not exited:
                verdict.append("today reads Cinven as owner")
            elif exited:
                verdict.append(f"exited {(e.get('exit') or {}).get('year')}, today route {today.get('route') or today.get('group_head_route')}")
            elif today.get("in_universe"):
                verdict.append(f"today route {today.get('route')} (Cinven not detected)")
        row["verdict"] = "; ".join(verdict)
        results.append(row)
    pit_rows = [r for r in results if r.get("point_in_time", {}).get("route")]
    summary = {
        "computed_at": now_iso(), "entries": len(results), "with_company_number": sum(1 for r in results if r.get("company_number")),
        "point_in_time_tested": len(pit_rows),
        "point_in_time_actionable": sum(1 for r in pit_rows if r["point_in_time"].get("actionable")),
        "point_in_time_routes": {},
        "size_bands_pre_deal": {},
        "today_reads_cinven": sum(1 for r in results if r.get("today", {}).get("reads_cinven_as_owner")),
        "current_portfolio_in_research": sum(1 for r in results if not r.get("today", {}).get("exited_per_research") and r.get("company_number")),
    }
    for r in pit_rows:
        k = r["point_in_time"]["route"]
        summary["point_in_time_routes"][k] = summary["point_in_time_routes"].get(k, 0) + 1
    for r in results:
        k = r["size_band_pre_deal"]
        summary["size_bands_pre_deal"][k] = summary["size_bands_pre_deal"].get(k, 0) + 1
    out = {"summary": summary, "results": results, "source": str(src.relative_to(REPO))}
    (REPO / "docs" / "backtests.json").write_text(json.dumps(out, indent=1, default=str))
    lines = ["# Back-tests on Cinven's UK entries", "", f"Computed {summary['computed_at']} from docs/research/03_uk_deals_companies_house.json.", "",
             f"**Conclusion:** {summary['point_in_time_tested']} entries could be tested on the PSC register as it stood the month before announcement; "
             f"{summary['point_in_time_actionable']} of them sat on a route the screener acts on. Pre-deal size bands: {json.dumps(summary['size_bands_pre_deal'])}. "
             f"Today the screener reads Cinven as owner for {summary['today_reads_cinven']} of the entries still held.", "",
             "| Company | Announced | Deal type | Pre-deal size band | Point-in-time route | Today | Verdict |", "|---|---|---|---|---|---|---|"]
    for r in results:
        pit = r.get("point_in_time", {})
        t = r.get("today", {})
        lines.append(f"| {r['name']} | {r['announced']} | {r.get('deal_type') or ''} | {r['size_band_pre_deal']} | {pit.get('route') or pit.get('note') or ''} "
                     f"| {t.get('route') or t.get('note') or ''}{' (group head ' + str(t.get('group_head_route')) + ')' if t.get('group_head_route') else ''} | {r.get('verdict') or r.get('status') or ''} |")
    (REPO / "docs" / "backtests.md").write_text("\n".join(lines) + "\n")
    log.info("backtests: %s", json.dumps(summary))


if __name__ == "__main__":
    main()
