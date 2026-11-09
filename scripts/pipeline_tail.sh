#!/usr/bin/env bash
# Re-run everything downstream of the ingest: accounts wide table, universe, routes, website merge, classifier,
# themes, rubric, why-now, rankings, measured pattern, export, build. Every stage is cached and resumable.
set -euo pipefail
cd "$(dirname "$0")/.."
LOG=docs/logs/pipeline_tail.log
echo "=== pipeline tail $(date -u +%FT%TZ) ===" | tee -a "$LOG"
python3 -m src.ingest.accounts --build-wide >> "$LOG" 2>&1
python3 -m src.filter.universe >> "$LOG" 2>&1
python3 -m src.filter.routes >> "$LOG" 2>&1
python3 -m src.enrich.websites merge >> "$LOG" 2>&1 || true
python3 -m src.enrich.websites fetch --concurrency 3 >> "$LOG" 2>&1 || true
python3 -m src.score.classify --workers 4 >> "$LOG" 2>&1
python3 -m src.score.themes >> "$LOG" 2>&1 || true
python3 -m src.score.rubric --workers 4 >> "$LOG" 2>&1
python3 -m src.score.why_now >> "$LOG" 2>&1
python3 -m src.score.rankings >> "$LOG" 2>&1
python3 -m src.cv_pattern >> "$LOG" 2>&1 || true
python3 -m src.site.export >> "$LOG" 2>&1
python3 -m src.site.build >> "$LOG" 2>&1 || true
echo "=== done $(date -u +%FT%TZ) ===" | tee -a "$LOG"
tail -3 docs/rankings_summary.json
