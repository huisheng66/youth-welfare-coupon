#!/usr/bin/env bash
set -euo pipefail
HOST="${HOST:-198.44.182.107}"
PASS="${SSH_PASS:-1LMntnpAd0}"
SRC="${SRC:-/mnt/d/卡系统}"

TMP=$(mktemp -d)
trap 'rm -rf "${TMP}"' EXIT

mkdir -p "${TMP}/app/schemas" "${TMP}/dist"
cp "${SRC}/backend/app/schemas/auth.py" "${TMP}/app/schemas/"
tar -C "${SRC}/frontend/dist" -czf "${TMP}/dist.tgz" .
tar -C "${TMP}" -czf "${TMP}/patch.tgz" app

sshpass -p "${PASS}" scp -o StrictHostKeyChecking=no \
  "${TMP}/patch.tgz" "${TMP}/dist.tgz" "root@${HOST}:/tmp/"

sshpass -p "${PASS}" ssh -o StrictHostKeyChecking=no "root@${HOST}" bash -s <<'REMOTE'
set -euo pipefail
mkdir -p /tmp/welfare-patch
tar -xzf /tmp/patch.tgz -C /tmp/welfare-patch
install -m 644 /tmp/welfare-patch/app/schemas/auth.py /opt/welfare/backend/app/schemas/auth.py

rm -rf /opt/welfare/frontend/dist/*
mkdir -p /opt/welfare/frontend/dist
tar -xzf /tmp/dist.tgz -C /opt/welfare/frontend/dist
chown -R www-data:www-data /opt/welfare/frontend/dist

systemctl restart welfare-api
sleep 2
systemctl is-active welfare-api
curl -sS -m 8 http://127.0.0.1:19001/api/health
echo
# unit check schema on server
cd /opt/welfare/backend
.venv/bin/python - <<'PY'
from app.schemas.auth import CreateIssueAdminIn
from pydantic import ValidationError
try:
    CreateIssueAdminIn(username='ab', password='12345678')
except ValidationError as e:
    print('expect fail:', e.errors()[0]['msg'])
m = CreateIssueAdminIn(username='issuer_ok', password='12345678', display_name='测')
print('ok', m.model_dump())
PY
rm -f /tmp/patch.tgz /tmp/dist.tgz
REMOTE
echo done
