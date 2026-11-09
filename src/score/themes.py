"""Stage 5b: theme maps. For each theme in config.themes, every company in the universe whose
fetched site text uses the theme's vocabulary, with the sentence that matched. No model call.

A theme map is how an end-market sourcing team works: all the players in one space, founder-owned
or not, with size, ownership and the register facts beside each. Investor-owned companies stay on
the map as comparables; the founder-owned ones are the calls to make.

Output: themes.parquet (company_number, theme, distinct_keywords, total_hits, top_keywords,
snippet, url, candidate). Run: python -m src.score.themes
"""
from __future__ import annotations

import re
import sys

import polars as pl

from src.common import cfg, get_logger, now_iso, parquet_exists, read_parquet, write_parquet
from src.score.classify import load_web

log = get_logger("themes")


def _patterns(keywords: list[str]) -> dict[str, re.Pattern]:
    return {k: re.compile(r"(?<![a-z0-9])" + re.escape(k.lower()) + r"(?![a-z0-9])") for k in keywords}


def _snippet(text: str, kw: str, width: int = 220) -> str:
    low = text.lower()
    i = low.find(kw.lower())
    if i < 0:
        return ""
    start = max(0, low.rfind(". ", 0, i) + 2, i - width // 2)
    end = min(len(text), low.find(". ", i) + 1 or len(text), i + width)
    return re.sub(r"\s+", " ", text[start:end]).strip()


def scan(pages: list[dict], pats: dict[str, re.Pattern]) -> dict:
    text = " ".join((p.get("text") or "") for p in pages)
    low = text.lower()
    counts = {k: len(p.findall(low)) for k, p in pats.items()}
    counts = {k: v for k, v in counts.items() if v}
    if not counts:
        return {}
    top = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    best_kw = top[0][0]
    url, snip = None, ""
    for p in pages:
        s = _snippet(p.get("text") or "", best_kw)
        if s:
            url, snip = p.get("url"), s
            break
    return {"distinct_keywords": len(counts), "total_hits": sum(counts.values()),
            "top_keywords": ", ".join(f"{k} ({v})" for k, v in top[:5]), "snippet": snip, "url": url}


def main(argv=None):
    th = cfg()["themes"]
    uni = read_parquet("universe")
    web = read_parquet("websites").filter(pl.col("domain").is_not_null()).select(["company_number", "name_match", "uk_signal"]).unique(subset=["company_number"]) if parquet_exists("websites") else None
    if web is None:
        log.error("websites.parquet missing")
        return
    wrong = set(web.filter((pl.col("name_match") == False) & (pl.col("uk_signal") == False))["company_number"].to_list())  # noqa: E712
    numbers = [n for n in web["company_number"].to_list() if n in set(uni["company_number"].to_list()) and n not in wrong]
    pats = {t: _patterns(spec["keywords"]) for t, spec in th["list"].items()}
    rows = []
    for n in numbers:
        w = load_web(n)
        if not w or not w.get("pages"):
            continue
        for t, pp in pats.items():
            r = scan(w["pages"], pp)
            if r:
                rows.append({"company_number": n, "theme": t, **r,
                             "candidate": r["distinct_keywords"] >= th["min_distinct"] and r["total_hits"] >= th["min_total"],
                             "computed_at": now_iso()})
    df = pl.DataFrame(rows, infer_schema_length=None)
    write_parquet(df, "themes")
    log.info("themes: %d rows, %d candidates\n%s", df.height, df.filter(pl.col("candidate")).height,
             df.filter(pl.col("candidate")).group_by("theme").len().sort("theme"))


if __name__ == "__main__":
    main(sys.argv[1:])
