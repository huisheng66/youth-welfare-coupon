#!/usr/bin/env bash
# welfare MySQL 每日备份：mysqldump → gzip → 校验 → 原子发布 → 按天保留，
# 并随附 .env（含字段加密钥）副本。建议由 cron 调用（install-ubuntu.sh 已安装
# /etc/cron.d/welfare-backup，使用 welfare_backup 备份账号）。
# 手动执行：bash /opt/welfare/deploy/backup-mysql.sh
# 恢复方法见 deploy/README.md 与 deploy/restore-mysql.sh。
#
# T10 加固：
# - 连接串结构化解析：支持 mysql+pymysql:// 无显式端口、URL 编码密码等；
# - 先写临时文件，gzip 完整性 + 内容校验通过后原子改名发布；
# - 校验失败不发布、不触发保留期清理，退出码非 0 让 cron 日志可见。
set -euo pipefail

APP_ROOT="${APP_ROOT:-/opt/welfare}"
BACKUP_DIR="${BACKUP_DIR:-${APP_ROOT}/backups}"
RETAIN_DAYS="${RETAIN_DAYS:-14}"
ENV_FILE="${ENV_FILE:-${APP_ROOT}/backend/.env}"

mkdir -p "${BACKUP_DIR}"
chmod 700 "${BACKUP_DIR}"

# 连接来源优先级：BACKUP_DATABASE_URL（备份账号，推荐）> ENV_FILE 的 DATABASE_URL
# 每行一个字段读取，密码为空等缺失字段不会错位
mapfile -t _DBPARTS < <(ENV_FILE="${ENV_FILE}" BACKUP_DATABASE_URL="${BACKUP_DATABASE_URL:-}" python3 - <<'PY' | tr -d "\r"
import os
import urllib.parse

url = os.environ.get("BACKUP_DATABASE_URL", "")
if not url:
    env_file = os.environ.get("ENV_FILE", "")
    if env_file:
        for line in open(env_file, encoding="utf-8"):
            line = line.strip()
            if line.startswith("DATABASE_URL="):
                url = line.split("=", 1)[1].strip().strip('"').strip("'")
                break
if not url:
    raise SystemExit(0)
u = urllib.parse.urlparse(url)
if u.scheme.split("+")[0] not in ("mysql", "mariadb"):
    raise SystemExit(0)
for v in (
    urllib.parse.unquote(u.username or ""),
    urllib.parse.unquote(u.password or ""),
    u.hostname or "",
    str(u.port or 3306),
    u.path.strip("/").split("?")[0],
):
    print(v)
PY
)
DB_USER="${_DBPARTS[0]:-}"
DB_PASS="${_DBPARTS[1]:-}"
DB_HOST="${_DBPARTS[2]:-}"
DB_PORT="${_DBPARTS[3]:-}"
DB_NAME="${_DBPARTS[4]:-}"

if [[ -z "${DB_NAME}" || -z "${DB_USER}" ]]; then
  echo "ERROR: 未提供 BACKUP_DATABASE_URL 且 ENV_FILE 中无有效 MySQL 连接串" >&2
  exit 1
fi

STAMP="$(date +%Y%m%d-%H%M%S)"
OUT_SQL="${BACKUP_DIR}/${DB_NAME}-${STAMP}.sql.gz"
TMP_SQL="$(mktemp "${BACKUP_DIR}/.tmp-${DB_NAME}-XXXXXX.sql.gz")"
trap 'rm -f "${TMP_SQL}"' EXIT

echo "==> mysqldump ${DB_NAME} @ ${DB_HOST}:${DB_PORT} → ${OUT_SQL}"
# --single-transaction 获得一致性快照且不锁业务表；--no-tablespaces 让备份账号
# 无需 PROCESS 全局权限；密码经环境变量传递，不进命令行
if ! MYSQL_PWD="${DB_PASS}" mysqldump \
  -h "${DB_HOST}" -P "${DB_PORT}" -u "${DB_USER}" \
  --single-transaction --quick --routines --triggers --events --no-tablespaces \
  --default-character-set=utf8mb4 \
  "${DB_NAME}" | gzip -9 > "${TMP_SQL}"; then
  echo "ERROR: mysqldump 失败，未发布备份（保留期清理本次不执行）" >&2
  exit 1
fi

# 发布前校验：gzip 完整性 + 转储应包含建表语句（空库/截断文件判定为失败）
if ! gzip -t "${TMP_SQL}"; then
  echo "ERROR: 备份 gzip 校验失败，未发布备份" >&2
  exit 1
fi
TABLE_COUNT="$(gzip -cd "${TMP_SQL}" | grep -c "^CREATE TABLE" || true)"
if [[ "${TABLE_COUNT}" -lt 1 ]]; then
  echo "ERROR: 备份内容无 CREATE TABLE，疑似空转储，未发布备份" >&2
  exit 1
fi

mv "${TMP_SQL}" "${OUT_SQL}"
chmod 600 "${OUT_SQL}"
trap - EXIT

# 字段加密钥/JWT 密钥在 .env 里，没有它备份无法解密银行卡字段；随库一起备份并限权
OUT_ENV="${BACKUP_DIR}/env-${STAMP}.txt"
if [[ -f "${ENV_FILE}" ]]; then
  install -m 600 "${ENV_FILE}" "${OUT_ENV}"
else
  echo "WARN: 未找到 ${ENV_FILE}，本次未随附密钥副本" >&2
fi

SIZE_SQL="$(du -h "${OUT_SQL}" | cut -f1)"
echo "==> done: ${OUT_SQL} (${SIZE_SQL}, ${TABLE_COUNT} tables) + ${OUT_ENV:-no-env-copy}"

# 清理超过保留期的旧备份（仅在本次备份成功发布后执行）
find "${BACKUP_DIR}" -name "${DB_NAME}-*.sql.gz" -mtime "+${RETAIN_DAYS}" -delete
find "${BACKUP_DIR}" -name "env-*.txt" -mtime "+${RETAIN_DAYS}" -delete
REMAINING="$(find "${BACKUP_DIR}" -name "${DB_NAME}-*.sql.gz" | wc -l)"
echo "==> 保留 ${REMAINING} 份库备份（>${RETAIN_DAYS} 天自动清理）"
