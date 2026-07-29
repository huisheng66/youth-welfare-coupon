#!/bin/bash
set -e
echo "=== welfare site ==="
cat /etc/nginx/sites-available/welfare
echo
echo "=== nginx -T welfare snippets ==="
nginx -T 2>/dev/null | grep -nE 'deny-sensitive|server_name youth|location.*env|Strict-Transport|try_files' | head -60
echo
echo "=== curl verbose ==="
curl -sk -o /tmp/b -w 'code=%{http_code}\n' -H 'Host: youth.huishengbook.us.ci' 'https://127.0.0.1/.env'
head -c 100 /tmp/b; echo
curl -sk -D- -o /dev/null -H 'Host: youth.huishengbook.us.ci' 'https://127.0.0.1/.env' | head -20
