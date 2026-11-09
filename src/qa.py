"""QA helpers: hand-check samples and overrides.

  python -m src.qa sample-labels [--n 30]    -> docs/qa/labels_sample.csv (vertical, quote, url, blank "agree" column)
  python -m src.qa sample-scores [--n 20]    -> docs/qa/scores_sample.csv (200 sub-scores with quotes)
  python -m src.qa record                    -> reads the filled samples and writes docs/qa_results.json
  python -m src.qa apply-overrides           -> applies overrides.yaml to classification / websites / universe

overrides.yaml (repo root) format:
  companies:
    "01234567":
      vertical: healthcare          # replaces the classifier label; method becomes 'override'
      exclude: true                 # founders.founder_led false, gate 'excluded by review'
      note: "hidden investor: ..."
      domain: example.com           # replaces the discovered website (refetch afterwards)
"""
from __future__ import annotations

import csv
import json
import random
import sys

import polars as pl
import yaml

from src.common import REPO, get_logger, now_iso, parquet_exists, read_parquet, write_parquet

log = get_logger("qa")
QA_DIR = REPO / "docs" / "qa"


def sample_labels(n: int):
    QA_DIR.mkdir(parents=True, exist_ok=True)
    cls = read_parquet("classification").filter(pl.col("method") == "llm")
    uni = read_parquet("universe").select(["company_number", "name"])
    df = cls.join(uni, on="company_number", how="left")
    rows = df.sample(min(n, df.height), seed=42).to_dicts()
    with open(QA_DIR / "labels_sample.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["company_number", "name", "vertical", "sub_vertical", "confidence", "evidence_quote", "evidence_url", "agree (y/n)", "correct_vertical", "note"])
        for r in rows:
            w.writerow([r["company_number"], r["name"], r["vertical"], r["sub_vertical"], r["confidence"], r["evidence_quote"], r["evidence_url"], "", "", ""])
    log.info("wrote %s (%d rows)", QA_DIR / "labels_sample.csv", len(rows))


def sample_scores(n: int):
    QA_DIR.mkdir(parents=True, exist_ok=True)
    sc = read_parquet("scores")
    companies = sc["company_number"].unique().to_list()
    random.seed(42)
    pick = random.sample(companies, min(n, len(companies)))
    uni = {r["company_number"]: r["name"] for r in read_parquet("universe").select(["company_number", "name"]).to_dicts()}
    rows = sc.filter(pl.col("company_number").is_in(pick)).sort(["company_number", "dimension"]).to_dicts()
    with open(QA_DIR / "scores_sample.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["company_number", "name", "dimension", "dimension_name", "score", "confidence", "rationale", "evidence_quote", "evidence_url", "your_score", "note"])
        for r in rows:
            w.writerow([r["company_number"], uni.get(r["company_number"]), r["dimension"], r["dimension_name"], r["score"], r["confidence"], r["rationale"], r["evidence_quote"], r["evidence_url"], "", ""])
    log.info("wrote %s (%d rows)", QA_DIR / "scores_sample.csv", len(rows))


def record():
    out = {"computed_at": now_iso()}
    f = QA_DIR / "labels_sample.csv"
    if f.exists():
        rows = list(csv.DictReader(open(f)))
        done = [r for r in rows if (r.get("agree (y/n)") or "").strip().lower() in ("y", "n")]
        out["labels_checked"] = len(done)
        out["label_agreement_pct"] = round(100 * sum(r["agree (y/n)"].strip().lower() == "y" for r in done) / len(done), 1) if done else None
    f = QA_DIR / "labels_blind_check.json"
    if f.exists() and not out.get("labels_checked"):
        b = json.loads(f.read_text())
        out["labels_checked"] = b.get("checked")
        out["label_agreement_pct"] = b.get("vertical_agreement_pct")
        out["label_software_flag_agreement_pct"] = b.get("software_flag_agreement_pct")
        out["label_check_method"] = "blind re-labelling by an independent model reviewer from the same website extracts"
    f = QA_DIR / "scores_blind_check.json"
    if f.exists() and not out.get("subscores_checked"):
        b = json.loads(f.read_text())
        out["subscores_checked"] = b.get("checked")
        out["subscore_within_one_pct"] = b.get("within_one_pct")
        out["subscore_exact_pct"] = b.get("exact_pct")
        out["subscore_within_one_chance_pct"] = b.get("within_one_chance_pct")
        out["subscore_weighted_kappa"] = b.get("weighted_kappa")
        out["company_platform_gap"] = b.get("company_platform_gap_pipeline_minus_checker")
        out["top_decile_overlap"] = b.get("top_decile_overlap")
    f = QA_DIR / "scores_sample.csv"
    if f.exists():
        rows = list(csv.DictReader(open(f)))
        done = [r for r in rows if (r.get("your_score") or "").strip().isdigit() and (r.get("score") or "").strip().isdigit()]
        out["subscores_checked"] = len(done)
        out["subscore_within_one_pct"] = round(100 * sum(abs(int(r["your_score"]) - int(r["score"])) <= 1 for r in done) / len(done), 1) if done else None
    ov = REPO / "overrides.yaml"
    if ov.exists():
        o = yaml.safe_load(ov.read_text()) or {}
        out["overrides"] = len(o.get("companies", {}))
        notes = [(v.get("note") or "").lower() for v in o.get("companies", {}).values()]
        out["wrong_site_overrides"] = sum(1 for n in notes if n.startswith("wrong website") or n.startswith("probable wrong website") or n.startswith("group site matched"))
        out["listed_or_group_overrides"] = sum(1 for n in notes if n.startswith("listed company"))
        out["top30_reviewed"] = o.get("top30_reviewed", 0)
    f = QA_DIR / "site_suspects.json"
    if f.exists():
        b = json.loads(f.read_text())
        out["site_suspects_flagged"] = b.get("n_flagged")
        out["site_suspects_of_ranked"] = b.get("n_ranked")
        rev = []
        for part in ("A", "B"):
            g = QA_DIR / f"site_suspects_review_{part}.json"
            if g.exists():
                rev += json.loads(g.read_text())
        if rev:
            out["site_suspects_reviewed"] = len(rev)
            out["site_suspects_different"] = sum(1 for r in rev if r.get("verdict") == "different")
            out["site_suspects_listed_or_group"] = sum(1 for r in rev if r.get("listed_or_group"))
    (REPO / "docs" / "qa_results.json").write_text(json.dumps(out, indent=2))
    log.info("wrote docs/qa_results.json: %s", out)


def apply_overrides():
    ov = REPO / "overrides.yaml"
    if not ov.exists():
        log.info("no overrides.yaml")
        return
    o = (yaml.safe_load(ov.read_text()) or {}).get("companies", {})
    if not o:
        return
    if parquet_exists("classification"):
        cls = read_parquet("classification")
        rows = cls.to_dicts()
        for r in rows:
            spec = o.get(r["company_number"])
            if spec and spec.get("vertical"):
                r["vertical"], r["method"], r["confidence"] = spec["vertical"], "override", "high"
                r["flags"] = list(r.get("flags") or []) + ["override"]
        write_parquet(pl.DataFrame(rows, schema=cls.schema), "classification")
    if parquet_exists("founders"):
        fo = read_parquet("founders")
        key = "company_number" if "company_number" in fo.columns else "cik"
        rows = fo.to_dicts()
        for r in rows:
            spec = o.get(r[key])
            r["excluded"] = bool(spec and spec.get("exclude"))
            r["excluded_note"] = (spec.get("note") or "") if r["excluded"] else None
        schema = dict(fo.schema)
        schema.update({"excluded": pl.Boolean, "excluded_note": pl.Utf8})
        write_parquet(pl.DataFrame(rows, schema=schema), "founders")
    if parquet_exists("websites"):
        web = read_parquet("websites")
        rows = web.to_dicts()
        for r in rows:
            spec = o.get(r["company_number"])
            if spec and spec.get("domain"):
                r["domain"], r["homepage_url"], r["discovery_method"], r["fetched_at"] = spec["domain"], f"https://{spec['domain']}/", "override", None
        write_parquet(pl.DataFrame(rows, schema=web.schema), "websites")
    log.info("applied %d overrides; re-run fetch for domain overrides, then classify/rubric/rankings", len(o))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    n = int(sys.argv[sys.argv.index("--n") + 1]) if "--n" in sys.argv else (30 if cmd == "sample-labels" else 20)
    {"sample-labels": lambda: sample_labels(n), "sample-scores": lambda: sample_scores(n), "record": record, "apply-overrides": apply_overrides}.get(cmd, lambda: print(__doc__))()
