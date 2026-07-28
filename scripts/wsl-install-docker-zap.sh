#!/usr/bin/env bash
# Run as root in WSL: wsl -u root bash /mnt/d/.../wsl-install-docker-zap.sh
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

echo "==> OS"
uname -a
. /etc/os-release 2>/dev/null || true
echo "${PRETTY_NAME:-unknown}"

echo "==> apt-get update"
apt-get update -qq

echo "==> install docker.io curl"
apt-get install -y -qq docker.io curl ca-certificates

echo "==> start docker"
if command -v systemctl >/dev/null 2>&1; then
  systemctl enable docker 2>/dev/null || true
  systemctl start docker 2>/dev/null || true
fi
service docker start 2>/dev/null || true
if ! docker info >/dev/null 2>&1; then
  echo "starting dockerd in background..."
  nohup dockerd >/tmp/dockerd.log 2>&1 &
  for i in 1 2 3 4 5 6 7 8 9 10; do
    sleep 2
    if docker info >/dev/null 2>&1; then
      break
    fi
  done
fi

echo "==> docker info"
docker info 2>&1 | head -25

echo "==> pull ZAP image"
if ! docker pull ghcr.io/zaproxy/zaproxy:stable; then
  echo "ghcr failed, try docker hub"
  docker pull zaproxy/zap-stable
fi

echo "INSTALL_OK"
