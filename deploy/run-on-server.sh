#!/usr/bin/env bash
# 在目标机以 root/sudo 执行。示例：
#   DOMAIN=192.168.159.130 BOOTSTRAP_ADMIN_PASS='强密码' sudo -E bash run-on-server.sh
set -euo pipefail
export DEPLOY_HOME="${DEPLOY_HOME:-/home/huisheng}"
export DOMAIN="${DOMAIN:-192.168.159.130}"
export SKIP_FRONTEND_BUILD="${SKIP_FRONTEND_BUILD:-1}"
export BOOTSTRAP_ADMIN_USER="${BOOTSTRAP_ADMIN_USER:-admin}"
# BOOTSTRAP_ADMIN_PASS 未设置时由 install-ubuntu.sh 自动生成
export BOOTSTRAP_ADMIN_PASS="${BOOTSTRAP_ADMIN_PASS:-}"
bash "${DEPLOY_HOME}/remote-deploy.sh" "${DEPLOY_HOME}/welfare-prod.tgz"
