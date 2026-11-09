"""Measured entry profile of the fund, from docs/research/02a and 02b (every row sourced there).

    python -m src.cv_pattern      # writes docs/cv_pattern.json

Three cohorts are kept apart, because they answer different questions:
  core          flagship platform entries 2015 to 2026 with outlier=false (the pattern to replicate)
  core_recent   the same, announced 2024 onwards (where the flagship is today)
  strategic     Strategic Financials Fund and Strategic Fund 2 entries (the mid-market vehicle)
  outliers      everything flagged: US-led, club mega-deals, minority, fund-to-fund, listed as the brief asked
Figures are EUR millions as researched, with GBP equivalents at a flat 1 EUR = 0.85 GBP for the screener's bands.
"""
from __future__ import annotations

import json
import statistics as st
from pathlib import Path

from src.common import REPO, get_logger, now_iso

log = get_logger("cv_pattern")
RESEARCH = REPO / "docs" / "research"
EUR_GBP = 0.85


def _load() -> list[dict]:
    rows = []
    a = RESEARCH / "02a_entries_2015_2020.json"
    b = RESEARCH / "02b_entries_2021_2026.json"
    if a.exists():
        rows += json.loads(a.read_text()).get("entries", [])
    if b.exists():
        d = json.loads(b.read_text())
        rows += d.get("platform_entries", d.get("entries", []))
    return rows


def _q(values: list[float]) -> dict | None:
    v = sorted(x for x in values if isinstance(x, (int, float)) and x is not None)
    if not v:
        return None
    qs = st.quantiles(v, n=4) if len(v) >= 2 else [v[0], v[0], v[0]]
    return {"n": len(v), "min": v[0], "p25": round(qs[0]), "p50": round(st.median(v)), "p75": round(qs[2]), "max": v[-1], "mean": round(st.mean(v))}


def _mix(rows: list[dict], key: str) -> dict:
    out: dict[str, int] = {}
    for r in rows:
        k = str(r.get(key) or "unknown")
        out[k] = out.get(k, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))


def _profile(rows: list[dict], label: str) -> dict:
    ev = [r.get("ev_eur_m") for r in rows]
    return {
        "label": label, "n": len(rows),
        "ev_eur_m": _q(ev),
        "ev_gbp_m": {k: (round(v * EUR_GBP) if isinstance(v, (int, float)) else v) for k, v in (_q(ev) or {}).items()} if _q(ev) else None,
        "equity_eur_m": _q([r.get("equity_eur_m") for r in rows]),
        "revenue_eur_m": _q([r.get("revenue_at_entry_eur_m") for r in rows]),
        "ebitda_eur_m": _q([r.get("ebitda_at_entry_eur_m") for r in rows]),
        "ebitda_gbp_m": {k: (round(v * EUR_GBP) if isinstance(v, (int, float)) else v) for k, v in (_q([r.get("ebitda_at_entry_eur_m") for r in rows]) or {}).items()} if _q([r.get("ebitda_at_entry_eur_m") for r in rows]) else None,
        "headcount": _q([r.get("headcount_at_entry") for r in rows]),
        "deal_type": _mix(rows, "deal_type"),
        "sector": _mix(rows, "sector_cinven"),
        "country": _mix(rows, "hq_country"),
        "lead_office": _mix(rows, "lead_office"),
        "stake": _mix(rows, "cinven_stake"),
        "founder_or_family_involved": _mix(rows, "founder_or_family_involved_at_entry"),
        "fund": _mix(rows, "fund"),
        "entries": [{"name": r.get("name"), "announced": r.get("announced"), "sector": r.get("sector_cinven"), "country": r.get("hq_country"),
                     "deal_type": r.get("deal_type"), "fund": r.get("fund"), "ev_eur_m": r.get("ev_eur_m"), "ebitda_eur_m": r.get("ebitda_at_entry_eur_m"),
                     "revenue_eur_m": r.get("revenue_at_entry_eur_m"), "headcount": r.get("headcount_at_entry"), "seller": r.get("seller"),
                     "founder": r.get("founder_or_family_involved_at_entry"), "outlier_reason": r.get("outlier_reason") or None,
                     "source": (r.get("sources") or [None])[0]} for r in sorted(rows, key=lambda r: str(r.get("announced")))],
    }


def main() -> None:
    rows = _load()
    strategic = [r for r in rows if str(r.get("fund") or "").upper().startswith(("SFF", "SF2", "STRATEGIC"))
                 or "strategic fund" in str(r.get("outlier_reason") or "").lower() or "sff" in str(r.get("outlier_reason") or "").lower()]
    strategic_names = {r["name"] for r in strategic}
    core = [r for r in rows if not r.get("outlier") and r["name"] not in strategic_names]
    outliers = [r for r in rows if r.get("outlier") and r["name"] not in strategic_names]
    recent = [r for r in core if str(r.get("announced") or "") >= "2024-01"]
    uk_core = [r for r in core if str(r.get("hq_country") or "").upper() in ("UK", "UNITED KINGDOM", "GB")]
    out = {
        "computed_at": now_iso(), "eur_gbp": EUR_GBP,
        "source_files": ["docs/research/02a_entries_2015_2020.json", "docs/research/02b_entries_2021_2026.json", "docs/research/01_cinven_firm_profile.md"],
        "core": _profile(core, "Flagship platform entries 2015 to 2026, outliers removed"),
        "core_recent": _profile(recent, "Flagship platform entries announced 2024 onwards"),
        "uk_core": _profile(uk_core, "Flagship entries headquartered in the UK"),
        "strategic": _profile(strategic, "Strategic Financials Fund and Strategic Fund 2 entries"),
        "outliers": _profile(outliers, "Outliers measured and excluded: US-led, club mega-deals, minority stakes, fund-to-fund transfers"),
        "with_outliers": _profile(core + outliers, "Flagship entries with the outliers included, for contrast"),
        "notes": [
            "Published stated minimum equity ticket: EUR 200M (docs/research/02a, meta). Equity per deal is otherwise undisclosed.",
            "Fund 8 announcements: eight of ten investments primary or founder-led (Cinven, Oct 2025); 2015 to 2020 core was 78% secondary buyouts.",
            "Strategic Fund 2 (EUR 2.3B, closed Sep 2026): control positions in founder-owned, asset-light European mid-market businesses in Financial Services, Business Services and TMT.",
        ],
    }
    Path(REPO / "docs" / "cv_pattern.json").write_text(json.dumps(out, indent=1, default=str))
    c = out["core"]
    log.info("core n=%d EV p25/p50/p75 EUR %s; EBITDA %s; headcount %s; deal types %s; strategic n=%d; outliers n=%d",
             c["n"], [c["ev_eur_m"][k] for k in ("p25", "p50", "p75")] if c["ev_eur_m"] else None,
             [c["ebitda_eur_m"][k] for k in ("p25", "p50", "p75")] if c["ebitda_eur_m"] else None,
             [c["headcount"][k] for k in ("p25", "p50", "p75")] if c["headcount"] else None, c["deal_type"], out["strategic"]["n"], out["outliers"]["n"])


if __name__ == "__main__":
    main()
