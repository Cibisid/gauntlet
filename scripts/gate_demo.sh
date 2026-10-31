#!/usr/bin/env bash
# Run the full gate locally without Docker:
#   starts the mock model server, runs the baseline and one candidate release,
#   prints the gate report and exits non-zero if the candidate fails.
#
# Usage: scripts/gate_demo.sh [candidate-release.yaml]   (default: releases/trialbridge/candidate.yaml)
set -euo pipefail

CANDIDATE="${1:-releases/trialbridge/candidate.yaml}"
BASELINE="releases/trialbridge/baseline.yaml"
CASES="cases/trialbridge/synthetic_v1.jsonl"
PORT="${MOCK_PORT:-8089}"
OUT="${OUT_DIR:-out}"
mkdir -p "$OUT"

gauntlet mock-server --port "$PORT" >"$OUT/mock.log" 2>&1 &
MOCK_PID=$!
trap 'kill $MOCK_PID 2>/dev/null || true' EXIT

for _ in $(seq 1 50); do
  if curl -fsS "http://127.0.0.1:$PORT/healthz" >/dev/null 2>&1; then break; fi
  sleep 0.1
done

URL="http://127.0.0.1:$PORT/v1"
gauntlet run --release "$BASELINE" --cases "$CASES" --base-url "$URL" --out "$OUT/baseline.jsonl"
gauntlet run --release "$CANDIDATE" --cases "$CASES" --base-url "$URL" --out "$OUT/candidate.jsonl"
gauntlet gate --baseline "$OUT/baseline.jsonl" --candidate "$OUT/candidate.jsonl" \
  --release "$CANDIDATE" --report "$OUT/gate-report.md"
