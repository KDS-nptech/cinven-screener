"""Stage 10b: "why now" timing signals from data the screener already holds.

Every signal is a dated fact from the PSC register, the basic company record or the filed accounts,
written with its source so the reader can check it. They are hypotheses about timing and never part of
either score: a sponsor six years into its hold is a reason to call, a holding company incorporated last
quarter is a reason to ask what is being prepared. Signals carry a direction:
  approach  - a reason the conversation may be welcome now
  caution   - something to ask about before assuming the company is available
  context   - neutral background worth having in the room

Inputs: universe (routes and accounts), psc, companies, jobs (optional), charges (optional).
Outputs: why_now.parquet (one row per signal) and why_now_summary.parquet (one row per company).

Run: python -m src.score.why_now
"""
from __future__ import annotations

import datetime as dt
import json
import re
import sys

import polars as pl

from src.common import cfg, get_logger, now_iso, parquet_exists, read_parquet, read_parquet_where, write_parquet

log = get_logger("why_now")

SENIOR_COMMERCIAL = re.compile(r"\b(chief revenue|cro\b|chief commercial|cco\b|chief executive|ceo\b|chief financial|cfo\b|finance director|managing director|chief operating|coo\b|"
                              r"head of (m&a|corporate development|strategy|integration)|m&a director|corporate development)", re.I)


def _d(s) -> dt.date | None:
    try:
        return dt.date.fromisoformat(str(s)[:10]) if s else None
    except ValueError:
        return None


def _m(v) -> str:
    if v is None:
        return "n/a"
    return f"~£{v / 1e6:,.0f}M" if abs(v) >= 1e6 else f"~£{v / 1e3:,.0f}K"


def signals_for(u: dict, psc_rows: list[dict], holdco_inc: dict[str, dt.date | None], jobs: list[dict], as_of: dt.date) -> list[dict]:
    n = u["company_number"]
    out: list[dict] = []

    def add(signal, label, date, detail, source, direction):
        out.append({"company_number": n, "signal": signal, "label": label, "date": date.isoformat() if isinstance(date, dt.date) else (date or None),
                    "detail": detail, "source": source, "direction": direction})

    twelve = as_of - dt.timedelta(days=365)
    eighteen = as_of - dt.timedelta(days=548)
    route = u.get("route")

    # 1. Sponsor hold period: the secondary window.
    if route in ("sponsor", "sponsor_offshore"):
        hy, hs = u.get("hold_years"), u.get("hold_start")
        who = ", ".join((u.get("sponsor_names") or [])[:2]) or (u.get("parent_name") or "the sponsor")
        if hy is not None and hy >= 6:
            add("sponsor_hold", f"Sponsor {hy:.0f} years into the hold", _d(hs), f"{who} has been the PSC of record since {hs}: past the typical four to six year hold, so an exit process may be near or under way.", "PSC register (notified_on)", "approach")
        elif hy is not None and hy >= 4:
            add("sponsor_hold", f"Sponsor {hy:.0f} years into the hold", _d(hs), f"{who} has been the PSC of record since {hs}: inside the window where sponsors start preparing an exit.", "PSC register (notified_on)", "approach")
        elif hy is not None and hy < 2:
            add("sponsor_hold", f"Acquired by a sponsor {hy:.1f} years ago", _d(hs), f"{who} became the PSC of record on {hs}: a fresh hold, so the business is a watch-list name, and an add-on buyer.", "PSC register (notified_on)", "caution")
        elif hy is not None:
            add("sponsor_hold", f"Sponsor {hy:.1f} years into the hold", _d(hs), f"{who} has been the PSC of record since {hs}.", "PSC register (notified_on)", "context")
        if u.get("founder_rollover"):
            add("rollover", "Founders still hold a stake alongside the sponsor", None, f"Individuals hold ~{u.get('individuals_pct_mid') or 0:.0f}% through the chain: management or founders rolled over, so relationships matter in a secondary.", "PSC register", "context")

    # 2. Founder or family: age and succession.
    if route == "founder_family":
        age = u.get("oldest_owner_age")
        if age is not None and age >= 70:
            add("owner_age", f"Oldest owner is about {age}", None, f"The oldest individual PSC was born in {as_of.year - age}; {u.get('n_individuals') or 0} individual owners hold ~{u.get('individuals_pct_mid') or 0:.0f}%. Succession is the obvious conversation.", "PSC register (year of birth)", "approach")
        elif age is not None and age >= 60:
            add("owner_age", f"Oldest owner is about {age}", None, f"The oldest individual PSC was born in {as_of.year - age}; {u.get('n_individuals') or 0} individual owners hold ~{u.get('individuals_pct_mid') or 0:.0f}%.", "PSC register (year of birth)", "approach")
        if u.get("family_surname_shared"):
            add("family", "Family-owned: owners share a surname", None, f"{u.get('n_individuals') or 0} individual PSCs, at least two with the same surname.", "PSC register", "context")
        if (u.get("n_individuals") or 0) >= 4:
            add("owner_count", f"{u.get('n_individuals')} individual owners", None, "A wide owner group often means a partnership or second-generation family; alignment on a sale takes longer.", "PSC register", "caution")

    # 3. Listed or widely held.
    if route == "plc_dispersed":
        add("plc", "Widely held PLC", None, "The register says nobody holds 25%: a public-to-private route, with the premium and process that implies.", "PSC register (statement)", "context")

    # 4. Register movement in the last 12 months on the company itself.
    recent_new = [r for r in psc_rows if _d(r.get("notified_on")) and _d(r["notified_on"]) >= twelve and r.get("is_active")]
    recent_ceased = [r for r in psc_rows if _d(r.get("ceased_on")) and _d(r["ceased_on"]) >= twelve]
    for r in sorted(recent_new, key=lambda r: str(r.get("notified_on")), reverse=True)[:2]:
        add("psc_new", f"New PSC notified {r['notified_on']}", _d(r.get("notified_on")), f"{r.get('name')} ({str(r.get('kind') or '').replace('-', ' ')}) notified as a person with significant control.", "PSC register", "caution")
    for r in sorted(recent_ceased, key=lambda r: str(r.get("ceased_on")), reverse=True)[:2]:
        add("psc_ceased", f"PSC ceased {r['ceased_on']}", _d(r.get("ceased_on")), f"{r.get('name')} ceased to be a person with significant control.", "PSC register", "context")

    # 5. A holding company incorporated recently at the top of the chain: a deal just closed or a sale being prepared.
    path_ = u.get("walkup_path") or ""
    tops = [hop.split(" -> ")[1] for hop in path_.split("; ") if " -> " in hop]
    for cn in tops[-1:]:
        inc = holdco_inc.get(cn)
        if inc and inc >= eighteen:
            add("new_holdco", f"Holding company incorporated {inc}", inc, f"Company {cn} at the top of the ownership chain was incorporated on {inc}: a recent transaction or a pre-sale reorganisation.", "Companies House (incorporation date)", "caution")

    # 6. Accounts: growth, margin, cash, dividends, leverage, timeliness.
    if u.get("latest_period_end"):
        g = u.get("turnover_growth")
        pe = _d(u.get("latest_period_end"))
        if g is not None and g >= 0.15:
            add("growth", f"Turnover up {g * 100:.0f}%", pe, f"Turnover {_m(u.get('latest_turnover'))} against {_m(u.get('prior_turnover'))} the period before.", "Filed accounts", "approach")
        elif g is not None and g <= -0.10:
            add("growth", f"Turnover down {abs(g) * 100:.0f}%", pe, f"Turnover {_m(u.get('latest_turnover'))} against {_m(u.get('prior_turnover'))} the period before.", "Filed accounts", "caution")
        m = u.get("operating_margin")
        if m is not None and m < 0.03:
            add("margin", f"Operating margin {m * 100:.0f}%", pe, f"Operating profit {_m(u.get('latest_operating_profit'))} on turnover {_m(u.get('latest_turnover'))}.", "Filed accounts", "caution")
        div, op = u.get("latest_dividends"), u.get("latest_operating_profit")
        if div and op and abs(div) >= 0.5 * abs(op) and op > 0:
            add("dividends", f"Dividends {_m(abs(div))} paid", pe, f"Dividends of {_m(abs(div))} against operating profit of {_m(op)}: owners taking cash out, which a sale would replace.", "Filed accounts", "context")
        bb, eb = u.get("latest_bank_borrowings"), u.get("ebitda_proxy")
        if bb and eb and eb > 0 and abs(bb) / eb >= 4:
            add("leverage", f"Bank borrowings ~{abs(bb) / eb:.1f}x EBITDA", pe, f"Bank borrowings {_m(abs(bb))} against EBITDA proxy {_m(eb)}: a refinancing or recapitalisation may be due.", "Filed accounts", "caution")
        ncfo = u.get("latest_net_cash_from_ops")
        if ncfo is not None and ncfo < 0:
            add("cash", "Negative cash from operations", pe, f"Net cash from operating activities {_m(ncfo)} in the latest period.", "Filed accounts", "caution")
        if str(u.get("latest_accounts_type") or "").startswith("PDF"):
            add("accounts_source", "Accounts read from a PDF", pe, "Figures were read from the filed PDF by OCR and a model; verify against the document before quoting.", "Companies House document", "context")
    nd = _d(u.get("next_due_date"))
    if nd and nd < as_of:
        add("overdue", f"Accounts overdue since {nd}", nd, "The next accounts are past their due date on the register.", "Companies House (basic data)", "caution")
    if u.get("previous_name"):
        add("renamed", "Changed its name", None, f"Previously {u['previous_name']}.", "Companies House (basic data)", "context")
    co = u.get("charges_outstanding") or 0
    if co >= 1:
        add("charges", f"{co} outstanding charge{'s' if co != 1 else ''}", None, f"{u.get('charges_total') or 0} registered in total, {u.get('charges_satisfied') or 0} satisfied: secured debt is in place.", "Companies House (basic data)", "context")

    # 7. Senior hires on the public job board.
    senior = [j for j in jobs if SENIOR_COMMERCIAL.search(str(j.get("title") or ""))]
    if senior:
        add("senior_roles", f"{len(senior)} senior role{'s' if len(senior) != 1 else ''} open", None, "; ".join(str(j.get("title")) for j in senior[:3]), "Public job board", "context")
    return out


def main(argv=None):
    as_of = dt.date.fromisoformat(cfg()["build"]["as_of_date"])
    uni = read_parquet("universe")
    if parquet_exists("rankings"):
        targets = set(read_parquet("rankings")["company_number"].to_list())
    elif parquet_exists("classification"):
        targets = set(read_parquet("classification").filter(pl.col("vertical").is_in(cfg()["target"]["sectors"]))["company_number"].to_list())
    else:
        targets = set(uni["company_number"].to_list())
    uni = uni.filter(pl.col("company_number").is_in(list(targets)))
    log.info("companies: %d", uni.height)
    psc = read_parquet_where("psc", "company_number", targets, ["company_number", "kind", "name", "notified_on", "ceased_on", "is_active"])
    psc_by: dict[str, list[dict]] = {}
    for r in psc.to_dicts():
        psc_by.setdefault(r["company_number"], []).append(r)
    tops = set()
    for p in uni["walkup_path"].to_list():
        for hop in (p or "").split("; "):
            if " -> " in hop:
                tops.add(hop.split(" -> ")[1])
    holdco_inc = {}
    if tops and parquet_exists("companies"):
        for r in read_parquet_where("companies", "company_number", tops, ["company_number", "inc_date"]).to_dicts():
            holdco_inc[r["company_number"]] = _d(r["inc_date"])
    jobs_by: dict[str, list[dict]] = {}
    if parquet_exists("jobs"):
        for r in read_parquet("jobs").filter(pl.col("company_number").is_in(list(targets))).to_dicts():
            jobs_by.setdefault(r["company_number"], []).append(r)
    rows, summary = [], []
    for u in uni.to_dicts():
        n = u["company_number"]
        sig = signals_for(u, psc_by.get(n, []), holdco_inc, jobs_by.get(n, []), as_of)
        for s in sig:
            s["computed_at"] = now_iso()
        rows.extend(sig)
        approach = [s for s in sig if s["direction"] == "approach"]
        caution = [s for s in sig if s["direction"] == "caution"]
        summary.append({"company_number": n, "why_now_signals": len(sig), "why_now_approach": len(approach), "why_now_caution": len(caution),
                        "why_now_line": "; ".join(s["label"] for s in (approach + caution)[:3]), "computed_at": now_iso()})
    schema = {"company_number": pl.Utf8, "signal": pl.Utf8, "label": pl.Utf8, "date": pl.Utf8, "detail": pl.Utf8, "source": pl.Utf8, "direction": pl.Utf8, "computed_at": pl.Utf8}
    write_parquet(pl.DataFrame(rows, schema=schema) if rows else pl.DataFrame(schema=schema), "why_now")
    write_parquet(pl.DataFrame(summary, infer_schema_length=None), "why_now_summary")
    if rows:
        counts = pl.DataFrame(rows, schema=schema).group_by(["signal", "direction"]).len().sort(["signal", "direction"])
        log.info("signals: %d rows for %d companies\n%s", len(rows), len(summary), counts)


if __name__ == "__main__":
    main(sys.argv[1:])
