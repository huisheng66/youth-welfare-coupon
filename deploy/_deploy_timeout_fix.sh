#!/usr/bin/env bash
# Deploy frontend dist + enable nginx timed access log on public host
set -euo pipefail

HOST="${HOST:-198.44.182.107}"
PASS="${SSH_PASS:-1LMntnpAd0}"
SRC="${SRC:-/mnt/d/卡系统}"
REMOTE_DIR="/opt/welfare/frontend/dist"

if [[ ! -f "${SRC}/frontend/dist/index.html" ]]; then
  echo "missing dist" >&2
  exit 1
fi

TMP=$(mktemp -d)
trap 'rm -rf "${TMP}"' EXIT
tar -C "${SRC}/frontend/dist" -czf "${TMP}/dist.tgz" .
cp "${SRC}/deploy/enable-nginx-request-time.sh" "${TMP}/enable-nginx-request-time.sh"

sshpass -p "${PASS}" scp -o StrictHostKeyChecking=no \
  "${TMP}/dist.tgz" "${TMP}/enable-nginx-request-time.sh" \
  "root@${HOST}:/tmp/"

sshpass -p "${PASS}" ssh -o StrictHostKeyChecking=no "root@${HOST}" bash -s <<'REMOTE'
set -euo pipefail
REMOTE_DIR="/opt/welfare/frontend/dist"
rm -rf "${REMOTE_DIR:?}"/*
mkdir -p "${REMOTE_DIR}"
tar -xzf /tmp/dist.tgz -C "${REMOTE_DIR}"
chown -R www-data:www-data "${REMOTE_DIR}"
rm -f /tmp/dist.tgz
bash /tmp/enable-nginx-request-time.sh
rm -f /tmp/enable-nginx-request-time.sh
echo "=== health ==="
curl -sS -m 8 -H 'Host: youth.huishengbook.us.ci' http://127.0.0.1/api/health || true
echo
ls -la "${REMOTE_DIR}/index.html" "${REMOTE_DIR}/assets" | head -20
echo "=== asset hash sample ==="
ls "${REMOTE_DIR}/assets" | head -5
REMOTE

echo "deploy done to ${HOST}"
