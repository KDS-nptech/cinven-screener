"""Blind cross-check of classifier labels: a second model's answers (batch packs answered by a
Claude subagent) against the labels the pipeline used (Gemini pool or any provider).

    python -m src.qa_blind labels      -> docs/qa/labels_blind_check.json
    python -m src.qa_blind scores      -> docs/qa/scores_blind_check.json (rubric packs, if any)

Reads data/cache/llm_batch/answers/*.jsonl (key, data) and matches each key to the prompt in
data/cache/llm_batch/packs/*.jsonl (key, user) to recover the company name, then to
classification.parquet by name.
"""
from __future__ import annotations

import json
import re
import sys

import polars as pl

from src.common import cfg, REPO, get_logger, now_iso, path, read_parquet

log = get_logger("qa_blind")
B = path("cache") / "llm_batch"


def _pack_index(prefix):
    idx = {}
    for p in sorted(B.glob(f"packs/{prefix}*.jsonl")):
        for i, line in enumerate(p.read_text().splitlines()):
            if not i or not line.strip():
                continue
            d = json.loads(line)
            m = re.search(r"^Company: (.+)$", d["user"], re.M)
            idx[d["key"]] = m.group(1).strip() if m else None
    return idx


def labels():
    idx = _pack_index("classify")
    answers = {}
    for a in B.glob("answers/classify*.jsonl"):
        for line in a.read_text().splitlines():
            if line.strip():
                try:
                    d = json.loads(line)
                    answers[d["key"]] = d["data"]
                except (json.JSONDecodeError, KeyError):
                    pass
    cls = read_parquet("classification").filter((pl.col("method") == "llm") & (pl.col("model") != "batch"))  # only labels a second model can be independent of
    uni = read_parquet("universe").select(["company_number", "name"])
    cls = cls.join(uni, on="company_number", how="left")
    by_name = {r["name"]: r for r in cls.to_dicts()}
    rows = []
    for k, data in answers.items():
        name = idx.get(k)
        r = by_name.get(name)
        if not r or not isinstance(data, dict):
            continue
        rows.append({"company": name, "pipeline_vertical": r["vertical"], "checker_vertical": data.get("vertical"), "agree": r["vertical"] == data.get("vertical"),
                     "pipeline_product": r.get("is_software_product"), "checker_product": data.get("is_product_company"), "pipeline_model": r.get("model")})
    out = {"computed_at": now_iso(), "method": "blind re-labelling by a second model (Claude via batch pack) from the same website extracts; pipeline labels from the Gemini pool; pairs where the pipeline label itself came from the batch are excluded",
           "checked": len(rows), "vertical_agreement_pct": round(100 * sum(x["agree"] for x in rows) / len(rows), 1) if rows else None,
           "software_flag_agreement_pct": round(100 * sum((x["pipeline_product"] == x["checker_product"]) for x in rows) / len(rows), 1) if rows else None,
           "disagreements": [x for x in rows if not x["agree"]]}
    (REPO / "docs" / "qa").mkdir(parents=True, exist_ok=True)
    (REPO / "docs" / "qa" / "labels_blind_check.json").write_text(json.dumps(out, indent=1))
    log.info("checked %d, vertical agreement %s%%", out["checked"], out["vertical_agreement_pct"])


def _cache_answer(key: str):
    f = path("cache") / "llm" / key[:2] / f"{key}.json"
    if not f.exists():
        return None
    try:
        return json.loads(f.read_text())
    except json.JSONDecodeError:
        return None


def _dims(data) -> dict:
    out = {}
    for d in (data or {}).get("scores", []) if isinstance(data, dict) else []:
        try:
            out[int(d["dimension"])] = int(d["score"])
        except (KeyError, TypeError, ValueError):
            continue
    return out


def _weighted_kappa(a: list[int], b: list[int], k: int = 5) -> float | None:
    """Quadratic-weighted Cohen's kappa on 1..k scores."""
    n = len(a)
    if n < 2:
        return None
    obs = [[0.0] * k for _ in range(k)]
    for x, y in zip(a, b):
        obs[x - 1][y - 1] += 1
    pa = [sum(obs[i]) / n for i in range(k)]
    pb = [sum(obs[i][j] for i in range(k)) / n for j in range(k)]
    num = den = 0.0
    for i in range(k):
        for j in range(k):
            wgt = (i - j) ** 2 / (k - 1) ** 2
            num += wgt * obs[i][j] / n
            den += wgt * pa[i] * pb[j]
    return round(1 - num / den, 3) if den else None


def scores():
    """Pair the batch answers with the live model's answer to the SAME prompt (same cache key), so the
    comparison is two models reading identical text and facts. Reports within-one and exact agreement,
    the chance level of within-one agreement (checker scores permuted within each dimension), quadratic
    weighted kappa, the company-level platform-score gap, and the top-decile overlap."""
    import random
    idx = _pack_index("rubric")
    answers = {}
    for a in B.glob("answers/rubric*.jsonl"):
        for line in a.read_text().splitlines():
            if line.strip():
                try:
                    d = json.loads(line)
                    answers[d["key"]] = d["data"]
                except (json.JSONDecodeError, KeyError):
                    pass
    w = {int(k): float(v) for k, v in cfg()["rubric"]["weights"].items()}
    pairs, companies = [], []
    for k, data in answers.items():
        live = _cache_answer(k)
        if not live or live.get("model") in (None, "", "batch"):
            continue  # no independent answer to compare with
        p, c = _dims(live.get("data")), _dims(data)
        common = sorted(set(p) & set(c))
        if len(common) < 8:
            continue
        for d in common:
            pairs.append((idx.get(k) or k, d, p[d], c[d]))
        ps = sum(w[d] * p[d] for d in common) / sum(w[d] for d in common)
        cs = sum(w[d] * c[d] for d in common) / sum(w[d] for d in common)
        companies.append((idx.get(k) or k, (ps - 1) / 4 * 100, (cs - 1) / 4 * 100, live.get("model")))
    out = {"computed_at": now_iso(), "method": "blind re-scoring by a second model (Claude, batch packs) of the same prompt the live model answered, paired by prompt key",
           "checked": len(pairs), "companies": len(companies)}
    if pairs:
        out["within_one_pct"] = round(100 * sum(abs(p - s) <= 1 for _, _, p, s in pairs) / len(pairs), 1)
        out["exact_pct"] = round(100 * sum(p == s for _, _, p, s in pairs) / len(pairs), 1)
        out["mean_pipeline_minus_checker"] = round(sum(p - s for _, _, p, s in pairs) / len(pairs), 2)
        rng = random.Random(7)
        chance = []
        for _ in range(20):
            tot = hit = 0
            for d in range(1, 11):
                rows = [(p, s) for _, dd, p, s in pairs if dd == d]
                shuf = [s for _, s in rows]
                rng.shuffle(shuf)
                hit += sum(abs(p - s) <= 1 for (p, _), s in zip(rows, shuf))
                tot += len(rows)
            chance.append(hit / tot if tot else 0)
        out["within_one_chance_pct"] = round(100 * sum(chance) / len(chance), 1)
        out["weighted_kappa"] = _weighted_kappa([p for _, _, p, _ in pairs], [s for _, _, _, s in pairs])
        out["weighted_kappa_by_dimension"] = {d: _weighted_kappa([p for _, dd, p, _ in pairs if dd == d], [s for _, dd, _, s in pairs if dd == d]) for d in range(1, 11)}
    if companies:
        gaps = [ps - cs for _, ps, cs, _ in companies]
        out["company_platform_gap_pipeline_minus_checker"] = round(sum(gaps) / len(gaps), 1)
        out["company_platform_gap_note"] = "mean platform score (weighted mean of the ten dimensions, 0 to 100, no coverage factor) of the live model minus the batch model on the same prompts; the rubric adds it to batch-scored companies"
        n10 = max(1, len(companies) // 10)
        top_p = {x[0] for x in sorted(companies, key=lambda x: -x[1])[:n10]}
        top_c = {x[0] for x in sorted(companies, key=lambda x: -x[2])[:n10]}
        out["top_decile_overlap"] = {"n": n10, "overlap": len(top_p & top_c)}
        try:
            import numpy as np
            from scipy.stats import spearmanr  # type: ignore
            out["company_spearman"] = round(float(spearmanr([x[1] for x in companies], [x[2] for x in companies]).correlation), 3)
        except Exception:
            pass
        by_model = {}
        for _, ps, cs, m in companies:
            by_model.setdefault(m, []).append(ps - cs)
        out["company_gap_by_live_model"] = {m: round(sum(v) / len(v), 1) for m, v in by_model.items()}
    (REPO / "docs" / "qa").mkdir(parents=True, exist_ok=True)
    (REPO / "docs" / "qa" / "scores_blind_check.json").write_text(json.dumps(out, indent=1))
    log.info("%s", {k: v for k, v in out.items() if k != "weighted_kappa_by_dimension"})


if __name__ == "__main__":
    {"labels": labels, "scores": scores}.get(sys.argv[1] if len(sys.argv) > 1 else "", lambda: print(__doc__))()
