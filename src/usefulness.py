"""What the ranked list holds, for the Methods page: routes, sponsors past a four-year hold, founders aged
60 or more, size bands, PDF-read figures, companies already in Cinven's portfolio. -> docs/usefulness.json"""
from __future__ import annotations

import json

import polars as pl

from src.common import REPO, get_logger, now_iso, read_parquet

log = get_logger("usefulness")


def main():
    rk = read_parquet("rankings")
    r = rk.filter(pl.col("ranked"))
    flags = lambda df, f: df.filter(pl.col("flags").list.contains(f)).height
    out = {"computed_at": now_iso(), "ranked": r.height, "in_scope": rk.height,
           "founder_family": r.filter(pl.col("route") == "founder_family").height,
           "founder_60plus": r.filter((pl.col("route") == "founder_family") & (pl.col("oldest_owner_age") >= 60)).height,
           "sponsor": r.filter(pl.col("route").is_in(["sponsor", "sponsor_offshore"])).height,
           "sponsor_past_hold": r.filter(pl.col("route").is_in(["sponsor", "sponsor_offshore"]) & (pl.col("hold_years") >= 4)).height,
           "strategic_band": r.filter(pl.col("size_fit").str.starts_with("strategic")).height,
           "flagship_band": r.filter(pl.col("size_fit").str.starts_with("flagship")).height,
           "pdf_read": flags(r, "accounts_read_from_pdf"),
           "cinven_owned": flags(rk, "cinven_owned"),
           "by_sector": dict(r.group_by("vertical").len().iter_rows())}
    (REPO / "docs" / "usefulness.json").write_text(json.dumps(out, indent=1))
    log.info("usefulness: %s", out)


if __name__ == "__main__":
    main()
