"""Trading name for every company in scope with a fetched website: a model proposes the name the business
trades under from the homepage title and opening text; kept only when that name appears on the page or in
the domain. -> data/parquet/trading_names.parquet

  python -m src.enrich.trading_names
"""
from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor

import polars as pl

from src.common import get_logger, now_iso, parquet_exists, path, read_parquet, write_parquet
from src.score.llm import LLM

log = get_logger("trading_names")
SYSTEM = """You are given a UK company's legal name and text from its website. Return the name the business trades under, exactly as the website writes it (brand capitalisation, no Limited, Ltd, PLC, Holdings, Group Holdings, Topco, Midco or Bidco).
Answer with JSON only: {"trading_name": "..."}. If the site is clearly for a different business, return {"trading_name": null}."""


def main():
    rk = read_parquet("rankings").filter(pl.col("domain").is_not_null()).select(["company_number", "name", "domain"])
    prev = {r["company_number"]: r for r in read_parquet("trading_names").to_dicts()} if parquet_exists("trading_names") else {}
    todo = [r for r in rk.to_dicts() if r["company_number"] not in prev]
    llm = LLM("trading-name-v1", providers=["anthropic_haiku45"])

    def work(r):
        f = path("cache") / "web" / f"{r['company_number']}.json"
        pages = json.loads(f.read_text()).get("pages", []) if f.exists() else []
        if not pages:
            return None
        text = " ".join((p.get("title") or "") + " " + (p.get("text") or "") for p in pages)
        user = f"Legal name: {r['name']}\nDomain: {r['domain']}\nHomepage title: {pages[0].get('title')}\nWebsite text: {(pages[0].get('text') or '')[:1500]}"
        d = llm.complete_json(SYSTEM, user).data or {}
        tn = str(d.get("trading_name") or "").strip()
        ok = bool(tn) and 2 <= len(tn) <= 40 and (tn.lower() in text.lower() or re.sub(r"[^a-z0-9]", "", tn.lower()) in re.sub(r"[^a-z0-9]", "", r["domain"].lower()))
        return {"company_number": r["company_number"], "trading_name": tn if ok else None, "computed_at": now_iso()}

    with ThreadPoolExecutor(max_workers=10) as pool:
        out = [x for x in pool.map(work, todo) if x]
    rows = list(prev.values()) + out
    write_parquet(pl.DataFrame(rows, schema={"company_number": pl.Utf8, "trading_name": pl.Utf8, "computed_at": pl.Utf8}), "trading_names")
    log.info("trading names: %d new, %d kept of %d", len(out), sum(1 for r in rows if r["trading_name"]), len(rows))


if __name__ == "__main__":
    main()
