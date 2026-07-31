#!/usr/bin/env bash
# 一次性补丁：已合入主线，保留作历史参考。详见 deploy/archive/README.md
# Deploy IP/rate-limit fix + Cloudflare origin protect
set -euo pipefail
HOST="${HOST:-198.44.182.107}"
PASS="${SSH_PASS:-1LMntnpAd0}"
SRC="${SRC:-/mnt/d/卡系统}"

TMP=$(mktemp -d)
trap 'rm -rf "${TMP}"' EXIT

# backend modules
mkdir -p "${TMP}/app/core" "${TMP}/app/api" "${TMP}/deploy"
cp "${SRC}/backend/app/core/client_ip.py" "${TMP}/app/core/"
cp "${SRC}/backend/app/main.py" "${TMP}/app/"
cp "${SRC}/backend/app/api/auth.py" "${TMP}/app/api/"
cp "${SRC}/deploy/cloudflare-origin-protect.sh" "${TMP}/deploy/"
tar -C "${TMP}" -czf "${TMP}/patch.tgz" app deploy

sshpass -p "${PASS}" scp -o StrictHostKeyChecking=no "${TMP}/patch.tgz" "root@${HOST}:/tmp/welfare-xff.tgz"

sshpass -p "${PASS}" ssh -o StrictHostKeyChecking=no "root@${HOST}" bash -s <<'REMOTE'
set -euo pipefail
cd /tmp
rm -rf welfare-xff-unpack
mkdir welfare-xff-unpack
tar -xzf /tmp/welfare-xff.tgz -C welfare-xff-unpack
mkdir -p /opt/welfare/deploy /opt/welfare/backend/app/core
install -m 644 welfare-xff-unpack/app/core/client_ip.py /opt/welfare/backend/app/core/client_ip.py
install -m 644 welfare-xff-unpack/app/main.py /opt/welfare/backend/app/main.py
install -m 644 welfare-xff-unpack/app/api/auth.py /opt/welfare/backend/app/api/auth.py
install -m 755 welfare-xff-unpack/deploy/cloudflare-origin-protect.sh /opt/welfare/deploy/cloudflare-origin-protect.sh

# clear rate limit state so tests are clean
rm -f /opt/welfare/backend/data/rate_limit.db /opt/welfare/backend/data/rate_limit_ip.db || true

systemctl restart welfare-api
sleep 2
systemctl is-active welfare-api
curl -sS -m 8 http://127.0.0.1:19001/api/health
echo

echo "==> Cloudflare origin protect (nginx + ufw)"
bash /opt/welfare/deploy/cloudflare-origin-protect.sh

echo "==> health via domain"
curl -sS -m 15 https://youth.huishengbook.us.ci/api/health || true
echo
REMOTE

echo deploy-xff done
