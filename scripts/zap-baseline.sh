#!/usr/bin/env bash
# OWASP ZAP baseline scan via Docker. Usage:
#   TARGET=https://staging.example.com bash scripts/zap-baseline.sh
#   # Local API from container (Linux Docker):
#   TARGET=http://172.17.0.1:19001 bash scripts/zap-baseline.sh
#   # Docker Desktop / Mac:
#   TARGET=http://host.docker.internal:19001 bash scripts/zap-baseline.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TARGET="${TARGET:-}"
if [[ -z "$TARGET" ]]; then
  echo "Usage: TARGET=https://staging.example.com bash scripts/zap-baseline.sh" >&2
  echo "   or: TARGET=http://host.docker.internal:19001 bash scripts/zap-baseline.sh" >&2
  exit 2
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "docker not found — install/start Docker first" >&2
  exit 2
fi

OUT="${ROOT}/reports"
mkdir -p "$OUT"
STAMP="$(date +%Y%m%d-%H%M%S)"
REPORT="zap-baseline-${STAMP}.html"

echo "ZAP baseline -> $TARGET"
echo "Report: reports/${REPORT}"

IMAGE="ghcr.io/zaproxy/zaproxy:stable"
if ! docker pull "$IMAGE"; then
  IMAGE="zaproxy/zap-stable"
  docker pull "$IMAGE"
fi

docker run --rm \
  -v "${OUT}:/zap/wrk/:rw" \
  -t "$IMAGE" \
  zap-baseline.py -t "$TARGET" -r "$REPORT" -I

echo "Done. Archive reports/${REPORT} with commit hash and triage notes."
echo "See docs/security-ops.md §7e"
