#!/usr/bin/env bash
set -euo pipefail
echo "=== sites-enabled ==="
ls -la /etc/nginx/sites-enabled/ || true
echo "=== site snippets ==="
for f in /etc/nginx/sites-enabled/*; do
  echo "FILE:$f"
  grep -E 'server_name|listen|root |proxy_pass' "$f" | head -30 || true
  echo
done
echo "=== /opt ==="
ls -la /opt
echo "=== mysql dbs ==="
mysql -e 'SHOW DATABASES;' 2>/dev/null || true
