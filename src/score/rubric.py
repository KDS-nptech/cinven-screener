"""Stage 9: AI-durability rubric, adapted from Mark Dzialga (Brighton Park Capital, Feb 2026).

One LLM call per company returns ten dimension scores with a verbatim quote each. Quotes
are validated against the fetched website text or the structured FACT lines; dimensions
whose quote fails validation are re-asked once, then stored as `unscored`.

Inputs: classification.parquet (shortlist = target verticals), universe, websites,
accounts_wide, charges, registers, jobs_summary, data/cache/web/<n>.json
Output: scores.parquet (company x dimension), durability.parquet (company)

Run: python -m src.score.rubric [--limit N] [--numbers a,b] [--include-excluded]
"""
from __future__ import annotations

import argparse
import json
import sys

import polars as pl

from src.common import REPO, cfg, get_logger, now_iso, parquet_exists, path, read_parquet, write_parquet
from src.score.llm import LLM, quote_in_text

log = get_logger("rubric")
RUBRIC = cfg()["rubric"]
PROMPT_VERSION = RUBRIC["prompt_version"]
SYSTEM = (REPO / "src" / "score" / "prompts" / f"{PROMPT_VERSION.replace('rubric-', 'rubric_')}.md").read_text()
TEXT_BUDGET = 7500
FACT_URLS = {"companies_house", "fca_register", "ats_jobs", "none"}


def _fmt_money(v) -> str:
    if v is None:
        return "n/a"
    return f"GBP {v / 1e6:.1f}M" if abs(v) >= 1e6 else f"GBP {v:,.0f}"


def structured_facts(n: str, ctx: dict) -> list[str]:
    """Plain-language FACT lines the model may quote verbatim."""
    facts = ["FACT: no evidence found"]
    cls = ctx["classification"].get(n)
    if cls:
        facts.append(f"FACT: classifier label {cls['vertical']} ({cls.get('sub_vertical') or 'n/a'}), confidence {cls.get('confidence')}")
    hc = ctx["headcount"].get(n) or []
    if hc:
        series = ", ".join(f"{p}: {int(e)}" for p, e in hc)
        facts.append(f"FACT: average employees by period end {series}")
        if len(hc) >= 2 and hc[0][1] and hc[-1][1]:
            try:
                years = max(0.5, (hc[-1][0] - hc[0][0]).days / 365.25)
                cagr = (hc[-1][1] / hc[0][1]) ** (1 / years) - 1
                facts.append(f"FACT: headcount CAGR {cagr * 100:+.0f}% a year over {years:.1f} years")
            except Exception:
                pass
    acc = ctx["accounts"].get(n)
    if acc:
        facts.append(f"FACT: latest accounts {acc.get('accounts_type') or 'n/a'} for period ending {acc.get('period_end')}, turnover {_fmt_money(acc.get('turnover'))}, "
                     f"accruals and deferred income {_fmt_money(acc.get('accrued_deferred_income'))}, consolidated {acc.get('consolidated')}")
    ch = ctx["charges"].get(n) or []
    if ch:
        outstanding = [c for c in ch if (c.get("status") or "").lower().startswith("outstanding") or not c.get("satisfied_on")]
        recent = [c for c in outstanding if c.get("created_on") and str(c["created_on"]) >= ctx["recent_cutoff"]]
        holders = sorted({p for c in outstanding for p in (c.get("persons_entitled") or [])})[:4]
        facts.append(f"FACT: {len(outstanding)} outstanding charges, {len(recent)} created in the last 18 months, held by {', '.join(holders) or 'n/a'}")
    else:
        facts.append("FACT: no outstanding charges on the Companies House register")
    own = ctx["universe"].get(n)
    if own:
        facts.append(f"FACT: ownership {own.get('founder_flag')} ({own.get('founder_confidence') or 'n/a'}), {own.get('n_individual_pscs') or 0} individual PSCs, "
                     f"{own.get('n_corporate_pscs') or 0} corporate PSCs, walk-up path {own.get('walkup_path') or 'none'}, flags {', '.join(own.get('flags') or []) or 'none'}")
    reg = ctx["registers"].get(n)
    if reg and reg.get("fca_status"):
        facts.append(f"FACT: FCA register status {reg['fca_status']} (FRN {reg.get('fca_frn')}), {reg.get('fca_permissions_count') or 0} permissions")
    elif reg:
        facts.append("FACT: not found on the FCA register under this company name")
    else:
        facts.append("FACT: FCA register not checked")
    jobs = ctx["jobs"].get(n)
    if jobs:
        facts.append(f"FACT: {jobs.get('open_roles') or 0} open roles, engineering share {round((jobs.get('engineering_share') or 0) * 100)}%, "
                     f"{jobs.get('ai_roles') or 0} AI roles, {jobs.get('international_roles') or 0} roles outside the UK, functions {jobs.get('functions_json')}")
    web = ctx["websites"].get(n)
    if web:
        facts.append(f"FACT: website signals: api docs {web.get('api_docs_url') or 'none'}, github {web.get('github_org') or 'none'}, "
                     f"{web.get('integrations_count') or 0} named integrations, pricing page {bool(web.get('pricing_hint'))}, ATS {web.get('ats') or 'none'}")
    return facts


def build_user(name: str, pages: list[dict], facts: list[str]) -> tuple[str, str, set[str]]:
    parts, used, urls = [], 0, set()
    for p in pages:
        txt = (p.get("text") or "").strip()
        if not txt or TEXT_BUDGET - used <= 200:
            continue
        chunk = txt[: TEXT_BUDGET - used]
        parts.append(f"--- PAGE: {p.get('url')}\nTITLE: {p.get('title') or ''}\n{chunk}")
        urls.add(p.get("url"))
        used += len(chunk)
    body = "\n\n".join(parts)
    user = (f"Company: {name}\n\nSTRUCTURED FACTS (each line may be quoted exactly):\n" + "\n".join(facts) +
            f"\n\nPage URLs supplied: {json.dumps(sorted(urls))}\n\nWEBSITE TEXT:\n{body}\n\nReturn the JSON object now.")
    return user, body, urls


def validate_dim(d: dict, body: str, urls: set[str], facts: list[str]) -> list[str]:
    probs = []
    try:
        s = int(d.get("score"))
        if s < 1 or s > 5:
            probs.append("bad_score")
    except (TypeError, ValueError):
        probs.append("bad_score")
    q = str(d.get("evidence_quote") or "")
    fact_match = any(q.strip() == f for f in facts) or any(quote_in_text(q, f) and len(q) > 20 for f in facts)
    if not (fact_match or quote_in_text(q, body)):
        probs.append("quote_not_verbatim")
    if len(q.split()) > 45:
        probs.append("quote_too_long")
    url = d.get("evidence_url")
    if url not in urls and url not in FACT_URLS:
        probs.append("bad_url")
    if d.get("confidence") not in {"high", "medium", "low"}:
        probs.append("bad_confidence")
    return probs


def score_company(llm: LLM, n: str, name: str, pages: list[dict], facts: list[str]) -> tuple[list[dict], str]:
    user, body, urls = build_user(name, pages, facts)
    res = llm.complete_json(SYSTEM, user)
    if res.error in ("pending_batch", "quota_exhausted"):
        return [], "pending_batch"
    dims = _dims(res.data)
    failed = {k: validate_dim(v, body, urls, facts) for k, v in dims.items()}
    failed = {k: v for k, v in failed.items() if v}
    missing = [k for k in range(1, 11) if k not in dims]
    if failed or missing:
        retry = (user + "\n\nYour previous answer failed validation for dimensions " +
                 ", ".join(str(k) for k in sorted(set(failed) | set(missing))) + ": " +
                 "; ".join(f"{k}: {', '.join(v)}" for k, v in sorted(failed.items())) +
                 ". Every evidence_quote must be an exact contiguous substring of the WEBSITE TEXT or an exact FACT line. Return all ten dimensions again.")
        res2 = llm.complete_json(SYSTEM, retry)
        if res2.error == "quota_exhausted":
            return [], "pending_batch"
        dims2 = _dims(res2.data)
        for k in range(1, 11):
            if k in dims2 and not validate_dim(dims2[k], body, urls, facts):
                dims[k] = dims2[k]
                failed.pop(k, None)
            elif k in missing and k in dims2:
                dims[k] = dims2[k]
                failed[k] = validate_dim(dims2[k], body, urls, facts)
        missing = [k for k in range(1, 11) if k not in dims]
        if res2.data:
            res = res2
    rows = []
    for k in range(1, 11):
        d = dims.get(k)
        probs = failed.get(k) or (["missing"] if k in missing else [])
        if d is None or probs:
            rows.append({"company_number": n, "dimension": k, "dimension_name": RUBRIC["dimension_names"][k], "score": None,
                         "rationale": (d or {}).get("rationale"), "evidence_quote": (d or {}).get("evidence_quote"), "evidence_url": None,
                         "confidence": "unscored", "status": "unscored", "problems": probs, "model": res.model,
                         "prompt_version": PROMPT_VERSION, "computed_at": now_iso()})
        else:
            rows.append({"company_number": n, "dimension": k, "dimension_name": RUBRIC["dimension_names"][k], "score": int(d["score"]),
                         "rationale": str(d.get("rationale") or "")[:300], "evidence_quote": str(d.get("evidence_quote") or "")[:400],
                         "evidence_url": d.get("evidence_url"), "confidence": d.get("confidence"), "status": "scored", "problems": [],
                         "model": res.model, "prompt_version": PROMPT_VERSION, "computed_at": now_iso()})
    return rows, "scored"


def _dims(data) -> dict[int, dict]:
    out = {}
    if not isinstance(data, dict):
        return out
    items = data.get("scores") if isinstance(data.get("scores"), list) else None
    if items is None and all(str(k).isdigit() for k in data.keys()):
        items = [dict(v, dimension=int(k)) for k, v in data.items() if isinstance(v, dict)]
    for it in items or []:
        try:
            k = int(it.get("dimension"))
        except (TypeError, ValueError):
            continue
        if 1 <= k <= 10:
            out[k] = it
    return out


def durability(scores: pl.DataFrame) -> pl.DataFrame:
    """Weighted mean of scored dimensions rescaled to 0 to 100; grey flag when 2+ unscored."""
    w = {int(k): float(v) for k, v in RUBRIC["weights"].items()}
    rows = []
    for n, g in scores.group_by("company_number"):
        n = n[0] if isinstance(n, tuple) else n
        scored = [(r["dimension"], r["score"]) for r in g.to_dicts() if r["status"] == "scored" and r["score"] is not None]
        unscored = 10 - len(scored)
        if scored:
            wsum = sum(w[d] for d, _ in scored)
            wmean = sum(w[d] * s for d, s in scored) / wsum
            dur = round((wmean - 1) / 4 * 100, 1)
        else:
            dur = None
        conf = g.filter(pl.col("status") == "scored")["confidence"].to_list()
        rows.append({"company_number": n, "durability_score": dur, "n_unscored": unscored,
                     "grey": unscored >= RUBRIC["min_unscored_for_grey"],
                     "share_high_confidence": round(sum(c == "high" for c in conf) / len(conf), 2) if conf else None,
                     "scores_json": json.dumps({d: s for d, s in scored}), "prompt_version": PROMPT_VERSION, "computed_at": now_iso()})
    return pl.DataFrame(rows)


def adjust_scores(scores: pl.DataFrame, ctx: dict) -> pl.DataFrame:
    """Rule-based corrections applied after the model, both measured in the blind check:
    - Dimension 4 (leading indicators) is scored from the filed headcount trend and open roles,
      which the model ignored (it gave 3 to every company).
    - Dimension 3 (metrics that matter) is capped at 3 when a charge was created in the last
      18 months by a non-bank lender, the leverage signal the model missed."""
    import datetime as dt

    rows = scores.to_dicts()
    cutoff = ctx["recent_cutoff"]
    banks = ("bank", "hsbc", "barclays", "lloyds", "natwest", "santander", "royal bank", "clydesdale", "virgin money", "metro bank",
             "starling", "handelsbanken", "allied irish", "danske", "ulster", "bank of scotland", "tsb", "nationwide", "close brothers")
    for r in rows:
        n = r["company_number"]
        if r["dimension"] == 4:
            hc = ctx["headcount"].get(n) or []
            jobs = ctx["jobs"].get(n) or {}
            cagr = None
            if len(hc) >= 2 and hc[0][1] and hc[-1][1]:
                years = max(0.5, (hc[-1][0] - hc[0][0]).days / 365.25)
                cagr = (hc[-1][1] / hc[0][1]) ** (1 / years) - 1
            eng_open = (jobs.get("open_roles") or 0) * (jobs.get("engineering_share") or 0)
            if cagr is None:
                score, conf, why = 3, "low", "no headcount trend on file"
            elif cagr >= 0.20:
                score, conf, why = 5 if eng_open >= 1 else 4, "high", f"headcount CAGR {cagr * 100:+.0f}% a year" + (", engineering roles open" if eng_open >= 1 else "")
            elif cagr >= 0.08:
                score, conf, why = 4, "high", f"headcount CAGR {cagr * 100:+.0f}% a year"
            elif cagr >= -0.03:
                score, conf, why = 3, "high", f"headcount flat ({cagr * 100:+.0f}% a year)"
            elif cagr >= -0.12:
                score, conf, why = 2, "high", f"headcount shrinking ({cagr * 100:+.0f}% a year)"
            else:
                score, conf, why = 1, "high", f"headcount shrinking fast ({cagr * 100:+.0f}% a year)"
            fact = next((f for f in structured_facts(n, ctx) if f.startswith("FACT: headcount CAGR") or f.startswith("FACT: average employees")), "FACT: no evidence found")
            r.update(score=score, confidence=conf, status="scored", rationale=f"Rule-scored from filings: {why}.", evidence_quote=fact,
                     evidence_url="companies_house", model="rule:headcount-trend", problems=[])
        if r["dimension"] == 3 and r.get("score") and r["score"] > 3:
            ch = ctx["charges"].get(n) or []
            recent = [c for c in ch if not c.get("satisfied_on") and c.get("created_on") and str(c["created_on"])[:10] >= cutoff]
            lenders = [p for c in recent for p in (c.get("persons_entitled") or [])]
            nonbank = [p for p in lenders if not any(b in p.lower() for b in banks)]
            if nonbank:
                r["score"] = 3
                r["rationale"] = (r.get("rationale") or "") + f" Capped at 3: charge created in the last 18 months in favour of {nonbank[0]}."
                r["model"] = (r.get("model") or "") + "+rule:leverage-cap"
    return pl.DataFrame(rows, schema=scores.schema)


def load_context(numbers: set[str]) -> dict:
    import datetime as dt

    ctx = {"classification": {}, "headcount": {}, "accounts": {}, "charges": {}, "universe": {}, "registers": {}, "jobs": {}, "websites": {}}

    ctx["recent_cutoff"] = (dt.date.fromisoformat(cfg()["build"]["as_of_date"]) - dt.timedelta(days=int(30.44 * cfg()["investability"]["leverage_recent_charge_months"]))).isoformat()
    if parquet_exists("classification"):
        for r in read_parquet("classification").filter(pl.col("company_number").is_in(list(numbers))).to_dicts():
            ctx["classification"][r["company_number"]] = r
    if parquet_exists("accounts_wide"):
        aw = read_parquet("accounts_wide").filter(pl.col("company_number").is_in(list(numbers)) & pl.col("employees").is_not_null())
        # prior-year comparatives inside a filing are real headcount figures; keep them for the trend
        for n, g in aw.sort("period_end").group_by("company_number"):
            n = n[0] if isinstance(n, tuple) else n
            ctx["headcount"][n] = [(dt.date.fromisoformat(str(r["period_end"])[:10]), r["employees"]) for r in g.to_dicts() if r.get("period_end")][-4:]
            ctx["accounts"][n] = g.to_dicts()[-1]
    if parquet_exists("charges"):
        for n, g in read_parquet("charges").filter(pl.col("company_number").is_in(list(numbers))).group_by("company_number"):
            n = n[0] if isinstance(n, tuple) else n
            ctx["charges"][n] = g.to_dicts()
    if parquet_exists("universe"):
        for r in read_parquet("universe").filter(pl.col("company_number").is_in(list(numbers))).to_dicts():
            ctx["universe"][r["company_number"]] = r
    if parquet_exists("registers"):
        for r in read_parquet("registers").filter(pl.col("company_number").is_in(list(numbers))).to_dicts():
            ctx["registers"][r["company_number"]] = r
    if parquet_exists("jobs_summary"):
        for r in read_parquet("jobs_summary").filter(pl.col("company_number").is_in(list(numbers))).to_dicts():
            ctx["jobs"][r["company_number"]] = r
    if parquet_exists("websites"):
        for r in read_parquet("websites").filter(pl.col("company_number").is_in(list(numbers))).to_dicts():
            ctx["websites"][r["company_number"]] = r
    return ctx


def shortlist(include_excluded: bool) -> pl.DataFrame:
    cls = read_parquet("classification").filter(pl.col("vertical").is_in(cfg()["target"]["verticals"]))
    ucols = ["company_number", "name", "founder_flag", "founder_confidence"] + (["founder_led"] if "founder_led" in read_parquet("universe").columns else [])
    uni = read_parquet("universe").select(ucols)
    df = cls.join(uni, on="company_number", how="inner")
    if not include_excluded:
        keep = pl.col("founder_flag") != "excluded"
        if "founder_led" in df.columns:
            keep = keep | pl.col("founder_led").fill_null(False)
        df = df.filter(keep)
    return df


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int)
    ap.add_argument("--numbers")
    ap.add_argument("--include-excluded", action="store_true", help="also score excluded companies (comparables and back-tests)")
    ap.add_argument("--workers", type=int, default=3, help="parallel model calls")
    ap.add_argument("--adjust-only", action="store_true", help="re-apply the rule-based corrections to scores_raw and rewrite scores")
    args = ap.parse_args(argv)
    if args.adjust_only:
        raw = read_parquet("scores_raw") if parquet_exists("scores_raw") else read_parquet("scores")
        _write(raw.to_dicts())
        log.info("adjusted %d rows", raw.height)
        return
    if args.numbers:
        nums = args.numbers.split(",")
        uni = read_parquet("universe").select(["company_number", "name"]).filter(pl.col("company_number").is_in(nums))
        if uni.height < len(nums):
            comp = read_parquet("companies").select(["company_number", "name"]).filter(pl.col("company_number").is_in(nums))
            uni = pl.concat([uni, comp.filter(~pl.col("company_number").is_in(uni["company_number"]))])
        todo = uni
    else:
        todo = shortlist(args.include_excluded).select(["company_number", "name"])
    if args.limit:
        todo = todo.head(args.limit)
    existing = read_parquet("scores_raw") if parquet_exists("scores_raw") else (read_parquet("scores") if parquet_exists("scores") else None)
    done = set(existing["company_number"].to_list()) if existing is not None else set()
    rows = existing.to_dicts() if existing is not None else []
    todo = todo.filter(~pl.col("company_number").is_in(list(done)))
    ctx = load_context(set(todo["company_number"].to_list()))
    llm = LLM(PROMPT_VERSION)
    log.info("provider=%s model=%s; %d companies to score (%d done)", llm.provider, llm.model, todo.height, len(done))
    pending = 0
    jobs = []
    for r in todo.to_dicts():
        n = r["company_number"]
        f = path("cache") / "web" / f"{n}.json"
        pages = json.loads(f.read_text()).get("pages", []) if f.exists() else []
        if not pages:
            for k in range(1, 11):
                rows.append({"company_number": n, "dimension": k, "dimension_name": RUBRIC["dimension_names"][k], "score": None, "rationale": None,
                             "evidence_quote": None, "evidence_url": None, "confidence": "unscored", "status": "no_website", "problems": ["no_website"],
                             "model": None, "prompt_version": PROMPT_VERSION, "computed_at": now_iso()})
            continue
        jobs.append((n, r["name"], pages, structured_facts(n, ctx)))

    from concurrent.futures import ThreadPoolExecutor, as_completed

    done_n = 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futs = {pool.submit(score_company, llm, n, name, pages, facts): n for n, name, pages, facts in jobs}
        for fut in as_completed(futs):
            try:
                out, status = fut.result()
            except Exception as e:
                log.error("rubric failed for %s: %s", futs[fut], e)
                continue
            if status == "pending_batch":
                pending += 1
                continue
            rows.extend(out)
            done_n += 1
            if done_n % 10 == 0:
                log.info("%d/%d scored (calls=%d cache_hits=%d pending=%d)", done_n, len(jobs), llm.calls, llm.cache_hits, pending)
                _write(rows)
    _write(rows)
    log.info("done: %d score rows, %d pending", len(rows), pending)


def _write(rows: list[dict], adjust: bool = True):
    schema = {"company_number": pl.Utf8, "dimension": pl.Int32, "dimension_name": pl.Utf8, "score": pl.Int32, "rationale": pl.Utf8,
              "evidence_quote": pl.Utf8, "evidence_url": pl.Utf8, "confidence": pl.Utf8, "status": pl.Utf8, "problems": pl.List(pl.Utf8),
              "model": pl.Utf8, "prompt_version": pl.Utf8, "computed_at": pl.Utf8}
    df = pl.DataFrame([{k: r.get(k) for k in schema} for r in rows], schema=schema)
    write_parquet(df, "scores_raw")
    if adjust and df.height:
        df = adjust_scores(df, load_context(set(df["company_number"].to_list())))
    write_parquet(df, "scores")
    if df.height:
        write_parquet(durability(df), "durability")


if __name__ == "__main__":
    main(sys.argv[1:])
