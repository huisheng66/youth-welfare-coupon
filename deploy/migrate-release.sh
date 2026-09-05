#!/usr/bin/env bash
# T08：发布期数据库迁移入口（在部署流程中单独执行，凭据不进入常驻 worker）。
#
# 用法：
#   MIGRATE_DATABASE_URL='mysql+pymysql://welfare_migrate:密码@127.0.0.1:3306/welfare' \
#     bash deploy/migrate-release.sh
#
# 或通过离散变量（优先级低于 MIGRATE_DATABASE_URL）：
#   MIGRATE_DB_HOST=127.0.0.1 MIGRATE_DB_PORT=3306 \
#   MIGRATE_DB_USER=welfare_migrate MIGRATE_DB_PASS='密码' MIGRATE_DB_NAME=welfare
#
# 权限要求见 deploy/setup-mysql.sql：welfare_migrate 仅需 welfare 库内 DDL/DML。
# 重复执行幂等（alembic upgrade head 已在 head 时为 no-op）。
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(cd "${SCRIPT_DIR}/../backend" && pwd)"

URL="${MIGRATE_DATABASE_URL:-}"
if [[ -z "${URL}" ]]; then
  if [[ -n "${MIGRATE_DB_USER:-}" && -n "${MIGRATE_DB_NAME:-}" ]]; then
    HOST="${MIGRATE_DB_HOST:-127.0.0.1}"
    PORT="${MIGRATE_DB_PORT:-3306}"
    # 密码做 URL 编码，覆盖含特殊字符的凭据
    ENC_PASS="$(python3 - "${MIGRATE_DB_PASS:-}" <<'PY'
import sys, urllib.parse
print(urllib.parse.quote_plus(sys.argv[1] or ""))
PY
)"
    URL="mysql+pymysql://${MIGRATE_DB_USER}:${ENC_PASS}@${HOST}:${PORT}/${MIGRATE_DB_NAME}"
  else
    echo "ERROR: 未提供 MIGRATE_DATABASE_URL 或 MIGRATE_DB_USER/MIGRATE_DB_NAME" >&2
    exit 2
  fi
fi

echo "==> 使用迁移账号执行 alembic upgrade head（不回显连接串）"
cd "${BACKEND_DIR}"
export DATABASE_URL="${URL}"

HEAD="$(python3 -c "from app.core.migrate import get_migration_head; print(get_migration_head())")"
echo "==> 目标迁移版本: ${HEAD}"

if python3 -c "
import sys
from sqlalchemy import create_engine, inspect, text
e = create_engine(sys.argv[1])
try:
    insp = inspect(e)
    if 'alembic_version' in insp.get_table_names():
        with e.connect() as c:
            cur = c.execute(text('SELECT version_num FROM alembic_version')).scalar_one()
        if cur == sys.argv[2]:
            print('ALREADY_AT_HEAD')
finally:
    e.dispose()
" "${URL}" "${HEAD}" | grep -q ALREADY_AT_HEAD; then
  echo "==> 数据库已在 ${HEAD}，无需迁移"
  exit 0
fi

python3 -c "from app.core.migrate import run_alembic_upgrade; run_alembic_upgrade()"

# 迁移后用同一连接校验 schema 满足运行要求，失败即发布失败（退出码非 0）
python3 -c "
import sys
from sqlalchemy import create_engine
from app.core.migrate import verify_schema_current
e = create_engine(sys.argv[1])
try:
    verify_schema_current(e)
finally:
    e.dispose()
" "${URL}"
echo "==> 迁移完成且 schema 校验通过：${HEAD}"
