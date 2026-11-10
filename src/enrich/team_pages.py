"""Named leadership roles for ranked companies. Finds the team, leadership, board or about page from the
homepage links, fetches up to three, and asks a model for the people and titles named there. A person is kept
only when the name appears verbatim in the fetched text. -> data/parquet/team.parquet

  python -m src.enrich.team_pages
"""
from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urljoin, urlparse

import polars as pl
from bs4 import BeautifulSoup

from src.common import cfg, get_logger, now_iso, parquet_exists, read_parquet, write_parquet
from src.enrich import websites as W
from src.score.llm import LLM

log = get_logger("team_pages")
LINK_RE = re.compile(r"leadership|our[- ]team|the[- ]team|meet[- ]the|management|board|directors|executive|our[- ]people|who[- ]we[- ]are|about", re.I)
PRIORITY = ["leadership", "management", "board", "executive", "directors", "team", "people", "who", "about"]
SYSTEM = """You are given text from a company's website. List the senior people it names with their job titles, most senior first (chief executive, managing director, chair, finance director, founders, other directors and executives). Use only what the text states.
Answer with JSON only: {"people": [{"name": "Full Name", "title": "Title as written"}]}. At most 12. If the text names nobody with a title, return {"people": []}."""


def main():
    rk = read_parquet("rankings").filter(pl.col("ranked") & pl.col("homepage_url").is_not_null()).select(["company_number", "name", "homepage_url", "domain"])
    prev = read_parquet("team") if parquet_exists("team") else None
    done = set(prev["company_number"].to_list()) if prev is not None else set()
    todo = [r for r in rk.to_dicts() if r["company_number"] not in done]
    fetcher = W.DomainFetcher(cfg()["websites"])
    llm = LLM("team-v1", providers=["anthropic_haiku45"])

    def work(r):
        out = []
        try:
            st, final, html = fetcher._get(r["homepage_url"])
            if st != 200 or not html or html.startswith("__error__"):
                return [{"company_number": r["company_number"], "name": None, "title": None, "url": None, "computed_at": now_iso()}]
            dom = W.registered_domain(final) or r["domain"]
            cands = {}
            for a in BeautifulSoup(html, "lxml").find_all("a", href=True):
                href = urljoin(final, a["href"].strip()).split("#")[0]
                if not href.startswith("http") or W.registered_domain(urlparse(href).hostname or "") != dom:
                    continue
                label = (a.get_text(" ", strip=True) + " " + urlparse(href).path).lower()
                if LINK_RE.search(label) and not re.search(r"\.(pdf|jpg|png)$|news|blog|career|job|privacy|cookie", href, re.I):
                    score = min((i for i, k in enumerate(PRIORITY) if k in label), default=99)
                    cands[href.rstrip("/")] = min(score, cands.get(href.rstrip("/"), 99))
            pages = [(final, html)]
            for href, _ in sorted(cands.items(), key=lambda x: x[1])[:3]:
                s2, f2, h2 = fetcher._get(href)
                if s2 == 200 and h2 and not h2.startswith("__error__"):
                    pages.append((f2, h2))
            seen = set()
            for url, h in pages[1:] + pages[:1]:
                _, text = W.extract_text(h, url)
                if len(text) < 200:
                    continue
                d = llm.complete_json(SYSTEM, f"Company: {r['name']}\nPage: {url}\n\nTEXT:\n{text[:9000]}").data or {}
                low = re.sub(r"\s+", " ", text).lower()
                for p in (d.get("people") or [])[:12]:
                    nm, ti = str(p.get("name") or "").strip(), str(p.get("title") or "").strip()
                    if len(nm.split()) >= 2 and ti and nm.lower() in low and nm.lower() not in seen:
                        seen.add(nm.lower())
                        out.append({"company_number": r["company_number"], "name": nm, "title": ti[:80], "url": url, "computed_at": now_iso()})
                if len(out) >= 3:
                    break
        except Exception as e:  # noqa: BLE001
            log.warning("%s: %s", r["company_number"], e)
        return out or [{"company_number": r["company_number"], "name": None, "title": None, "url": None, "computed_at": now_iso()}]

    with ThreadPoolExecutor(max_workers=6) as pool:
        rows = [x for res in pool.map(work, todo) for x in res]
    schema = {"company_number": pl.Utf8, "name": pl.Utf8, "title": pl.Utf8, "url": pl.Utf8, "computed_at": pl.Utf8}
    df = pl.DataFrame(rows, schema=schema)
    if prev is not None:
        df = pl.concat([prev, df])
    write_parquet(df, "team")
    got = df.filter(pl.col("name").is_not_null())
    log.info("team pages: %d companies tried, %d with named people, %d people", len(todo), got["company_number"].n_unique(), got.height)


if __name__ == "__main__":
    main()
