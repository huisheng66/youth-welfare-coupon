#!/usr/bin/env bash
# Run ZAP quick/baseline-style scan from WSL standalone install.
# Usage (as root or user with java):
#   bash wsl-run-zap-baseline.sh [TARGET]
# Default TARGET tries localhost then Windows host gateway.
set -euo pipefail

ZAP="${ZAP:-/opt/zap/zap.sh}"
REPORT_DIR="${REPORT_DIR:-/mnt/d/卡系统/reports}"
mkdir -p "$REPORT_DIR"
STAMP=$(date +%Y%m%d-%H%M%S)
HTML="$REPORT_DIR/zap-baseline-$STAMP.html"
MD="$REPORT_DIR/zap-baseline-$STAMP.md"
XML="$REPORT_DIR/zap-baseline-$STAMP.xml"

pick_target() {
  if [[ -n "${1:-}" ]]; then
    echo "$1"
    return
  fi
  if [[ -n "${TARGET:-}" ]]; then
    echo "$TARGET"
    return
  fi
  for t in \
    "http://127.0.0.1:19001" \
    "http://localhost:19001" \
    "http://$(grep -m1 nameserver /etc/resolv.conf 2>/dev/null | awk '{print $2}'):19001" \
    "http://host.docker.internal:19001"
  do
    if curl -fsS --connect-timeout 2 "$t/api/health" >/dev/null 2>&1; then
      echo "$t"
      return
    fi
  done
  echo ""
}

TARGET_URL=$(pick_target "${1:-}")
if [[ -z "$TARGET_URL" ]]; then
  echo "FATAL: cannot reach API. Start uvicorn on Windows (port 19001) and ensure WSL can access it."
  echo "Tried localhost and Windows host IP from /etc/resolv.conf"
  exit 2
fi

echo "ZAP: $ZAP"
echo "Target: $TARGET_URL"
echo "Report: $HTML"

# Ensure health
curl -fsS "$TARGET_URL/api/health" | head -c 200
echo

# Quick scan (spider + active scan light) — built into ZAP CLI
# -quickurl: target
# -quickout: HTML report
# -cmd: non-interactive
set +e
"$ZAP" -cmd \
  -quickurl "$TARGET_URL" \
  -quickout "$HTML" \
  -quickprogress \
  2>&1 | tee "$REPORT_DIR/zap-console-$STAMP.log"
ZAP_EXIT=$?
set -e

# Also try XML if HTML missing (older flags)
if [[ ! -f "$HTML" ]]; then
  echo "HTML missing, try -report"
  "$ZAP" -cmd -quickurl "$TARGET_URL" -report "$HTML" 2>&1 | tee -a "$REPORT_DIR/zap-console-$STAMP.log" || true
fi

# Summary markdown
{
  echo "# ZAP scan summary"
  echo
  echo "- Time: $(date -Iseconds)"
  echo "- Target: $TARGET_URL"
  echo "- ZAP exit: $ZAP_EXIT"
  echo "- HTML: $HTML"
  echo
  if [[ -f "$HTML" ]]; then
    echo "Report size: $(stat -c%s "$HTML") bytes"
    # crude extract of alert counts if present
    grep -oE 'Risk Level[^<]{0,40}' "$HTML" 2>/dev/null | head -20 || true
    grep -iE 'High|Medium|Low|Informational' "$HTML" 2>/dev/null | head -30 || true
  else
    echo "No HTML report produced."
  fi
} > "$MD"

echo "DONE exit=$ZAP_EXIT"
echo "See $HTML and $MD"
exit $ZAP_EXIT
