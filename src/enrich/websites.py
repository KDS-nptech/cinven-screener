"""Stage 4b/4c: company website discovery and fetch.

Run from the repo root:
    python -m src.enrich.websites discover --from-universe
    python -m src.enrich.websites discover --companies "06452255|PortSwigger Ltd|Knutsford,10113345|usecure Ltd|Manchester"
    python -m src.enrich.websites fetch                      # every websites.parquet row with a domain
    python -m src.enrich.websites fetch --numbers 06452255

discover: for each company find its website domain. Engines are tried in order
(default bing, seznam, ddg; see ENGINES) and a result is accepted only when the host or
page title carries distinctive tokens of the company name. When no engine yields a
match, name-based domain probes (slug.co.uk, slug.com, slug.io ...) are tried. Every
search response is cached in data/cache/<engine>/ keyed on the query; blocked, CAPTCHA
or decoy responses are never cached. An engine that returns 5 consecutive blocked
responses is disabled for the rest of the run.

Bing from a datacenter egress returns 200 with decoy results (a random popular query's
results). The decoy check flags a result page none of whose results mention any query
token. Seznam.cz returned real results from the same egress; DuckDuckGo lite served a
CAPTCHA. See docs/enrichment_notes.md.

fetch: robots.txt aware homepage plus up to websites.max_pages - 1 product/about pages,
trafilatura text extraction capped at websites.max_chars, ATS / careers / GitHub / API
docs / integrations / pricing detection. Full text per company goes to
data/cache/web/<company_number>.json; the summary to data/parquet/websites.parquet.
"""
from __future__ import annotations

import argparse
import base64
import concurrent.futures as cf
import hashlib
import json
import os
import random
import re
import sys
import threading
import time
import urllib.robotparser
from dataclasses import dataclass, field
from urllib.parse import parse_qs, urljoin, urlparse, urlsplit, urlunsplit

import requests
import tldextract
from bs4 import BeautifulSoup

from src.common import (REPO, DiskCache, cfg, get_logger, name_tokens, normalise_company_number, now_iso,
                        parquet_path, path, read_parquet, write_parquet)

log = get_logger("websites")
WEBSITES_TABLE = os.environ.get("WEBSITES_TABLE", "websites")   # a second discovery worker writes to its own table

DESKTOP_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/129.0.0.0 Safari/537.36")
SEARCH_HEADERS = {
    "User-Agent": DESKTOP_UA,
    "Accept-Language": "en-GB,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}
ENGINES = ["brave", "bing", "seznam", "ddg"]   # brave is skipped when BRAVE_API_KEY is absent
DECOY_CHECK_ENGINES = {"bing"}
SEARCH_GAP_SECONDS = 1.5
SEARCH_JITTER = 0.6
BLOCK_DISABLE_AFTER = 5
PROBE_TIMEOUT = 6
FETCH_TIMEOUT = 10
PER_DOMAIN_DELAY = 1.0
MAX_HTML_BYTES = 2_000_000

# Hosts that are never a company's own site; extends config websites.directory_domains.
EXTRA_DIRECTORY_DOMAINS = {
    "approvedbusiness.co.uk", "tiscreport.org", "thefreedictionary.com", "easydigitalfiling.com", "lse.co.uk", "stacklok.com", "acronymfinder.com", "acronyms.thefreedictionary.com",
    "cloudtango.net", "datalog.co.uk", "checkall.co.uk", "businessmagnet.co.uk", "nottinghampost.com", "companycheck.co.uk",
    "allaboutjobs.co.uk", "clutch.co", "goodfirms.co", "sortlist.com", "designrush.com", "themanifest.com", "topdevelopers.co", "dealroom.co", "app.dealroom.co", "globaldata.com", "cybo.com", "yably.co.uk",
    "bizstats.co.uk", "govwire.co.uk", "datanyze.com", "craft.co", "ukbusinessdatabase.co.uk", "business-sale.com",
    "tracxn.com", "f6s.com", "wellfound.com", "angel.co", "growjo.com", "charitybase.uk", "legislation.gov.uk",
    "ico.org.uk", "fca.org.uk", "register.fca.org.uk", "reuters.com", "marketscreener.com", "morningstar.co.uk", "morningstar.com",
    "finance.yahoo.com", "uk.finance.yahoo.com", "sec.gov", "nasdaq.com", "companieshouse.gov.uk", "companydata.co.uk",
    "endole.co.uk", "checkcompany.co.uk", "opengovuk.com", "openly.co.uk", "ukcompanyinfo.com", "companiesdata.uk", "companyhouse.de",
    "dnb.co.uk", "experian.co.uk", "creditsafe.com", "redflagalert.com", "pomanda.com", "companyinfo.ai", "findcompany.co.uk",
    "ukcompaniesdirectory.com", "infobelpro.com", "infobel.com", "yell.com", "192.com", "ukdirectory.co.uk", "theukcompanies.com",
    "business-directory-uk.co.uk", "uk-local-search.co.uk", "localstore.co.uk", "mapcarta.com", "showmelocal.com", "manta.com",
    "glassdoor.co.uk", "indeed.com", "totaljobs.com", "reed.co.uk", "cv-library.co.uk", "jobsite.co.uk", "monster.co.uk", "adzuna.co.uk",
    "zoominfo.com", "crunchbase.com", "pitchbook.com", "beauhurst.com", "linkedin.com", "uk.linkedin.com", "facebook.com", "x.com",
    "instagram.com", "youtube.com", "twitter.com", "wikipedia.org", "en.wikipedia.org", "bloomberg.com", "thegazette.co.uk",
    "google.com", "play.google.com", "apple.com", "microsoft.com", "amazon.co.uk", "amazon.com",
    "g2.com", "capterra.com", "capterra.co.uk", "getapp.com", "trustpilot.com", "github.com",
    "medium.com", "reddit.com", "tiktok.com", "vimeo.com", "booking.com", "tripadvisor.com",
    "tripadvisor.co.uk", "gov.uk", "nhs.uk", "ft.com", "theguardian.com", "bbc.co.uk", "telegraph.co.uk",
    "prnewswire.com", "businesswire.com", "globenewswire.com", "techcrunch.com", "sifted.eu",
    "uktech.news", "startups.co.uk", "growthbusiness.co.uk", "insidermedia.com", "thebusinessdesk.com",
    "cbinsights.com", "owler.com", "signalhire.com", "rocketreach.co", "apollo.io", "lusha.com",
    "kompass.com", "europages.co.uk", "cylex.co.uk", "hotfrog.co.uk", "freeindex.co.uk", "scoot.co.uk",
    "thomsonlocal.com", "touchlocal.com", "misterwhat.co.uk", "ukbusinessdirectory.co.uk",
    "companiesintheuk.co.uk", "company-director-check.co.uk", "companies.london", "ukdata.com",
    "find-and-update.company-information.service.gov.uk", "wikidata.org", "wikimedia.org",
    "chromewebstore.google.com", "slideshare.net", "issuu.com", "yumpu.com", "scribd.com",
    "seznam.cz", "bing.com", "duckduckgo.com", "wordpress.com", "blogspot.com",
}
INTEGRATION_NAMES = ["Salesforce", "Xero", "Sage", "QuickBooks", "Slack", "Microsoft", "Teams", "HubSpot",
                     "Zapier", "SAP", "Oracle", "NetSuite", "EMIS", "SystmOne", "Cerner", "Epic", "NHS Spine"]
CAREER_TOKENS = ("career", "jobs", "join", "vacanc", "work-with-us", "work with us", "join us", "join-us",
                 "we're hiring", "we are hiring", "hiring")
PRIORITY_TOKENS = ["product", "platform", "solutions", "features", "integrations", "pricing", "customers",
                   "about", "careers", "api", "developers"]
# Markers of a CAPTCHA interstitial. The bare word "captcha" is not one: Seznam's normal
# result page carries a conf_recaptcha_key config value.
CAPTCHA_MARKERS = ("confirm this search was made by a human", "are you not a robot",
                   "unusual traffic", "select all squares containing", "verify you are human",
                   "<title>captcha", "showcaptcha", "captcha-block", "/captcha?")


# ---------------------------------------------------------------- name helpers
LEGAL_SUFFIX_RE = re.compile(r"\b(LIMITED|LTD\.?|PLC|LLP|L\.L\.P\.|LP|INC\.?|CIC|CIO)\b\.?", re.I)


def clean_name(name: str) -> str:
    """Company name without its legal suffix and trailing punctuation."""
    s = LEGAL_SUFFIX_RE.sub(" ", name or "")
    s = re.sub(r"[(),.]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def slugs(name: str) -> list[str]:
    """Candidate domain slugs: joined and hyphenated forms of the cleaned name, plus the token form."""
    base = clean_name(name).lower()
    words = [w for w in re.split(r"[^a-z0-9]+", base) if w]
    out: list[str] = []
    if words:
        out.append("".join(words))
        if len(words) > 1:
            out.append("-".join(words))
    toks = [t.lower() for t in name_tokens(name)]
    if toks and "".join(toks) not in out:
        out.append("".join(toks))
    if len(toks) > 1 and "-".join(toks) not in out:
        out.append("-".join(toks))
    # initials for three-plus word names ("Digital Applications International" -> dai)
    if len(words) >= 3:
        ini = "".join(w[0] for w in words)
        if 3 <= len(ini) <= 6:
            out.append(ini)
    return [s for s in dict.fromkeys(out) if 3 <= len(s) <= 60]


def distinctive_tokens(name: str) -> list[str]:
    """name_tokens with very short or purely numeric tokens dropped (lowercase)."""
    toks = [t.lower() for t in name_tokens(name)]
    keep = [t for t in toks if len(t) >= 3 and not t.isdigit()]
    return keep or toks


def registered_domain(url_or_host: str) -> str | None:
    host = urlparse(url_or_host).hostname if "://" in url_or_host else url_or_host
    if not host:
        return None
    ext = tldextract.extract(host.lower())
    if not ext.domain:
        return None
    if hasattr(ext, "top_domain_under_public_suffix"):
        return ext.top_domain_under_public_suffix or None
    return ext.registered_domain or None


_DIRS: set[str] | None = None


def directory_domains() -> set[str]:
    global _DIRS
    if _DIRS is None:
        _DIRS = set(d.lower() for d in cfg()["websites"]["directory_domains"]) | EXTRA_DIRECTORY_DOMAINS
    return _DIRS


def is_directory_host(host: str) -> bool:
    host = re.sub(r"^www\.", "", (host or "").lower())
    dirs = directory_domains()
    reg = registered_domain(host) or host
    return host in dirs or reg in dirs or any(host.endswith("." + d) for d in dirs)


def host_label(host: str) -> str:
    """The registrable label of a host without suffix or subdomains: www.red-gate.com -> redgate."""
    ext = tldextract.extract((host or "").lower())
    return re.sub(r"[^a-z0-9]", "", ext.domain or "")


def match_kind(name: str, host: str, title: str) -> str | None:
    """Classify a search result against a company name.

    Returns 'host' when the site's own domain label carries the name (strongest), 'title'
    when only the page title does, None otherwise.
    - one-token names: the token in the host label, or in the title.
    - multi-token names: host label equals a token, contains the joined tokens, or contains a
      token of six plus characters; else two tokens across host plus title; else the full
      cleaned name inside the title.
    """
    toks = distinctive_tokens(name)
    if not toks:
        return None
    label = host_label(host)
    title_compact = re.sub(r"[^a-z0-9]", "", (title or "").lower())
    full = re.sub(r"[^a-z0-9]", "", clean_name(name).lower())
    joined = "".join(toks)
    if len(toks) == 1:
        t = toks[0]
        if t in label:
            return "host"
        return "title" if t in title_compact else None
    if label and (label in (joined, full) or joined in label or any(label == t for t in toks)
                  or any(t in label for t in toks if len(t) >= 6)):
        return "host"
    host_hits = sum(1 for t in toks if t in label)
    title_hits = sum(1 for t in toks if t in title_compact)
    if host_hits and host_hits + title_hits >= 2:
        return "host"
    if title_hits >= 2 or (full and full in title_compact):
        return "title"
    return None


def title_matches(name: str, host: str, title: str) -> bool:
    return match_kind(name, host, title) is not None


# ---------------------------------------------------------------- search engines
@dataclass
class SearchResult:
    title: str
    url: str
    host: str
    snippet: str = ""


@dataclass
class EngineState:
    name: str
    enabled: bool = True
    queries: int = 0
    blocked: int = 0
    consecutive_blocked: int = 0
    cache_hits: int = 0
    last_call: float = 0.0
    lock: threading.Lock = field(default_factory=threading.Lock)


class Blocked(Exception):
    """Search engine refused, served a CAPTCHA or decoy results."""


def decode_bing_url(href: str) -> str:
    """Bing wraps result links as /ck/a?...&u=a1<base64url>; decode to the target URL."""
    if "bing.com/ck/a" not in href:
        return href
    q = parse_qs(urlparse(href).query)
    u = (q.get("u") or [""])[0]
    if u.startswith("a1"):
        u = u[2:]
    try:
        pad = "=" * (-len(u) % 4)
        return base64.urlsafe_b64decode(u + pad).decode("utf-8", "replace")
    except Exception:
        return href


def parse_bing(html: str) -> list[SearchResult]:
    soup = BeautifulSoup(html, "lxml")
    out = []
    for li in soup.select("li.b_algo"):
        a = li.select_one("h2 a[href]")
        if not a:
            continue
        url = decode_bing_url(a["href"])
        if not url.startswith("http"):
            cite = li.select_one("cite")
            if cite:
                url = "https://" + re.sub(r"\s*›.*$", "", cite.get_text(" ", strip=True)).replace("https://", "").replace("http://", "")
        host = urlparse(url).hostname or ""
        snippet_el = li.select_one("p") or li.select_one(".b_caption")
        out.append(SearchResult(a.get_text(" ", strip=True), url, host,
                                snippet_el.get_text(" ", strip=True) if snippet_el else ""))
    return out


def parse_seznam(html: str) -> list[SearchResult]:
    soup = BeautifulSoup(html, "lxml")
    out = []
    for h3 in soup.select("h3"):
        a = h3.find("a", href=True)
        if not a or not a["href"].startswith("http"):
            continue
        url = a["href"]
        snippet = ""
        nxt = h3.find_next_sibling()
        if nxt is not None:
            snippet = nxt.get_text(" ", strip=True)[:300]
        out.append(SearchResult(h3.get_text(" ", strip=True), url, urlparse(url).hostname or "", snippet))
    return out


def parse_ddg_lite(html: str) -> list[SearchResult]:
    soup = BeautifulSoup(html, "lxml")
    out = []
    links = soup.select("a.result-link")
    snippets = soup.select("td.result-snippet")
    for i, a in enumerate(links):
        url = a.get("href", "")
        if url.startswith("//duckduckgo.com/l/?") or "uddg=" in url:
            q = parse_qs(urlparse(url).query)
            url = (q.get("uddg") or [url])[0]
        if not url.startswith("http"):
            continue
        snip = snippets[i].get_text(" ", strip=True) if i < len(snippets) else ""
        out.append(SearchResult(a.get_text(" ", strip=True), url, urlparse(url).hostname or "", snip))
    return out


def parse_brave(text: str) -> list[SearchResult]:
    """Brave Search API JSON -> results."""
    try:
        j = json.loads(text)
    except json.JSONDecodeError:
        return []
    out = []
    for r in (j.get("web") or {}).get("results") or []:
        url = r.get("url") or ""
        if not url.startswith("http"):
            continue
        out.append(SearchResult(r.get("title") or "", url, urlparse(url).hostname or "", r.get("description") or ""))
    return out


def _dotenv_value(name: str) -> str | None:
    f = REPO / ".env"
    if not f.exists():
        return None
    for line in f.read_text().splitlines():
        if line.strip().startswith(name + "="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


UK_SIGNAL_RE = re.compile(r"united kingdom|\buk\b|\bltd\b|\blimited\b|\+44|£|\bengland\b|\bscotland\b|\bwales\b|\blondon\b|\bmanchester\b|"
                          r"\bbirmingham\b|\bleeds\b|\bedinburgh\b|\bglasgow\b|\bbristol\b|\.co\.uk|\b[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}\b|companies house|vat no", re.I)


def uk_signal(html_or_text: str) -> bool:
    """True when a page carries any UK marker (country, Ltd, +44, £, a postcode, a big city)."""
    return bool(UK_SIGNAL_RE.search(html_or_text[:300_000] if html_or_text else ""))


def looks_like_decoy(results: list[SearchResult], query_tokens: list[str]) -> bool:
    """True when a non-empty result page mentions none of the query tokens anywhere."""
    if not results or not query_tokens:
        return False
    blob = " ".join(f"{r.title} {r.url} {r.snippet}" for r in results).lower()
    blob_compact = re.sub(r"[^a-z0-9]", "", blob)
    return not any(t in blob_compact for t in query_tokens)


class Searcher:
    """Runs queries against the engines in order with pacing, caching and block detection."""

    def __init__(self, engines: list[str] | None = None, session: requests.Session | None = None,
                 gap: float = SEARCH_GAP_SECONDS, jitter: float = SEARCH_JITTER):
        self.engines = engines or list(ENGINES)
        if "brave" in self.engines and not (os.environ.get("BRAVE_API_KEY") or _dotenv_value("BRAVE_API_KEY")):
            self.engines = [e for e in self.engines if e != "brave"]
        self.state = {e: EngineState(e) for e in self.engines}
        self.caches = {e: DiskCache(e) for e in self.engines}
        self.session = session or requests.Session()
        self.session.headers.update(SEARCH_HEADERS)
        self.gap = gap
        self.jitter = jitter

    def _pace(self, st: EngineState):
        with st.lock:
            wait = st.last_call + self.gap + random.uniform(0, self.jitter) - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            st.last_call = time.monotonic()

    def _request(self, engine: str, query: str) -> requests.Response:
        if engine == "brave":
            key = os.environ.get("BRAVE_API_KEY") or _dotenv_value("BRAVE_API_KEY")
            return self.session.get("https://api.search.brave.com/res/v1/web/search",
                                    params={"q": query, "country": "GB", "count": 10, "search_lang": "en"},
                                    headers={"Accept": "application/json", "X-Subscription-Token": key or ""}, timeout=20)
        if engine == "bing":
            return self.session.get("https://www.bing.com/search",
                                    params={"q": query, "setlang": "en-GB", "cc": "GB"}, timeout=20)
        if engine == "seznam":
            return self.session.get("https://search.seznam.cz/", params={"q": query}, timeout=20)
        if engine == "ddg":
            return self.session.post("https://lite.duckduckgo.com/lite/", data={"q": query}, timeout=20)
        raise ValueError(engine)

    @staticmethod
    def _parse(engine: str, html: str) -> list[SearchResult]:
        return {"bing": parse_bing, "seznam": parse_seznam, "ddg": parse_ddg_lite, "brave": parse_brave}[engine](html)

    def search(self, engine: str, query: str, query_tokens: list[str]) -> list[SearchResult]:
        """Results for a query. Raises Blocked on CAPTCHA / 4xx / decoy. Caches good responses."""
        st = self.state[engine]
        if not st.enabled:
            raise Blocked(f"{engine} disabled")
        cache = self.caches[engine]
        cached = cache.get(query)
        if cached is not None:
            st.cache_hits += 1
            return self._parse(engine, cached["text"])
        self._pace(st)
        st.queries += 1
        try:
            r = self._request(engine, query)
        except requests.RequestException as e:
            self._note_block(st, f"network {e.__class__.__name__}")
            raise Blocked(str(e))
        if engine == "seznam":
            r.encoding = "utf-8"
        text = r.text
        low = text[:200_000].lower()
        if r.status_code in (403, 429, 500, 502, 503) or any(m in low for m in CAPTCHA_MARKERS):
            self._note_block(st, f"status {r.status_code}, captcha={any(m in low for m in CAPTCHA_MARKERS)}")
            raise Blocked(f"{engine} {r.status_code}")
        if r.status_code != 200 and r.status_code != 202:
            self._note_block(st, f"status {r.status_code}")
            raise Blocked(f"{engine} {r.status_code}")
        results = self._parse(engine, text)
        # Bing's soft block serves a full page of results for an unrelated popular query.
        # Other engines return a thin or empty page for an obscure name, which is a genuine
        # "no match", so the decoy check is Bing-only.
        if engine in DECOY_CHECK_ENGINES and looks_like_decoy(results, query_tokens):
            self._note_block(st, "decoy results")
            raise Blocked(f"{engine} decoy")
        st.consecutive_blocked = 0
        cache.put({"status": r.status_code, "text": text, "fetched_at": now_iso(), "query": query}, query)
        return results

    def _note_block(self, st: EngineState, why: str):
        st.blocked += 1
        st.consecutive_blocked += 1
        log.info("%s blocked (%s), %d consecutive", st.name, why, st.consecutive_blocked)
        if st.consecutive_blocked >= BLOCK_DISABLE_AFTER and st.enabled:
            st.enabled = False
            log.warning("%s disabled for this run after %d consecutive blocks", st.name, st.consecutive_blocked)

    def stats(self) -> dict:
        return {e: {"queries": s.queries, "blocked": s.blocked, "cache_hits": s.cache_hits, "enabled": s.enabled}
                for e, s in self.state.items()}


# ---------------------------------------------------------------- discovery
def build_query(name: str, post_town: str | None) -> str:
    q = f'"{clean_name(name)}"'
    if post_town:
        q += f" {post_town.strip().title()}"
    return q


# Title-only matches on these suffixes are ignored: Seznam ranks Czech download and
# directory sites that merely mention a company.
TITLE_ONLY_SKIP_SUFFIXES = (".cz", ".sk", ".pl", ".hu", ".ru", ".ua", ".by")


DIRECTORY_PATH_RE = re.compile(r"/(company|companies|business|biz|profile|overview|insight|firm|organisation|organization|directory|listing|supplier|vendor)s?/", re.I)
DIRECTORY_TITLE_RE = re.compile(r"company (profile|information|overview|details|check|data)|credit report|business summary|filing history|"
                                r"\b[A-Z]{1,2}\d[A-Z\d]?\s?\d[A-Z]{2}\b|\bltd\.?,\s|\blimited,\s|\bltd in\b|find and update|registered office|"
                                r"\b(overview|profile) -|companies house|vat number|turnover|net worth|employees:|people also|client reviews|"
                                r"\breviews\b.*\b(ltd|limited)\b|how is .* abbreviated|acronym|what does .* stand for", re.I)


def looks_like_directory_result(url: str, title: str) -> bool:
    """A listing page about the company rather than the company's own site."""
    path = urlparse(url).path or ""
    return bool(DIRECTORY_PATH_RE.search(path)) or bool(DIRECTORY_TITLE_RE.search(title or ""))


def pick_match(name: str, results: list[SearchResult]) -> tuple[SearchResult | None, list[dict]]:
    """Best non-directory result: the first whose host carries the name, else the first whose
    title does. Also returns the top 5 non-directory candidates (host, title)."""
    candidates = []
    host_match = None
    title_match = None
    for r in results:
        if not r.host or is_directory_host(r.host):
            continue
        if looks_like_directory_result(r.url, r.title) and match_kind(name, r.host, r.title) != "host":
            continue
        candidates.append({"host": r.host, "title": r.title[:120]})
        kind = match_kind(name, r.host, r.title)
        if kind == "host" and host_match is None:
            host_match = r
        elif kind == "title" and title_match is None and not r.host.lower().endswith(TITLE_ONLY_SKIP_SUFFIXES):
            title_match = r
    return host_match or title_match, candidates[:5]


def homepage_of(url: str) -> str:
    p = urlsplit(url)
    return urlunsplit((p.scheme or "https", p.netloc, "/", "", ""))


def probe_domains(name: str, session: requests.Session | None = None, timeout: int = PROBE_TIMEOUT) -> tuple[str | None, str | None, list[dict]]:
    """Try slug.co.uk / www.slug.co.uk / slug.com / slug.io / slug.ai / slug.co; accept when the
    final page title carries a distinctive token. Returns (homepage_url, title, tried)."""
    session = session or requests.Session()
    tried = []
    for slug in slugs(name)[:4]:
        for host in (f"{slug}.co.uk", f"www.{slug}.co.uk", f"{slug}.com", f"{slug}.io", f"{slug}.ai", f"{slug}.uk", f"{slug}.net"):
            url = f"https://{host}/"
            try:
                r = session.get(url, headers={"User-Agent": DESKTOP_UA, "Accept-Language": "en-GB,en;q=0.9"},
                                timeout=timeout, allow_redirects=True, stream=True)
                body = r.raw.read(200_000, decode_content=True) if r.status_code == 200 else b""
                r.close()
            except (requests.RequestException, UnicodeError, ValueError) as e:
                tried.append({"host": host, "title": None})
                continue
            if r.status_code != 200 or not body:
                tried.append({"host": host, "title": f"HTTP {r.status_code}"})
                continue
            soup = BeautifulSoup(body, "lxml")
            title = soup.title.get_text(" ", strip=True) if soup.title else ""
            final_host = urlparse(r.url).hostname or host
            tried.append({"host": final_host, "title": title[:120]})
            if is_directory_host(final_host):
                continue
            if any(k in title.lower() for k in ("for sale", "domain parked", "parked domain", "buy this domain",
                                                 "sedo", "godaddy", "coming soon", "index of", "apache", "nginx", "iis windows",
                                                 "default web", "untitled", "web server", "under construction", "hugedomains",
                                                 "namecheap", "dan.com", "afternic", "squarespace", "wix.com", "page not found")):
                continue
            if len(title.strip()) < 4:
                continue
            if title_matches(name, final_host, title):
                if not final_host.endswith(".uk") and not uk_signal(body.decode("utf-8", "replace")):
                    tried[-1]["title"] = (title[:100] + " [no UK signal]")
                    continue
                return homepage_of(r.url), title, tried
    return None, None, tried


def discover_one(company: dict, searcher: Searcher, session: requests.Session | None = None,
                 probe: bool = True) -> dict:
    name = company["name"]
    n = normalise_company_number(company["company_number"])
    query = build_query(name, company.get("post_town"))
    # Decoy detection uses name tokens only: a town such as London appears in random results.
    qtokens = distinctive_tokens(name)
    row = {"company_number": n, "domain": None, "homepage_url": None, "discovery_method": "none",
           "matched_title": None, "candidates_json": None, "discovered_at": now_iso()}
    candidates: list[dict] = []
    for engine in searcher.engines:
        if not searcher.state[engine].enabled:
            continue
        try:
            # Brave ranks the official site higher without the town; directories crowd in with it.
            results = searcher.search(engine, clean_name(name) if engine == "brave" else query, qtokens)
        except Blocked:
            continue
        match, cands = pick_match(name, results)
        candidates = candidates or cands
        if match:
            row.update(domain=registered_domain(match.url), homepage_url=homepage_of(match.url),
                       discovery_method=f"{engine}_title_match", matched_title=match.title[:200])
            break
        if cands:
            break  # a real result page with non-directory hosts but no match: do not burn another engine
    if row["domain"] is None and probe:
        url, title, tried = probe_domains(name, session)
        candidates = candidates or tried
        if url:
            row.update(domain=registered_domain(url), homepage_url=url, discovery_method="domain_probe",
                       matched_title=(title or "")[:200])
    row["candidates_json"] = json.dumps(candidates[:5]) if candidates else None
    return row


DISCOVERY_COLS = ["company_number", "domain", "homepage_url", "discovery_method", "matched_title",
                  "candidates_json", "discovered_at"]
FETCH_COLS = ["pages_fetched", "text_chars", "text_hash", "careers_url", "ats", "ats_token", "github_org",
              "api_docs_url", "integrations_count", "customer_logos_hint", "pricing_hint", "robots_blocked",
              "fetch_error", "fetched_at", "name_match", "uk_signal"]


def websites_frame(rows: list[dict]):
    import polars as pl

    schema = {
        "company_number": pl.Utf8, "domain": pl.Utf8, "homepage_url": pl.Utf8, "discovery_method": pl.Utf8,
        "matched_title": pl.Utf8, "candidates_json": pl.Utf8, "discovered_at": pl.Utf8,
        "pages_fetched": pl.Int64, "text_chars": pl.Int64, "text_hash": pl.Utf8, "careers_url": pl.Utf8,
        "ats": pl.Utf8, "ats_token": pl.Utf8, "github_org": pl.Utf8, "api_docs_url": pl.Utf8,
        "integrations_count": pl.Int64, "customer_logos_hint": pl.Int64, "pricing_hint": pl.Boolean,
        "robots_blocked": pl.Boolean, "fetch_error": pl.Utf8, "fetched_at": pl.Utf8, "name_match": pl.Boolean, "uk_signal": pl.Boolean,
    }
    if not rows:
        return pl.DataFrame(schema=schema)
    return pl.DataFrame([{k: r.get(k) for k in schema} for r in rows], schema=schema)


def load_existing() -> dict[str, dict]:
    p = parquet_path(WEBSITES_TABLE)
    if not p.exists():
        return {}
    df = read_parquet(WEBSITES_TABLE)
    return {r["company_number"]: r for r in df.to_dicts()}


def discover(companies: list[dict], engines: list[str] | None = None, probe: bool = True,
             write: bool = True, redo: bool = False, write_every: int = 200) -> list[dict]:
    """Discover domains for [{company_number, name, post_town}] and merge into websites.parquet."""
    existing = load_existing() if write else {}
    searcher = Searcher(engines)
    session = requests.Session()
    out_rows: list[dict] = []
    t0 = time.time()
    found = 0

    def flush():
        if write:
            merged = dict(existing)
            for r in out_rows:
                merged[r["company_number"]] = {**merged.get(r["company_number"], {}), **r}
            write_parquet(websites_frame(list(merged.values())), WEBSITES_TABLE)

    for i, c in enumerate(companies, 1):
        n = normalise_company_number(c["company_number"])
        prev = existing.get(n)
        if prev and not redo and prev.get("discovery_method") not in (None, "none"):
            out_rows.append({k: prev.get(k) for k in DISCOVERY_COLS})
            found += 1
            continue
        row = discover_one({**c, "company_number": n}, searcher, session, probe=probe)
        if row["domain"]:
            found += 1
        out_rows.append(row)
        log.info("%s %-40s -> %s (%s)", n, c["name"][:40], row["domain"], row["discovery_method"])
        if i % 25 == 0:
            log.info("%d/%d, %d with domain, %.0fs, engines=%s", i, len(companies), found,
                     time.time() - t0, searcher.stats())
        if write_every and i % write_every == 0:
            flush()
    flush()
    log.info("discover done: %d/%d with domain in %.0fs; engines=%s", found, len(companies),
             time.time() - t0, searcher.stats())
    return out_rows


# ---------------------------------------------------------------- fetch
ATS_PATTERNS = [
    ("greenhouse", re.compile(r"(?:boards|job-boards|boards-api)\.greenhouse\.io/(?:v1/boards/)?(?:embed/job_board\?for=)?([A-Za-z0-9_-]+)", re.I)),
    ("greenhouse", re.compile(r"greenhouse\.io/embed/job_board(?:/js)?\?for=([A-Za-z0-9_-]+)", re.I)),
    ("lever", re.compile(r"jobs\.lever\.co/([A-Za-z0-9_-]+)", re.I)),
    ("ashby", re.compile(r"jobs\.ashbyhq\.com/([A-Za-z0-9_.-]+)", re.I)),
    ("workable", re.compile(r"apply\.workable\.com/(?!api/|j/|jobs/)([A-Za-z0-9_-]+)", re.I)),
    ("workable", re.compile(r"https?://(?!www\.|apply\.|help\.|resources\.|jobs\.)([A-Za-z0-9-]+)\.workable\.com", re.I)),
    ("teamtailor", re.compile(r"https?://(?!www\.|app\.|api\.)([A-Za-z0-9-]+)\.teamtailor\.com", re.I)),
    ("bamboohr", re.compile(r"https?://(?!www\.|app\.)([A-Za-z0-9-]+)\.bamboohr\.com", re.I)),
    ("personio", re.compile(r"https?://([A-Za-z0-9-]+)\.jobs\.personio\.(?:de|com)", re.I)),
    ("recruitee", re.compile(r"https?://(?!www\.|app\.)([A-Za-z0-9-]+)\.recruitee\.com", re.I)),
    ("pinpoint", re.compile(r"https?://(?!www\.|app\.)([A-Za-z0-9-]+)\.pinpointhq\.com", re.I)),
    ("hibob", re.compile(r"app\.hibob\.com/jobs/([A-Za-z0-9_-]+)", re.I)),
    ("workday", re.compile(r"https?://([A-Za-z0-9-]+)\.wd\d+\.myworkdayjobs\.com", re.I)),
    ("smartrecruiters", re.compile(r"(?:jobs|careers)\.smartrecruiters\.com/([A-Za-z0-9_-]+)", re.I)),
]
ATS_HOST_HINTS = {"greenhouse.io": "greenhouse", "lever.co": "lever", "ashbyhq.com": "ashby",
                  "workable.com": "workable", "teamtailor.com": "teamtailor", "teamtailor-cdn.com": "teamtailor",
                  "teamtailor-jobs-widget": "teamtailor", "bamboohr.com": "bamboohr",
                  "personio.de": "personio", "personio.com": "personio", "recruitee.com": "recruitee",
                  "pinpointhq.com": "pinpoint", "hibob.com": "hibob", "myworkdayjobs.com": "workday",
                  "smartrecruiters.com": "smartrecruiters", "breezy.hr": "breezy", "jazz.co": "jazzhr",
                  "applytojob.com": "jazzhr", "homerun.co": "homerun", "jobvite.com": "jobvite",
                  "icims.com": "icims", "successfactors.com": "successfactors", "occupop.com": "occupop",
                  "jobs.personio": "personio", "welcometothejungle.com": "wttj"}
GITHUB_RE = re.compile(r"https?://(?:www\.)?github\.com/([A-Za-z0-9_.-]+)/?(?:[\"'\s#?]|$)", re.I)
GITHUB_SKIP = {"features", "topics", "login", "join", "about", "pricing", "marketplace", "explore", "sponsors",
               "enterprise", "settings", "orgs", "search", "apps", "collections", "events", "site", "security",
               "readme", "customer-stories", "team", "github", "contact", "trending"}
PRICING_RE = re.compile(r"(?:[£$€]\s?\d[\d,.]*\s*(?:/|per)\s*(?:user|seat|month|mo|year|annum|licen[cs]e|bed|resident|site|location|employee))"
                        r"|(?:per\s+(?:user|seat)\s*(?:/|per)\s*month)|(?:pricing\s+plans?)|(?:free\s+trial)", re.I)
CUSTOMER_RE = re.compile(r"trusted by|our customers|customers|case stud(?:y|ies)", re.I)


def detect_ats(html_blobs: list[str]) -> tuple[str | None, str | None]:
    """Return (ats, token) from raw HTML/links. Tokenised ATSs first, then name-only hints."""
    joined = "\n".join(html_blobs)
    for ats, rx in ATS_PATTERNS:
        m = rx.search(joined)
        if m:
            tok = m.group(1)
            if tok.lower() in ("embed", "v1", "boards", "js"):
                continue
            return ats, tok
    low = joined.lower()
    for host, ats in ATS_HOST_HINTS.items():
        if host in low:
            return ats, None
    return None, None


def detect_github_org(links: list[str]) -> str | None:
    for href in links:
        m = GITHUB_RE.search(href + " ")
        if m and m.group(1).lower() not in GITHUB_SKIP:
            return m.group(1)
    return None


def detect_api_docs(links: list[str], domain: str) -> str | None:
    for href in links:
        p = urlparse(href)
        host = (p.hostname or "").lower()
        if not host:
            continue
        same = registered_domain(host) == domain
        if host.startswith(("docs.", "developer.", "developers.", "api.")) and same:
            return href
        if same and re.match(r"^/(api|docs|developers?|developer-portal|documentation)(/|$)", p.path or ""):
            return href
    for href in links:
        host = (urlparse(href).hostname or "").lower()
        if host.endswith((".readme.io", ".redoc.ly", ".stoplight.io", ".gitbook.io")):
            return href
    return None


def detect_careers(links: list[tuple[str, str]], domain: str) -> str | None:
    """links: (href, anchor_text). Prefer same-domain links; fall back to any ATS link."""
    best = None
    for href, text in links:
        blob = (href.lower() + " " + (text or "").lower())
        if any(t in blob for t in CAREER_TOKENS):
            host = (urlparse(href).hostname or "").lower()
            if registered_domain(host) == domain:
                return href
            if best is None and any(h in host for h in ATS_HOST_HINTS):
                best = href
    return best


def count_integrations(text: str) -> int:
    hits = 0
    for nm in INTEGRATION_NAMES:
        if re.search(r"\b" + re.escape(nm) + r"\b", text):
            hits += 1
    return hits


def pricing_hint(pages: list[dict]) -> bool:
    for p in pages:
        blob = (p.get("url", "") + " " + p.get("title", "")).lower()
        if "pricing" in blob or "plans" in blob:
            if PRICING_RE.search(p.get("text", "")) or re.search(r"[£$€]\s?\d", p.get("text", "")):
                return True
        if PRICING_RE.search(p.get("text", "")):
            return True
    return False


def extract_text(html: str, url: str) -> tuple[str, str]:
    """(title, main text) via trafilatura with a bs4 fallback."""
    import trafilatura

    soup = BeautifulSoup(html, "lxml")
    title = ""
    if soup.title and soup.title.string:
        title = soup.title.get_text(" ", strip=True)
    else:
        og = soup.find("meta", property="og:title")
        if og and og.get("content"):
            title = og["content"].strip()
    text = None
    try:
        text = trafilatura.extract(html, url=url, include_comments=False, include_tables=True,
                                   favor_recall=True, deduplicate=True)
    except Exception:
        text = None
    if not text or len(text) < 200:
        for tag in soup(["script", "style", "noscript", "svg", "nav", "footer", "header", "form", "iframe"]):
            tag.decompose()
        body = soup.body or soup
        text = re.sub(r"\n\s*\n+", "\n", body.get_text("\n", strip=True))
    return title[:300], text or ""


_META_CHARSET_RE = re.compile(rb"""<meta[^>]+charset=["']?\s*([A-Za-z0-9_-]+)""", re.I)


def decode_html(raw: bytes, content_type: str = "") -> str:
    """Decode HTML bytes using the header charset, else the meta charset, else UTF-8.

    requests defaults text/html without a charset to ISO-8859-1, which turns UTF-8 dashes
    into mojibake (portswigger.net), so the header is only trusted when it names a charset.
    """
    m = re.search(r"charset=([A-Za-z0-9_-]+)", content_type or "", re.I)
    enc = m.group(1) if m else None
    if not enc:
        mm = _META_CHARSET_RE.search(raw[:4096])
        enc = mm.group(1).decode("ascii", "ignore") if mm else "utf-8"
    try:
        return raw.decode(enc, "replace")
    except LookupError:
        return raw.decode("utf-8", "replace")


def page_priority(href: str, anchor: str, tokens: list[str]) -> int | None:
    blob = (urlparse(href).path or "").lower() + " " + (anchor or "").lower()
    for i, t in enumerate(tokens):
        if t in blob:
            return i
    return None


class DomainFetcher:
    """Fetches one domain politely: robots.txt, homepage, prioritised same-domain pages."""

    def __init__(self, cfg_web: dict, session: requests.Session | None = None):
        self.cfg = cfg_web
        self.ua = cfg_web["user_agent"]
        self.session = session or requests.Session()
        self.max_pages = int(cfg_web["max_pages"])
        self.max_chars = int(cfg_web["max_chars"])
        tokens = [str(t) for t in cfg_web["page_tokens"]]
        # Preferred order: product-type tokens first, then about/careers/api/developers.
        self.tokens = [t for t in PRIORITY_TOKENS if t in tokens] + [t for t in tokens if t not in PRIORITY_TOKENS]
        self.cache = DiskCache("webpages")

    def _get(self, url: str, timeout: int = FETCH_TIMEOUT) -> tuple[int, str, str]:
        """(status, final_url, html). Cached per URL. Retries once with a browser UA on 403/406/429."""
        cached = self.cache.get(url)
        if cached is not None:
            return cached["status"], cached["final_url"], cached["html"]
        headers = {"User-Agent": self.ua, "Accept-Language": "en-GB,en;q=0.9",
                   "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8"}
        status, final_url, html = 0, url, ""
        for attempt in range(2):
            try:
                r = self.session.get(url, headers=headers, timeout=timeout, allow_redirects=True, stream=True)
                ct = r.headers.get("content-type", "")
                if "html" not in ct and "xml" not in ct and ct:
                    r.close()
                    status, final_url, html = r.status_code, r.url, ""
                    break
                raw = r.raw.read(MAX_HTML_BYTES, decode_content=True)
                r.close()
                html = decode_html(raw, ct)
                status, final_url = r.status_code, r.url
            except requests.RequestException as e:
                status, final_url, html = -1, url, f"__error__ {e.__class__.__name__}: {str(e)[:200]}"
                break
            if status in (403, 406, 429) and attempt == 0:
                headers["User-Agent"] = DESKTOP_UA
                time.sleep(PER_DOMAIN_DELAY)
                continue
            break
        if status not in (-1,):
            self.cache.put({"status": status, "final_url": final_url, "html": html, "fetched_at": now_iso()}, url)
        return status, final_url, html

    def robots_allows(self, homepage: str) -> bool:
        parts = urlsplit(homepage)
        robots_url = urlunsplit((parts.scheme, parts.netloc, "/robots.txt", "", ""))
        try:
            r = self.session.get(robots_url, headers={"User-Agent": self.ua}, timeout=PROBE_TIMEOUT)
        except requests.RequestException:
            return True
        if r.status_code != 200 or "html" in r.headers.get("content-type", ""):
            return True
        rp = urllib.robotparser.RobotFileParser()
        rp.parse(r.text.splitlines())
        agent = self.ua.split("/")[0]
        return rp.can_fetch(agent, homepage)

    def fetch_domain(self, company_number: str, homepage: str, domain: str, name: str | None = None) -> dict:
        out = {"company_number": company_number, "pages_fetched": 0, "text_chars": 0, "text_hash": None,
               "careers_url": None, "ats": None, "ats_token": None, "github_org": None, "api_docs_url": None,
               "integrations_count": 0, "customer_logos_hint": 0, "pricing_hint": False, "robots_blocked": False,
               "fetch_error": None, "fetched_at": now_iso(), "name_match": None, "uk_signal": None}
        if not self.robots_allows(homepage):
            out["robots_blocked"] = True
            return out, {"domain": domain, "pages": [], "fetched_at": out["fetched_at"]}
        status, final_url, html = self._get(homepage)
        if status != 200 or not html or html.startswith("__error__"):
            out["fetch_error"] = html[:200] if html.startswith("__error__") else f"HTTP {status}"
            return out, {"domain": domain, "pages": [], "fetched_at": out["fetched_at"]}
        final_domain = registered_domain(final_url) or domain
        pages: list[dict] = []
        htmls: list[str] = [html]
        all_links: list[tuple[str, str]] = []

        def collect_links(page_html: str, base: str):
            soup = BeautifulSoup(page_html, "lxml")
            for a in soup.find_all("a", href=True):
                href = urljoin(base, a["href"].strip())
                if href.startswith("http"):
                    all_links.append((href.split("#")[0], a.get_text(" ", strip=True)[:80]))
            for tag in soup.find_all(["script", "iframe"], src=True):
                all_links.append((urljoin(base, tag["src"]), ""))

        title, text = extract_text(html, final_url)
        pages.append({"url": final_url, "title": title, "text": text})
        collect_links(html, final_url)
        out["uk_signal"] = uk_signal(html) or final_domain.endswith(".uk")
        if name:
            # Does the site actually belong to this company? Distinctive name tokens must appear
            # in the homepage title, the first part of its text, or the domain itself.
            toks = [t for t in name_tokens(name) if len(t) >= 3]
            hay = (title or "").upper() + " " + text[:4000].upper() + " " + final_domain.upper().replace("-", "")
            out["name_match"] = bool(toks) and (all(t in hay for t in toks[:2]) if len(toks) >= 2 else toks[0] in hay)

        # choose same-domain pages by token priority
        seen = {final_url.rstrip("/"), homepage.rstrip("/")}
        scored: list[tuple[int, str]] = []
        for href, anchor in all_links:
            host = (urlparse(href).hostname or "").lower()
            if registered_domain(host) != final_domain:
                continue
            key = href.rstrip("/")
            if key in seen or any(key.lower().endswith(ext) for ext in (".pdf", ".jpg", ".png", ".zip", ".xml")):
                continue
            pr = page_priority(href, anchor, self.tokens)
            if pr is None:
                continue
            seen.add(key)
            scored.append((pr, href))
        scored.sort(key=lambda x: x[0])
        budget = self.max_pages - 1
        for _, href in scored[:budget]:
            if not self.cache.has(href):
                time.sleep(PER_DOMAIN_DELAY)
            st, fu, h = self._get(href)
            if st != 200 or not h or h.startswith("__error__"):
                continue
            t, tx = extract_text(h, fu)
            pages.append({"url": fu, "title": t, "text": tx})
            htmls.append(h)
            collect_links(h, fu)

        careers = detect_careers(all_links, final_domain)
        ats, tok = detect_ats(htmls + [h for h, _ in all_links])
        # Scan the careers page for an ATS when none seen yet and it was not fetched already.
        if careers and ats is None and careers.rstrip("/") not in {p["url"].rstrip("/") for p in pages}:
            host = (urlparse(careers).hostname or "").lower()
            if registered_domain(host) == final_domain:
                if not self.cache.has(careers):
                    time.sleep(PER_DOMAIN_DELAY)
                st, fu, h = self._get(careers)
                if st == 200 and h and not h.startswith("__error__"):
                    collect_links(h, fu)
                    htmls.append(h)
                    ats, tok = detect_ats(htmls + [hh for hh, _ in all_links])
                    if len(pages) < self.max_pages:
                        t, tx = extract_text(h, fu)
                        pages.append({"url": fu, "title": t, "text": tx})
        if ats is None:
            ats, tok = detect_ats([h for h, _ in all_links])

        # cap text: homepage first, then pages in priority order. A long homepage keeps at
        # most half the budget when product pages exist so they are not squeezed out.
        total = 0
        kept = []
        for idx, p in enumerate(pages):
            room = self.max_chars - total
            if idx == 0 and len(pages) > 1:
                room = min(room, self.max_chars // 2)
            if room <= 0:
                break
            txt = p["text"][:room]
            kept.append({**p, "text": txt})
            total += len(txt)
        all_text = "\n\n".join(p["text"] for p in kept)
        out.update(
            pages_fetched=len(pages), text_chars=total,
            text_hash=hashlib.sha1(all_text.encode("utf-8", "replace")).hexdigest() if all_text else None,
            careers_url=careers, ats=ats, ats_token=tok,
            github_org=detect_github_org([h for h, _ in all_links]),
            api_docs_url=detect_api_docs([h for h, _ in all_links], final_domain),
            integrations_count=count_integrations("\n".join(p["text"] for p in pages)),
            customer_logos_hint=len(CUSTOMER_RE.findall("\n".join(p["title"] + " " + p["text"] for p in pages))),
            pricing_hint=pricing_hint(pages),
        )
        return out, {"domain": final_domain, "homepage_url": final_url, "pages": kept, "fetched_at": out["fetched_at"]}


def fetch(rows: list[dict] | None = None, numbers: list[str] | None = None, concurrency: int | None = None,
          redo: bool = False, write: bool = True) -> list[dict]:
    """Fetch every websites.parquet row with a domain (or the given rows) and write text + summary."""
    web_cfg = cfg()["websites"]
    concurrency = concurrency or int(web_cfg["concurrency"])
    existing = load_existing()
    if rows is None:
        rows = [r for r in existing.values() if r.get("domain")]
        if numbers:
            wanted = {normalise_company_number(n) for n in numbers}
            rows = [r for r in rows if r["company_number"] in wanted]
    if not redo:
        rows = [r for r in rows if not r.get("fetched_at") or r.get("fetch_error")]
    web_dir = path("cache") / "web"
    web_dir.mkdir(parents=True, exist_ok=True)
    fetcher = DomainFetcher(web_cfg)
    results: list[dict] = []
    lock = threading.Lock()
    t0 = time.time()
    names: dict[str, str] = {}
    try:
        from src.common import parquet_exists, read_parquet

        if parquet_exists("universe"):
            u = read_parquet("universe").select(["company_number", "name"])
            names = dict(zip(u["company_number"].to_list(), u["name"].to_list()))
    except Exception:
        names = {}
    log.info("fetching %d domains with concurrency %d", len(rows), concurrency)

    def work(r: dict) -> dict:
        n = r["company_number"]
        homepage = r.get("homepage_url") or f"https://{r['domain']}/"
        try:
            summary, blob = fetcher.fetch_domain(n, homepage, r["domain"], name=names.get(n) or r.get("name"))
        except Exception as e:  # keep the pool alive
            log.exception("fetch failed for %s %s", n, r["domain"])
            summary = {"company_number": n, "pages_fetched": 0, "text_chars": 0, "fetch_error": f"{e.__class__.__name__}: {str(e)[:150]}",
                       "fetched_at": now_iso(), "robots_blocked": False, "pricing_hint": False,
                       "integrations_count": 0, "customer_logos_hint": 0}
            blob = None
        if blob is not None:
            (web_dir / f"{n}.json").write_text(json.dumps(blob, ensure_ascii=False))
        with lock:
            results.append(summary)
            log.info("%s %-30s pages=%s chars=%s ats=%s careers=%s err=%s", n, r["domain"][:30],
                     summary.get("pages_fetched"), summary.get("text_chars"), summary.get("ats"),
                     bool(summary.get("careers_url")), summary.get("fetch_error"))
        return summary

    def flush():
        if not write:
            return
        merged = dict(existing)
        for s in results:
            merged[s["company_number"]] = {**merged.get(s["company_number"], {}), **s}
        write_parquet(websites_frame(list(merged.values())), WEBSITES_TABLE)

    with cf.ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = [pool.submit(work, r) for r in rows]
        for i, f in enumerate(cf.as_completed(futures), 1):
            f.result()
            if i % 100 == 0:
                flush()
                log.info("checkpoint: %d/%d domains, %.0fs", i, len(rows), time.time() - t0)
    flush()
    log.info("fetch done: %d domains in %.0fs", len(results), time.time() - t0)
    return results


# ---------------------------------------------------------------- CLI
def universe_companies(limit: int | None = None) -> list[dict]:
    p = parquet_path("universe")
    if not p.exists():
        log.error("data/parquet/universe.parquet not found; pass --companies")
        return []
    df = read_parquet("universe")
    cols = [c for c in ("company_number", "name", "post_town") if c in df.columns]
    rows = df.select(cols).to_dicts()
    for r in rows:
        r.setdefault("post_town", None)
    return rows[:limit] if limit else rows


def parse_companies_arg(s: str) -> list[dict]:
    out = []
    for item in s.split(","):
        parts = [p.strip() for p in item.split("|")]
        if len(parts) < 2:
            continue
        out.append({"company_number": normalise_company_number(parts[0]), "name": parts[1],
                    "post_town": parts[2] if len(parts) > 2 and parts[2] else None})
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("discover")
    d.add_argument("--from-universe", action="store_true")
    d.add_argument("--companies", help='"number|name|town,number|name|town"')
    d.add_argument("--engines", default=",".join(ENGINES))
    d.add_argument("--no-probe", action="store_true")
    d.add_argument("--redo", action="store_true", help="re-discover companies already in websites.parquet")
    d.add_argument("--limit", type=int)
    d.add_argument("--reverse", action="store_true", help="process companies in reverse order (second worker)")
    d.add_argument("--skip-file", help="parquet whose company_numbers with a method are skipped (the other worker's output)")
    f = sub.add_parser("fetch")
    f.add_argument("--numbers", help="comma-separated company numbers (default: every row with a domain)")
    f.add_argument("--concurrency", type=int)
    f.add_argument("--redo", action="store_true")
    args = ap.parse_args(argv)

    if args.cmd == "discover":
        companies: list[dict] = []
        if args.from_universe:
            companies = universe_companies(args.limit)
        if args.companies:
            companies += parse_companies_arg(args.companies)
        if not companies:
            log.info("nothing to discover")
            return 0
        if args.skip_file:
            import polars as pl

            done = {r["company_number"] for r in pl.read_parquet(args.skip_file).to_dicts() if r.get("discovery_method") not in (None, "none")}
            companies = [c for c in companies if normalise_company_number(c["company_number"]) not in done]
        if args.reverse:
            companies = list(reversed(companies))
        discover(companies, engines=[e for e in args.engines.split(",") if e], probe=not args.no_probe,
                 redo=args.redo)
        return 0
    if args.cmd == "fetch":
        nums = [x for x in args.numbers.split(",")] if args.numbers else None
        if not parquet_path(WEBSITES_TABLE).exists():
            log.info("no websites.parquet yet; run discover first")
            return 0
        fetch(numbers=nums, concurrency=args.concurrency, redo=args.redo)
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
