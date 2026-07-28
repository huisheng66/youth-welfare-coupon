#!/usr/bin/env bash
# 从开发机（WSL）打包并上传到生产服务器
set -euo pipefail

SRC="${SRC:-/mnt/d/卡系统}"
HOST="${HOST:-192.168.159.130}"
USER="${USER_REMOTE:-huisheng}"
PASS="${SSH_PASS:-000000}"
REMOTE_TGZ="welfare-prod.tgz"

if [[ ! -d "${SRC}" ]]; then
  echo "SRC not found: ${SRC}" >&2
  exit 1
fi
if [[ ! -f "${SRC}/frontend/dist/index.html" ]]; then
  echo "frontend/dist missing; build frontend first" >&2
  exit 1
fi

TMP=$(mktemp -d)
trap 'rm -rf "${TMP}"' EXIT
OUT="${TMP}/${REMOTE_TGZ}"

echo "==> packing ${SRC}"
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

echo "==> package size: $(du -h "${OUT}" | cut -f1)"
echo "==> sample contents:"
tar -tzf "${OUT}" | grep -E 'frontend/dist/index.html|deploy/install-ubuntu.sh|deploy/remote-deploy.sh' || {
  echo "required files missing in tarball" >&2
  exit 1
}

# 保证 shell 脚本为 LF
for f in remote-deploy.sh run-on-server.sh install-ubuntu.sh; do
  if [[ -f "${SRC}/deploy/${f}" ]]; then
    sed -i 's/\r$//' "${SRC}/deploy/${f}" || true
  fi
done

echo "==> upload to ${USER}@${HOST}"
sshpass -p "${PASS}" scp -o StrictHostKeyChecking=no "${OUT}" "${USER}@${HOST}:~/${REMOTE_TGZ}"
sshpass -p "${PASS}" scp -o StrictHostKeyChecking=no \
  "${SRC}/deploy/remote-deploy.sh" \
  "${SRC}/deploy/run-on-server.sh" \
  "${USER}@${HOST}:~/"
sshpass -p "${PASS}" ssh -o StrictHostKeyChecking=no "${USER}@${HOST}" \
  "chmod +x ~/remote-deploy.sh ~/run-on-server.sh; ls -lh ~/${REMOTE_TGZ} ~/remote-deploy.sh ~/run-on-server.sh"
echo "==> upload done"
