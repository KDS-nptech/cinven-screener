"""Current officers (directors, secretaries, LLP members) for every company in scope, from the Companies
House officers endpoint. Ranked companies first. -> data/parquet/officers.parquet

  python -m src.enrich.officers [--ranked-only]
"""
from __future__ import annotations

import sys

import polars as pl

from src.common import get_logger, now_iso, read_parquet, write_parquet
from src.enrich.ch_api import CHClient

log = get_logger("officers")


def main(argv=None):
    argv = argv or sys.argv[1:]
    rk = read_parquet("rankings").sort(["ranked", "durability_score"], descending=[True, True], nulls_last=True)
    if "--ranked-only" in argv:
        rk = rk.filter(pl.col("ranked"))
    client = CHClient()
    rows = []
    for i, n in enumerate(rk["company_number"].to_list(), 1):
        try:
            d = client.get(f"/company/{n}/officers", {"items_per_page": 100}) or {}
        except Exception as e:  # noqa: BLE001
            log.warning("%s: %s", n, e)
            continue
        for o in d.get("items", []):
            if o.get("resigned_on"):
                continue
            dob = o.get("date_of_birth") or {}
            rows.append({"company_number": n, "name": o.get("name"), "role": o.get("officer_role"), "appointed_on": o.get("appointed_on"),
                         "occupation": o.get("occupation"), "nationality": o.get("nationality"), "country_of_residence": o.get("country_of_residence"),
                         "dob_year": dob.get("year"), "corporate": bool(o.get("identification")), "fetched_at": now_iso()})
        if i % 50 == 0:
            write_parquet(pl.DataFrame(rows, infer_schema_length=None), "officers")
            log.info("%d/%d companies, %d active officers", i, rk.height, len(rows))
    write_parquet(pl.DataFrame(rows, infer_schema_length=None), "officers")
    log.info("done: %d companies, %d active officers", rk.height, len(rows))


if __name__ == "__main__":
    main()
