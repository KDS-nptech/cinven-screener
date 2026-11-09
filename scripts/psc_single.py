"""Flatten the single-file PSC snapshot (persons-with-significant-control-snapshot-<date>.zip).

    python scripts/psc_single.py

Streams the one newline-delimited JSON member out of the zip in chunks of
config-sized line counts, flattens each chunk with the same SQL as src.ingest.psc
into data/parquet/psc/part-NN.parquet, and deletes the chunk. Resumable: a part that
already exists is skipped (the chunk is still streamed past, which is cheap).
"""
from __future__ import annotations

import os
import pathlib
import sys
import time
import zipfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from src.common import cfg, get_logger, now_iso, path  # noqa: E402
from src.ingest.psc import FLATTEN_SQL, TRAILER_SQL, _con, _q, out_dir  # noqa: E402

log = get_logger("psc")
LINES_PER_CHUNK = 450_000


def main() -> None:
    name = cfg()["build"]["snapshot_psc_file"]
    snap = cfg()["build"]["snapshot_psc_date"]
    zip_path = path("raw") / name
    if not zip_path.exists():
        raise SystemExit(f"missing {zip_path}")
    con = _con()
    t0 = time.time()
    with zipfile.ZipFile(zip_path) as z:
        members = [m for m in z.infolist() if not m.is_dir()]
        if len(members) != 1:
            raise SystemExit(f"expected one member, found {[m.filename for m in members]}")
        m = members[0]
        log.info("streaming %s (%d bytes uncompressed)", m.filename, m.file_size)
        i = 0
        total_rows = 0
        with z.open(m) as src:
            done = False
            while not done:
                i += 1
                out = out_dir() / f"part-{i:02d}.parquet"
                chunk = path("raw") / "psc" / f"chunk-{i:02d}.txt"
                chunk.parent.mkdir(parents=True, exist_ok=True)
                n = 0
                with open(chunk, "wb") as dst:
                    for line in src:
                        dst.write(line)
                        n += 1
                        if n >= LINES_PER_CHUNK:
                            break
                    else:
                        done = True
                if n == 0:
                    chunk.unlink(missing_ok=True)
                    break
                if out.exists():
                    log.info("skip part %02d (exists)", i)
                    chunk.unlink(missing_ok=True)
                    continue
                t1 = time.time()
                for t in [r[0] for r in con.execute(TRAILER_SQL.format(src=_q(str(chunk)))).fetchall()]:
                    log.info("chunk %d trailer (not loaded): %s", i, t[:300])
                sql = FLATTEN_SQL.format(src=_q(str(chunk)), fetched=now_iso(), snap=snap)
                tmp = out.with_suffix(".parquet.tmp")
                con.execute(f"COPY ({sql}) TO '{_q(str(tmp))}' (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 200000)")
                os.replace(tmp, out)
                rows = con.execute(f"SELECT count(*) FROM read_parquet('{_q(str(out))}')").fetchone()[0]
                total_rows += rows
                chunk.unlink(missing_ok=True)
                log.info("part %02d: %s lines, %s rows -> %s in %.0fs", i, f"{n:,}", f"{rows:,}", out.name, time.time() - t1)
    log.info("psc flatten done: %d parts, %s rows, %.0fs", i, f"{total_rows:,}", time.time() - t0)
    con.close()


if __name__ == "__main__":
    main()
