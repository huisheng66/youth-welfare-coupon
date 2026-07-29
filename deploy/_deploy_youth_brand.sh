#!/usr/bin/env bash
# Deploy youth rebrand + backend modules to production (preserve .env)
set -euo pipefail
HOST="${HOST:-198.44.182.107}"
PASS="${SSH_PASS:-1LMntnpAd0}"
SRC="${SRC:-/mnt/d/卡系统}"
SSH_OPTS=(-o PreferredAuthentications=password -o PubkeyAuthentication=no -o StrictHostKeyChecking=accept-new -o ConnectTimeout=25)

if [[ ! -f "${SRC}/frontend/dist/index.html" ]]; then
  echo "missing frontend/dist; run npm run build first" >&2
  exit 1
fi

TMP=$(mktemp -d)
trap 'rm -rf "${TMP}"' EXIT

mkdir -p "${TMP}/app/core" "${TMP}/app/api" "${TMP}/app/schemas" "${TMP}/app/services"
cp "${SRC}/backend/app/main.py" "${TMP}/app/"
cp "${SRC}/backend/app/core/config.py" "${TMP}/app/core/"
cp "${SRC}/backend/app/core/client_ip.py" "${TMP}/app/core/"
cp "${SRC}/backend/app/api/auth.py" "${TMP}/app/api/"
cp "${SRC}/backend/app/schemas/auth.py" "${TMP}/app/schemas/"
cp "${SRC}/backend/app/services/mail.py" "${TMP}/app/services/"

tar -C "${TMP}" -czf "${TMP}/backend-patch.tgz" app
tar -C "${SRC}/frontend/dist" -czf "${TMP}/dist.tgz" .

echo "==> upload"
sshpass -p "${PASS}" scp "${SSH_OPTS[@]}" \
  "${TMP}/backend-patch.tgz" "${TMP}/dist.tgz" "root@${HOST}:/tmp/"

echo "==> apply on server"
sshpass -p "${PASS}" ssh "${SSH_OPTS[@]}" "root@${HOST}" bash -s <<'REMOTE'
set -euo pipefail
mkdir -p /tmp/welfare-brand /opt/welfare/backend/app/core /opt/welfare/backend/app/api /opt/welfare/backend/app/schemas /opt/welfare/backend/app/services
tar -xzf /tmp/backend-patch.tgz -C /tmp/welfare-brand
install -m 644 /tmp/welfare-brand/app/main.py /opt/welfare/backend/app/main.py
install -m 644 /tmp/welfare-brand/app/core/config.py /opt/welfare/backend/app/core/config.py
install -m 644 /tmp/welfare-brand/app/core/client_ip.py /opt/welfare/backend/app/core/client_ip.py
install -m 644 /tmp/welfare-brand/app/api/auth.py /opt/welfare/backend/app/api/auth.py
install -m 644 /tmp/welfare-brand/app/schemas/auth.py /opt/welfare/backend/app/schemas/auth.py
install -m 644 /tmp/welfare-brand/app/services/mail.py /opt/welfare/backend/app/services/mail.py

rm -rf /opt/welfare/frontend/dist/*
mkdir -p /opt/welfare/frontend/dist
tar -xzf /tmp/dist.tgz -C /opt/welfare/frontend/dist
chown -R www-data:www-data /opt/welfare/frontend/dist

# Optional: align app_name if not set (do not force overwrite mail display name)
if [[ -f /opt/welfare/backend/.env ]]; then
  if ! grep -qE '^APP_NAME=' /opt/welfare/backend/.env; then
    echo 'APP_NAME=youth' >> /opt/welfare/backend/.env
    echo "added APP_NAME=youth"
  else
    sed -i 's/^APP_NAME=.*/APP_NAME=youth/' /opt/welfare/backend/.env
    echo "set APP_NAME=youth"
  fi
  # leave MAIL_FROM_NAME as-is per ops choice
fi

systemctl restart welfare-api
sleep 2
systemctl is-active welfare-api
curl -sS -m 8 http://127.0.0.1:19001/api/health
echo
echo "==> dist sample"
ls -la /opt/welfare/frontend/dist/ | head -20
test -f /opt/welfare/frontend/dist/favicon.ico && echo "favicon ok" || echo "favicon missing"
grep -o 'youth' /opt/welfare/frontend/dist/index.html | head -3 || true
head -c 400 /opt/welfare/frontend/dist/index.html; echo
rm -f /tmp/backend-patch.tgz /tmp/dist.tgz
rm -rf /tmp/welfare-brand
REMOTE

echo "==> public checks"
curl -sS -m 15 -o /tmp/youth-index.html -w "index:%{http_code}\n" "https://youth.huishengbook.us.ci/" || true
grep -E 'youth|favicon' /tmp/youth-index.html | head -10 || true
curl -sS -m 15 -o /dev/null -w "favicon:%{http_code}\n" "https://youth.huishengbook.us.ci/favicon.ico" || true
curl -sS -m 15 "https://youth.huishengbook.us.ci/api/health" || true
echo
echo deploy-youth-brand done
