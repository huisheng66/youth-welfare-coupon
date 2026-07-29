#!/usr/bin/env bash
set -euo pipefail
LOG=/root/welfare-deploy.log
for i in $(seq 1 40); do
  if [[ -f "$LOG" ]] && grep -q '部署完成' "$LOG"; then
    echo DONE
    tail -50 "$LOG"
    systemctl is-active welfare-api nginx mysql || true
    curl -sS -m 5 http://127.0.0.1:19001/api/health || true
    echo
    curl -sS -o /dev/null -w "home=%{http_code}\n" -m 5 -H 'Host: 198.44.182.107' http://127.0.0.1/ || true
    exit 0
  fi
  # still running?
  if ! pgrep -f 'run-on-public|install-ubuntu' >/dev/null 2>&1; then
    if [[ -f "$LOG" ]] && ! grep -q '部署完成' "$LOG"; then
      echo FAILED_OR_IDLE
      tail -60 "$LOG"
      exit 1
    fi
  fi
  lines=$(wc -l <"$LOG" 2>/dev/null || echo 0)
  echo "wait_$i lines=$lines"
  sleep 15
done
echo TIMEOUT
tail -60 "$LOG" || true
exit 2
