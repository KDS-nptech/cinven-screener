"""Stage 7 data pull: open job postings from public ATS boards.

Run from the repo root:
    python -m src.enrich.jobs                       # every websites.parquet row with an ATS token
    python -m src.enrich.jobs --numbers 06719143
    python -m src.enrich.jobs --board greenhouse:cognism --company 09392705   # one board by hand

Supported boards (public JSON, no key):
    greenhouse  https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true
    lever       https://api.lever.co/v0/postings/{slug}?mode=json
    ashby       https://api.ashbyhq.com/posting-api/job-board/{name}
    workable    https://apply.workable.com/api/v1/widget/accounts/{sub}
                (fallback https://www.workable.com/api/accounts/{sub}?details=true)
Name-only ATSs (teamtailor, bamboohr, personio, recruitee, pinpoint, hibob ...) are skipped.
Adzuna is implemented behind ADZUNA_APP_ID / ADZUNA_APP_KEY and skipped without them.

Outputs:
    data/parquet/jobs.parquet          one row per posting
    data/parquet/jobs_summary.parquet  one row per company
Every ATS response is cached in data/cache/ats/ keyed on the URL and the as_of date so a
re-run on the same day costs nothing.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import time
from collections import Counter

import requests

from src.common import (DiskCache, cfg, env_key, get_logger, normalise_company_number, now_iso,
                        parquet_path, read_parquet, today, write_parquet)

log = get_logger("jobs")

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"
HEADERS = {"User-Agent": UA, "Accept": "application/json"}
SUPPORTED = ("greenhouse", "lever", "ashby", "workable")
PACE_SECONDS = {"greenhouse": 0.5, "lever": 0.5, "ashby": 0.5, "workable": 5.0, "adzuna": 1.0}

UK_PLACES = [
    "united kingdom", "uk", "u.k.", "great britain", "britain", "england", "scotland", "wales",
    "northern ireland", "london", "manchester", "birmingham", "leeds", "glasgow", "edinburgh", "bristol",
    "cambridge", "oxford", "belfast", "cardiff", "liverpool", "newcastle", "sheffield", "nottingham",
    "leicester", "reading", "brighton", "guildford", "knutsford", "cheshire", "milton keynes", "bath",
    "exeter", "southampton", "portsmouth", "york", "aberdeen", "dundee", "swansea", "coventry", "derby",
    "sunderland", "bournemouth", "poole", "norwich", "ipswich", "peterborough", "northampton", "luton",
    "watford", "slough", "basingstoke", "farnborough", "woking", "maidenhead", "swindon", "gloucester",
    "cheltenham", "warrington", "chester", "preston", "bolton", "stockport", "salford", "wigan",
    "huddersfield", "bradford", "wakefield", "hull", "middlesbrough", "durham", "lancaster", "carlisle",
    "canterbury", "maidstone", "tunbridge wells", "crawley", "horsham", "chichester", "winchester",
    "salisbury", "plymouth", "truro", "taunton", "hereford", "worcester", "shrewsbury", "stoke",
    "wolverhampton", "solihull", "telford", "lincoln", "oxfordshire", "surrey", "kent", "essex",
    "hertfordshire", "hampshire", "berkshire", "yorkshire", "lancashire", "merseyside", "midlands",
    "londonderry", "derry", "stirling", "inverness", "newport", "wrexham", "bangor", "remote - uk",
    "remote (uk)", "uk remote", "remote, uk", "remote uk", "gb",
]
COUNTRY_SYNONYMS = {
    "usa": "US", "u.s.": "US", "u.s.a.": "US", "united states": "US", "united states of america": "US",
    "us": "US", "america": "US", "new york": "US", "san francisco": "US", "california": "US", "texas": "US",
    "austin": "US", "boston": "US", "chicago": "US", "seattle": "US", "denver": "US", "atlanta": "US",
    "ny": "US", "ca": "US", "tx": "US", "ma": "US", "wa": "US",
    "ireland": "Ireland", "dublin": "Ireland", "cork": "Ireland",
    "germany": "Germany", "berlin": "Germany", "munich": "Germany", "deutschland": "Germany",
    "france": "France", "paris": "France", "spain": "Spain", "madrid": "Spain", "barcelona": "Spain",
    "netherlands": "Netherlands", "amsterdam": "Netherlands", "the netherlands": "Netherlands",
    "portugal": "Portugal", "lisbon": "Portugal", "poland": "Poland", "warsaw": "Poland", "krakow": "Poland",
    "india": "India", "bangalore": "India", "bengaluru": "India", "mumbai": "India", "pune": "India",
    "hyderabad": "India", "chennai": "India", "australia": "Australia", "sydney": "Australia",
    "melbourne": "Australia", "canada": "Canada", "toronto": "Canada", "vancouver": "Canada",
    "singapore": "Singapore", "uae": "UAE", "dubai": "UAE", "south africa": "South Africa",
    "cape town": "South Africa", "johannesburg": "South Africa", "sweden": "Sweden", "stockholm": "Sweden",
    "denmark": "Denmark", "copenhagen": "Denmark", "norway": "Norway", "oslo": "Norway", "finland": "Finland",
    "helsinki": "Finland", "italy": "Italy", "milan": "Italy", "rome": "Italy", "belgium": "Belgium",
    "brussels": "Belgium", "switzerland": "Switzerland", "zurich": "Switzerland", "austria": "Austria",
    "vienna": "Austria", "czech republic": "Czechia", "czechia": "Czechia", "prague": "Czechia",
    "romania": "Romania", "bucharest": "Romania", "bulgaria": "Bulgaria", "sofia": "Bulgaria",
    "ukraine": "Ukraine", "kyiv": "Ukraine", "israel": "Israel", "tel aviv": "Israel", "japan": "Japan",
    "tokyo": "Japan", "philippines": "Philippines", "manila": "Philippines", "pakistan": "Pakistan",
    "nigeria": "Nigeria", "lagos": "Nigeria", "kenya": "Kenya", "nairobi": "Kenya", "brazil": "Brazil",
    "sao paulo": "Brazil", "mexico": "Mexico", "argentina": "Argentina", "colombia": "Colombia",
    "egypt": "Egypt", "turkey": "Turkey", "istanbul": "Turkey", "greece": "Greece", "athens": "Greece",
    "hungary": "Hungary", "budapest": "Hungary", "serbia": "Serbia", "belgrade": "Serbia",
    "lithuania": "Lithuania", "vilnius": "Lithuania", "latvia": "Latvia", "estonia": "Estonia",
    "tallinn": "Estonia", "new zealand": "New Zealand", "auckland": "New Zealand", "hong kong": "Hong Kong",
    "china": "China", "shanghai": "China", "malaysia": "Malaysia", "kuala lumpur": "Malaysia",
    "indonesia": "Indonesia", "vietnam": "Vietnam", "thailand": "Thailand", "bangkok": "Thailand",
    "skopje": "North Macedonia", "north macedonia": "North Macedonia", "cologne": "Germany", "hamburg": "Germany",
    "frankfurt": "Germany", "zagreb": "Croatia", "croatia": "Croatia", "slovakia": "Slovakia", "slovenia": "Slovenia",
    "cyprus": "Cyprus", "malta": "Malta", "luxembourg": "Luxembourg", "iceland": "Iceland", "georgia": "Georgia",
    "armenia": "Armenia", "morocco": "Morocco", "tunisia": "Tunisia", "ghana": "Ghana", "uganda": "Uganda",
    "saudi arabia": "Saudi Arabia", "riyadh": "Saudi Arabia", "qatar": "Qatar", "doha": "Qatar",
    "south korea": "South Korea", "seoul": "South Korea", "taiwan": "Taiwan", "sri lanka": "Sri Lanka",
    "bangladesh": "Bangladesh", "nepal": "Nepal", "chile": "Chile", "peru": "Peru", "uruguay": "Uruguay",
    "emea": "EMEA", "europe": "Europe", "eu": "Europe", "apac": "APAC", "latam": "LATAM",
}

_cache = DiskCache("ats")
_last_call: dict[str, float] = {}


# ---------------------------------------------------------------- classification
def _compile_functions() -> list[tuple[str, re.Pattern]]:
    out = []
    # Keywords match as whole words with an optional plural or gerund suffix, so "engineer"
    # also matches "Engineering" and "test" matches "Tester".
    for fn, kws in cfg()["jobs"]["function_keywords"].items():
        parts = [r"\b" + re.escape(str(k)).replace(r"\ ", r"\s+") + r"(?:s|es|ing|er|ers)?\b" for k in kws]
        out.append((fn, re.compile("|".join(parts), re.I)))
    return out


_FUNCTIONS: list[tuple[str, re.Pattern]] | None = None
_AI_RE: re.Pattern | None = None
_SENIOR_RE: re.Pattern | None = None


def classify_function(title: str, department: str | None = None) -> str:
    """First function (config order) whose keyword matches the title, then the department."""
    global _FUNCTIONS
    if _FUNCTIONS is None:
        _FUNCTIONS = _compile_functions()
    for text in (title or "", department or ""):
        if not text:
            continue
        for fn, rx in _FUNCTIONS:
            if rx.search(text):
                return fn
    return "other"


def is_ai_role(title: str) -> bool:
    global _AI_RE
    if _AI_RE is None:
        _AI_RE = re.compile(cfg()["jobs"]["ai_title_regex"], re.I)
    return bool(_AI_RE.search(title or ""))


def is_senior_commercial(title: str) -> bool:
    global _SENIOR_RE
    if _SENIOR_RE is None:
        _SENIOR_RE = re.compile(cfg()["jobs"]["senior_commercial_regex"], re.I)
    return bool(_SENIOR_RE.search(title or ""))


def country_guess(location: str | None, country_code: str | None = None, is_remote: bool = False) -> str | None:
    """'UK' when the location names the UK or a UK place; else a country label; 'remote' when only
    remote is stated; None when nothing is known."""
    if country_code:
        cc = country_code.strip().upper()
        if cc in ("GB", "UK"):
            return "UK"
    loc = (location or "").strip()
    low = loc.lower()
    if low:
        padded = f" {re.sub(r'[^a-z0-9.]+', ' ', low)} "
        for place in UK_PLACES:
            if f" {place} " in padded or (len(place) > 3 and place in low):
                return "UK"
        parts = [p.strip().lower() for p in re.split(r"[,/|;()\-]+", low) if p.strip()]
        for part in reversed(parts):
            if part in COUNTRY_SYNONYMS:
                return COUNTRY_SYNONYMS[part]
        for key, val in COUNTRY_SYNONYMS.items():
            if len(key) > 3 and f" {key} " in padded:
                return val
        if "remote" in low or "anywhere" in low or "distributed" in low:
            return "remote"
        last = parts[-1] if parts else low
        return last.title()[:40] if last else None
    if country_code:
        return country_code.strip().upper()
    if is_remote:
        return "remote"
    return None


# ---------------------------------------------------------------- HTTP
def _get_json(url: str, pace_key: str, timeout: int = 20, retries: int = 3):
    """GET JSON with per-ATS pacing, a daily disk cache and 429 backoff. Returns (status, json)."""
    cache_key = (url, today().isoformat())
    cached = _cache.get(*cache_key)
    if cached is not None:
        return cached["status"], cached["json"]
    status, data = 0, None
    backoff = 10.0
    for attempt in range(retries):
        gap = PACE_SECONDS.get(pace_key, 1.0) - (time.monotonic() - _last_call.get(pace_key, 0.0))
        if gap > 0:
            time.sleep(gap)
        try:
            r = requests.get(url, headers=HEADERS, timeout=timeout)
        except requests.RequestException as e:
            log.warning("%s network error %s", url, e)
            status, data = -1, None
            time.sleep(backoff)
            continue
        finally:
            _last_call[pace_key] = time.monotonic()
        status = r.status_code
        if status == 200:
            try:
                data = r.json()
            except ValueError:
                data = None
                status = 599
            break
        if status == 429:
            ra = r.headers.get("Retry-After")
            wait = float(ra) if ra and ra.replace(".", "").isdigit() else backoff
            if wait > 180:
                log.info("429 from %s with Retry-After %.0fs; giving up on this board for now", url.split("/")[2], wait)
                break
            log.info("429 from %s; sleeping %.0fs", url.split("/")[2], wait)
            time.sleep(wait)
            backoff = min(backoff * 2, 120)
            continue
        if status >= 500:
            time.sleep(backoff)
            continue
        break  # 404 and other 4xx are final
    if status in (200, 404):
        _cache.put({"status": status, "json": data, "fetched_at": now_iso()}, *cache_key)
    return status, data


# ---------------------------------------------------------------- board fetchers
def _iso_from_ms(ms) -> str | None:
    try:
        return dt.datetime.fromtimestamp(int(ms) / 1000, dt.timezone.utc).date().isoformat()
    except (TypeError, ValueError, OSError):
        return None


def fetch_greenhouse(token: str) -> tuple[int, list[dict]]:
    status, data = _get_json(f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true", "greenhouse")
    out = []
    for j in (data or {}).get("jobs", []) if isinstance(data, dict) else []:
        depts = [d.get("name") for d in j.get("departments") or [] if d.get("name")]
        out.append({"job_id": str(j.get("id")), "title": j.get("title"),
                    "location": (j.get("location") or {}).get("name"), "country_code": None, "is_remote": False,
                    "department": "; ".join(depts) or None,
                    "posted_at": (j.get("first_published") or j.get("updated_at") or "")[:10] or None,
                    "url": j.get("absolute_url")})
    return status, out


def fetch_lever(slug: str) -> tuple[int, list[dict]]:
    status, data = _get_json(f"https://api.lever.co/v0/postings/{slug}?mode=json", "lever")
    out = []
    for j in data if isinstance(data, list) else []:
        cats = j.get("categories") or {}
        loc = cats.get("location") or "; ".join(cats.get("allLocations") or []) or None
        out.append({"job_id": str(j.get("id")), "title": j.get("text"), "location": loc,
                    "country_code": j.get("country"), "is_remote": (j.get("workplaceType") == "remote"),
                    "department": cats.get("team") or cats.get("department"),
                    "posted_at": _iso_from_ms(j.get("createdAt")), "url": j.get("hostedUrl") or j.get("applyUrl")})
    return status, out


def fetch_ashby(name: str) -> tuple[int, list[dict]]:
    status, data = _get_json(f"https://api.ashbyhq.com/posting-api/job-board/{name}", "ashby")
    out = []
    for j in (data or {}).get("jobs", []) if isinstance(data, dict) else []:
        if j.get("isListed") is False:
            continue
        addr = ((j.get("address") or {}).get("postalAddress") or {})
        loc = j.get("location")
        if addr.get("addressCountry") and addr["addressCountry"].lower() not in (loc or "").lower():
            loc = f"{loc}, {addr['addressCountry']}" if loc else addr["addressCountry"]
        out.append({"job_id": str(j.get("id")), "title": j.get("title"), "location": loc,
                    "country_code": None, "is_remote": bool(j.get("isRemote")),
                    "department": j.get("department") or j.get("team"),
                    "posted_at": (j.get("publishedAt") or "")[:10] or None, "url": j.get("jobUrl") or j.get("applyUrl")})
    return status, out


def fetch_workable(sub: str) -> tuple[int, list[dict]]:
    status, data = _get_json(f"https://apply.workable.com/api/v1/widget/accounts/{sub}", "workable")
    jobs = (data or {}).get("jobs") if isinstance(data, dict) else None
    if status != 200 or jobs is None:
        status2, data2 = _get_json(f"https://www.workable.com/api/accounts/{sub}?details=true", "workable")
        if status2 == 200 and isinstance(data2, dict):
            status, jobs = status2, data2.get("jobs") or []
    out = []
    for j in jobs or []:
        loc = j.get("location")
        if isinstance(loc, dict):
            loc_txt = ", ".join(str(loc.get(k)) for k in ("city", "region", "country") if loc.get(k))
            cc = loc.get("country_code")
        else:
            loc_txt = ", ".join(str(j.get(k)) for k in ("city", "state", "country") if j.get(k)) or loc
            cc = None
        if j.get("telecommuting") and loc_txt:
            loc_txt = f"{loc_txt} (remote)"
        out.append({"job_id": str(j.get("shortcode") or j.get("id") or j.get("code")), "title": j.get("title"),
                    "location": loc_txt or None, "country_code": cc, "is_remote": bool(j.get("telecommuting")),
                    "department": j.get("department") if isinstance(j.get("department"), str) else None,
                    "posted_at": (j.get("published_on") or j.get("created_at") or "")[:10] or None,
                    "url": j.get("url") or j.get("application_url")})
    return status, out


FETCHERS = {"greenhouse": fetch_greenhouse, "lever": fetch_lever, "ashby": fetch_ashby, "workable": fetch_workable}


def fetch_adzuna(company_name: str, country: str = "gb", pages: int = 1) -> list[dict]:
    """Adzuna job search by company (cut list). Requires both env keys; returns [] without them."""
    app_id = env_key("adzuna_app_id_env")
    app_key = env_key("adzuna_key_env")
    if not (app_id and app_key):
        return []
    out = []
    for page in range(1, pages + 1):
        url = (f"https://api.adzuna.com/v1/api/jobs/{country}/search/{page}?app_id={app_id}&app_key={app_key}"
               f"&results_per_page=50&company={requests.utils.quote(company_name)}&content-type=application/json")
        status, data = _get_json(url, "adzuna")
        for j in (data or {}).get("results", []) if isinstance(data, dict) else []:
            out.append({"job_id": str(j.get("id")), "title": j.get("title"),
                        "location": (j.get("location") or {}).get("display_name"), "country_code": "GB",
                        "is_remote": False, "department": (j.get("category") or {}).get("label"),
                        "posted_at": (j.get("created") or "")[:10] or None, "url": j.get("redirect_url")})
        if not data or len(data.get("results", [])) < 50:
            break
    return out


# ---------------------------------------------------------------- rows
def posting_rows(company_number: str, ats: str, postings: list[dict], fetched_at: str) -> list[dict]:
    rows = []
    for p in postings:
        title = p.get("title") or ""
        rows.append({
            "company_number": company_number, "ats": ats, "job_id": p.get("job_id"), "title": title,
            "function": classify_function(title, p.get("department")),
            "location": p.get("location"),
            "country_guess": country_guess(p.get("location"), p.get("country_code"), bool(p.get("is_remote"))),
            "is_ai_role": is_ai_role(title), "is_senior_commercial": is_senior_commercial(title),
            "posted_at": p.get("posted_at"), "url": p.get("url"), "fetched_at": fetched_at,
        })
    return rows


def summarise(company_number: str, rows: list[dict], fetched_at: str) -> dict:
    n = len(rows)
    funcs = Counter(r["function"] for r in rows)
    eng = funcs.get("engineering", 0) + funcs.get("product", 0) + funcs.get("data_ai", 0)
    intl = sum(1 for r in rows if r["country_guess"] not in ("UK", "remote", None))
    return {"company_number": company_number, "open_roles": n,
            "engineering_share": round(eng / n, 3) if n else None,
            "ai_roles": sum(1 for r in rows if r["is_ai_role"]),
            "senior_commercial_roles": sum(1 for r in rows if r["is_senior_commercial"]),
            "international_roles": intl, "functions_json": json.dumps(dict(funcs), sort_keys=True),
            "fetched_at": fetched_at}


def jobs_frame(rows: list[dict]):
    import polars as pl

    schema = {"company_number": pl.Utf8, "ats": pl.Utf8, "job_id": pl.Utf8, "title": pl.Utf8, "function": pl.Utf8,
              "location": pl.Utf8, "country_guess": pl.Utf8, "is_ai_role": pl.Boolean,
              "is_senior_commercial": pl.Boolean, "posted_at": pl.Utf8, "url": pl.Utf8, "fetched_at": pl.Utf8}
    return pl.DataFrame([{k: r.get(k) for k in schema} for r in rows], schema=schema) if rows else pl.DataFrame(schema=schema)


def summary_frame(rows: list[dict]):
    import polars as pl

    schema = {"company_number": pl.Utf8, "open_roles": pl.Int64, "engineering_share": pl.Float64, "ai_roles": pl.Int64,
              "senior_commercial_roles": pl.Int64, "international_roles": pl.Int64, "functions_json": pl.Utf8,
              "fetched_at": pl.Utf8}
    return pl.DataFrame([{k: r.get(k) for k in schema} for r in rows], schema=schema) if rows else pl.DataFrame(schema=schema)


# ---------------------------------------------------------------- pull
def pull(boards: list[dict], write: bool = True) -> tuple[list[dict], list[dict]]:
    """boards: [{company_number, ats, ats_token}]. Writes jobs.parquet and jobs_summary.parquet."""
    all_rows: list[dict] = []
    summaries: list[dict] = []
    t0 = time.time()
    for i, b in enumerate(boards, 1):
        n = normalise_company_number(b["company_number"])
        ats, tok = b.get("ats"), b.get("ats_token")
        if ats not in FETCHERS or not tok:
            continue
        fetched_at = now_iso()
        status, postings = FETCHERS[ats](tok)
        if status != 200:
            log.info("%s %s:%s -> HTTP %s", n, ats, tok, status)
            summaries.append({**summarise(n, [], fetched_at), "open_roles": None})
            continue
        rows = posting_rows(n, ats, postings, fetched_at)
        all_rows.extend(rows)
        s = summarise(n, rows, fetched_at)
        summaries.append(s)
        log.info("%s %s:%s -> %d roles, eng_share=%s, ai=%s, intl=%s", n, ats, tok, s["open_roles"],
                 s["engineering_share"], s["ai_roles"], s["international_roles"])
        if write and i % 100 == 0:
            write_parquet(jobs_frame(all_rows), "jobs")
            write_parquet(summary_frame(summaries), "jobs_summary")
    if write:
        write_parquet(jobs_frame(all_rows), "jobs")
        write_parquet(summary_frame(summaries), "jobs_summary")
    log.info("jobs done: %d boards, %d postings, %.0fs", len(boards), len(all_rows), time.time() - t0)
    return all_rows, summaries


def boards_from_websites(numbers: list[str] | None = None) -> list[dict]:
    if not parquet_path("websites").exists():
        log.info("no websites.parquet; nothing to pull")
        return []
    import polars as pl

    df = read_parquet("websites")
    if "ats" not in df.columns:
        return []
    df = df.filter(pl.col("ats").is_in(list(SUPPORTED)) & pl.col("ats_token").is_not_null())
    if numbers:
        df = df.filter(pl.col("company_number").is_in([normalise_company_number(x) for x in numbers]))
    return df.select(["company_number", "ats", "ats_token"]).to_dicts()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--numbers", help="comma-separated company numbers to restrict to")
    ap.add_argument("--board", help="ats:token to pull one board by hand, e.g. greenhouse:cognism")
    ap.add_argument("--company", help="company number to attribute a --board pull to", default="00000000")
    ap.add_argument("--no-write", action="store_true")
    args = ap.parse_args(argv)
    if args.board:
        ats, tok = args.board.split(":", 1)
        boards = [{"company_number": args.company, "ats": ats, "ats_token": tok}]
    else:
        boards = boards_from_websites(args.numbers.split(",") if args.numbers else None)
    if not boards:
        log.info("no supported ATS boards to pull")
        return 0
    rows, summaries = pull(boards, write=not args.no_write)
    if args.board:
        for r in rows[:15]:
            print(f'{r["function"]:16s} {r["country_guess"] or "-":10s} ai={int(r["is_ai_role"])} sc={int(r["is_senior_commercial"])} {r["title"][:60]} | {r["location"]}')
        print(summaries[0] if summaries else None)
    return 0


if __name__ == "__main__":
    sys.exit(main())
