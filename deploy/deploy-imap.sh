#!/usr/bin/env bash
set -euo pipefail
APP=/opt/welfare/backend
ENV_FILE=$APP/.env

# 1) 写 IMAP 配置到 .env
cp -a "$ENV_FILE" "${ENV_FILE}.bak-imap-$(date +%Y%m%d%H%M%S)"
set_kv() {
  local key="$1" val="$2"
  if grep -q "^${key}=" "$ENV_FILE"; then
    sed -i "s|^${key}=.*|${key}=${val}|" "$ENV_FILE"
  else
    echo "${key}=${val}" >> "$ENV_FILE"
  fi
}
set_kv IMAP_SERVER imap.exmail.qq.com
set_kv IMAP_PORT 993
set_kv IMAP_SSL true

echo "==> mail+imap (password redacted)"
grep -E '^(MAIL_|IMAP_|EMAIL_)' "$ENV_FILE" | sed -E 's/^(MAIL_PASSWORD)=.*/\1=***/'

# 2) 代码已由 scp 覆盖，重启
systemctl restart welfare-api
sleep 3
systemctl is-active welfare-api
curl -sS -m 8 http://127.0.0.1:19001/api/health
echo

TOKEN=$(curl -sS -m 10 -X POST http://127.0.0.1:19001/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"Admin@Welfare2026"}' \
  | python3 -c 'import sys,json; print(json.load(sys.stdin).get("access_token",""))')

if [[ -z "$TOKEN" ]]; then
  echo "login failed"
  exit 1
fi

echo "==> smtp-status"
curl -sS -m 10 http://127.0.0.1:19001/api/auth/email/smtp-status \
  -H "Authorization: Bearer $TOKEN"
echo

echo "==> test-imap"
curl -sS -m 30 -X POST http://127.0.0.1:19001/api/auth/email/test-imap \
  -H "Authorization: Bearer $TOKEN"
echo
echo DONE
