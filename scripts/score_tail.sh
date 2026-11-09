#!/usr/bin/env bash
# Everything after the rubric: why-now, rankings, calibration, usefulness, coverage, QA record, export, build.
set -uo pipefail
cd "$(dirname "$0")/.."
LOG=docs/logs/score_tail.log
echo "=== score tail $(date -u +%FT%TZ) ===" >> "$LOG"
for step in "src.score.why_now" "src.score.rankings" "src.cv_pattern" "src.usefulness"; do python3 -m $step >> "$LOG" 2>&1 || echo "FAILED $step" >> "$LOG"; done
python3 scripts/coverage.py >> "$LOG" 2>&1 || echo "FAILED coverage" >> "$LOG"
python3 -m src.qa record >> "$LOG" 2>&1 || true
python3 -m src.site.export >> "$LOG" 2>&1 || echo "FAILED export" >> "$LOG"
python3 -m src.site.build >> "$LOG" 2>&1 || echo "FAILED build" >> "$LOG"
echo "=== done $(date -u +%FT%TZ) ===" >> "$LOG"
