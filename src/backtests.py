"""Stage 12: back-tests on Brighton Park's own UK deals, written to docs/backtests.json for the methods panel.

Run: python -m src.backtests
"""
from __future__ import annotations

import json

import polars as pl

from src.common import REPO, cfg, get_logger, now_iso, parquet_exists, read_parquet

log = get_logger("backtests")


def _row(table: str, n: str) -> dict:
    if not parquet_exists(table):
        return {}
    df = read_parquet(table).filter(pl.col("company_number") == n)
    return df.to_dicts()[0] if df.height else {}


def _scores(n: str) -> dict[int, int | None]:
    if not parquet_exists("scores"):
        return {}
    df = read_parquet("scores").filter(pl.col("company_number") == n)
    return {int(r["dimension"]): r["score"] for r in df.to_dicts()}


def main():
    results = []
    for bt in cfg()["backtests"]:
        n = bt["company_number"]
        uni, rev, cls, dur = _row("universe", n), _row("revenue_estimates", n), _row("classification", n), _row("durability", n)
        sc = _scores(n)
        acc = read_parquet("accounts_wide").filter(pl.col("company_number") == n).sort("period_end") if parquet_exists("accounts_wide") else pl.DataFrame()
        latest = acc.to_dicts()[-1] if acc.height else {}
        notes, passed = [], None
        name = bt["name"]
        if name == "PortSwigger":
            pscs = json.loads(uni.get("individual_pscs_json") or "[]") if uni else []
            investor_visible = any("dzialga" in (p.get("name") or "").lower() for p in pscs)
            passed = rev.get("tier") in ("A", "A-rolled", "A-ocr") and all((sc.get(d) or 0) >= 4 for d in (6, 9)) and investor_visible
            notes.append(f"tier {rev.get('tier')}, {rev.get('display')}; points 6/9 = {sc.get(6)}/{sc.get(9)}; founder_flag {uni.get('founder_flag')} ({uni.get('founder_confidence') or uni.get('exclusion_reason')}); investor_flag {uni.get('investor_flag')}")
            notes.append("register shows Dr Dafydd Stuttard 50 to 75% and Mark Dzialga (significant influence as firm, Jul 2024); the PSC rule reads an individual, the SH01/share-premium check sets investor possible, and the top-30 review excludes it as Brighton Park's own 2024 investment" if investor_visible else "Dzialga not visible on the register")
        elif name == "usecure":
            band_ok = rev.get("p10") is not None and rev["p10"] <= 3_000_000 <= rev["p90"]
            passed = band_ok
            notes.append(f"tier {rev.get('tier')}, band {rev.get('display')} vs ~£3M public ARR (period {rev.get('period_end')}); founder rule: {uni.get('founder_flag')} / {uni.get('exclusion_reason')} ({', '.join(uni.get('investor_names') or [])})")
        elif name == "Person Centred Software":
            # Not ranked: either excluded by the investor rule or left uncertain by an unresolved holdco chain.
            passed = uni.get("founder_flag") in ("excluded", "uncertain") and all((sc.get(d) or 0) >= 4 for d in (6, 8, 10))
            notes.append("SIC 82990 on the register: outside the software SIC net, force-included for the back-test")
            notes.append(f"founder rule: {uni.get('founder_flag')} / {uni.get('exclusion_reason')} ({', '.join(uni.get('investor_names') or [])}); points 6/8/10 = {sc.get(6)}/{sc.get(8)}/{sc.get(10)}; revenue {rev.get('display')}")
        elif name == "Camascope":
            passed = all((sc.get(d) or 0) >= 4 for d in (6, 8, 10))
            notes.append(f"points 6/8/10 = {sc.get(6)}/{sc.get(8)}/{sc.get(10)}; founder rule: {uni.get('founder_flag')} / {uni.get('exclusion_reason')} ({', '.join(uni.get('investor_names') or [])}); revenue {rev.get('display')}")
        results.append({"Company": name, "Number": n, "Expected": bt["expect"], "Result": "pass" if passed else ("fail" if passed is False else "pending"),
                        "Detail": " | ".join(x for x in notes if x), "Vertical": cls.get("vertical"), "Durability": dur.get("durability_score"),
                        "Staff": latest.get("employees"), "Turnover filed": latest.get("turnover")})
        log.info("%s: %s", name, results[-1]["Result"])
    (REPO / "docs" / "backtests.json").write_text(json.dumps({"computed_at": now_iso(), "results": results}, indent=2, default=str))


if __name__ == "__main__":
    main()
