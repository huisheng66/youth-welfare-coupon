#!/usr/bin/env bash
# welfare MySQL 恢复与校验（T10 演练/应急使用）。
#
# 用法：
#   bash deploy/restore-mysql.sh <backup.sql.gz> <目标库名> [MySQL连接URL]
#
# 目标库应为隔离环境的空库（演练库/重建后的库）；脚本不自动删库不覆盖已有表，
# 目标库存在同名表时 mysql 会直接报错退出，避免静默混入旧数据。
#
# 恢复后校验：业务表数量、关键行数、时长余额=账本变更之和、券状态分布；
# 任何对账异常退出码非 0。
set -euo pipefail

DUMP_FILE="${1:?用法: restore-mysql.sh <backup.sql.gz> <目标库> [URL]}"
TARGET_DB="${2:?缺少目标库名}"
DATABASE_URL="${3:-${BACKUP_DATABASE_URL:-}}"

if [[ ! -f "${DUMP_FILE}" ]]; then
  echo "ERROR: 备份文件不存在: ${DUMP_FILE}" >&2
  exit 1
fi
if [[ -z "${DATABASE_URL}" ]]; then
  echo "ERROR: 请通过第 3 参数或 BACKUP_DATABASE_URL 提供连接 URL" >&2
  exit 2
fi

# 每行一个字段读取，密码为空等缺失字段不会错位
mapfile -t _DBPARTS < <(python3 - "${DATABASE_URL}" "${TARGET_DB}" <<'PY' | tr -d "\r"
import sys, urllib.parse
u = urllib.parse.urlparse(sys.argv[1])
for v in (
    urllib.parse.unquote(u.username or ""),
    urllib.parse.unquote(u.password or ""),
    u.hostname or "",
    str(u.port or 3306),
    sys.argv[2],
):
    print(v)
PY
)
DB_USER="${_DBPARTS[0]:-}"
DB_PASS="${_DBPARTS[1]:-}"
DB_HOST="${_DBPARTS[2]:-}"
DB_PORT="${_DBPARTS[3]:-}"
DB_NAME="${_DBPARTS[4]:-}"

mysql_cmd() {
  MYSQL_PWD="${DB_PASS}" mysql -h "${DB_HOST}" -P "${DB_PORT}" -u "${DB_USER}" "${DB_NAME}"
}

echo "==> 恢复 ${DUMP_FILE} → ${DB_NAME}@${DB_HOST}:${DB_PORT}"
gunzip -cd "${DUMP_FILE}" | mysql_cmd

echo "==> 恢复完成，开始校验"
mysql_cmd <<'SQL'
SELECT 'business_tables' AS check_item, COUNT(*) AS value
  FROM information_schema.tables
 WHERE table_schema = DATABASE()
   AND table_name IN ('accounts','merchants','user_profiles','user_verifications',
                      'coupon_templates','coupon_instances','redemption_logs','audit_logs',
                      'point_accounts','point_ledgers','email_codes')
UNION ALL
SELECT 'accounts_total', COUNT(*) FROM accounts
UNION ALL
SELECT 'coupon_instances_total', COUNT(*) FROM coupon_instances
UNION ALL
SELECT 'coupon_used', COUNT(*) FROM coupon_instances WHERE status='used'
UNION ALL
SELECT 'coupon_unused', COUNT(*) FROM coupon_instances WHERE status='unused'
UNION ALL
SELECT 'coupon_void', COUNT(*) FROM coupon_instances WHERE status='void'
UNION ALL
SELECT 'coupon_expired', COUNT(*) FROM coupon_instances WHERE status='expired'
UNION ALL
SELECT 'redemption_success', COUNT(*) FROM redemption_logs WHERE result='success'
UNION ALL
SELECT 'ledger_rows', COUNT(*) FROM point_ledgers;
SQL

MISMATCH="$(mysql_cmd -N --batch <<'SQL'
SELECT a.user_id
  FROM point_accounts a
  LEFT JOIN point_ledgers l ON l.user_id = a.user_id
 GROUP BY a.user_id, a.balance
HAVING a.balance <> IFNULL(SUM(l.change), 0);
SQL
)"

if [[ -z "${MISMATCH}" ]]; then
  echo "==> PASS: 余额与账本一致，恢复校验通过"
else
  echo "==> FAIL: 以下账户余额与账本之和不一致:" >&2
  echo "${MISMATCH}" >&2
  exit 1
fi
