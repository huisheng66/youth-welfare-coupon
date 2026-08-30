#!/usr/bin/env bash
# 一次性补丁：已合入主线，保留作历史参考。详见 deploy/archive/README.md
# Deploy decimal volunteer-hours (cost_points / balance) + frontend
set -euo pipefail
HOST="${HOST:-198.44.182.107}"
PASS="${SSH_PASS:?（归档脚本）历史密码已移除并应轮换；如确需重跑请 export SSH_PASS}"
SRC="${SRC:-/mnt/d/卡系统}"
SSH_OPTS=(-o PreferredAuthentications=password -o PubkeyAuthentication=no -o StrictHostKeyChecking=accept-new -o ConnectTimeout=25)

if [[ ! -f "${SRC}/frontend/dist/index.html" ]]; then
  echo "missing frontend/dist; run npm run build first" >&2
  exit 1
fi

TMP=$(mktemp -d)
trap 'rm -rf "${TMP}"' EXIT

mkdir -p \
  "${TMP}/app/api" \
  "${TMP}/app/core" \
  "${TMP}/app/models" \
  "${TMP}/app/schemas" \
  "${TMP}/app/services"

cp "${SRC}/backend/app/api/points.py" "${TMP}/app/api/"
cp "${SRC}/backend/app/core/migrate.py" "${TMP}/app/core/"
cp "${SRC}/backend/app/models/entities.py" "${TMP}/app/models/"
cp "${SRC}/backend/app/schemas/coupon.py" "${TMP}/app/schemas/"
cp "${SRC}/backend/app/schemas/points.py" "${TMP}/app/schemas/"
cp "${SRC}/backend/app/services/points.py" "${TMP}/app/services/"

tar -C "${TMP}" -czf "${TMP}/backend-patch.tgz" app
tar -C "${SRC}/frontend/dist" -czf "${TMP}/dist.tgz" .

echo "==> upload"
sshpass -p "${PASS}" scp "${SSH_OPTS[@]}" \
  "${TMP}/backend-patch.tgz" "${TMP}/dist.tgz" "root@${HOST}:/tmp/"

echo "==> apply on server"
sshpass -p "${PASS}" ssh "${SSH_OPTS[@]}" "root@${HOST}" bash -s <<'REMOTE'
set -euo pipefail
mkdir -p /tmp/welfare-dec /opt/welfare/backend/app/{api,core,models,schemas,services}
tar -xzf /tmp/backend-patch.tgz -C /tmp/welfare-dec
install -m 644 /tmp/welfare-dec/app/api/points.py /opt/welfare/backend/app/api/points.py
install -m 644 /tmp/welfare-dec/app/core/migrate.py /opt/welfare/backend/app/core/migrate.py
install -m 644 /tmp/welfare-dec/app/models/entities.py /opt/welfare/backend/app/models/entities.py
install -m 644 /tmp/welfare-dec/app/schemas/coupon.py /opt/welfare/backend/app/schemas/coupon.py
install -m 644 /tmp/welfare-dec/app/schemas/points.py /opt/welfare/backend/app/schemas/points.py
install -m 644 /tmp/welfare-dec/app/services/points.py /opt/welfare/backend/app/services/points.py

rm -rf /opt/welfare/frontend/dist/*
mkdir -p /opt/welfare/frontend/dist
tar -xzf /tmp/dist.tgz -C /opt/welfare/frontend/dist
chown -R www-data:www-data /opt/welfare/frontend/dist

# Run schema migrate (INTEGER -> DECIMAL) then restart API
cd /opt/welfare/backend
.venv/bin/python - <<'PY'
from app.core.database import engine
from app.core.migrate import ensure_schema
ensure_schema(engine)
print("schema migrate ok")
# show column types
from sqlalchemy import inspect, text
insp = inspect(engine)
for table, col in [
    ("coupon_templates", "cost_points"),
    ("point_accounts", "balance"),
    ("point_ledgers", "change"),
    ("point_ledgers", "balance_after"),
]:
    for c in insp.get_columns(table):
        if c["name"] == col:
            print(f"  {table}.{col}: {c['type']}")
PY

systemctl restart welfare-api
sleep 2
systemctl is-active welfare-api
curl -sS -m 8 http://127.0.0.1:19001/api/health
echo

# unit-level schema accept float
.venv/bin/python - <<'PY'
from decimal import Decimal
from app.schemas.coupon import TemplateCreate
from app.schemas.points import GrantPointsIn
m = TemplateCreate(name="t", merchant_id="00000000-0000-0000-0000-000000000001", cost_points=0.5)
assert m.cost_points == Decimal("0.50"), m.cost_points
g = GrantPointsIn(user_id="u", amount=1.25)
assert g.amount == Decimal("1.25"), g.amount
print("schema decimal ok", m.cost_points, g.amount)
PY

rm -f /tmp/backend-patch.tgz /tmp/dist.tgz
rm -rf /tmp/welfare-dec
REMOTE

echo "==> public checks"
curl -sS -m 15 "https://youth.huishengbook.us.ci/api/health" || true
echo
curl -sS -m 15 -o /dev/null -w "index:%{http_code}\n" "https://youth.huishengbook.us.ci/" || true
echo deploy-decimal-points done
