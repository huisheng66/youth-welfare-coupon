#!/usr/bin/env bash
# 生产 Nginx 加固：敏感路径 404、HSTS、禁止访问隐藏文件
set -euo pipefail

SITE=/etc/nginx/sites-available/welfare
if [[ ! -f "${SITE}" ]]; then
  echo "missing ${SITE}" >&2
  exit 1
fi

cp -a "${SITE}" "${SITE}.bak-harden-$(date +%Y%m%d%H%M%S)"

# 若尚未加入敏感路径拦截，在 location /api/ 之前插入
if ! grep -q 'deny-sensitive-paths' "${SITE}"; then
  python3 - <<'PY'
from pathlib import Path
path = Path("/etc/nginx/sites-available/welfare")
text = path.read_text()
block = """
    # deny-sensitive-paths — do not SPA-fallback secrets
    location ~* /(\\.env|\\.git|\\.svn|\\.hg|\\.DS_Store|docker-compose|composer\\.(json|lock)|package-lock\\.json) {
        return 404;
    }
    location ~ /\\.(?!well-known) {
        return 404;
    }
    location = /backend/.env { return 404; }
    location ^~ /backend/ { return 404; }

"""
# insert once before first "location /api/"
needle = "location /api/"
idx = text.find(needle)
if idx < 0:
    raise SystemExit("no location /api/ found")
# only first server block occurrence is enough if pattern repeats — insert before every location /api/
parts = text.split(needle)
# parts[0] + block + location /api/ + parts[1] + location /api/ + ...
out = parts[0]
for i, p in enumerate(parts[1:]):
    # avoid double-insert if already present near this location
    out += block + needle + p
path.write_text(out)
print("inserted deny-sensitive-paths")
PY
else
  echo "deny-sensitive-paths already present"
fi

# HSTS on HTTPS server blocks (listen 443)
if ! grep -q 'Strict-Transport-Security' "${SITE}"; then
  # after add_header X-Content-Type-Options lines, add HSTS only if ssl listen exists
  if grep -q 'listen .*443' "${SITE}"; then
    sed -i '/add_header X-Content-Type-Options/a\    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;' "${SITE}"
    echo "inserted HSTS"
  fi
fi

# ensure timed log format exists
if [[ ! -f /etc/nginx/conf.d/welfare-timed-log.conf ]]; then
  cat > /etc/nginx/conf.d/welfare-timed-log.conf <<'EOF'
log_format welfare_timed '$remote_addr - $remote_user [$time_local] '
    '"$request" $status $body_bytes_sent '
    '"$http_referer" "$http_user_agent" '
    'rt=$request_time urt=$upstream_response_time';
EOF
fi

nginx -t
systemctl reload nginx

echo "=== verify sensitive paths ==="
for p in /.env /.git/HEAD /backend/.env /api/health; do
  code=$(curl -sk -o /tmp/hbody -w '%{http_code}' -H 'Host: youth.huishengbook.us.ci' "https://127.0.0.1${p}")
  ctype=$(curl -sk -I -H 'Host: youth.huishengbook.us.ci' "https://127.0.0.1${p}" | tr -d '\r' | grep -i '^content-type:' | head -1)
  echo "$p -> $code $ctype"
done
echo OK
