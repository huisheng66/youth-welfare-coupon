#!/usr/bin/env bash
# 在目标服务器上由 root/sudo 执行：解压 + 一键安装
set -euo pipefail

# 允许从 sudo 调用：默认用部署用户家目录
DEPLOY_HOME="${DEPLOY_HOME:-/home/huisheng}"
SRC_TGZ="${1:-${DEPLOY_HOME}/welfare-prod.tgz}"
WORK="${DEPLOY_HOME}/welfare-src"
DOMAIN="${DOMAIN:-192.168.159.130}"
DB_PASS="${DB_PASS:-}"
BOOTSTRAP_ADMIN_USER="${BOOTSTRAP_ADMIN_USER:-admin}"
BOOTSTRAP_ADMIN_PASS="${BOOTSTRAP_ADMIN_PASS:-}"

if [[ ! -f "${SRC_TGZ}" ]]; then
  echo "missing tarball: ${SRC_TGZ}" >&2
  exit 1
fi

rm -rf "${WORK}"
mkdir -p "${WORK}"
tar -xzf "${SRC_TGZ}" -C "${WORK}"
# 去掉 Windows 换行
find "${WORK}/deploy" -type f -name '*.sh' -exec sed -i 's/\r$//' {} +

if [[ ! -f "${WORK}/frontend/dist/index.html" ]]; then
  echo "ERROR: frontend/dist missing in package" >&2
  tar -tzf "${SRC_TGZ}" | grep -E 'frontend|install' | head -40 || true
  exit 1
fi

cd "${WORK}"
export DOMAIN
export SKIP_FRONTEND_BUILD=1
export BOOTSTRAP_ADMIN_USER
if [[ -n "${DB_PASS}" ]]; then
  export DB_PASS
fi
if [[ -n "${BOOTSTRAP_ADMIN_PASS}" ]]; then
  export BOOTSTRAP_ADMIN_PASS
fi

bash deploy/install-ubuntu.sh
