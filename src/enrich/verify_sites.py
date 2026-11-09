"""Site verification: does the discovered website belong to this company?

Looks for the Companies House number, the registered postcode or the registered town in the
homepage HTML and, failing that, in the usual legal pages (/about, /contact, /privacy, /terms,
/legal, /imprint). Writes site_verified, site_verify_source into websites.parquet. A discovered
site that fails every check and came from a domain probe on a one-word name is the classic
wrong-site case (Clarity, Vitesse, Symmetry) and is flagged website_unverified downstream.

Run: python -m src.enrich.verify_sites [--all]   (default: shortlist = rankings rows)
"""
from __future__ import annotations

import argparse
import re
import sys
import time
from urllib.parse import urljoin

import polars as pl
import requests

from src.common import DiskCache, cfg, get_logger, name_tokens, now_iso, parquet_exists, read_parquet, write_parquet

log = get_logger("verify_sites")
cache = DiskCache("webpages")
LEGAL_PATHS = ["/about", "/about-us", "/contact", "/contact-us", "/privacy", "/privacy-policy", "/terms", "/terms-and-conditions", "/legal", "/imprint", "/company"]
UA = cfg()["websites"]["user_agent"]


def _get(url: str) -> str:
    c = cache.get(url)
    if c is not None:
        return c.get("html") or ""
    try:
        r = requests.get(url, headers={"User-Agent": UA, "Accept-Language": "en-GB,en;q=0.9"}, timeout=10, allow_redirects=True)
        html = r.text if r.status_code == 200 and "html" in r.headers.get("content-type", "") else ""
        cache.put({"status": r.status_code, "final_url": r.url, "html": html[:600_000], "fetched_at": now_iso()}, url)
        return html
    except requests.RequestException:
        cache.put({"status": -1, "final_url": url, "html": "", "fetched_at": now_iso()}, url)
        return ""


def _check(html: str, number: str, postcode: str | None, town: str | None) -> str | None:
    if not html:
        return None
    low = html.lower()
    if number and (number in low or (number.lstrip("0") and re.search(rf"\b0*{number.lstrip('0')}\b", low))):
        return "company_number"
    if postcode:
        pc = postcode.upper().replace(" ", "")
        if pc and pc in html.upper().replace(" ", ""):
            return "postcode"
    if town and len(town) >= 4 and town.lower() in low:
        return "town"
    return None


def verify(number: str, homepage: str, postcode: str | None, town: str | None) -> tuple[bool, str | None]:
    html = _get(homepage)
    src = _check(html, number, postcode, town)
    if src:
        return True, f"homepage:{src}"
    # footer links often point at the legal pages; try the usual paths too
    hrefs = set(re.findall(r'href="([^"]+)"', html or ""))
    candidates = [urljoin(homepage, h) for h in hrefs if any(k in h.lower() for k in ("privacy", "terms", "legal", "contact", "about", "imprint"))][:4]
    candidates += [urljoin(homepage, p) for p in LEGAL_PATHS]
    seen = set()
    for url in candidates:
        if url in seen or len(seen) >= 6:
            continue
        seen.add(url)
        src = _check(_get(url), number, postcode, town)
        if src:
            return True, f"{url.replace(homepage.rstrip('/'), '')}:{src}"
        time.sleep(0.3)
    return False, None


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true", help="every websites row with a domain (default: rankings rows)")
    args = ap.parse_args(argv)
    web = read_parquet("websites")
    comp = read_parquet("companies").select(["company_number", "postcode", "post_town"])
    if args.all or not parquet_exists("rankings"):
        targets = web.filter(pl.col("domain").is_not_null())["company_number"].to_list()
    else:
        targets = read_parquet("rankings")["company_number"].to_list()
    rows = web.to_dicts()
    info = {r["company_number"]: r for r in comp.filter(pl.col("company_number").is_in(targets)).to_dicts()}
    done = 0
    for r in rows:
        n = r["company_number"]
        if n not in info or not r.get("domain") or (r.get("site_verified") is not None and not args.all):
            continue
        homepage = r.get("homepage_url") or f"https://{r['domain']}/"
        ok, src = verify(n, homepage, info[n].get("postcode"), info[n].get("post_town"))
        r["site_verified"], r["site_verify_source"] = ok, src
        done += 1
        if done % 25 == 0:
            log.info("%d verified so far", done)
    df = pl.DataFrame(rows, infer_schema_length=None)
    write_parquet(df, "websites")
    sub = df.filter(pl.col("company_number").is_in(targets))
    log.info("done: %d checked; verified %d of %d targets", done, sub.filter(pl.col("site_verified") == True).height, sub.height)  # noqa: E712


if __name__ == "__main__":
    main(sys.argv[1:])
