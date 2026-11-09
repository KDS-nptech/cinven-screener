"""Stage 6 prediction: one revenue estimate per universe company (shortlist plus comparables).

Reads accounts_wide, companies, data/models/tier_c_*; writes data/parquet/revenue_estimates.parquet
with tier, p10, p50, p90, period_end, extrapolated, inputs_json, model_version, display.

Run: python -m src.estimate.predict [--numbers a,b] [--all-universe]
"""
from __future__ import annotations

import argparse
import json
import pickle
import sys

import numpy as np
import polars as pl

from src.common import REPO, get_logger, now_iso, read_parquet, write_parquet
from src.estimate.tiers import inputs_json, render_band, tier_a, tier_c
from src.estimate.train import BALANCE_FEATURES, MODEL_DIR, band_of, feature_frame, to_pandas_X

log = get_logger("predict")


def load_model():
    with open(MODEL_DIR / "tier_c_lgbm.pkl", "rb") as f:
        model = pickle.load(f)
    meta = json.loads((MODEL_DIR / "tier_c_meta.json").read_text())
    return model, meta


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--numbers")
    ap.add_argument("--all-universe", action="store_true", help="estimate every universe row (default: non-excluded)")
    args = ap.parse_args(argv)

    uni = read_parquet("universe")
    if args.numbers:
        uni = uni.filter(pl.col("company_number").is_in(args.numbers.split(",")))
    elif not args.all_universe and "founder_flag" in uni.columns:
        pass  # estimate everyone in the universe; comparables need a revenue card too
    numbers = uni["company_number"].to_list()
    aw = read_parquet("accounts_wide").filter(pl.col("company_number").is_in(numbers))
    if "comparative" in aw.columns:
        aw = aw.filter(~pl.col("comparative").fill_null(False))
    aw = aw.filter(pl.col("employees").is_not_null()).sort(["company_number", "period_end"])
    comp = read_parquet("companies").select(["company_number", "sic1", "inc_date", "postcode", "account_category"])
    cat_by = dict(zip(comp["company_number"].to_list(), comp["account_category"].to_list()))
    model, meta = load_model()
    dist = meta["training_distribution"]

    rows = []
    hist_by = {}
    for n, g in aw.group_by("company_number"):
        n = n[0] if isinstance(n, tuple) else n
        hist_by[n] = g.to_dicts()
    # batch the Tier C feature frame for speed
    latest_rows = [h[-1] for h in hist_by.values()]
    latest_df = pl.DataFrame(latest_rows).join(comp, on="company_number", how="left")
    feats = feature_frame(latest_df)
    X, _ = to_pandas_X(feats, meta["cat_levels"])
    log_pred = model.predict(X)
    pred_by = dict(zip(feats["company_number"].to_list(), log_pred.tolist()))

    for n, history in hist_by.items():
        latest = history[-1]
        est = tier_a(latest, history)
        if est is None:
            emp = float(latest["employees"])
            extrapolated = not (dist["employees_p1"] <= emp <= dist["employees_p99"])
            na = latest.get("net_assets")
            if na is not None and not (dist["net_assets_p1"] <= na <= dist["net_assets_p99"]):
                extrapolated = True
            inputs = {"employees": emp, **{c: latest.get(c) for c in BALANCE_FEATURES if latest.get(c) is not None},
                      "accounts_type": latest.get("accounts_type"), "sic1": None}
            est = tier_c(latest, pred_by[n], meta["quantiles"], band_of(emp), extrapolated, inputs, meta["model_version"],
                         ratios=meta.get("ratios"), account_category=cat_by.get(n))
        est.setdefault("extrapolated", False)
        rows.append({"company_number": n, "tier": est["tier"], "p10": round(est["p10"]), "p50": round(est["p50"]), "p90": round(est["p90"]),
                     "period_end": est["period_end"], "extrapolated": bool(est["extrapolated"]), "inputs_json": inputs_json(est["inputs"]),
                     "model_version": meta["model_version"] if est["tier"] == "C" else ("ocr" if est["tier"] == "A-ocr" else "filed"), "display": render_band(est),
                     "employees_latest": latest.get("employees"), "revenue_per_head_p50": round(est["p50"] / latest["employees"]) if latest.get("employees") else None,
                     "computed_at": now_iso()})
    missing = set(numbers) - set(hist_by)
    for n in missing:
        rows.append({"company_number": n, "tier": "none", "p10": None, "p50": None, "p90": None, "period_end": None, "extrapolated": None,
                     "inputs_json": None, "model_version": None, "display": "no accounts with headcount", "employees_latest": None,
                     "revenue_per_head_p50": None, "computed_at": now_iso()})
    df = pl.DataFrame(rows)
    write_parquet(df, "revenue_estimates")
    summary = {k: int(v) for k, v in zip(*[c.to_list() for c in df.group_by("tier").len().sort("tier")])}
    (REPO / "docs" / "revenue_estimates_summary.json").write_text(json.dumps({"computed_at": now_iso(), "rows": df.height, "tiers": summary}, indent=2))
    log.info("done: %d rows, tiers %s", df.height, summary)


if __name__ == "__main__":
    main(sys.argv[1:])
