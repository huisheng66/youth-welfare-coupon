#!/bin/bash
set -e
echo "=== .env perms ==="
ls -la /opt/welfare/backend/.env
stat -c '%a %U:%G %n' /opt/welfare/backend/.env
echo "=== listening ports ==="
ss -lntp
echo "=== mysql/redis/api bind ==="
ss -lntp | grep -E ':(3306|19001|6379|80|443)\s' || true
echo "=== ufw ==="
ufw status verbose 2>/dev/null || echo 'ufw n/a'
echo "=== fail2ban ==="
systemctl is-active fail2ban 2>/dev/null || echo 'fail2ban inactive'
echo "=== welfare-api unit ==="
systemctl cat welfare-api | head -40
echo "=== openapi env ==="
grep -E '^(APP_ENV|OPENAPI|SEED|CORS|RATE_)' /opt/welfare/backend/.env | sed 's/PASSWORD=.*/PASSWORD=***/;s/SECRET=.*/SECRET=***/'
echo "=== path checks public-facing local ==="
for p in /.env /.git/HEAD /backend/.env /api/docs /api/openapi.json /api/health; do
  code=$(curl -sk -o /dev/null -w '%{http_code}' -H 'Host: youth.huishengbook.us.ci' "https://127.0.0.1${p}")
  echo "$p $code"
done
