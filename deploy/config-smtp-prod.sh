#!/usr/bin/env bash
# 生产机配置腾讯企业邮 SMTP（仅写 /opt/welfare/backend/.env，不入库）
set -euo pipefail

ENV_FILE=/opt/welfare/backend/.env
if [[ ! -f "$ENV_FILE" ]]; then
  echo "missing $ENV_FILE" >&2
  exit 1
fi

cp -a "$ENV_FILE" "${ENV_FILE}.bak-smtp-$(date +%Y%m%d%H%M%S)"

set_kv() {
  local key="$1" val="$2"
  if grep -q "^${key}=" "$ENV_FILE"; then
    # 用 | 分隔，避免密码里的特殊字符问题；此处密码无 |
    sed -i "s|^${key}=.*|${key}=${val}|" "$ENV_FILE"
  else
    echo "${key}=${val}" >> "$ENV_FILE"
  fi
}

set_kv MAIL_SERVER smtp.exmail.qq.com
set_kv MAIL_PORT 465
set_kv MAIL_SSL_TLS true
set_kv MAIL_STARTTLS false
set_kv MAIL_USERNAME 'huisheng@51huisheng.top'
set_kv MAIL_PASSWORD "${SMTP_PASSWORD:?请先 export SMTP_PASSWORD（企业邮箱 SMTP 专用密码）}"
set_kv MAIL_FROM 'huisheng@51huisheng.top'
set_kv MAIL_FROM_NAME '青年福利券系统'
set_kv MAIL_CONSOLE false
set_kv EMAIL_CODE_EXPIRE_MINUTES 10

chmod 640 "$ENV_FILE"
chown www-data:www-data "$ENV_FILE" 2>/dev/null || true

echo "==> mail keys (password redacted)"
grep -E '^MAIL_|^EMAIL_' "$ENV_FILE" | sed -E 's/^(MAIL_PASSWORD)=.*/\1=***/'

systemctl restart welfare-api
sleep 2
systemctl is-active welfare-api

echo "==> health"
curl -sS -m 8 http://127.0.0.1:19001/api/health
echo

# 登录超管后打测试发信（若密码已改则跳过测试）
echo "==> try admin login + smtp-status"
TOKEN=""
if [[ -n "${ADMIN_PASS:-}" ]]; then
  TOKEN=$(curl -sS -m 10 -X POST http://127.0.0.1:19001/api/auth/login \
    -H 'Content-Type: application/json' \
    -d "{\"username\":\"${ADMIN_USER:-admin}\",\"password\":\"${ADMIN_PASS}\"}" | python3 -c 'import sys,json; print(json.load(sys.stdin).get("access_token",""))' 2>/dev/null || true)
else
  echo "skip: ADMIN_PASS 未设置，跳过超管自检（SMTP 配置已写入）"
fi

if [[ -z "$TOKEN" ]]; then
  echo "admin login failed (password may have changed); SMTP env written, please test in UI"
  exit 0
fi

echo "==> smtp-status"
curl -sS -m 10 http://127.0.0.1:19001/api/auth/email/smtp-status \
  -H "Authorization: Bearer $TOKEN"
echo

echo "==> test send to self"
curl -sS -m 45 -X POST http://127.0.0.1:19001/api/auth/email/test \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"to":"huisheng@51huisheng.top"}'
echo
echo DONE
