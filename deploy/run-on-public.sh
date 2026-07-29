#!/usr/bin/env bash
# 公网机 root 部署（不删其它站点）
set -euo pipefail
export DEPLOY_HOME="${DEPLOY_HOME:-/root}"
export DOMAIN="${DOMAIN:-198.44.182.107}"
export SKIP_FRONTEND_BUILD="${SKIP_FRONTEND_BUILD:-1}"
export BOOTSTRAP_ADMIN_USER="${BOOTSTRAP_ADMIN_USER:-admin}"
export BOOTSTRAP_ADMIN_PASS="${BOOTSTRAP_ADMIN_PASS:-Admin@Welfare2026}"
# 使用固定 DB 密码便于运维（写入 .env）
export DB_PASS="${DB_PASS:-Welfare_$(openssl rand -hex 6)}"

# 安装公钥，后续可用密钥登录
mkdir -p /root/.ssh
chmod 700 /root/.ssh
PUB='ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIBVwSNMQ2zMWAB4knj9LTMTjto9u+v2Awvb2pKLaBdYz litianqi6668@gmail.com'
grep -qxF "$PUB" /root/.ssh/authorized_keys 2>/dev/null || echo "$PUB" >> /root/.ssh/authorized_keys
chmod 600 /root/.ssh/authorized_keys

bash /root/remote-deploy.sh /root/welfare-prod.tgz
