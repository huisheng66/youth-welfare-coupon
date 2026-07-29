#!/usr/bin/env bash
set -euo pipefail
SRC="${SRC:-/mnt/d/卡系统}"
HOST="${HOST:-198.44.182.107}"
USER_REMOTE="${USER_REMOTE:-root}"
PASS="${SSH_PASS:-1LMntnpAd0}"
SSH_OPTS=(-o PreferredAuthentications=password -o PubkeyAuthentication=no -o StrictHostKeyChecking=accept-new -o ConnectTimeout=20)

if [[ ! -f "${SRC}/frontend/dist/index.html" ]]; then
  echo "missing dist" >&2
  exit 1
fi

TMP=$(mktemp -d)
trap 'rm -rf "${TMP}"' EXIT
OUT="${TMP}/welfare-prod.tgz"

for f in remote-deploy.sh run-on-public.sh install-ubuntu.sh; do
  sed -i 's/\r$//' "${SRC}/deploy/${f}" || true
done

echo "==> packing"
tar -C "${SRC}" -czf "${OUT}" \
  --exclude='./backend/.venv' \
  --exclude='./frontend/node_modules' \
  --exclude='./tools/sqlmap' \
  --exclude='./reports' \
  --exclude='./.git' \
  --exclude='./backend/data' \
  --exclude='./backend/.env' \
  --exclude='**/__pycache__' \
  --exclude='*.pyc' \
  .
ls -lh "${OUT}"
tar -tzf "${OUT}" | grep -E 'frontend/dist/index.html|deploy/install-ubuntu.sh' 

echo "==> upload"
sshpass -p "${PASS}" scp "${SSH_OPTS[@]}" "${OUT}" "${USER_REMOTE}@${HOST}:/root/welfare-prod.tgz"
sshpass -p "${PASS}" scp "${SSH_OPTS[@]}" \
  "${SRC}/deploy/remote-deploy.sh" \
  "${SRC}/deploy/run-on-public.sh" \
  "${USER_REMOTE}@${HOST}:/root/"
sshpass -p "${PASS}" ssh "${SSH_OPTS[@]}" "${USER_REMOTE}@${HOST}" \
  "chmod +x /root/remote-deploy.sh /root/run-on-public.sh; ls -lh /root/welfare-prod.tgz /root/run-on-public.sh"
echo "==> upload done"
