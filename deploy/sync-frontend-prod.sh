#!/usr/bin/env bash
# 仅同步 frontend/dist 到生产（不改 .env / 数据库）
set -euo pipefail
SRC="${SRC:-/mnt/d/卡系统}"
HOST="${HOST:-192.168.159.130}"
USER_REMOTE="${USER_REMOTE:-huisheng}"
PASS="${SSH_PASS:-000000}"
REMOTE_DIR="/opt/welfare/frontend/dist"

if [[ ! -f "${SRC}/frontend/dist/index.html" ]]; then
  echo "missing dist; run npm run build first" >&2
  exit 1
fi

TMP=$(mktemp -d)
trap 'rm -rf "${TMP}"' EXIT
tar -C "${SRC}/frontend/dist" -czf "${TMP}/dist.tgz" .
sshpass -p "${PASS}" scp -o StrictHostKeyChecking=no "${TMP}/dist.tgz" "${USER_REMOTE}@${HOST}:/tmp/welfare-dist.tgz"
sshpass -p "${PASS}" ssh -o StrictHostKeyChecking=no "${USER_REMOTE}@${HOST}" \
  "echo ${PASS} | sudo -S bash -c 'rm -rf ${REMOTE_DIR}/*; mkdir -p ${REMOTE_DIR}; tar -xzf /tmp/welfare-dist.tgz -C ${REMOTE_DIR}; chown -R www-data:www-data ${REMOTE_DIR}; rm -f /tmp/welfare-dist.tgz; nginx -t && systemctl reload nginx; ls -la ${REMOTE_DIR}'"
echo "frontend synced to ${HOST}:${REMOTE_DIR}"
