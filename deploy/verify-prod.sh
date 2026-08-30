#!/usr/bin/env bash
set -euo pipefail
BASE="${1:-http://192.168.159.130}"
echo "BASE=$BASE"
echo "--- health ---"
curl -sS -m 10 "$BASE/api/health" || true
echo
echo "--- home ---"
curl -sS -o /dev/null -w "http=%{http_code} size=%{size_download}\n" -m 10 "$BASE/" || true
echo "--- docs (expect 404) ---"
curl -sS -o /dev/null -w "http=%{http_code}\n" -m 10 "$BASE/docs" || true
echo "--- openapi (expect 404) ---"
curl -sS -o /dev/null -w "http=%{http_code}\n" -m 10 "$BASE/openapi.json" || true
echo "--- login (export ADMIN_PASS to enable) ---"
if [[ -n "${ADMIN_PASS:-}" ]]; then
  curl -sS -m 10 -X POST "$BASE/api/auth/login" \
    -H 'Content-Type: application/json' \
    -d "{\"username\":\"${ADMIN_USER:-admin}\",\"password\":\"${ADMIN_PASS}\"}" || true
else
  echo "SKIP: ADMIN_PASS 未设置，跳过登录自检"
fi
echo
echo "--- security headers (home) ---"
curl -sSI -m 10 "$BASE/" | tr -d '\r' | grep -iE 'HTTP/|x-content-type|x-frame|referrer|content-security' || true
