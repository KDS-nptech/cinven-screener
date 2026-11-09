"""Second website discovery pass for at-scale companies the search engine missed.

A model (Claude Sonnet) is asked for the official website of the business behind a legal entity, given its
name, town, SIC text and previous name. The suggestion is only kept when the fetched site verifies it: the
legal name's distinctive tokens, the company number or the model's stated trading name must appear on the
site's pages. Kept rows carry discovery_method "model_suggested_verified"; rejected ones keep no domain.

  python -m src.enrich.suggest [--min-ebitda 8000000] [--limit N]
"""
from __future__ import annotations

import argparse
import json
import re
from concurrent.futures import ThreadPoolExecutor

import polars as pl

from src.common import cfg, get_logger, name_tokens, now_iso, path, read_parquet, write_parquet
from src.enrich import websites as W
from src.score.llm import LLM

log = get_logger("suggest")
SYSTEM = """You identify the official website of UK businesses. You are given a company's legal name as registered at Companies House, its town, its SIC description and any previous name. Holding companies (Topco, Bidco, Holdings) usually trade under a brand: give the trading business's site.
Answer with JSON only: {"domain": "example.co.uk" or null, "trading_name": "name the business trades under" or null, "confidence": "high"|"medium"|"low"}.
Give a domain only when you actually know the business and its site. If you do not recognise the company, return null for domain. Never guess a domain from the name alone."""


def candidates(min_ebitda: float, min_turnover: float) -> list[dict]:
    u = read_parquet("universe")
    routes = cfg()["classifier"].get("routes", [])
    a = u.filter(pl.col("route").is_in(routes) & pl.col("is_group_head").fill_null(True) & (pl.col("provisional") == False)  # noqa: E712
                 & ((pl.col("ebitda_proxy") >= min_ebitda) | (pl.col("ebitda_proxy").is_null() & (pl.col("latest_turnover") >= min_turnover))))
    have = {r["company_number"] for r in W.load_existing().values() if r.get("domain")}
    cols = [c for c in ("company_number", "name", "post_town", "sic_text1", "previous_name", "ebitda_proxy") if c in a.columns]
    return [r for r in a.select(cols).sort("ebitda_proxy", descending=True, nulls_last=True).to_dicts() if r["company_number"] not in have]


def verified(row: dict, blob: dict | None, trading: str | None, final_domain: str) -> str | None:
    pages = (blob or {}).get("pages") or []
    if not pages:
        return None
    text = " ".join((p.get("title") or "") + " " + (p.get("text") or "") for p in pages).upper()
    dom = final_domain.upper().replace("-", "")
    if row["company_number"] in text:
        return "company number on site"
    toks = [t for t in name_tokens(row["name"]) if len(t) >= 3 and t not in {"TOPCO", "BIDCO", "MIDCO", "HOLDCO", "NEWCO", "INVESTMENTS", "PUBLIC", "GLOBAL", "MANAGEMENT", "TRADING", "ENTERPRISES", "INVESTMENT", "CAPITAL", "PARTNERS"}]
    if toks and all(t in text or t in dom for t in toks[:2]):
        return "legal name on site"
    legal = re.sub(r"\s+", " ", re.sub(r"\b(LIMITED|LTD\.?)\b", "", row["name"].upper())).strip()
    if len(legal) >= 6 and legal in text:
        return "legal name on site"
    tt = [t for t in name_tokens(trading or "") if len(t) >= 4]
    if tt and all(t in text[:6000] or t in dom for t in tt[:2]) and any(t in dom for t in tt):
        return "trading name on site and in domain"
    return None


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-ebitda", type=float, default=float(cfg()["target"]["ebitda_early_floor_gbp"]))
    ap.add_argument("--min-turnover", type=float, default=float(cfg()["target"]["rank_turnover_min_gbp"]))
    ap.add_argument("--limit", type=int)
    a = ap.parse_args(argv)
    todo = candidates(a.min_ebitda, a.min_turnover)
    if a.limit:
        todo = todo[: a.limit]
    log.info("%d at-scale companies without a website", len(todo))
    llm = LLM("suggest-site-v1", providers=["anthropic_sonnet55"])
    fetcher = W.DomainFetcher(cfg()["websites"])
    web_dir = path("cache") / "web"
    web_dir.mkdir(parents=True, exist_ok=True)

    uu = read_parquet("universe").select(["company_number", "name", "group_head"])
    subs: dict[str, list] = {}
    for x in uu.filter(pl.col("group_head") != pl.col("company_number")).to_dicts():
        subs.setdefault(x["group_head"], []).append(x["name"])
    prev_none = {k for k, v in W.load_existing().items() if v.get("discovery_method") == "model_suggested_none"}

    def work(r: dict) -> dict:
        user = f"Legal name: {r['name']}\nTown: {r.get('post_town') or 'n/a'}\nSIC: {r.get('sic_text1') or 'n/a'}\nPrevious name: {r.get('previous_name') or 'none'}"
        if r["company_number"] in prev_none and subs.get(r["company_number"]):
            user += "\nUK subsidiaries that report into it: " + "; ".join(sorted(subs[r["company_number"]])[:12])
        d = llm.complete_json(SYSTEM, user).data or {}
        dom = W.registered_domain(str(d.get("domain") or "")) if d.get("domain") else None
        row = {"company_number": r["company_number"], "domain": None, "homepage_url": None, "discovery_method": "model_suggested_none",
               "matched_title": d.get("trading_name"), "candidates_json": json.dumps({"suggested": d.get("domain"), "confidence": d.get("confidence")}), "discovered_at": now_iso()}
        if not dom or W.is_directory_host(dom):
            return row
        try:
            summary, blob = fetcher.fetch_domain(r["company_number"], f"https://{dom}/", dom, name=r["name"])
        except Exception as e:  # noqa: BLE001
            row["discovery_method"] = "model_suggested_unreachable"
            log.info("%s %s -> %s unreachable (%s)", r["company_number"], r["name"], dom, type(e).__name__)
            return row
        why = verified(r, blob, d.get("trading_name"), dom)
        if not why:
            row["discovery_method"] = "model_suggested_rejected"
            log.info("%s %-40s -> %s REJECTED", r["company_number"], r["name"][:40], dom)
            return row
        (web_dir / f"{r['company_number']}.json").write_text(json.dumps(blob, ensure_ascii=False))
        summary["name_match"] = True
        row.update(summary)
        row.update(domain=dom, homepage_url=f"https://{dom}/", discovery_method="model_suggested_verified",
                   candidates_json=json.dumps({"suggested": d.get("domain"), "confidence": d.get("confidence"), "verified_by": why}))
        log.info("%s %-40s -> %s (%s)", r["company_number"], r["name"][:40], dom, why)
        return row

    with ThreadPoolExecutor(max_workers=4) as pool:
        out = list(pool.map(work, todo))
    merged = W.load_existing()
    for r in out:
        prev = merged.get(r["company_number"], {})
        if r["domain"] or not prev.get("domain"):
            merged[r["company_number"]] = {**prev, **r}
    write_parquet(W.websites_frame(list(merged.values())), W.WEBSITES_TABLE)
    n = sum(1 for r in out if r["domain"])
    log.info("verified %d of %d; rejected %d; unknown to the model %d", n, len(out), sum(1 for r in out if r["discovery_method"] == "model_suggested_rejected"),
             sum(1 for r in out if r["discovery_method"] == "model_suggested_none"))


if __name__ == "__main__":
    main()
