#!/usr/bin/env bash
# 一次性补丁：已合入主线，保留作历史参考。详见 deploy/archive/README.md
# Production: CORS_ORIGINS HTTPS only
set -euo pipefail

ENV_FILE=/opt/welfare/backend/.env
DOMAIN=youth.huishengbook.us.ci

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "missing ${ENV_FILE}" >&2
  exit 1
fi

cp -a "${ENV_FILE}" "${ENV_FILE}.bak-cors-$(date +%Y%m%d%H%M%S)"

if grep -q '^CORS_ORIGINS=' "${ENV_FILE}"; then
  sed -i "s|^CORS_ORIGINS=.*|CORS_ORIGINS=https://${DOMAIN}|" "${ENV_FILE}"
else
  echo "CORS_ORIGINS=https://${DOMAIN}" >> "${ENV_FILE}"
fi

if grep -q '^CORS_ALLOW_LAN=' "${ENV_FILE}"; then
  sed -i 's|^CORS_ALLOW_LAN=.*|CORS_ALLOW_LAN=false|' "${ENV_FILE}"
else
  echo 'CORS_ALLOW_LAN=false' >> "${ENV_FILE}"
fi

echo "=== CORS after ==="
grep -E '^(CORS_|APP_ENV)' "${ENV_FILE}"

systemctl restart welfare-api
sleep 2
systemctl is-active welfare-api
curl -sS -m 8 http://127.0.0.1:19001/api/health
echo

# quick CORS check: evil vs https
python3 - <<'PY'
import urllib.request
base = "http://127.0.0.1:19001/api/health"
for origin in ("https://youth.huishengbook.us.ci", "http://youth.huishengbook.us.ci", "https://evil.example"):
    req = urllib.request.Request(base, headers={"Origin": origin, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            acao = r.headers.get("Access-Control-Allow-Origin", "")
            print(f"origin={origin!r} status={r.status} ACAO={acao!r}")
    except Exception as e:
        print(f"origin={origin!r} err={e}")
PY
