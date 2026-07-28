#!/usr/bin/env bash
set -euo pipefail
echo "=== services ==="
systemctl is-active welfare-api nginx mysql || true
echo "=== ports ==="
ss -lntp | grep -E ':80 |:19001 |:3306 ' || true
echo "=== env (redacted) ==="
if [[ -f /opt/welfare/backend/.env ]]; then
  sed -E 's/(SECRET_KEY|FIELD_ENCRYPTION_KEY|PASSWORD|DATABASE_URL)=.*/\1=***/' /opt/welfare/backend/.env
fi
echo "=== api local ==="
curl -sS -m 5 http://127.0.0.1:19001/api/health || true
echo
echo "=== recent api log ==="
journalctl -u welfare-api -n 20 --no-pager || true
