#!/usr/bin/env bash
# Ubuntu 22.04/24.04 一键部署骨架（MySQL + API + 前端静态 + Nginx）
# 用法（root 或 sudo）:
#   cd /opt && git clone <repo> welfare && cd welfare
#   sudo bash deploy/install-ubuntu.sh
#
# 可选环境变量:
#   DOMAIN=192.168.x.x | coupon.example.com
#   DB_PASS='强密码'
#   SKIP_FRONTEND_BUILD=1   # 使用已有 frontend/dist，不装 Node / 不 npm build
#   BOOTSTRAP_ADMIN_USER=admin
#   BOOTSTRAP_ADMIN_PASS='强密码'   # 未设则自动生成并打印
#   PRESERVE_ENV=1          # 保留已有 backend/.env（升级时）
set -euo pipefail

APP_ROOT="${APP_ROOT:-/opt/welfare}"
DB_NAME="${DB_NAME:-welfare}"
# T09 三账号拆分：运行（DML）/ 迁移（DDL，仅发布期使用）/ 备份（只读+锁表）
APP_DB_USER="${APP_DB_USER:-welfare_app}"
MIGRATE_DB_USER="${MIGRATE_DB_USER:-welfare_migrate}"
BACKUP_DB_USER="${BACKUP_DB_USER:-welfare_backup}"
APP_DB_PASS="${APP_DB_PASS:-ChangeMe_App_$(openssl rand -hex 8)}"
MIGRATE_DB_PASS="${MIGRATE_DB_PASS:-ChangeMe_Mig_$(openssl rand -hex 8)}"
BACKUP_DB_PASS="${BACKUP_DB_PASS:-ChangeMe_Bak_$(openssl rand -hex 8)}"
DOMAIN="${DOMAIN:-_}"   # Nginx server_name，默认 _
SKIP_FRONTEND_BUILD="${SKIP_FRONTEND_BUILD:-0}"
PRESERVE_ENV="${PRESERVE_ENV:-0}"
BOOTSTRAP_ADMIN_USER="${BOOTSTRAP_ADMIN_USER:-admin}"
BOOTSTRAP_ADMIN_PASS="${BOOTSTRAP_ADMIN_PASS:-}"

# URL-encode DB password for DATABASE_URL（@ # % 等）
_urlencode() {
  python3 -c 'import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1], safe=""))' "$1"
}
APP_DB_PASS_ENC="$(_urlencode "${APP_DB_PASS}")"

echo "==> 安装系统依赖"
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
PKGS=(python3 python3-venv python3-pip nginx mysql-server git curl ca-certificates rsync)
if [[ "${SKIP_FRONTEND_BUILD}" != "1" ]]; then
  PKGS+=(nodejs npm)
fi
apt-get install -y "${PKGS[@]}"

if [[ "${SKIP_FRONTEND_BUILD}" != "1" ]]; then
  echo "==> Node: $(node -v 2>/dev/null || echo missing)  npm: $(npm -v 2>/dev/null || echo missing)"
else
  echo "==> SKIP_FRONTEND_BUILD=1：跳过 Node/npm 安装与前端构建"
fi

echo "==> 配置 MySQL 库与账号（T09 最小权限拆分，仅 localhost 来源）"
# 使用 sudo mysql（Ubuntu 默认 unix_socket root）
mysql -e "CREATE DATABASE IF NOT EXISTS \`${DB_NAME}\` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
create_minimal_user() {
  local user="$1" pass="$2"; shift 2
  mysql -e "CREATE USER IF NOT EXISTS '${user}'@'localhost' IDENTIFIED BY '${pass}';" || true
  mysql -e "ALTER USER '${user}'@'localhost' IDENTIFIED BY '${pass}';"
  mysql -e "GRANT $* ON \`${DB_NAME}\`.* TO '${user}'@'localhost';"
}
# 运行账号：仅 DML；不能建表/改表，避免运行进程获得 schema 控制权
create_minimal_user "${APP_DB_USER}" "${APP_DB_PASS}" "SELECT, INSERT, UPDATE, DELETE"
# 迁移账号：发布期执行 alembic upgrade head（deploy/migrate-release.sh）
create_minimal_user "${MIGRATE_DB_USER}" "${MIGRATE_DB_PASS}" \
  "SELECT, INSERT, UPDATE, DELETE, CREATE, DROP, ALTER, INDEX, REFERENCES, CREATE TEMPORARY TABLES"
# 备份账号：mysqldump 最小权限；SHOW_ROUTINE 为全局权限（例程定义导出）
create_minimal_user "${BACKUP_DB_USER}" "${BACKUP_DB_PASS}" "SELECT, LOCK TABLES, SHOW VIEW, EVENT, TRIGGER"
mysql -e "GRANT SHOW_ROUTINE ON *.* TO '${BACKUP_DB_USER}'@'localhost';"
# 历史遗留：若存在旧 ALL 权限的 welfare@% / welfare@localhost，提示人工清理
mysql -N -e "SELECT CONCAT('WARN: legacy account exists: ', User, '@', Host, '（确认无依赖后执行 DROP USER 清理）') FROM mysql.user WHERE User='welfare';" || true
mysql -e "FLUSH PRIVILEGES;"

echo "==> 应用目录: ${APP_ROOT}"
mkdir -p "${APP_ROOT}"
# 若脚本从仓库内执行，同步到 /opt/welfare
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
if [[ "${REPO_ROOT}" != "${APP_ROOT}" ]]; then
  RSYNC_EXCLUDES=(
    --exclude '.git'
    --exclude 'backend/.venv'
    --exclude 'frontend/node_modules'
    --exclude 'backend/data'
    --exclude 'reports'
    --exclude 'tools/sqlmap'
    --exclude 'tools/nuclei-templates'
    --exclude '.env'
    --exclude 'backend/.env'
  )
  # 默认排除 dist（会在服务器构建）；预构建模式保留 dist
  if [[ "${SKIP_FRONTEND_BUILD}" != "1" ]]; then
    RSYNC_EXCLUDES+=(--exclude 'frontend/dist')
  fi
  rsync -a --delete "${RSYNC_EXCLUDES[@]}" "${REPO_ROOT}/" "${APP_ROOT}/"
fi

echo "==> 后端 venv + 依赖"
cd "${APP_ROOT}/backend"
python3 -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
pip install -U pip
# 国内镜像加速（失败则回退官方源）
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple || \
  pip install -r requirements.txt

ENV_FILE="${APP_ROOT}/backend/.env"
if [[ "${PRESERVE_ENV}" == "1" && -f "${ENV_FILE}" ]]; then
  echo "==> PRESERVE_ENV=1：保留已有 ${ENV_FILE}"
else
  SECRET="$(openssl rand -hex 32)"
  FIELD_KEY="$(openssl rand -hex 32)"
  # 按 DOMAIN 写 CORS：IP 用 http；域名同时写 http/https
  if [[ "${DOMAIN}" == "_" || "${DOMAIN}" == "" ]]; then
    CORS_ORIGINS="http://localhost"
  elif [[ "${DOMAIN}" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    CORS_ORIGINS="http://${DOMAIN}"
  else
    CORS_ORIGINS="http://${DOMAIN},https://${DOMAIN}"
  fi
  cat > "${ENV_FILE}" <<EOF
APP_ENV=production
SECRET_KEY=${SECRET}
FIELD_ENCRYPTION_KEY=${FIELD_KEY}
DATABASE_URL=mysql+pymysql://${APP_DB_USER}:${APP_DB_PASS_ENC}@127.0.0.1:3306/${DB_NAME}?charset=utf8mb4
CORS_ORIGINS=${CORS_ORIGINS}
CORS_ALLOW_LAN=false
OPENAPI_ENABLED=false
SEED_DEMO_ACCOUNTS=false
RATE_LIMIT_BACKEND=file
RATE_LIMIT_FILE_PATH=./data/rate_limit.db
GLOBAL_IP_MAX_REQUESTS=300
GLOBAL_IP_WINDOW_SECONDS=60
ACCESS_TOKEN_EXPIRE_MINUTES=1440
LIVE_CODE_EXPIRE_SECONDS=30
# 前端已全面使用 HttpOnly Cookie，生产关闭 Bearer 头兼容，缩小令牌攻击面
AUTH_ALLOW_BEARER=false
# 读取路径过期券扫描节流（秒）；0 = 每次请求都扫描
COUPON_EXPIRE_SCAN_INTERVAL=30
# 生产环境禁止通过 HTTP 响应暴露验证码；请配置真实 SMTP 后再启用邮箱功能。
MAIL_CONSOLE=false
MAIL_SERVER=
MAIL_PORT=465
MAIL_SSL_TLS=true
MAIL_STARTTLS=false
MAIL_USERNAME=
MAIL_PASSWORD=
MAIL_FROM=
MAIL_FROM_NAME=青年福利券系统
EMAIL_CODE_EXPIRE_MINUTES=10
EOF
fi
mkdir -p "${APP_ROOT}/backend/data"
chown www-data:www-data "${ENV_FILE}"
chmod 640 "${ENV_FILE}"
chown -R www-data:www-data "${APP_ROOT}/backend/data"

echo "==> 发布迁移（迁移账号，独立于 worker 启动）"
cd "${APP_ROOT}/backend"
# shellcheck disable=SC1091
source .venv/bin/activate
# T08：DDL 由发布流程用迁移账号单独执行；运行账号无 DDL 权限也能启动
MIGRATE_DB_HOST="127.0.0.1" \
MIGRATE_DB_PORT="3306" \
MIGRATE_DB_USER="${MIGRATE_DB_USER}" \
MIGRATE_DB_PASS="${MIGRATE_DB_PASS}" \
MIGRATE_DB_NAME="${DB_NAME}" \
  bash "${APP_ROOT}/deploy/migrate-release.sh"

echo "==> 种子数据（运行账号，仅 DML）"
python - <<'PY'
from app.core.database import SessionLocal
from app.seed import seed_if_empty
db = SessionLocal()
try:
    seed_if_empty(db)
finally:
    db.close()
print("db ready")
PY

# 引导创建首个超管（仅当库中无 super_admin 时）
if [[ -z "${BOOTSTRAP_ADMIN_PASS}" ]]; then
  BOOTSTRAP_ADMIN_PASS="$(openssl rand -base64 18 | tr -d '/+=' | head -c 16)"
fi
export BOOTSTRAP_ADMIN_USER BOOTSTRAP_ADMIN_PASS
python - <<'PY'
import os
from app.core.database import SessionLocal
from app.core.security import hash_password
from app.models.entities import Account, Role

user = os.environ.get("BOOTSTRAP_ADMIN_USER", "admin").strip() or "admin"
password = os.environ["BOOTSTRAP_ADMIN_PASS"]
db = SessionLocal()
try:
    exists = db.query(Account).filter(Account.role == Role.super_admin).first()
    if exists:
        print(f"super_admin already exists: {exists.username} (skip bootstrap)")
    else:
        if db.query(Account).filter(Account.username == user).first():
            raise SystemExit(f"username {user!r} already exists with non-super role")
        db.add(
            Account(
                username=user,
                email=None,
                password_hash=hash_password(password),
                role=Role.super_admin,
                display_name="超级管理员",
            )
        )
        db.commit()
        print(f"bootstrap super_admin created: {user}")
finally:
    db.close()
PY
chown -R www-data:www-data "${APP_ROOT}/backend"

echo "==> 前端"
if [[ "${SKIP_FRONTEND_BUILD}" == "1" ]]; then
  if [[ ! -f "${APP_ROOT}/frontend/dist/index.html" ]]; then
    echo "ERROR: SKIP_FRONTEND_BUILD=1 但 ${APP_ROOT}/frontend/dist/index.html 不存在" >&2
    exit 1
  fi
  echo "使用预构建 dist/"
else
  cd "${APP_ROOT}/frontend"
  npm install
  npm run build
fi
chown -R www-data:www-data "${APP_ROOT}/frontend/dist"

echo "==> systemd 服务"
cp "${APP_ROOT}/deploy/welfare-api.service" /etc/systemd/system/welfare-api.service
# 若 APP_ROOT 不是 /opt/welfare，改 service 里路径
if [[ "${APP_ROOT}" != "/opt/welfare" ]]; then
  sed -i "s|/opt/welfare|${APP_ROOT}|g" /etc/systemd/system/welfare-api.service
fi
systemctl daemon-reload
systemctl enable --now welfare-api.service
systemctl restart welfare-api.service

echo "==> Nginx"
cp "${APP_ROOT}/deploy/nginx-welfare.conf" /etc/nginx/sites-available/welfare
if [[ "${DOMAIN}" == "_" || -z "${DOMAIN}" ]]; then
  sed -i "s|your-domain.com|_|g" /etc/nginx/sites-available/welfare
else
  sed -i "s|your-domain.com|${DOMAIN}|g" /etc/nginx/sites-available/welfare
fi
sed -i "s|/opt/welfare|${APP_ROOT}|g" /etc/nginx/sites-available/welfare
ln -sfn /etc/nginx/sites-available/welfare /etc/nginx/sites-enabled/welfare
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl enable --now nginx
systemctl reload nginx

# 放行 HTTP（有 ufw 时）
if command -v ufw >/dev/null 2>&1; then
  ufw allow OpenSSH >/dev/null 2>&1 || true
  ufw allow 'Nginx Full' >/dev/null 2>&1 || ufw allow 80/tcp >/dev/null 2>&1 || true
  ufw allow 443/tcp >/dev/null 2>&1 || true
  # 不自动 ufw --force enable，避免锁死远程会话；仅确保规则在启用后生效
fi

# 每日 03:17 自动备份数据库（备份账号 + .env 副本，字段加密钥必须随库备份）
BACKUP_DB_PASS_ENC="$(_urlencode "${BACKUP_DB_PASS}")"
cat > /etc/cron.d/welfare-backup <<CRON
# welfare MySQL 每日备份（保留 14 天），日志 /var/log/welfare-backup.log
SHELL=/bin/bash
17 3 * * * root BACKUP_DATABASE_URL='mysql+pymysql://${BACKUP_DB_USER}:${BACKUP_DB_PASS_ENC}@127.0.0.1:3306/${DB_NAME}?charset=utf8mb4' bash /opt/welfare/deploy/backup-mysql.sh >> /var/log/welfare-backup.log 2>&1
CRON
chmod 600 /etc/cron.d/welfare-backup
touch /var/log/welfare-backup.log && chmod 600 /var/log/welfare-backup.log
BACKUP_DATABASE_URL="mysql+pymysql://${BACKUP_DB_USER}:${BACKUP_DB_PASS_ENC}@127.0.0.1:3306/${DB_NAME}?charset=utf8mb4" \
  bash /opt/welfare/deploy/backup-mysql.sh || echo "首次备份失败（可手动重跑 /opt/welfare/deploy/backup-mysql.sh）"

sleep 2
HEALTH="$(curl -sS -m 5 http://127.0.0.1:19001/api/health || true)"
HTTP_CODE="$(curl -sS -o /dev/null -w '%{http_code}' -m 5 http://127.0.0.1/ || true)"

echo ""
echo "=============================================="
echo " 部署完成"
echo " 站点: http://${DOMAIN}/  （或本机 IP）"
echo " 本机 API 健康: http://127.0.0.1:19001/api/health -> ${HEALTH}"
echo " Nginx 首页 HTTP: ${HTTP_CODE}"
echo " MySQL: 库=${DB_NAME} 运行=${APP_DB_USER} 迁移=${MIGRATE_DB_USER} 备份=${BACKUP_DB_USER}（最小权限，仅 localhost）"
echo " 密码与密钥已写入 ${ENV_FILE} （请妥善保管 / 备份）"
echo " 生产 SEED_DEMO_ACCOUNTS=false（无演示弱口令）"
echo " 首个超管: ${BOOTSTRAP_ADMIN_USER} / ${BOOTSTRAP_ADMIN_PASS}"
echo "   *** 请立即登录后修改密码，并妥善保存此输出 ***"
echo " OpenAPI 已关闭；CORS 无局域网正则"
echo " 邮件当前 MAIL_CONSOLE=true（验证码打日志）；上线请配 SMTP"
echo " HTTPS: sudo certbot --nginx -d 你的域名"
echo " 备份: /opt/welfare/backups（cron 每日 03:17，保留 14 天）；恢复见 deploy/README.md"
echo " 服务: systemctl status welfare-api nginx"
echo "=============================================="
# 单独落盘一份可删的凭据提示（root only）
umask 077
cat > /root/welfare-bootstrap-once.txt <<CREDS
created_at=$(date -Iseconds)
site=http://${DOMAIN}/
admin_user=${BOOTSTRAP_ADMIN_USER}
admin_pass=${BOOTSTRAP_ADMIN_PASS}
env_file=${ENV_FILE}
mysql_app_user=${APP_DB_USER}
mysql_app_pass=${APP_DB_PASS}
mysql_migrate_user=${MIGRATE_DB_USER}
mysql_migrate_pass=${MIGRATE_DB_PASS}
mysql_backup_user=${BACKUP_DB_USER}
mysql_backup_pass=${BACKUP_DB_PASS}
CREDS
chmod 600 /root/welfare-bootstrap-once.txt
echo "凭据副本: /root/welfare-bootstrap-once.txt （用后请删除）"
