"""Stage 8: register checks. FCA Financial Services Register (API V0.1) for the shortlist.

Match rule: search the register by company name; accept a firm when its record carries the
same Companies House number, or when the normalised names match exactly. Anything looser
is recorded as a candidate only (fca_match_method = 'name_loose') and not treated as a match.

Env: FCA_API_EMAIL and FCA_API_KEY (config.api.fca_email_env / fca_key_env). Without them
the script logs one line and exits 0. G-Cloud and CQC columns are placeholders (cut list).

Run: python -m src.enrich.registers [--numbers a,b] [--all-shortlist]
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import time

import httpx
import polars as pl

from src.common import DiskCache, cfg, env_key, get_logger, now_iso, parquet_exists, read_parquet, write_parquet

log = get_logger("registers")
BASE = cfg()["api"]["fca_base"]
cache = DiskCache("fca")


def _norm(name: str) -> str:
    s = re.sub(r"\(POSTCODE:.*?\)", " ", (name or "").upper())
    s = re.sub(r"\b(LIMITED|LTD|PLC|LLP|L\.L\.P\.|LTD\.|THE|UK)\b", " ", s)
    s = re.sub(r"[^A-Z0-9]+", " ", s)
    return " ".join(s.split())


class FCAClient:
    def __init__(self):
        email_env = cfg()["api"]["fca_email_env"]
        self.email = os.environ.get(email_env) or _dotenv(email_env)
        self.key = env_key("fca_key_env")
        self.ok = bool(self.email and self.key)
        self.client = httpx.Client(timeout=30, headers={"X-Auth-Email": self.email or "", "X-Auth-Key": self.key or "", "Accept": "application/json"})
        self.last = 0.0

    def get(self, path: str, **params):
        hit = cache.get(path, params)
        if hit is not None:
            return hit
        gap = 1.1 - (time.monotonic() - self.last)
        if gap > 0:
            time.sleep(gap)
        for attempt in range(4):
            r = self.client.get(BASE + path, params=params)
            self.last = time.monotonic()
            if r.status_code == 429:
                time.sleep(10 * (attempt + 1))
                continue
            if r.status_code >= 500:
                time.sleep(5)
                continue
            if r.status_code == 404:
                cache.put({"Data": [], "Status": "404"}, path, params)
                return {"Data": [], "Status": "404"}
            r.raise_for_status()
            j = r.json()
            cache.put(j, path, params)
            return j
        return {"Data": [], "Status": "error"}

    def search_firm(self, name: str) -> list[dict]:
        j = self.get("/Search", q=name, type="firm")
        return j.get("Data") or []

    def firm(self, frn: str) -> dict | None:
        j = self.get(f"/Firm/{frn}")
        d = j.get("Data") or []
        return d[0] if d else None

    def permissions(self, frn: str) -> int | None:
        j = self.get(f"/Firm/{frn}/Permissions")
        d = j.get("Data")
        if isinstance(d, list):
            return len(d)
        if isinstance(d, dict):
            return len(d)
        return None


def lookup(client: FCAClient, number: str, name: str) -> dict:
    row = {"company_number": number, "fca_frn": None, "fca_status": None, "fca_firm_name": None, "fca_permissions_count": None,
           "fca_match_method": None, "fca_candidates_json": None, "gcloud_supplier": None, "cqc_relevance": None, "fetched_at": now_iso()}
    short = re.sub(r"\b(LIMITED|LTD)\b\.?", "", name, flags=re.I).strip()
    cands = client.search_firm(short)
    import json

    row["fca_candidates_json"] = json.dumps([{"name": c.get("Name"), "frn": c.get("Reference Number"), "status": c.get("Status")} for c in cands[:8]])
    target = _norm(name)
    for c in cands[:8]:
        frn = str(c.get("Reference Number") or "")
        if not frn:
            continue
        rec = client.firm(frn) or {}
        ch_no = str(rec.get("Companies House Number") or "").strip().upper().zfill(8) if rec.get("Companies House Number") else ""
        if ch_no and ch_no == number:
            method = "companies_house_number"
        elif _norm(c.get("Name") or rec.get("Organisation Name") or "") == target:
            method = "name_exact"
        else:
            continue
        row.update(fca_frn=frn, fca_status=rec.get("Status") or c.get("Status"), fca_firm_name=rec.get("Organisation Name") or c.get("Name"),
                   fca_match_method=method)
        try:
            row["fca_permissions_count"] = client.permissions(frn)
        except Exception as e:  # permissions endpoint is optional
            log.warning("permissions failed for %s: %s", frn, e)
        break
    if row["fca_frn"] is None and cands:
        row["fca_match_method"] = "name_loose"
    return row


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--numbers")
    ap.add_argument("--all-shortlist", action="store_true")
    args = ap.parse_args(argv)
    client = FCAClient()
    if not client.ok:
        log.info("FCA_API_EMAIL / FCA_API_KEY not set; skipping register lookups (exit 0)")
        return
    if args.numbers:
        nums = args.numbers.split(",")
        src = read_parquet("companies").select(["company_number", "name"]).filter(pl.col("company_number").is_in(nums))
    else:
        cls = read_parquet("classification").filter(pl.col("vertical").is_in(cfg()["target"]["verticals"]))
        src = read_parquet("universe").select(["company_number", "name"]).join(cls.select("company_number"), on="company_number")
    existing = read_parquet("registers") if parquet_exists("registers") else None
    rows = existing.to_dicts() if existing is not None else []
    done = {r["company_number"] for r in rows}
    todo = [r for r in src.to_dicts() if r["company_number"] not in done]
    log.info("%d companies to look up (%d done)", len(todo), len(done))
    for i, r in enumerate(todo):
        try:
            rows.append(lookup(client, r["company_number"], r["name"]))
        except Exception as e:
            log.error("%s %s: %s", r["company_number"], r["name"], e)
        if (i + 1) % 25 == 0:
            write_parquet(pl.DataFrame(rows), "registers")
            log.info("%d/%d", i + 1, len(todo))
    if rows:
        write_parquet(pl.DataFrame(rows), "registers")
    df = pl.DataFrame(rows) if rows else None
    if df is not None:
        log.info("done: %d rows, %d matched", df.height, df.filter(pl.col("fca_frn").is_not_null()).height)


def _dotenv(name: str):
    from src.common import REPO

    f = REPO / ".env"
    if f.exists():
        for line in f.read_text().splitlines():
            if line.strip().startswith(name + "="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


if __name__ == "__main__":
    main(sys.argv[1:])
