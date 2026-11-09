"""Stage 6, Tier C training: peer model for log(turnover) from headcount and balance-sheet lines.

Training rows: software-SIC companies in accounts_wide that file turnover, 15 to 400
employees, turnover above GBP 250k, period end 2022 or later. Features are restricted to
what a filleted (no P&L) filer also discloses, so the model is never fed a feature the
prediction set lacks. Baseline: OLS on log(employees) plus the balance-sheet terms.
Validation: GroupKFold by company, five folds; MdAPE by headcount band, p10 to p90 coverage.

Outputs: data/models/tier_c_lgbm.pkl, data/models/tier_c_meta.json, docs/model_report.json
Run: python -m src.estimate.train
"""
from __future__ import annotations

import json
import pickle
import re
import sys

import numpy as np
import polars as pl

from src.common import REPO, cfg, get_logger, now_iso, read_parquet

log = get_logger("train")
EST = cfg()["estimator"]
MODEL_DIR = REPO / "data" / "models"
MODEL_VERSION = "tier-c-v1"

BALANCE_FEATURES = ["trade_debtors", "accrued_deferred_income", "tax_social_security", "corp_tax", "cash", "net_assets",
                    "creditors_within_one_year", "current_assets", "fixed_assets", "intangible_assets", "bank_borrowings"]
CATEGORICALS = ["sic1", "account_category", "accounts_type"]
LONDON_RE = re.compile(r"^(E|EC|N|NW|SE|SW|W|WC)\d")


def band_of(emp: float) -> str:
    for lo, hi in EST["headcount_bands"]:
        if lo <= emp < hi or (hi == EST["headcount_bands"][-1][1] and emp == hi):
            return f"{lo}-{hi}"
    return "out_of_range"


def feature_frame(df: pl.DataFrame) -> pl.DataFrame:
    """Add model features to a frame that has employees, balance-sheet columns, inc_date, postcode, period_end."""
    df = df.with_columns([
        pl.col("period_end").cast(pl.Utf8).str.to_date(strict=False).alias("period_end"),
        pl.col("inc_date").cast(pl.Utf8).str.to_date(strict=False).alias("inc_date"),
    ])
    out = df.with_columns([
        pl.col("employees").cast(pl.Float64).log().alias("log_employees"),
        ((pl.col("period_end") - pl.col("inc_date")).dt.total_days() / 365.25).alias("age_years"),
        pl.col("postcode").fill_null("").str.extract(r"^([A-Z]{1,2}\d)", 1).fill_null("").str.contains(r"^(E|EC|N|NW|SE|SW|W|WC)\d").alias("london"),
        pl.col("period_end").dt.year().alias("period_year"),
    ])
    for c in BALANCE_FEATURES:
        if c not in out.columns:
            out = out.with_columns(pl.lit(None, dtype=pl.Float64).alias(c))
        out = out.with_columns(
            pl.when(pl.col(c).is_null()).then(None).otherwise(pl.col(c).cast(pl.Float64).clip(lower_bound=0).log1p()).alias(f"log1p_{c}")
        )
    for c in CATEGORICALS:
        if c not in out.columns:
            out = out.with_columns(pl.lit("unknown").alias(c))
        out = out.with_columns(pl.col(c).cast(pl.Utf8).fill_null("unknown"))
    return out


def feature_columns() -> list[str]:
    return ["log_employees", "age_years", "london", "period_year"] + [f"log1p_{c}" for c in BALANCE_FEATURES] + CATEGORICALS


def training_set() -> pl.DataFrame:
    aw = read_parquet("accounts_wide")
    if "comparative" in aw.columns:
        aw = aw.filter(~pl.col("comparative").fill_null(False))
    comp = read_parquet("companies").select(["company_number", "sic1", "inc_date", "postcode", "account_category", "is_software_sic"])
    df = aw.join(comp, on="company_number", how="inner")
    df = df.filter(
        pl.col("turnover").is_not_null() & (pl.col("turnover") > EST["training_turnover_min"]) &
        pl.col("employees").is_not_null() & (pl.col("employees") >= EST["training_employees_min"]) & (pl.col("employees") <= EST["training_employees_max"]) &
        (pl.col("period_end").cast(pl.Utf8).str.to_date(strict=False) >= pl.lit(EST["training_period_from"]).str.to_date()) &
        pl.col("sic1").is_in(cfg()["target"]["software_sic"]) &
        # OCR-derived rows carry no balance-sheet lines and occasional digit errors; they are
        # shown as Tier A-ocr on the company page but kept out of the peer model (MdAPE 33% vs 43%).
        ~pl.col("accounts_type").fill_null("").str.starts_with("PDF")
    )
    return feature_frame(df)


def to_pandas_X(df: pl.DataFrame, cat_levels: dict[str, list[str]] | None = None):
    import pandas as pd

    X = df.select(feature_columns()).to_pandas()
    X["london"] = X["london"].astype(float)
    levels = cat_levels or {}
    for c in CATEGORICALS:
        if c in levels:
            X[c] = pd.Categorical(X[c], categories=levels[c])
        else:
            X[c] = X[c].astype("category")
            levels[c] = list(X[c].cat.categories)
    return X, levels


def ols_baseline(X, y, X_val):
    """Ridge-free OLS on numeric columns with median imputation and missing indicators."""
    import pandas as pd

    def design(Xd):
        num = Xd.drop(columns=CATEGORICALS).copy()
        for c in num.columns:
            num[f"{c}_missing"] = num[c].isna().astype(float)
        return num

    D = design(X)
    med = D.median()
    D = D.fillna(med)
    A = np.column_stack([np.ones(len(D)), D.values])
    beta, *_ = np.linalg.lstsq(A, y, rcond=None)
    Dv = design(X_val).fillna(med)
    Av = np.column_stack([np.ones(len(Dv)), Dv.values])
    return Av @ beta


def main():
    import lightgbm as lgb
    from sklearn.model_selection import GroupKFold

    df = training_set()
    log.info("training rows: %d companies: %d", df.height, df["company_number"].n_unique())
    if df.height < 200:
        log.error("too few training rows; aborting")
        sys.exit(1)
    y = np.log(df["turnover"].to_numpy())
    X, levels = to_pandas_X(df)
    groups = df["company_number"].to_numpy()
    bands = np.array([band_of(e) for e in df["employees"].to_numpy()])

    params = dict(objective="regression", n_estimators=EST["lgbm"]["n_estimators"], learning_rate=EST["lgbm"]["learning_rate"],
                  num_leaves=EST["lgbm"]["num_leaves"], min_child_samples=EST["lgbm"]["min_child_samples"], subsample=0.8,
                  subsample_freq=1, colsample_bytree=0.8, reg_lambda=1.0, verbose=-1,
                  monotone_constraints=[EST["lgbm"]["monotone_employees"]] + [0] * (len(feature_columns()) - 1))

    oof = np.full(len(y), np.nan)
    oof_base = np.full(len(y), np.nan)
    best_iters = []
    for fold, (tr, va) in enumerate(GroupKFold(n_splits=EST["folds"]).split(X, y, groups)):
        m = lgb.LGBMRegressor(**params)
        m.fit(X.iloc[tr], y[tr], eval_set=[(X.iloc[va], y[va])], callbacks=[lgb.early_stopping(50, verbose=False)])
        oof[va] = m.predict(X.iloc[va])
        best_iters.append(int(m.best_iteration_ or params["n_estimators"]))
        oof_base[va] = ols_baseline(X.iloc[tr], y[tr], X.iloc[va])
        log.info("fold %d: best_iter=%d", fold, best_iters[-1])

    resid = y - oof
    resid_base = y - oof_base
    report = {"model_version": MODEL_VERSION, "trained_at": now_iso(), "training_rows": int(df.height),
              "training_companies": int(df["company_number"].n_unique()), "features": feature_columns(),
              "folds": EST["folds"], "best_iterations": best_iters, "by_band": {}, "overall": {}}

    def mdape(r):
        return float(np.median(np.abs(np.exp(r) - 1)) * 100)

    quantiles = {}
    for b in sorted(set(bands)):
        mask = bands == b
        q10, q90 = np.quantile(resid[mask], [0.10, 0.90])
        quantiles[b] = {"q10": float(q10), "q90": float(q90), "n": int(mask.sum())}
        inside = np.mean((resid[mask] >= q10) & (resid[mask] <= q90))
        report["by_band"][b] = {"n": int(mask.sum()), "mdape_lgbm_pct": round(mdape(resid[mask]), 1),
                                "mdape_ols_pct": round(mdape(resid_base[mask]), 1), "p10_p90_coverage_in_sample": round(float(inside), 3),
                                "band_width_log": round(float(q90 - q10), 3),
                                "typical_band_pct": {"low": round((np.exp(q10) - 1) * 100, 0), "high": round((np.exp(q90) - 1) * 100, 0)}}
    report["overall"] = {"mdape_lgbm_pct": round(mdape(resid), 1), "mdape_ols_pct": round(mdape(resid_base), 1),
                         "rmse_log_lgbm": round(float(np.sqrt(np.mean(resid ** 2))), 3), "rmse_log_ols": round(float(np.sqrt(np.mean(resid_base ** 2))), 3),
                         "r2_log_lgbm": round(float(1 - np.sum(resid ** 2) / np.sum((y - y.mean()) ** 2)), 3)}
    # honest coverage: quantiles from folds 0-3 applied to fold 4 would be stricter; report a split-half check
    half = np.arange(len(y)) % 2 == 0
    cov = []
    for b in quantiles:
        m1 = (bands == b) & half
        m2 = (bands == b) & ~half
        if m1.sum() > 20 and m2.sum() > 20:
            q10, q90 = np.quantile(resid[m1], [0.10, 0.90])
            cov.append(float(np.mean((resid[m2] >= q10) & (resid[m2] <= q90))))
    report["overall"]["p10_p90_coverage_split_half"] = round(float(np.mean(cov)), 3) if cov else None

    # revenue per head sanity against SaaS Capital anchors (USD, converted at ~1.30)
    rph = df["turnover"].to_numpy() / df["employees"].to_numpy()
    report["revenue_per_head_gbp"] = {"p25": round(float(np.quantile(rph, 0.25))), "p50": round(float(np.quantile(rph, 0.5))),
                                      "p75": round(float(np.quantile(rph, 0.75))),
                                      "anchor_saas_capital_2026_median_usd": EST["revenue_per_head_anchor_usd"]["saas_capital_2026_median"]}
    report["training_distribution"] = {"employees_p1": float(np.quantile(df["employees"].to_numpy(), 0.01)),
                                       "employees_p99": float(np.quantile(df["employees"].to_numpy(), 0.99)),
                                       "net_assets_p1": float(np.nanquantile(df["net_assets"].fill_null(np.nan).to_numpy(), 0.01)),
                                       "net_assets_p99": float(np.nanquantile(df["net_assets"].fill_null(np.nan).to_numpy(), 0.99)),
                                       "account_category_counts": {k: int(v) for k, v in zip(*[c.to_list() for c in df.group_by("account_category").len().sort("len", descending=True)])}}

    final = lgb.LGBMRegressor(**{**params, "n_estimators": max(100, int(np.mean(best_iters)))})
    final.fit(X, y)
    imp = sorted(zip(feature_columns(), final.feature_importances_.tolist()), key=lambda t: -t[1])
    report["feature_importance_gain_rank"] = [f for f, _ in imp]
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    with open(MODEL_DIR / "tier_c_lgbm.pkl", "wb") as f:
        pickle.dump(final, f)
    # empirical turnover ratios for the balance-sheet cross-checks (p25 to p75 among disclosers)
    ratios = {}
    for col in ("tax_social_security", "trade_debtors", "accrued_deferred_income"):
        sub = df.filter(pl.col(col).is_not_null() & (pl.col(col) > 0))
        if sub.height > 30:
            r = (sub["turnover"] / sub[col]).to_numpy()
            ratios[col] = {"p25": round(float(np.quantile(r, 0.25)), 1), "p50": round(float(np.quantile(r, 0.5)), 1), "p75": round(float(np.quantile(r, 0.75)), 1), "n": int(sub.height)}
    report["balance_sheet_ratios"] = ratios
    (MODEL_DIR / "tier_c_meta.json").write_text(json.dumps({"model_version": MODEL_VERSION, "cat_levels": levels, "quantiles": quantiles, "ratios": ratios,
                                                            "features": feature_columns(), "training_distribution": report["training_distribution"],
                                                            "trained_at": now_iso()}, indent=2))
    (REPO / "docs" / "model_report.json").write_text(json.dumps(report, indent=2))
    log.info("report: overall %s", report["overall"])
    for b, r in report["by_band"].items():
        log.info("band %s: %s", b, r)


if __name__ == "__main__":
    main()
