#!/usr/bin/env bash
set -euo pipefail

# hair-flow 不再占用 IP
if [[ -f /etc/nginx/sites-available/hair-flow.conf ]]; then
  sed -i 's/server_name manger\.huishengbook\.us\.ci 198\.44\.182\.107;/server_name manger.huishengbook.us.ci;/' \
    /etc/nginx/sites-available/hair-flow.conf || true
fi

# 福利券：IP 作为 default_server，确保裸 IP 访问落到本站
cat > /etc/nginx/sites-available/welfare <<'EOF'
# Youth welfare coupon — public IP
server {
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name 198.44.182.107 _;

    root /opt/welfare/frontend/dist;
    index index.html;
    client_max_body_size 10m;

    add_header X-Content-Type-Options nosniff always;
    add_header X-Frame-Options DENY always;
    add_header Referrer-Policy strict-origin-when-cross-origin always;

    location /api/ {
        proxy_pass http://127.0.0.1:19001;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 60s;
    }

    location = /docs { return 404; }
    location = /redoc { return 404; }
    location = /openapi.json { return 404; }

    location / {
        try_files $uri $uri/ /index.html;
    }
}
EOF

ln -sfn /etc/nginx/sites-available/welfare /etc/nginx/sites-enabled/welfare

# 去掉其它站点的 default_server（若有）
for f in /etc/nginx/sites-enabled/*; do
  [[ "$(basename "$f")" == "welfare" ]] && continue
  if grep -q 'default_server' "$f" 2>/dev/null; then
    echo "strip default_server from $f"
    sed -i 's/ default_server//g' "$f"
  fi
done

nginx -t
systemctl reload nginx

echo "=== verify ==="
curl -sS -m 5 -H 'Host: 198.44.182.107' http://127.0.0.1/ | head -c 300
echo
curl -sS -m 5 -H 'Host: 198.44.182.107' http://127.0.0.1/api/health
echo
curl -sS -m 8 -X POST -H 'Host: 198.44.182.107' -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"Admin@Welfare2026"}' \
  http://127.0.0.1/api/auth/login
echo
systemctl is-active welfare-api
