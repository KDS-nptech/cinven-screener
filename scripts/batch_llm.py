"""Batch mode plumbing for the two LLM stages when no API key is present.

src/score/llm.py writes each unanswered prompt to data/cache/llm_batch/pending/<key>.json and
reads answers back from data/cache/llm_batch/responses/<key>.json. This script packs pending
prompts into JSONL files a subagent can answer in one sitting, and unpacks the answers.

    python scripts/batch_llm.py pack --prompt classify-gc-v1 --size 25     # -> data/cache/llm_batch/packs/classify-gc-v1_###.jsonl
    python scripts/batch_llm.py unpack                                     # answers/*.jsonl -> responses/<key>.json
    python scripts/batch_llm.py status

Pack format: first line {"system": ...}; then one line per prompt {"key": ..., "user": ...}.
Answer format (written by the agent to data/cache/llm_batch/answers/<pack>.jsonl): one line per
prompt {"key": ..., "data": {...}}. Unpack validates that data is an object and writes it to
responses/<key>.json, where the pipeline picks it up on the next run of the stage.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
B = ROOT / "data" / "cache" / "llm_batch"
PENDING, RESPONSES, PACKS, ANSWERS = B / "pending", B / "responses", B / "packs", B / "answers"
CACHE = B.parent / "llm"


def pack(prompt: str, size: int, limit: int | None):
    PACKS.mkdir(parents=True, exist_ok=True)
    items = []
    for f in sorted(PENDING.glob("*.json")):
        try:
            d = json.loads(f.read_text())
        except json.JSONDecodeError:
            continue
        if d.get("prompt_version") != prompt or (RESPONSES / f"{d['key']}.json").exists():
            continue
        if (CACHE / d["key"][:2] / f"{d['key']}.json").exists():
            continue  # answered live (Gemini) after the request was queued
        items.append(d)
    if limit:
        items = items[:limit]
    existing = {l.strip() for p in PACKS.glob(f"{prompt}_*.jsonl") for i, l in enumerate(p.read_text().splitlines()) if i and l.strip()}
    packed_keys = {json.loads(l)["key"] for l in existing}
    items = [d for d in items if d["key"] not in packed_keys]
    n0 = len(list(PACKS.glob(f"{prompt}_*.jsonl")))
    k = 0
    for i in range(0, len(items), size):
        chunk = items[i:i + size]
        p = PACKS / f"{prompt}_{n0 + k:03d}.jsonl"
        with open(p, "w") as fh:
            fh.write(json.dumps({"system": chunk[0]["system"], "prompt_version": prompt, "n": len(chunk)}) + "\n")
            for d in chunk:
                fh.write(json.dumps({"key": d["key"], "user": d["user"]}) + "\n")
        k += 1
    print(f"packed {len(items)} prompts into {k} packs for {prompt} (pending {len(list(PENDING.glob('*.json')))})")


def unpack():
    RESPONSES.mkdir(parents=True, exist_ok=True)
    ok = bad = 0
    for a in sorted(ANSWERS.glob("*.jsonl")):
        for line in a.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                bad += 1
                continue
            key, data = d.get("key"), d.get("data")
            if not key or not isinstance(data, dict):
                bad += 1
                continue
            (RESPONSES / f"{key}.json").write_text(json.dumps({"data": data}))
            # Also seed the main LLM cache so a provider-pool run picks the answer up without a call.
            cf = ROOT / "data" / "cache" / "llm" / key[:2] / f"{key}.json"
            cf.parent.mkdir(parents=True, exist_ok=True)
            if not cf.exists():
                cf.write_text(json.dumps({"data": data, "raw": json.dumps(data), "model": "batch", "provider": "batch", "fetched_at": __import__("datetime").datetime.utcnow().isoformat()}))
            ok += 1
    print(f"unpacked {ok} answers ({bad} bad lines); responses on disk {len(list(RESPONSES.glob('*.json')))}")


def status():
    pend = [json.loads(f.read_text()) for f in PENDING.glob("*.json")]
    by = {}
    for d in pend:
        by[d.get("prompt_version")] = by.get(d.get("prompt_version"), 0) + 1
    print(f"pending {len(pend)} by prompt {by}; responses {len(list(RESPONSES.glob('*.json')))}; packs {len(list(PACKS.glob('*.jsonl')))}; answer files {len(list(ANSWERS.glob('*.jsonl')))}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["pack", "unpack", "status"])
    ap.add_argument("--prompt", default="classify-gc-v1")
    ap.add_argument("--size", type=int, default=25)
    ap.add_argument("--limit", type=int)
    a = ap.parse_args()
    {"pack": lambda: pack(a.prompt, a.size, a.limit), "unpack": unpack, "status": status}[a.cmd]()
