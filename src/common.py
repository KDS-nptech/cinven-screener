"""Shared helpers for every stage: config, paths, parquet IO, DuckDB, disk cache, logging.

Conventions (see docs/CONVENTIONS.md):
- Stages write parquet to data/parquet/<table>.parquet (or a directory of parts).
  Only src/build_db.py writes data/screener.duckdb, so concurrent stages never
  contend for the single DuckDB writer.
- Every external call (API, website, LLM) is cached to data/cache/<namespace>/<sha1>.json.
- Every row carries fetched_at or computed_at (UTC ISO).
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
import os
import pathlib
import sys
from typing import Any, Iterable

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
CONFIG_PATH = REPO / "config.yaml"

_cfg: dict | None = None


def cfg() -> dict:
    global _cfg
    if _cfg is None:
        with open(CONFIG_PATH) as f:
            _cfg = yaml.safe_load(f)
    return _cfg


def path(key: str) -> pathlib.Path:
    """Resolve a path from config.paths relative to the repo root and create it."""
    p = REPO / cfg()["paths"][key]
    if key != "duckdb":
        p.mkdir(parents=True, exist_ok=True)
    else:
        p.parent.mkdir(parents=True, exist_ok=True)
    return p


def parquet_path(table: str) -> pathlib.Path:
    return path("parquet") / f"{table}.parquet"


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def today() -> dt.date:
    return dt.date.fromisoformat(cfg()["build"]["as_of_date"])


def get_logger(name: str) -> logging.Logger:
    log = logging.getLogger(name)
    if not log.handlers:
        h = logging.StreamHandler(sys.stdout)
        h.setFormatter(logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s"))
        log.addHandler(h)
        log.setLevel(logging.INFO)
        logs = REPO / "docs" / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(logs / f"{name}.log")
        fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        log.addHandler(fh)
    return log


# ---------------------------------------------------------------- disk cache
class DiskCache:
    """One JSON file per request, keyed on a sha1 of the request description."""

    def __init__(self, namespace: str):
        self.dir = path("cache") / namespace
        self.dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def key(*parts: Any) -> str:
        raw = json.dumps(parts, sort_keys=True, default=str)
        return hashlib.sha1(raw.encode()).hexdigest()

    def file(self, *parts: Any) -> pathlib.Path:
        k = self.key(*parts)
        return self.dir / k[:2] / f"{k}.json"

    def get(self, *parts: Any):
        f = self.file(*parts)
        if f.exists():
            try:
                return json.loads(f.read_text())
            except json.JSONDecodeError:
                f.unlink(missing_ok=True)
        return None

    def put(self, value: Any, *parts: Any) -> None:
        f = self.file(*parts)
        f.parent.mkdir(parents=True, exist_ok=True)
        tmp = f.with_suffix(".tmp")
        tmp.write_text(json.dumps(value, default=str))
        os.replace(tmp, f)

    def has(self, *parts: Any) -> bool:
        return self.file(*parts).exists()


# ---------------------------------------------------------------- duckdb
def connect(read_only: bool = True):
    """Open data/screener.duckdb. Writers should be src/build_db.py only."""
    import duckdb

    return duckdb.connect(str(path("duckdb")), read_only=read_only)


def read_parquet(table: str):
    """Read a stage output as a polars DataFrame (file or directory of parts)."""
    import polars as pl

    p = parquet_path(table)
    d = path("parquet") / table          # directory-of-parts form: data/parquet/<table>/part-*.parquet
    if d.is_dir():
        return pl.read_parquet(str(d / "*.parquet"))
    if p.is_dir():
        return pl.read_parquet(str(p / "*.parquet"))
    return pl.read_parquet(str(p))


def parquet_exists(table: str) -> bool:
    p = parquet_path(table)
    d = path("parquet") / table
    return p.exists() or (d.is_dir() and any(d.glob("*.parquet")))


def write_parquet(df, table: str) -> pathlib.Path:
    """Write a polars (or pandas) DataFrame atomically to data/parquet/<table>.parquet."""
    p = parquet_path(table)
    tmp = p.with_suffix(".parquet.tmp")
    if hasattr(df, "write_parquet"):
        df.write_parquet(str(tmp), compression="zstd")
    else:
        df.to_parquet(str(tmp), index=False)
    os.replace(tmp, p)
    return p


def env_key(name_in_config: str) -> str | None:
    """Look up an API key by its config.api.*_env name; also reads .env in the repo root."""
    env_name = cfg()["api"][name_in_config]
    if env_name in os.environ:
        return os.environ[env_name]
    dotenv = REPO / ".env"
    if dotenv.exists():
        for line in dotenv.read_text().splitlines():
            line = line.strip()
            if line.startswith(env_name + "="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def chunks(items: Iterable, n: int):
    buf = []
    for it in items:
        buf.append(it)
        if len(buf) == n:
            yield buf
            buf = []
    if buf:
        yield buf


def normalise_company_number(n: str | int | None) -> str | None:
    """Companies House numbers are 8 chars, zero-padded; some carry a prefix (SC, NI, OC)."""
    if n is None:
        return None
    s = str(n).strip().upper()
    if not s:
        return None
    if s.isdigit():
        return s.zfill(8)
    return s


def name_tokens(name: str) -> list[str]:
    """Distinctive tokens of a company name, with legal suffixes and stopwords removed."""
    import re

    stop = {"LIMITED", "LTD", "LTD.", "PLC", "LLP", "THE", "AND", "&", "CO", "COMPANY", "GROUP",
            "HOLDINGS", "UK", "SERVICES", "SOLUTIONS", "SYSTEMS", "SOFTWARE", "TECHNOLOGIES",
            "TECHNOLOGY", "INTERNATIONAL", "LTD,", "OF", "FOR"}
    toks = [t for t in re.split(r"[^A-Z0-9]+", name.upper()) if t and t not in stop]
    return toks
