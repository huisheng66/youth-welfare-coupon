#!/usr/bin/env bash
# 绑定 youth.huishengbook.us.ci 到福利券站点
set -euo pipefail

DOMAIN="youth.huishengbook.us.ci"
IP_EXPECT="198.44.182.107"
APP_ROOT="/opt/welfare"
ENV_FILE="${APP_ROOT}/backend/.env"

echo "==> DNS check"
RESOLVED="$(getent ahostsv4 "${DOMAIN}" 2>/dev/null | awk '{print $1; exit}' || true)"
if [[ -z "${RESOLVED}" ]]; then
  RESOLVED="$(dig +short A "${DOMAIN}" 2>/dev/null | head -1 || true)"
fi
echo "resolved=${RESOLVED:-none}"
if [[ -n "${RESOLVED}" && "${RESOLVED}" != "${IP_EXPECT}" ]]; then
  echo "WARN: DNS A 记录是 ${RESOLVED}，期望 ${IP_EXPECT}"
fi

echo "==> Nginx site for ${DOMAIN}"
cat > /etc/nginx/sites-available/welfare <<EOF
# Youth welfare coupon — ${DOMAIN}
server {
    listen 80;
    listen [::]:80;
    server_name ${DOMAIN};

    root ${APP_ROOT}/frontend/dist;
    index index.html;
    client_max_body_size 10m;
    access_log /var/log/nginx/welfare-access.log welfare_timed;

    add_header X-Content-Type-Options nosniff always;
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    add_header X-Frame-Options DENY always;
    add_header Referrer-Policy strict-origin-when-cross-origin always;

    location ~* /(\\.env|\\.git|\\.svn|\\.hg|\\.DS_Store|docker-compose|composer\\.(json|lock)|package-lock\\.json) {
        return 404;
    }
    location ~ /\\.(?!well-known) {
        return 404;
    }
    location ^~ /backend/ { return 404; }

    location /api/ {
        proxy_pass http://127.0.0.1:19001;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_connect_timeout 10s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
    }

    location = /docs { return 404; }
    location = /redoc { return 404; }
    location = /openapi.json { return 404; }

    location / {
        try_files \$uri \$uri/ /index.html;
    }
}
EOF

ln -sfn /etc/nginx/sites-available/welfare /etc/nginx/sites-enabled/welfare
nginx -t
systemctl reload nginx

echo "==> Update CORS in .env"
if [[ ! -f "${ENV_FILE}" ]]; then
  echo "missing ${ENV_FILE}" >&2
  exit 1
fi
# 备份
cp -a "${ENV_FILE}" "${ENV_FILE}.bak-$(date +%Y%m%d%H%M%S)"

# 设置 CORS 为正式域名（仅 https）
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

grep -E '^(APP_ENV|CORS_|OPENAPI|SEED)' "${ENV_FILE}" || true

systemctl restart welfare-api
sleep 2
systemctl is-active welfare-api

echo "==> HTTP verify by Host"
curl -sS -m 8 -H "Host: ${DOMAIN}" http://127.0.0.1/api/health
echo
curl -sS -o /dev/null -w "home=%{http_code}\n" -m 8 -H "Host: ${DOMAIN}" http://127.0.0.1/
if [[ -n "${ADMIN_PASS:-}" ]]; then
  curl -sS -m 8 -X POST -H "Host: ${DOMAIN}" -H 'Content-Type: application/json' \
    -d "{\"username\":\"${ADMIN_USER:-admin}\",\"password\":\"${ADMIN_PASS}\"}" \
    http://127.0.0.1/api/auth/login | head -c 180
else
  echo "SKIP: ADMIN_PASS 未设置，跳过登录自检"
fi
echo

# HTTPS：若 certbot 可用且 DNS 已指向本机
if command -v certbot >/dev/null 2>&1; then
  echo "==> Try certbot for ${DOMAIN}"
  # 非交互；失败不让整脚本挂掉
  if certbot --nginx -d "${DOMAIN}" --non-interactive --agree-tos --register-unsafely-without-email --redirect 2>&1 | tee /tmp/certbot-youth.log; then
    echo "certbot ok"
  else
    echo "certbot failed or skipped; see /tmp/certbot-youth.log"
    tail -30 /tmp/certbot-youth.log || true
  fi
else
  echo "==> certbot not installed; installing python3-certbot-nginx"
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -y
  apt-get install -y certbot python3-certbot-nginx || true
  if command -v certbot >/dev/null 2>&1; then
    certbot --nginx -d "${DOMAIN}" --non-interactive --agree-tos --register-unsafely-without-email --redirect 2>&1 | tee /tmp/certbot-youth.log || true
  fi
fi

echo "==> Final external-style checks"
curl -sS -m 10 -H "Host: ${DOMAIN}" http://127.0.0.1/api/health || true
echo
if curl -skS -m 10 "https://${DOMAIN}/api/health" 2>/dev/null; then
  echo
  echo "HTTPS health OK"
else
  echo "HTTPS not ready yet (DNS or cert); HTTP by Host works"
fi

echo "DONE domain=${DOMAIN}"
