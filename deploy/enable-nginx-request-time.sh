#!/usr/bin/env bash
# 为福利券站点启用带 request_time / upstream_response_time 的 access log
set -euo pipefail

LOG_FMT=/etc/nginx/conf.d/welfare-timed-log.conf
SITE=/etc/nginx/sites-available/welfare

cat > "${LOG_FMT}" <<'EOF'
# Youth welfare — timed access log format
log_format welfare_timed '$remote_addr - $remote_user [$time_local] '
    '"$request" $status $body_bytes_sent '
    '"$http_referer" "$http_user_agent" '
    'rt=$request_time urt=$upstream_response_time';
EOF

if [[ ! -f "${SITE}" ]]; then
  echo "missing ${SITE}" >&2
  exit 1
fi

# 每个含 client_max_body_size 的 server 块写入 timed access_log（幂等）
if ! grep -q 'welfare_timed' "${SITE}"; then
  cp -a "${SITE}" "${SITE}.bak-timed-$(date +%Y%m%d%H%M%S)"
  # 在 client_max_body_size 行后插入 access_log
  sed -i '/client_max_body_size/a\    access_log /var/log/nginx/welfare-access.log welfare_timed;' "${SITE}"
  echo "inserted access_log into ${SITE}"
else
  echo "access_log welfare_timed already present"
fi

# API 超时略收紧连接阶段，避免挂死连接占 worker
if ! grep -q 'proxy_connect_timeout' "${SITE}"; then
  sed -i '/proxy_read_timeout/i\        proxy_connect_timeout 10s;\n        proxy_send_timeout 60s;' "${SITE}"
fi

nginx -t
systemctl reload nginx

echo "=== sample (empty until next request) ==="
touch /var/log/nginx/welfare-access.log
ls -la /var/log/nginx/welfare-access.log
echo "OK: logs at /var/log/nginx/welfare-access.log (fields rt= total, urt= upstream)"
