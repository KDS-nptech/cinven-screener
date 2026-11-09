"""Accounts coverage: how many universe companies have verified size figures, by route and source.

    python3 scripts/coverage.py     # writes docs/accounts_coverage.json
"""
from __future__ import annotations

import glob
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import polars as pl  # noqa: E402

from src.common import REPO, now_iso, parquet_exists, read_parquet  # noqa: E402


def main() -> None:
    uni = read_parquet("universe").filter(pl.col("passes_all"))
    actionable = ["founder_family", "sponsor", "sponsor_offshore", "plc_dispersed", "employee_owned"]
    out = {"computed_at": now_iso(), "universe": uni.height}
    src = {}
    if parquet_exists("accounts_wide"):
        aw = read_parquet("accounts_wide").filter(~pl.col("comparative")).select(["company_number", "accounts_type", "source_file"]).unique(subset=["company_number"])
        aw = aw.with_columns(pl.when(pl.col("accounts_type").str.starts_with("PDF")).then(pl.lit("document API: PDF read by vision model"))
                             .when(pl.col("source_file").str.starts_with("Prod000_0000")).then(pl.lit("document API: iXBRL"))
                             .otherwise(pl.lit("iXBRL bulk data")).alias("source"))
        src = dict(aw.join(uni.select(["company_number"]), on="company_number", how="inner").group_by("source").len().iter_rows())
    out["parsed_accounts_by_source"] = src
    heads = uni.filter(pl.col("is_group_head").fill_null(True))
    by_route = {}
    for route, g in heads.group_by("route"):
        route = route[0] if isinstance(route, tuple) else route
        by_route[str(route)] = {"group_heads": g.height, "size_verified": int((~pl.Series(g["provisional"].fill_null(False))).sum()),
                                "at_scale": int(g["at_scale"].fill_null(False).sum())}
    out["group_heads_by_route"] = by_route
    act = heads.filter(pl.col("route").is_in(actionable))
    out["actionable_group_heads"] = {"total": act.height, "size_verified": int((~pl.Series(act["provisional"].fill_null(False))).sum()),
                                     "at_scale": int(act["at_scale"].fill_null(False).sum()),
                                     "group_accounts_filers": int((act["account_category"] == "GROUP").sum()),
                                     "group_accounts_filers_verified": int(((act["account_category"] == "GROUP") & ~pl.Series(act["provisional"].fill_null(False))).sum())}
    # document API progress across shards
    stats = {"done": 0}
    for f in glob.glob(str(REPO / "data" / "raw" / "accounts_api_progress*.json")):
        p = json.loads(pathlib.Path(f).read_text())
        stats["done"] += len(p.get("done", {}))
        for k, v in (p.get("stats") or {}).items():
            if isinstance(v, (int, float)):
                stats[k] = stats.get(k, 0) + v
    out["document_api"] = stats
    if parquet_exists("websites"):
        w = read_parquet("websites")
        out["websites"] = {"discovery_attempted": w.height, "domain_found": int(w["domain"].is_not_null().sum()),
                           "fetched": int((w["pages_fetched"].fill_null(0) > 0).sum()), "name_match": int((w["name_match"] == True).sum())}  # noqa: E712
    if parquet_exists("classification"):
        c = read_parquet("classification")
        out["classification"] = dict(c.group_by("vertical").len().iter_rows())
    (REPO / "docs" / "accounts_coverage.json").write_text(json.dumps(out, indent=1, default=str))
    print(json.dumps({k: v for k, v in out.items() if k != "group_heads_by_route"}, indent=1, default=str))


if __name__ == "__main__":
    main()
