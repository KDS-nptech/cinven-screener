"""Stage 6 tier logic. Filed beats observed beats modelled.

Tier A        turnover filed for the latest period.
Tier A-rolled turnover filed in a prior period within tier_a_lookback_years, rolled forward
              by headcount growth since then; band +/-15%.
Tier A-derived gross profit filed without turnover; turnover backed out at a 70% to 85%
              gross margin (p10 at 85%, p90 at 70%).
Tier B        observed floors (public spend, bottom-up) - cut list, not built.
Tier C        peer model prediction with residual-quantile band by headcount band.
"""
from __future__ import annotations

import datetime as dt
import json

from src.common import cfg

EST = cfg()["estimator"]


def _years_between(a, b) -> float:
    a = dt.date.fromisoformat(str(a)[:10])
    b = dt.date.fromisoformat(str(b)[:10])
    return max(0.0, (b - a).days / 365.25)


def tier_a(latest: dict, history: list[dict]) -> dict | None:
    """history: accounts_wide rows for the company sorted by period_end ascending, latest last."""
    if latest.get("turnover") and latest["turnover"] > 0:
        t = float(latest["turnover"])
        if str(latest.get("accounts_type") or "").startswith("PDF"):
            # read by OCR from a scanned filing: shown as filed, with a band for read errors
            return {"tier": "A-ocr", "p10": t * 0.9, "p50": t, "p90": t * 1.1, "period_end": str(latest["period_end"])[:10],
                    "inputs": {"turnover_filed_ocr": t, "accounts_type": latest.get("accounts_type"), "source": "tesseract OCR of the Companies House PDF"}}
        return {"tier": "A", "p10": t, "p50": t, "p90": t, "period_end": str(latest["period_end"])[:10],
                "inputs": {"turnover_filed": t, "accounts_type": latest.get("accounts_type"), "consolidated": latest.get("consolidated")}}
    prior = [h for h in history[:-1] if h.get("turnover") and h["turnover"] > 0
             and _years_between(h["period_end"], latest["period_end"]) <= EST["tier_a_lookback_years"]]
    if prior:
        h = prior[-1]
        growth = 1.0
        if h.get("employees") and latest.get("employees") and h["employees"] > 0:
            growth = float(latest["employees"]) / float(h["employees"])
            growth = min(max(growth, 0.5), 3.0)
        p50 = float(h["turnover"]) * growth
        return {"tier": "A-rolled", "p10": p50 * 0.85, "p50": p50, "p90": p50 * 1.15, "period_end": str(latest["period_end"])[:10],
                "inputs": {"turnover_filed_prior": float(h["turnover"]), "prior_period_end": str(h["period_end"])[:10],
                           "employees_prior": h.get("employees"), "employees_latest": latest.get("employees"), "headcount_growth_factor": round(growth, 3)}}
    gp = latest.get("gross_profit")
    if gp and gp > 0:
        lo, hi = EST["derived_gross_margin"]
        return {"tier": "A-derived", "p10": float(gp) / hi, "p50": float(gp) / ((lo + hi) / 2), "p90": float(gp) / lo,
                "period_end": str(latest["period_end"])[:10],
                "inputs": {"gross_profit_filed": float(gp), "gross_margin_assumed": [lo, hi]}}
    return None


def balance_sheet_cross_checks(latest: dict, ratios: dict | None = None) -> dict:
    """Independent revenue readings from creditor and debtor lines, using the p25 to p75 turnover
    ratios measured on the training set (falls back to the methodology's rule-of-thumb multipliers)."""
    ratios = ratios or {}
    defaults = {"tax_social_security": (15, 20), "trade_debtors": (5, 8.3), "accrued_deferred_income": (1.7, 2.5)}
    out = {}
    for col, label in (("tax_social_security", "tax_and_social_security"), ("trade_debtors", "trade_debtors"), ("accrued_deferred_income", "deferred_income")):
        v = latest.get(col)
        if v and v > 0:
            r = ratios.get(col)
            lo, hi = (r["p25"], r["p75"]) if r else defaults[col]
            out[label] = {"low": round(v * lo), "high": round(v * hi), "multiplier": [lo, hi]}
    return out


# Companies Act size thresholds (turnover). Periods beginning on or after 6 April 2025 use the raised limits.
SIZE_CAPS = {"micro": (632_000, 1_000_000), "small": (10_200_000, 15_000_000), "medium": (36_000_000, 54_000_000)}
SMALL_CATEGORIES = {"SMALL", "TOTAL EXEMPTION FULL", "TOTAL EXEMPTION SMALL", "UNAUDITED ABRIDGED", "AUDITED ABRIDGED", "FILLETED", "AUDIT EXEMPTION SUBSIDIARY"}


BS_CAPS = {"small": (5_100_000, 7_500_000)}


def statutory_cap(account_category: str | None, accounts_type: str | None, employees: float | None, period_start: str | None,
                  balance_sheet_total: float | None = None) -> tuple[float | None, str | None]:
    """Upper bound on turnover implied by the size regime the company filed under. A small company
    with more than 50 staff must be under the turnover limit (two of three tests); medium companies
    are under the medium limit; micro entities under the micro limit."""
    new_regime = bool(period_start) and str(period_start)[:10] >= "2025-04-06"
    idx = 1 if new_regime else 0
    cat = (account_category or "").upper()
    typ = (accounts_type or "").lower()
    if cat == "MICRO ENTITY" or "micro" in typ:
        return SIZE_CAPS["micro"][idx], "micro_entity_turnover_limit"
    if cat in SMALL_CATEGORIES or "filleted" in typ or "abridged" in typ or "smallentities" in typ:
        if employees is not None and employees > 50:
            return SIZE_CAPS["small"][idx], "small_company_turnover_limit"
        if balance_sheet_total is not None and balance_sheet_total > BS_CAPS["small"][idx]:
            # 50 or fewer staff but over the balance-sheet limit: turnover must be the second criterion
            return SIZE_CAPS["small"][idx], "small_company_turnover_limit"
        return None, None
    if cat == "MEDIUM":
        return SIZE_CAPS["medium"][idx], "medium_company_turnover_limit"
    return None, None


def tier_c(latest: dict, log_pred: float, quantiles: dict, band: str, extrapolated: bool, inputs: dict, model_version: str,
           ratios: dict | None = None, account_category: str | None = None) -> dict:
    import math

    q = quantiles.get(band) or {"q10": -math.log(1 + EST["fallback_band_pct"] / 100), "q90": math.log(1 + EST["fallback_band_pct"] / 100)}
    p50 = math.exp(log_pred)
    p10, p90 = math.exp(log_pred + q["q10"]), math.exp(log_pred + q["q90"])
    checks = balance_sheet_cross_checks(latest, ratios)
    flags = []
    bs_total = (latest.get("current_assets") or 0) + (latest.get("fixed_assets") or 0) if (latest.get("current_assets") or latest.get("fixed_assets")) else None
    cap, cap_reason = statutory_cap(account_category, latest.get("accounts_type"), latest.get("employees"), latest.get("period_start"), bs_total)
    if cap is not None and p90 > cap:
        p90 = cap
        flags.append(cap_reason)
        if p50 > cap * 0.9:
            p50 = cap * 0.75
            flags.append("p50_pulled_under_cap")
        if p10 > p50:
            p10 = p50 * 0.6
    return {"tier": "C", "p10": p10, "p50": p50, "p90": p90,
            "period_end": str(latest["period_end"])[:10], "extrapolated": extrapolated,
            "inputs": {**inputs, "headcount_band": band, "residual_q10": round(q["q10"], 3), "residual_q90": round(q["q90"], 3),
                       "model_version": model_version, "balance_sheet_cross_checks": checks, "statutory_cap": cap, "flags": flags}}


def render_band(est: dict) -> str:
    """'~GBP 6M to 9M (Tier C model, FY Mar 2025)' for the company page."""
    def m(v):
        return f"£{v / 1e6:.1f}M" if v >= 1e6 else f"£{v / 1e3:.0f}k"

    pe = est.get("period_end") or ""
    try:
        fy = dt.date.fromisoformat(pe).strftime("FY %b %Y")
    except ValueError:
        fy = pe
    label = {"A": "filed", "A-ocr": "filed, read by OCR", "A-rolled": "filed, rolled forward", "A-derived": "derived from gross profit", "C": "model"}.get(est["tier"], est["tier"])
    if est["tier"] == "A":
        return f"{m(est['p50'])} (Tier A {label}, {fy})"
    return f"~{m(est['p10'])} to {m(est['p90'])} (Tier {est['tier']} {label}, {fy})"


def inputs_json(d: dict) -> str:
    return json.dumps(d, default=str)
