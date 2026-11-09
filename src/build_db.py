"""Build data/screener.duckdb from every parquet table in data/parquet.

This is the only writer of the DuckDB file. Run after any stage finishes:
    python -m src.build_db            # load every table
    python -m src.build_db universe   # reload one table

Big tables (a directory of parts) are loaded as tables too, so the Streamlit
app reads one self-contained file. Each run records the table list and row
counts in docs/db_manifest.json.
"""
from __future__ import annotations

import json
import pathlib
import sys
import time

import duckdb

from src.common import REPO, get_logger, now_iso, path

log = get_logger("build_db")


def load(con: duckdb.DuckDBPyConnection, name: str, src: str) -> int:
    con.execute(f'CREATE OR REPLACE TABLE "{name}" AS SELECT * FROM read_parquet(\'{src}\', union_by_name=true)')
    return con.execute(f'SELECT count(*) FROM "{name}"').fetchone()[0]


DEMO_FILTERED = {"companies", "psc", "accounts_wide", "accounts_meta", "accounts_facts", "size_age"}


def _demo_numbers(con: duckdb.DuckDBPyConnection, pq) -> None:
    """Company numbers the demo needs: the universe, every company on a walk-up path, back-tests."""
    con.execute(f"CREATE OR REPLACE TABLE demo_numbers AS SELECT DISTINCT company_number FROM read_parquet('{pq / 'universe.parquet'}')")
    con.execute(f"""INSERT INTO demo_numbers
        SELECT DISTINCT trim(x) FROM (SELECT unnest(string_split(replace(walkup_path, ';', ' -> '), ' -> ')) AS x
                                      FROM read_parquet('{pq / 'universe.parquet'}') WHERE walkup_path IS NOT NULL)
        WHERE trim(x) <> '' AND trim(x) NOT IN (SELECT company_number FROM demo_numbers)""")
    con.execute(f"INSERT INTO demo_numbers SELECT DISTINCT company_number FROM read_parquet('{pq / 'psc' / '*.parquet'}') p "
                "WHERE p.corporate_reg_number IN (SELECT company_number FROM demo_numbers) AND p.company_number NOT IN (SELECT company_number FROM demo_numbers)")


def build_demo(target: pathlib.Path) -> None:
    """A small self-contained DB for the demo laptop: big tables filtered to the companies the app can show."""
    pq = path("parquet")
    if target.exists():
        target.unlink()
    con = duckdb.connect(str(target))
    _demo_numbers(con, pq)
    n = con.execute("SELECT count(*) FROM demo_numbers").fetchone()[0]
    log.info("demo: %d company numbers", n)
    for entry in sorted(pq.iterdir()):
        name = entry.name.replace(".parquet", "")
        if name.startswith("_"):
            continue
        src = str(entry / "*.parquet") if entry.is_dir() else (str(entry) if entry.suffix == ".parquet" else None)
        if not src or (entry.is_dir() and not list(entry.glob("*.parquet"))):
            continue
        if name == "accounts_facts":
            continue  # not used by the app
        where = " WHERE company_number IN (SELECT company_number FROM demo_numbers)" if name in DEMO_FILTERED else ""
        con.execute(f'CREATE OR REPLACE TABLE "{name}" AS SELECT * FROM read_parquet(\'{src}\', union_by_name=true){where}')
        rows = con.execute(f'SELECT count(*) FROM "{name}"').fetchone()[0]
        log.info("demo %s: %s rows", name, f"{rows:,}")
    con.execute("DROP TABLE demo_numbers")
    con.close()
    log.info("wrote %s (%.0f MB)", target, target.stat().st_size / 1e6)


def main(only: list[str] | None = None) -> None:
    if only and only[0] == "--demo":
        build_demo(pathlib.Path(only[1]) if len(only) > 1 else path("duckdb").with_name("screener_demo.duckdb"))
        return
    pq = path("parquet")
    db = path("duckdb")
    tmp = db.with_suffix(".duckdb.building")
    # Build into a fresh file when loading everything so a half-written DB never ships.
    full = not only
    target = tmp if full else db
    if full and tmp.exists():
        tmp.unlink()
    con = duckdb.connect(str(target))
    manifest = {"built_at": now_iso(), "tables": {}}
    if not full:
        try:
            manifest = json.loads((REPO / "docs" / "db_manifest.json").read_text())
        except Exception:
            pass
    for entry in sorted(pq.iterdir()):
        name = entry.name.replace(".parquet", "")
        if only and name not in only:
            continue
        if entry.is_dir():
            parts = list(entry.glob("*.parquet"))
            if not parts:
                continue
            src = str(entry / "*.parquet")
        elif entry.suffix == ".parquet":
            src = str(entry)
        else:
            continue
        t0 = time.time()
        n = load(con, name, src)
        manifest["tables"][name] = {"rows": n, "source": src, "loaded_at": now_iso()}
        log.info("%s: %s rows in %.1fs", name, f"{n:,}", time.time() - t0)
    con.close()
    if full:
        tmp.replace(db)
    (REPO / "docs" / "db_manifest.json").write_text(json.dumps(manifest, indent=2))
    log.info("wrote %s", db)


if __name__ == "__main__":
    main(sys.argv[1:] or None)
