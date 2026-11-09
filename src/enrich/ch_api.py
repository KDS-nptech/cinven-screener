"""Stage 4a: Companies House REST API enrichment.

Run from the repo root:
    python -m src.enrich.ch_api --from-universe
    python -m src.enrich.ch_api --numbers 06452255,10113345
    python -m src.enrich.ch_api --names "PortSwigger Ltd,usecure Ltd"   # public search lookup, no key needed

For every company the client fetches the profile, officers, filing history (first 300
items) and charges, caches every response in data/cache/ch/, and writes four tables:
    data/parquet/profiles.parquet
    data/parquet/officers.parquet
    data/parquet/filings.parquet
    data/parquet/charges.parquet

Resumable: a company whose four first-page responses are already cached costs no API
call. Tables are rewritten atomically every 500 companies and at the end.

Without CH_API_KEY (config api.companies_house_key_env) the module logs how many
companies it would pull and exits 0 without writing anything.

filing_summary(company_number) counts SH01, MR01, RES*, AA and CS01 filings from
filings.parquet for Stage 3's second ownership check and Stage 10.
"""
from __future__ import annotations

import argparse
import collections
import re
import sys
import threading
import time
from typing import Any, Iterable

import requests

from src.common import (DiskCache, cfg, env_key, get_logger, normalise_company_number, now_iso,
                        parquet_path, read_parquet, write_parquet)

log = get_logger("ch_api")

PUBLIC_SEARCH = "https://find-and-update.company-information.service.gov.uk/search/companies"
PUBLIC_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"
FILINGS_MAX_ITEMS = 300
PAGE_SIZE = 100
WRITE_EVERY = 500
_NOT_FOUND = {"__status__": 404}


class AuthError(RuntimeError):
    pass


# ---------------------------------------------------------------- rate limiting
class SlidingWindowLimiter:
    """Allow at most max_calls in any window_seconds. Thread-safe."""

    def __init__(self, max_calls: int, window_seconds: float):
        self.max_calls = max_calls
        self.window = window_seconds
        self.calls: collections.deque[float] = collections.deque()
        self.lock = threading.Lock()

    def wait(self) -> float:
        waited = 0.0
        while True:
            with self.lock:
                now = time.monotonic()
                while self.calls and now - self.calls[0] >= self.window:
                    self.calls.popleft()
                if len(self.calls) < self.max_calls:
                    self.calls.append(now)
                    return waited
                sleep_for = self.window - (now - self.calls[0]) + 0.05
            time.sleep(sleep_for)
            waited += sleep_for


# ---------------------------------------------------------------- client
class CHClient:
    """Companies House REST client: basic auth, sliding window limiter, disk cache."""

    def __init__(self, key: str | None = None, cache: DiskCache | None = None,
                 limiter: SlidingWindowLimiter | None = None, session: requests.Session | None = None,
                 max_retries: int = 5):
        api = cfg()["api"]
        self.base = api["companies_house_base"].rstrip("/")
        self.key = key if key is not None else env_key("companies_house_key_env")
        self.cache = cache or DiskCache("ch")
        self.limiter = limiter or SlidingWindowLimiter(api["companies_house_per_window"],
                                                       api["companies_house_window_seconds"])
        # The document API (document-api.company-information.service.gov.uk) is a separate host; it is
        # paced on its own window so a document fetch does not spend the main API's quota. 429s on either
        # host still back off per the Retry-After header.
        self.doc_limiter = SlidingWindowLimiter(api.get("companies_house_doc_per_window", api["companies_house_per_window"]),
                                                api["companies_house_window_seconds"])
        self.session = session or requests.Session()
        self.max_retries = max_retries
        self.calls_made = 0
        self.cache_hits = 0

    # -- low level
    def cache_key(self, path: str, params: dict | None) -> tuple:
        return (path, sorted((params or {}).items()))

    def is_cached(self, path: str, params: dict | None = None) -> bool:
        return self.cache.has(*self.cache_key(path, params))

    def get(self, path: str, params: dict | None = None) -> dict | None:
        """GET a JSON resource. Returns None on 404. Cached by path plus params."""
        key = self.cache_key(path, params)
        cached = self.cache.get(*key)
        if cached is not None:
            self.cache_hits += 1
            return None if cached == _NOT_FOUND else cached
        if not self.key:
            raise AuthError("Companies House API key missing")
        url = self.base + path
        backoff = 2.0
        for attempt in range(1, self.max_retries + 1):
            self.limiter.wait()
            try:
                r = self.session.get(url, params=params, auth=(self.key, ""), timeout=30,
                                     headers={"Accept": "application/json"})
            except requests.RequestException as e:
                log.warning("%s attempt %d network error %s", path, attempt, e)
                time.sleep(backoff)
                backoff = min(backoff * 2, 60)
                continue
            self.calls_made += 1
            if r.status_code == 200:
                data = r.json()
                self.cache.put(data, *key)
                return data
            if r.status_code == 404:
                self.cache.put(_NOT_FOUND, *key)
                return None
            if r.status_code == 401:
                raise AuthError(f"401 from Companies House for {path}; check the key")
            if r.status_code == 429:
                retry_after = r.headers.get("Retry-After")
                wait = float(retry_after) if retry_after and retry_after.isdigit() else 60.0
                log.warning("429 on %s; sleeping %.0fs", path, wait)
                time.sleep(wait)
                continue
            if r.status_code >= 500:
                log.warning("%s on %s attempt %d; backoff %.0fs", r.status_code, path, attempt, backoff)
                time.sleep(backoff)
                backoff = min(backoff * 2, 60)
                continue
            log.error("unexpected %s on %s: %s", r.status_code, path, r.text[:200])
            return None
        log.error("giving up on %s after %d attempts", path, self.max_retries)
        return None

    def get_url(self, url: str) -> dict | None:
        """GET a JSON resource by absolute URL (document API metadata). Cached like get()."""
        if url.startswith(self.base):
            return self.get(url[len(self.base):])
        key = ("URL", url)
        cached = self.cache.get(*key)
        if cached is not None:
            self.cache_hits += 1
            return None if cached == _NOT_FOUND else cached
        for attempt in range(1, self.max_retries + 1):
            self.limiter.wait()
            try:
                r = self.session.get(url, auth=(self.key, ""), timeout=30, headers={"Accept": "application/json"})
            except requests.RequestException as e:
                log.warning("%s attempt %d network error %s", url, attempt, e)
                time.sleep(min(2.0 * attempt, 30))
                continue
            self.calls_made += 1
            if r.status_code == 200:
                data = r.json()
                self.cache.put(data, *key)
                return data
            if r.status_code == 404:
                self.cache.put(_NOT_FOUND, *key)
                return None
            if r.status_code == 429:
                ra = r.headers.get("Retry-After")
                wait = float(ra) if ra and ra.replace(".", "").isdigit() else 60.0
                log.warning("429 on document fetch; sleeping %.0fs", wait)
                time.sleep(wait)
                continue
            if r.status_code >= 500:
                time.sleep(min(2.0 * attempt, 30))
                continue
            log.error("unexpected %s on %s", r.status_code, url)
            return None
        return None

    def get_document(self, url: str, accept: str) -> bytes | None:
        """Download a document body (iXBRL or PDF). The API answers 302 to S3; requests drops the
        auth header on the cross-host redirect, which is what S3 requires. Not cached on disk
        (binary); callers keep the file."""
        for attempt in range(1, self.max_retries + 1):
            (self.doc_limiter if "document-api" in url else self.limiter).wait()
            try:
                r = self.session.get(url, auth=(self.key, ""), timeout=90, headers={"Accept": accept}, allow_redirects=True)
            except requests.RequestException as e:
                log.warning("%s attempt %d network error %s", url, attempt, e)
                time.sleep(min(2.0 * attempt, 30))
                continue
            self.calls_made += 1
            if r.status_code == 200:
                return r.content
            if r.status_code in (404, 406):
                return None
            if r.status_code == 429:
                ra = r.headers.get("Retry-After")
                wait = float(ra) if ra and ra.replace(".", "").isdigit() else 60.0
                log.warning("429 on document fetch; sleeping %.0fs", wait)
                time.sleep(wait)
                continue
            if r.status_code >= 500:
                time.sleep(min(2.0 * attempt, 30))
                continue
            log.error("unexpected %s on %s", r.status_code, url)
            return None
        return None

    def paginate(self, path: str, max_items: int | None = None, page_size: int = PAGE_SIZE) -> list[dict]:
        items: list[dict] = []
        start = 0
        while True:
            page = self.get(path, {"items_per_page": page_size, "start_index": start})
            if not page:
                break
            batch = page.get("items") or []
            items.extend(batch)
            total = page.get("total_results") or page.get("total_count") or 0
            start += page_size
            if not batch or start >= total or (max_items and len(items) >= max_items):
                break
        return items[:max_items] if max_items else items

    # -- resources
    def profile(self, n: str) -> dict | None:
        return self.get(f"/company/{n}")

    def officers(self, n: str) -> list[dict]:
        return self.paginate(f"/company/{n}/officers")

    def filing_history(self, n: str, max_items: int = FILINGS_MAX_ITEMS) -> list[dict]:
        return self.paginate(f"/company/{n}/filing-history", max_items=max_items)

    def charges(self, n: str) -> list[dict]:
        page = self.get(f"/company/{n}/charges")
        return (page or {}).get("items") or []

    def company_cached(self, n: str) -> bool:
        first = {"items_per_page": PAGE_SIZE, "start_index": 0}
        return (self.is_cached(f"/company/{n}")
                and self.is_cached(f"/company/{n}/officers", first)
                and self.is_cached(f"/company/{n}/filing-history", first)
                and self.is_cached(f"/company/{n}/charges"))


# ---------------------------------------------------------------- row builders
def profile_row(n: str, p: dict, fetched_at: str) -> dict:
    accounts = p.get("accounts") or {}
    last_accounts = accounts.get("last_accounts") or {}
    cs = p.get("confirmation_statement") or {}
    office = p.get("registered_office_address") or {}
    return {
        "company_number": normalise_company_number(p.get("company_number") or n),
        "name": p.get("company_name"),
        "status": p.get("company_status"),
        "type": p.get("type"),
        "inc_date": p.get("date_of_creation"),
        "sic_codes": list(p.get("sic_codes") or []),
        "registered_office_locality": office.get("locality"),
        "has_charges": bool(p.get("has_charges", False)),
        "has_insolvency_history": bool(p.get("has_insolvency_history", False)),
        "accounts_last_made_up_to": last_accounts.get("made_up_to"),
        "accounts_next_due": accounts.get("next_due"),
        "confirmation_statement_last_made_up_to": cs.get("last_made_up_to"),
        "links_self": (p.get("links") or {}).get("self"),
        "fetched_at": fetched_at,
    }


def officer_id_from_links(links: dict | None) -> str | None:
    appt = ((links or {}).get("officer") or {}).get("appointments")
    if not appt:
        return None
    m = re.search(r"/officers/([^/]+)/appointments", appt)
    return m.group(1) if m else appt


def officer_row(n: str, o: dict, fetched_at: str) -> dict:
    dob = o.get("date_of_birth") or {}
    return {
        "company_number": n,
        "officer_id": officer_id_from_links(o.get("links")),
        "name": o.get("name"),
        "role": o.get("officer_role"),
        "appointed_on": o.get("appointed_on"),
        "resigned_on": o.get("resigned_on"),
        "nationality": o.get("nationality"),
        "country_of_residence": o.get("country_of_residence"),
        "occupation": o.get("occupation"),
        "dob_year": dob.get("year"),
        "dob_month": dob.get("month"),
        "fetched_at": fetched_at,
    }


def filing_row(n: str, f: dict, fetched_at: str) -> dict:
    import json

    dv = f.get("description_values")
    return {
        "company_number": n,
        "transaction_id": f.get("transaction_id"),
        "type": f.get("type"),
        "date": f.get("date"),
        "description": f.get("description"),
        "category": f.get("category"),
        "subcategory": f.get("subcategory"),
        "description_values_json": json.dumps(dv, default=str) if dv else None,
        "fetched_at": fetched_at,
    }


def charge_row(n: str, c: dict, fetched_at: str) -> dict:
    return {
        "company_number": n,
        "charge_code": c.get("charge_code") or (str(c.get("charge_number")) if c.get("charge_number") is not None else None),
        "created_on": c.get("created_on"),
        "delivered_on": c.get("delivered_on"),
        "satisfied_on": c.get("satisfied_on"),
        "status": c.get("status"),
        "persons_entitled": [p.get("name") for p in (c.get("persons_entitled") or []) if p.get("name")],
        "classification_description": (c.get("classification") or {}).get("description"),
        "particulars_description": (c.get("particulars") or {}).get("description"),
        "fetched_at": fetched_at,
    }


PROFILE_SCHEMA = {
    "company_number": "str", "name": "str", "status": "str", "type": "str", "inc_date": "str",
    "sic_codes": "list_str", "registered_office_locality": "str", "has_charges": "bool",
    "has_insolvency_history": "bool", "accounts_last_made_up_to": "str", "accounts_next_due": "str",
    "confirmation_statement_last_made_up_to": "str", "links_self": "str", "fetched_at": "str",
}
OFFICER_SCHEMA = {
    "company_number": "str", "officer_id": "str", "name": "str", "role": "str", "appointed_on": "str",
    "resigned_on": "str", "nationality": "str", "country_of_residence": "str", "occupation": "str",
    "dob_year": "int", "dob_month": "int", "fetched_at": "str",
}
FILING_SCHEMA = {
    "company_number": "str", "transaction_id": "str", "type": "str", "date": "str", "description": "str",
    "category": "str", "subcategory": "str", "description_values_json": "str", "fetched_at": "str",
}
CHARGE_SCHEMA = {
    "company_number": "str", "charge_code": "str", "created_on": "str", "delivered_on": "str",
    "satisfied_on": "str", "status": "str", "persons_entitled": "list_str",
    "classification_description": "str", "particulars_description": "str", "fetched_at": "str",
}


def to_frame(rows: list[dict], schema: dict):
    """Build a polars frame with a fixed schema so empty tables still have columns."""
    import polars as pl

    kinds = {"str": pl.Utf8, "int": pl.Int64, "bool": pl.Boolean, "list_str": pl.List(pl.Utf8)}
    pl_schema = {k: kinds[v] for k, v in schema.items()}
    if not rows:
        return pl.DataFrame(schema=pl_schema)
    return pl.DataFrame([{k: r.get(k) for k in schema} for r in rows], schema=pl_schema)


# ---------------------------------------------------------------- pull
def pull(numbers: Iterable[str], client: CHClient | None = None, write_every: int = WRITE_EVERY,
         write: bool = True) -> dict:
    client = client or CHClient()
    numbers = [normalise_company_number(n) for n in numbers if n]
    profiles: list[dict] = []
    officers: list[dict] = []
    filings: list[dict] = []
    charges: list[dict] = []
    missing = 0
    t0 = time.time()

    def flush():
        if not write:
            return
        write_parquet(to_frame(profiles, PROFILE_SCHEMA), "profiles")
        write_parquet(to_frame(officers, OFFICER_SCHEMA), "officers")
        write_parquet(to_frame(filings, FILING_SCHEMA), "filings")
        write_parquet(to_frame(charges, CHARGE_SCHEMA), "charges")

    for i, n in enumerate(numbers, 1):
        fetched_at = now_iso()
        p = client.profile(n)
        if p is None:
            missing += 1
            log.info("%s not found (404)", n)
            continue
        profiles.append(profile_row(n, p, fetched_at))
        officers.extend(officer_row(n, o, fetched_at) for o in client.officers(n))
        filings.extend(filing_row(n, f, fetched_at) for f in client.filing_history(n))
        charges.extend(charge_row(n, c, fetched_at) for c in client.charges(n))
        if i % 50 == 0:
            el = time.time() - t0
            log.info("%d/%d companies, %d API calls, %d cache hits, %.0fs elapsed",
                     i, len(numbers), client.calls_made, client.cache_hits, el)
        if write_every and i % write_every == 0:
            flush()
            log.info("checkpoint written at %d companies", i)
    flush()
    summary = {"companies": len(numbers), "found": len(profiles), "missing": missing,
               "officers": len(officers), "filings": len(filings), "charges": len(charges),
               "api_calls": client.calls_made, "cache_hits": client.cache_hits,
               "seconds": round(time.time() - t0, 1)}
    log.info("done: %s", summary)
    return summary


# ---------------------------------------------------------------- filing summary
FILING_SUMMARY_TYPES = ("SH01", "MR01", "RES", "AA", "CS01")


def filing_summary(company_number: str, filings_df=None) -> dict:
    """Counts of SH01, MR01, RES* (all resolutions), AA and CS01 filings, plus dates.

    Reads data/parquet/filings.parquet unless a polars frame is passed. RES counts any
    type starting with RES (RES01, RES10, RES12, RES13, RES15 ...).
    """
    import polars as pl

    n = normalise_company_number(company_number)
    out = {"company_number": n, "n_filings": 0, "sh01": 0, "mr01": 0, "res": 0, "aa": 0, "cs01": 0,
           "first_filing": None, "last_filing": None, "last_sh01": None, "last_mr01": None}
    if filings_df is None:
        if not parquet_path("filings").exists():
            return out
        filings_df = read_parquet("filings")
    df = filings_df.filter(pl.col("company_number") == n)
    if df.height == 0:
        return out
    types = df["type"].fill_null("").to_list()
    dates = df["date"].to_list()
    out["n_filings"] = df.height
    out["sh01"] = sum(t == "SH01" for t in types)
    out["mr01"] = sum(t == "MR01" for t in types)
    out["res"] = sum(t.startswith("RES") for t in types)
    out["aa"] = sum(t == "AA" for t in types)
    out["cs01"] = sum(t == "CS01" for t in types)
    valid = sorted(d for d in dates if d)
    out["first_filing"] = valid[0] if valid else None
    out["last_filing"] = valid[-1] if valid else None
    sh = sorted(d for t, d in zip(types, dates) if t == "SH01" and d)
    mr = sorted(d for t, d in zip(types, dates) if t == "MR01" and d)
    out["last_sh01"] = sh[-1] if sh else None
    out["last_mr01"] = mr[-1] if mr else None
    return out


# ---------------------------------------------------------------- public search (no key)
_public_cache = DiskCache("ch_public")
_public_last_call = [0.0]


def _norm_name(name: str) -> str:
    s = re.sub(r"[^A-Z0-9 ]+", " ", (name or "").upper())
    s = re.sub(r"\b(LIMITED|LTD|PLC|LLP|L L P|THE)\b", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def public_search(query: str, session: requests.Session | None = None) -> list[dict]:
    """Companies House public search page (no key). Returns [{number, name, status_text, address}]."""
    from bs4 import BeautifulSoup

    cached = _public_cache.get("search", query)
    if cached is not None:
        return cached
    gap = 1.0 - (time.monotonic() - _public_last_call[0])
    if gap > 0:
        time.sleep(gap)
    session = session or requests.Session()
    r = session.get(PUBLIC_SEARCH, params={"q": query}, headers={"User-Agent": PUBLIC_UA}, timeout=20)
    _public_last_call[0] = time.monotonic()
    if r.status_code != 200:
        log.warning("public search %s for %r", r.status_code, query)
        return []
    soup = BeautifulSoup(r.text, "lxml")
    out = []
    for li in soup.select("li.type-company"):
        a = li.select_one("a[href*='/company/']")
        if not a:
            continue
        m = re.search(r"/company/([A-Z0-9]+)", a.get("href", ""))
        if not m:
            continue
        text = li.get_text(" ", strip=True)
        out.append({"number": normalise_company_number(m.group(1)), "name": a.get_text(strip=True),
                    "text": text})
    _public_cache.put(out, "search", query)
    return out


def lookup_company_number(name: str, town: str | None = None) -> str | None:
    """Best-effort company number for a name via the public search page.

    Requires an exact normalised name match; prefers an active company whose address text
    mentions the town. Returns None when nothing matches exactly.
    """
    target = _norm_name(name)
    hits = [h for h in public_search(name) if _norm_name(h["name"]) == target]
    if not hits:
        return None
    active = [h for h in hits if "Dissolved" not in h["text"]]
    pool = active or hits
    if town:
        t = town.upper()
        pool_town = [h for h in pool if t in h["text"].upper()]
        if pool_town:
            pool = pool_town
    if len(pool) > 1:
        log.info("%d exact name matches for %r; taking %s", len(pool), name, pool[0]["number"])
    return pool[0]["number"]


# ---------------------------------------------------------------- CLI
def universe_numbers(limit: int | None = None) -> list[str]:
    p = parquet_path("universe")
    if not p.exists():
        log.error("data/parquet/universe.parquet not found; pass --numbers or --names")
        return []
    df = read_parquet("universe")
    nums = [normalise_company_number(n) for n in df["company_number"].to_list()]
    return nums[:limit] if limit else nums


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--from-universe", action="store_true", help="pull every company in universe.parquet")
    ap.add_argument("--numbers", help="comma-separated company numbers")
    ap.add_argument("--names", help="comma-separated company names, resolved via the public search page")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--summary", help="print filing_summary for one company number and exit")
    args = ap.parse_args(argv)

    if args.summary:
        print(filing_summary(args.summary))
        return 0

    numbers: list[str] = []
    if args.from_universe:
        numbers = universe_numbers(args.limit)
    if args.numbers:
        numbers += [normalise_company_number(x) for x in args.numbers.split(",") if x.strip()]
    if args.names:
        for nm in [x.strip() for x in args.names.split(",") if x.strip()]:
            n = lookup_company_number(nm)
            log.info("public search %r -> %s", nm, n)
            if n:
                numbers.append(n)
    numbers = list(dict.fromkeys(n for n in numbers if n))
    if not numbers:
        log.info("nothing to pull")
        return 0

    key = env_key("companies_house_key_env")
    if not key:
        log.info("%s unset; would pull %d companies (~%d API calls). Nothing written.",
                 cfg()["api"]["companies_house_key_env"], len(numbers), len(numbers) * 5)
        return 0
    try:
        pull(numbers, CHClient(key=key))
    except AuthError as e:
        log.error("%s", e)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
