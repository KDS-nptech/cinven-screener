"""Re-score every ranked company's website-read rubric dimensions with the stricter model (Claude Sonnet),
so the ranked list is ordered on one consistent, less generous scale. Comparables keep their Haiku scores.

  python -m src.score.rescore
"""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor

import polars as pl

from src.common import get_logger, parquet_exists, path, read_parquet
from src.score import rubric as R
from src.score.llm import LLM

log = get_logger("rescore")
STRICT = "claude-sonnet-5-5"


def main():
    raw = read_parquet("scores_raw") if parquet_exists("scores_raw") else read_parquet("scores")
    rk = read_parquet("rankings").filter(pl.col("ranked")).select(["company_number", "name"])
    strict_done = set(raw.filter(pl.col("model") == STRICT)["company_number"].unique().to_list())
    todo = [r for r in rk.to_dicts() if r["company_number"] not in strict_done]
    log.info("%d ranked companies to re-score with %s (%d already)", len(todo), STRICT, len(strict_done))
    if not todo:
        return
    ctx = R.load_context({r["company_number"] for r in todo})
    llm = LLM(R.PROMPT_VERSION + "-strict-b", providers=["anthropic_sonnet55"])
    llm.max_tokens = 7000   # the stricter model writes longer answers; 2,500 tokens truncated one in eight

    def work(r):
        n = r["company_number"]
        f = path("cache") / "web" / f"{n}.json"
        pages = json.loads(f.read_text()).get("pages", []) if f.exists() else []
        if not pages:
            return n, []
        rows, status = R.score_company(llm, n, r["name"], pages, R.structured_facts(n, ctx))
        good = sum(1 for x in rows if x.get("status") == "scored")
        return n, rows if status == "scored" and good >= 6 else []   # a failed or thin answer never replaces existing scores

    with ThreadPoolExecutor(max_workers=4) as pool:
        res = dict(pool.map(work, todo))
    ok = {n for n, rows in res.items() if rows}
    keep = [x for x in raw.to_dicts() if x["company_number"] not in ok]
    new = [x for rows in res.values() for x in rows]
    R._write(keep + new)
    log.info("re-scored %d of %d", len(ok), len(todo))


if __name__ == "__main__":
    main()
