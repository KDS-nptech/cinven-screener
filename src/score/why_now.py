"""Stage 10b: "why now" timing signals from data the screener already holds.

Every signal is a dated fact from the register, the accounts or the careers page, written
with its source so the reader can check it. They are hypotheses about timing, never part of
either score: a founder in her sixties with no outside capital is a reason to call, a recent
allotment is a reason to ask who bought in. Signals carry a direction:
  approach  - a reason the conversation may be welcome now
  caution   - something to ask about before assuming the company is available
  context   - neutral background worth having in the room

Inputs: universe, filings, officers, charges, jobs, accounts_wide.
Outputs: why_now.parquet (one row per signal) and why_now_summary.parquet (one row per
company with counts and a short line). Rankings joins the summary when it is present.

Run: python -m src.score.why_now
"""
from __future__ import annotations

import datetime as dt
import json
import re
import sys

import polars as pl

from src.common import cfg, get_logger, now_iso, parquet_exists, read_parquet, write_parquet

log = get_logger("why_now")

SENIOR_COMMERCIAL = re.compile(
    r"\b(chief revenue|cro\b|chief commercial|cco\b|vp,? ?(of )?(sales|revenue|marketing|customer|partnerships|growth)|"
    r"head of (sales|revenue|growth|partnerships|commercial|marketing|customer success|business development|bd)|"
    r"(sales|commercial|revenue|partnerships|growth|marketing) director|director(,| of) (sales|revenue|partnerships|growth|commercial|marketing)|"
    r"country manager|general manager|managing director)", re.I)
FINANCE_LEADER = re.compile(r"\b(cfo|chief financial|finance director|head of finance|financial controller|vp,? ?(of )?finance)\b", re.I)
PSC_TYPES = {"PSC01", "PSC02", "PSC04", "PSC05", "PSC07", "PSC08", "PSC09"}
AA_CATEGORY = re.compile(r"accounts-with-accounts-type-(.*)")
SMALL_AA = {"total-exemption-full", "total-exemption-small", "small", "micro-entity", "dormant", "abridged", "filleted"}


def _d(s) -> dt.date | None:
    try:
        return dt.date.fromisoformat(str(s)[:10]) if s else None
    except ValueError:
        return None


def _months(a: dt.date, b: dt.date) -> int:
    return max(0, (b.year - a.year) * 12 + (b.month - a.month))


def _vals(r: dict) -> dict:
    try:
        return json.loads(r.get("description_values_json") or "{}") or {}
    except json.JSONDecodeError:
        return {}


def _name(s: str | None) -> str:
    s = re.sub(r"\s+", " ", str(s or "")).strip()
    if "," in s:   # officers are filed as "SURNAME, Given Names"
        surname, given = s.split(",", 1)
        s = f"{given.strip()} {surname.strip()}"
    return s.title()


def _surname_tokens(s: str | None) -> set[str]:
    return {t for t in re.split(r"[^a-z]+", str(s or "").lower()) if len(t) >= 3 and t not in {"mr", "mrs", "ms", "dr", "miss", "the"}}


def signals_for(n: str, u: dict, filings: list[dict], officers: list[dict], charges: list[dict], jobs: list[dict], accounts: list[dict], as_of: dt.date) -> list[dict]:
    out: list[dict] = []
    def add(signal, label, date, detail, source, direction):
        out.append({"company_number": n, "signal": signal, "label": label, "date": date.isoformat() if isinstance(date, dt.date) else (date or None),
                    "detail": detail, "source": source, "direction": direction})
    twelve = as_of - dt.timedelta(days=365)
    eighteen = as_of - dt.timedelta(days=548)

    # 1. Funding age: SH01 allotments on the filing history.
    sh01 = sorted([f for f in filings if f.get("type") == "SH01" and _d(f.get("date"))], key=lambda f: f["date"])
    inc = _d(u.get("inc_date"))
    if not sh01:
        yrs = round((as_of - inc).days / 365.25) if inc else None
        add("funding_age", "No share allotments on the register", None,
            f"No SH01 filed since incorporation{f' ({yrs} years)' if yrs else ''}: no outside equity visible, so the founders own the timing.",
            "Companies House filing history", "approach")
    else:
        last = sh01[-1]
        last_d = _d(last["date"])
        cap = (_vals(last).get("capital") or [{}])[0]
        cap_txt = f"; share capital after the allotment {cap.get('currency', '')} {cap.get('figure', '')}".rstrip("; ") if cap.get("figure") else ""
        m = _months(last_d, as_of)
        if m <= 12:
            add("funding_age", f"Share allotment {m} month{'s' if m != 1 else ''} ago", last_d,
                f"SH01 filed {last['date']}{cap_txt}. Could be new money, an option exercise or a founder reshuffle: ask who subscribed.",
                "Companies House filing history (SH01)", "caution")
        elif m >= 36:
            add("funding_age", f"Last allotment {m // 12} years ago", last_d,
                f"{len(sh01)} SH01 filing{'s' if len(sh01) > 1 else ''} in total, the latest {last['date']}{cap_txt}. Any early money has aged; investors from that period may want liquidity.",
                "Companies House filing history (SH01)", "approach")
        else:
            add("funding_age", f"Last allotment {m} month{'s' if m != 1 else ''} ago", last_d, f"{len(sh01)} SH01 filing{'s' if len(sh01) > 1 else ''} in total, the latest {last['date']}{cap_txt}.",
                "Companies House filing history (SH01)", "context")

    # 2. Ownership register movement in the last 12 months, grouped by effective date.
    psc_moves = [f for f in filings if f.get("type") in PSC_TYPES and (_d(f.get("date")) or dt.date.min) >= twelve]
    groups: dict[str, list[dict]] = {}
    for f in psc_moves:
        v = _vals(f)
        eff = v.get("cessation_date") or v.get("notification_date") or v.get("change_date") or f["date"]
        groups.setdefault(eff, []).append(f)
    for eff, fs in sorted(groups.items(), reverse=True)[:2]:
        parts, new_psc = [], False
        for f in sorted(fs, key=lambda f: f["type"]):
            v = _vals(f)
            who = _name(v.get("psc_name")) or "a PSC"
            kind = {"PSC07": "ceased", "PSC02": "notified as a new PSC", "PSC01": "notified as a new PSC", "PSC04": "details changed",
                    "PSC05": "details changed", "PSC08": "statement filed", "PSC09": "statement withdrawn"}.get(f["type"], f["type"])
            new_psc |= f["type"] in {"PSC01", "PSC02"}
            parts.append(f"{who} {kind}")
        ceased = [p for p in parts if p.endswith(" ceased")]
        label = (ceased[0] + " as a PSC") if ceased else parts[0]
        if len(parts) > 1:
            label += f" (+{len(parts) - 1} more)"
        add("ownership_change", label, _d(eff),
            f"Effective {eff}: " + "; ".join(parts) + f". Forms filed {', '.join(sorted({f['date'] for f in fs}))}. The cap table moved within the year: find out why before the meeting.",
            "Companies House filing history (PSC forms)", "caution" if new_psc else "approach")

    # 3. Board changes in the last 12 months (appointments and departures, with names).
    appts = [f for f in filings if f.get("type") == "AP01" and (_d(f.get("date")) or dt.date.min) >= twelve]
    terms = [f for f in filings if f.get("type") == "TM01" and (_d(f.get("date")) or dt.date.min) >= twelve]
    if appts:
        names = [_name(_vals(f).get("officer_name")) for f in sorted(appts, key=lambda f: f["date"], reverse=True)]
        fin = [x for x in names if FINANCE_LEADER.search(x)]
        add("board_change", f"{len(appts)} director{'s' if len(appts) > 1 else ''} appointed in the last 12 months", _d(max(f["date"] for f in appts)),
            "Appointed: " + ", ".join(x for x in names[:4] if x) + (" and others" if len(names) > 4 else "") + ". A new board seat often precedes a process; occupations are not on the register, so check the title on LinkedIn." + (" Finance title in the name: " + ", ".join(fin) if fin else ""),
            "Companies House filing history (AP01)", "approach")
    if terms:
        names = [_name(_vals(f).get("officer_name")) for f in sorted(terms, key=lambda f: f["date"], reverse=True)]
        psc_names = set()
        try:
            for p in json.loads(u.get("individual_pscs_json") or "[]"):
                psc_names |= _surname_tokens(p.get("surname") or p.get("name"))
        except json.JSONDecodeError:
            pass
        owner_left = [x for x in names if _surname_tokens(x) & psc_names]
        add("board_change", f"{len(terms)} director{'s' if len(terms) > 1 else ''} left in the last 12 months", _d(max(f["date"] for f in terms)),
            "Left: " + ", ".join(x for x in names[:4] if x) + (" and others" if len(names) > 4 else "") + (". A departing director shares a surname with a PSC: " + ", ".join(owner_left) + ", which can mean a shareholder stepping back." if owner_left else "."),
            "Companies House filing history (TM01)", "approach" if owner_left else "context")

    # 4. Founder-director tenure and age (register year of birth), for succession timing.
    act = [o for o in officers if (o.get("role") or "") == "director" and not o.get("resigned_on") and o.get("appointed_on")]
    psc_tokens = set()
    try:
        for p in json.loads(u.get("individual_pscs_json") or "[]"):
            psc_tokens |= _surname_tokens(p.get("surname") or p.get("name"))
    except json.JSONDecodeError:
        pass
    seen = set()
    for o in sorted(act, key=lambda o: o["appointed_on"]):
        if not (_surname_tokens(o.get("name")) & psc_tokens) or o.get("name") in seen:
            continue
        seen.add(o.get("name"))
        ap = _d(o["appointed_on"])
        tenure = round((as_of - ap).days / 365.25) if ap else None
        age = (as_of.year - int(o["dob_year"])) if o.get("dob_year") else None
        if age and age >= 55:
            add("founder_tenure", f"{_name(o['name'])}: owner-director aged about {age}, {tenure} years on the board", ap,
                f"Year of birth {o['dob_year']} on the register; appointed {o['appointed_on']}. Succession and liquidity become live questions in this decade.",
                "Companies House officers (date of birth month and year is public)", "approach")
        elif tenure and tenure >= 15:
            add("founder_tenure", f"{_name(o['name'])}: owner-director for {tenure} years", ap,
                f"Appointed {o['appointed_on']}" + (f"; year of birth {o['dob_year']}" if o.get("dob_year") else "") + ". A long hold with no outside capital is the profile that takes a first institutional partner.",
                "Companies House officers", "context")

    # 5. Debt: charges created or satisfied in the last 18 months.
    for c in charges:
        cd = _d(c.get("created_on"))
        sd = _d(c.get("satisfied_on"))
        who = ", ".join(_name(x) for x in (c.get("persons_entitled") or [])[:2])
        if cd and cd >= eighteen and not sd:
            add("charge", f"Charge taken by {who or 'a lender'}", cd, f"Created {c['created_on']}; {c.get('classification_description') or 'charge'}. Debt on the balance sheet is a reason to ask about use of proceeds and whether a refinancing is coming.",
                "Companies House charges register", "caution")
        elif sd and sd >= eighteen:
            add("charge", f"Charge satisfied ({who or 'lender'})", sd, f"Satisfied {c['satisfied_on']}; created {c.get('created_on')}. A cleared facility lowers the bar for a minority round.",
                "Companies House charges register", "approach")

    # 6. Headcount acceleration or contraction from filed average employees.
    pts = sorted({(_d(a["period_end"]), float(a["employees"])) for a in accounts if a.get("employees") and _d(a.get("period_end"))})
    pts = [p for p in pts if p[0]]
    if len(pts) >= 3:
        (d0, e0), (d1, e1), (d2, e2) = pts[-3], pts[-2], pts[-1]
        g1 = (e1 / e0 - 1) if e0 else None
        g2 = (e2 / e1 - 1) if e1 else None
        if g1 is not None and g2 is not None:
            if g2 >= 0.10 and g2 >= g1 + 0.05:
                add("headcount_trend", f"Headcount growth accelerating: {g1:+.0%} then {g2:+.0%}", d2,
                    f"Average employees {e0:.0f} ({d0}), {e1:.0f} ({d1}), {e2:.0f} ({d2}). Hiring ahead of revenue usually needs capital within 18 months.",
                    "Filed accounts (average employees note)", "approach")
            elif g2 <= -0.10:
                add("headcount_trend", f"Headcount fell {g2:+.0%} in the latest year", d2,
                    f"Average employees {e1:.0f} ({d1}) to {e2:.0f} ({d2}). A contraction to explain: lost contract, offshoring, or a deliberate reset.",
                    "Filed accounts (average employees note)", "caution")
    elif len(pts) == 2:
        (d1, e1), (d2, e2) = pts[-2], pts[-1]
        g2 = (e2 / e1 - 1) if e1 else None
        if g2 is not None and g2 >= 0.25:
            add("headcount_trend", f"Headcount up {g2:+.0%} in the latest year", d2, f"Average employees {e1:.0f} ({d1}) to {e2:.0f} ({d2}).",
                "Filed accounts (average employees note)", "approach")
        elif g2 is not None and g2 <= -0.10:
            add("headcount_trend", f"Headcount fell {g2:+.0%} in the latest year", d2, f"Average employees {e1:.0f} ({d1}) to {e2:.0f} ({d2}).",
                "Filed accounts (average employees note)", "caution")

    # 7. Accounts category stepped up (small to medium or full) in the latest filing.
    aa = sorted([f for f in filings if f.get("type") == "AA" and AA_CATEGORY.search(f.get("description") or "")], key=lambda f: f["date"])
    if len(aa) >= 2:
        cur, prev = AA_CATEGORY.search(aa[-1]["description"]).group(1), AA_CATEGORY.search(aa[-2]["description"]).group(1)
        if prev in SMALL_AA and cur not in SMALL_AA:
            add("accounts_category", f"Accounts stepped up from {prev} to {cur}", _d(aa[-1]["date"]),
                f"Latest accounts filed {aa[-1]['date']} as '{cur}', the prior year as '{prev}'. Crossing the small-company thresholds (turnover £15M, 50 staff, £7.5M balance sheet, two of three) means more disclosure from here and often a first outside shareholder.",
                "Companies House filing history (AA)", "approach")

    # 8. Hiring: open senior commercial roles and roles outside the UK.
    if jobs:
        senior = [j for j in jobs if SENIOR_COMMERCIAL.search(j.get("title") or "")]
        intl = [j for j in jobs if (j.get("country_guess") or "UK") not in ("UK", "United Kingdom", "")]
        fin = [j for j in jobs if FINANCE_LEADER.search(j.get("title") or "")]
        if senior:
            add("hiring", f"{len(senior)} senior commercial role{'s' if len(senior) > 1 else ''} open", None,
                "Open: " + "; ".join((j.get("title") or "").strip() for j in senior[:3]) + (" and others" if len(senior) > 3 else "") + ". Building a commercial leadership layer is what founders do a year before they raise or sell.",
                "Careers page (" + (jobs[0].get("ats") or "ATS") + ")", "approach")
        if fin:
            add("hiring", f"Finance leader being hired: {(fin[0].get('title') or '').strip()}", None,
                "A first CFO or finance director is the classic pre-process hire.", "Careers page (" + (jobs[0].get("ats") or "ATS") + ")", "approach")
        if intl and len(intl) >= max(2, 0.3 * len(jobs)):
            countries = sorted({j.get("country_guess") for j in intl if j.get("country_guess")})
            all_abroad = len(intl) == len(jobs) and len(jobs) >= 3
            add("hiring", f"{len(intl)} of {len(jobs)} open roles outside the UK", None,
                "Locations: " + ", ".join(countries[:5]) + (". Every open role is abroad: confirm the careers page belongs to this company and not a namesake before reading it as expansion." if all_abroad else ". International expansion from a UK base is the growth-capital use case."),
                "Careers page (" + (jobs[0].get("ats") or "ATS") + ")", "caution" if all_abroad else "approach")
    return out


def main(argv=None):
    as_of = dt.date.fromisoformat(cfg()["build"]["as_of_date"])
    uni = read_parquet("universe")
    if parquet_exists("rankings"):
        targets = set(read_parquet("rankings")["company_number"].to_list())
    elif parquet_exists("classification"):
        targets = set(read_parquet("classification").filter(pl.col("vertical").is_in(cfg()["target"]["verticals"]))["company_number"].to_list())
    else:
        targets = set(uni["company_number"].to_list())
    uni = uni.filter(pl.col("company_number").is_in(list(targets)))
    log.info("companies: %d", uni.height)

    def by_company(table: str) -> dict[str, list[dict]]:
        if not parquet_exists(table):
            return {}
        df = read_parquet(table).filter(pl.col("company_number").is_in(list(targets)))
        out: dict[str, list[dict]] = {}
        for r in df.to_dicts():
            out.setdefault(r["company_number"], []).append(r)
        return out

    filings, officers, charges, jobs, accounts = by_company("filings"), by_company("officers"), by_company("charges"), by_company("jobs"), by_company("accounts_wide")
    rows, summary = [], []
    for u in uni.to_dicts():
        n = u["company_number"]
        sig = signals_for(n, u, filings.get(n, []), officers.get(n, []), charges.get(n, []), jobs.get(n, []), accounts.get(n, []), as_of)
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
    counts = pl.DataFrame(rows, schema=schema).group_by(["signal", "direction"]).len().sort(["signal", "direction"]) if rows else None
    log.info("signals: %d rows for %d companies\n%s", len(rows), len(summary), counts)


if __name__ == "__main__":
    main(sys.argv[1:])
