#!/usr/bin/env bash
# welfare MySQL 每日备份：mysqldump → gzip → 按天保留，并随附 .env（含字段加密钥）副本。
# 建议由 cron 调用（install-ubuntu.sh 已安装 /etc/cron.d/welfare-backup）。
# 手动执行：bash /opt/welfare/deploy/backup-mysql.sh
# 恢复方法见 deploy/README.md「备份与恢复」。
set -euo pipefail

APP_ROOT="${APP_ROOT:-/opt/welfare}"
BACKUP_DIR="${BACKUP_DIR:-${APP_ROOT}/backups}"
RETAIN_DAYS="${RETAIN_DAYS:-14}"
ENV_FILE="${ENV_FILE:-${APP_ROOT}/backend/.env}"

mkdir -p "${BACKUP_DIR}"
chmod 700 "${BACKUP_DIR}"

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "ERROR: 未找到 ${ENV_FILE}，无法读取数据库连接" >&2
  exit 1
fi

# 从 .env 的 DATABASE_URL 解析 mysql+pymysql://user:pass@host:port/db
read -r DB_USER DB_PASS DB_HOST DB_PORT DB_NAME <<EOF
$(python3 - "${ENV_FILE}" <<'PY'
import re
import sys
import urllib.parse

url = ""
for line in open(sys.argv[1], encoding="utf-8"):
    line = line.strip()
    if line.startswith("DATABASE_URL="):
        url = line.split("=", 1)[1].strip().strip('"').strip("'")
        break
m = re.match(r"mysql\+pymysql://([^:/@]+):([^@]*)@([^:/]+):(\d+)/([^?]+)", url)
if not m:
    print("", "", "", "", "")
    sys.exit(0)
user, pwd, host, port, name = m.groups()
print(user, urllib.parse.unquote(pwd), host, port, name)
PY
)
EOF

if [[ -z "${DB_NAME}" || -z "${DB_USER}" ]]; then
  echo "ERROR: DATABASE_URL 不是 MySQL 连接串，无法备份" >&2
  exit 1
fi

STAMP="$(date +%Y%m%d-%H%M%S)"
OUT_SQL="${BACKUP_DIR}/${DB_NAME}-${STAMP}.sql.gz"

echo "==> mysqldump ${DB_NAME} @ ${DB_HOST}:${DB_PORT} → ${OUT_SQL}"
mysqldump \
  -h "${DB_HOST}" -P "${DB_PORT}" -u "${DB_USER}" \
  -p"${DB_PASS}" \
  --single-transaction --quick --routines --triggers --events \
  --default-character-set=utf8mb4 \
  "${DB_NAME}" | gzip -9 > "${OUT_SQL}"

# 字段加密钥/JWT 密钥在 .env 里，没有它备份无法解密银行卡字段；随库一起备份并限权
OUT_ENV="${BACKUP_DIR}/env-${STAMP}.txt"
install -m 600 "${ENV_FILE}" "${OUT_ENV}"

SIZE_SQL="$(du -h "${OUT_SQL}" | cut -f1)"
echo "==> done: ${OUT_SQL} (${SIZE_SQL}) + ${OUT_ENV}"

# 清理超过保留期的旧备份
find "${BACKUP_DIR}" -name "${DB_NAME}-*.sql.gz" -mtime "+${RETAIN_DAYS}" -delete
find "${BACKUP_DIR}" -name "env-*.txt" -mtime "+${RETAIN_DAYS}" -delete
REMAINING="$(find "${BACKUP_DIR}" -name "${DB_NAME}-*.sql.gz" | wc -l)"
echo "==> 保留 ${REMAINING} 份库备份（>${RETAIN_DAYS} 天自动清理）"
