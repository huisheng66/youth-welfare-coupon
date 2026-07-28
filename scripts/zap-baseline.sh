#!/usr/bin/env bash
# OWASP ZAP baseline scan via Docker. Usage:
#   TARGET=https://staging.example.com bash scripts/zap-baseline.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TARGET="${TARGET:-}"
if [[ -z "$TARGET" ]]; then
  echo "Usage: TARGET=https://staging.example.com bash scripts/zap-baseline.sh" >&2
  exit 2
fi

OUT="${ROOT}/reports"
mkdir -p "$OUT"
STAMP="$(date +%Y%m%d-%H%M%S)"
REPORT="zap-baseline-${STAMP}.html"

echo "ZAP baseline -> $TARGET"
echo "Report: reports/${REPORT}"
docker run --rm \
  -v "${OUT}:/zap/wrk/:rw" \
  -t ghcr.io/zaproxy/zaproxy:stable \
  zap-baseline.py -t "$TARGET" -r "$REPORT" -I

echo "Done. Archive reports/${REPORT} with commit hash and triage notes."
echo "See docs/security-ops.md §7e"
