#!/usr/bin/env bash
# Install OWASP ZAP standalone (no Docker pull) in WSL as root.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

echo "==> install JRE wget"
apt-get update -qq
apt-get install -y -qq openjdk-17-jre-headless wget ca-certificates tar

ZAP_DIR=/opt/zap
mkdir -p "$ZAP_DIR"
cd /tmp
rm -f zap.tgz

# Prefer GitHub releases
URLS=(
  "https://github.com/zaproxy/zaproxy/releases/download/v2.16.1/ZAP_2.16.1_Linux.tar.gz"
  "https://github.com/zaproxy/zaproxy/releases/download/v2.15.0/ZAP_2.15.0_Linux.tar.gz"
  "https://github.com/zaproxy/zaproxy/releases/download/v2.14.0/ZAP_2.14.0_Linux.tar.gz"
)

ok=0
for u in "${URLS[@]}"; do
  echo "==> try $u"
  if wget -q --timeout=120 --tries=2 -O /tmp/zap.tgz "$u"; then
    if tar -tzf /tmp/zap.tgz >/dev/null 2>&1; then
      ok=1
      echo "downloaded OK"
      break
    fi
  fi
done

if [[ "$ok" -ne 1 ]]; then
  echo "FATAL: could not download ZAP tarball (network?)"
  exit 1
fi

echo "==> extract to $ZAP_DIR"
rm -rf "$ZAP_DIR"/*
tar -xzf /tmp/zap.tgz -C "$ZAP_DIR" --strip-components=1
ls -la "$ZAP_DIR" | head -20
test -x "$ZAP_DIR/zap.sh"
echo "ZAP_INSTALL_OK=$ZAP_DIR"
