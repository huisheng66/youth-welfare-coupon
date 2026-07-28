#!/usr/bin/env bash
set -uo pipefail

echo "==> wait for wget"
for i in $(seq 1 80); do
  if pgrep -f "wget.*ZAP|wget.*zap" >/dev/null 2>&1; then
    sz=$(stat -c%s /tmp/zap.tgz 2>/dev/null || echo 0)
    echo "poll $i size_bytes=$sz"
    sleep 15
  else
    echo "wget not running"
    break
  fi
done

# stop stuck install script if any
pkill -f "wsl-install-zap-standalone" 2>/dev/null || true
sleep 1

ls -lh /tmp/zap.tgz 2>/dev/null || echo "no /tmp/zap.tgz"

if [[ ! -f /tmp/zap.tgz ]]; then
  echo "re-download ZAP..."
  wget --timeout=180 --tries=3 -O /tmp/zap.tgz \
    "https://github.com/zaproxy/zaproxy/releases/download/v2.16.1/ZAP_2.16.1_Linux.tar.gz" \
    || wget --timeout=180 --tries=3 -O /tmp/zap.tgz \
    "https://github.com/zaproxy/zaproxy/releases/download/v2.15.0/ZAP_2.15.0_Linux.tar.gz"
fi

if ! tar -tzf /tmp/zap.tgz >/dev/null 2>&1; then
  echo "tarball invalid, re-download..."
  rm -f /tmp/zap.tgz
  wget --timeout=180 --tries=3 -O /tmp/zap.tgz \
    "https://github.com/zaproxy/zaproxy/releases/download/v2.16.1/ZAP_2.16.1_Linux.tar.gz"
fi

if ! tar -tzf /tmp/zap.tgz >/dev/null 2>&1; then
  echo "FATAL: cannot get valid ZAP archive"
  file /tmp/zap.tgz || true
  exit 1
fi

echo "==> extract"
mkdir -p /opt/zap
rm -rf /opt/zap/*
tar -xzf /tmp/zap.tgz -C /opt/zap --strip-components=1
ls -la /opt/zap | head -25
test -x /opt/zap/zap.sh
echo "ZAP_READY"

# quick version
java -version 2>&1 | head -2
# ZAP headless version may take a bit
/opt/zap/zap.sh -cmd -version 2>&1 | head -10 || true
