#!/usr/bin/env bash
# Ubuntu 22.04/24.04 一键部署骨架（MySQL + API + 前端静态 + Nginx）
# 用法（root 或 sudo）:
#   cd /opt && git clone <repo> welfare && cd welfare
#   sudo bash deploy/install-ubuntu.sh
set -euo pipefail

APP_ROOT="${APP_ROOT:-/opt/welfare}"
DB_NAME="${DB_NAME:-welfare}"
DB_USER="${DB_USER:-welfare}"
DB_PASS="${DB_PASS:-ChangeMe_$(openssl rand -hex 8)}"
DOMAIN="${DOMAIN:-_}"   # Nginx server_name，默认 _

echo "==> 安装系统依赖"
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y \
  python3 python3-venv python3-pip \
  nginx mysql-server \
  git curl ca-certificates rsync \
  nodejs npm

# Node 可能偏旧；若 npm 版本过低可自行装 Node 20 LTS
echo "==> Node: $(node -v 2>/dev/null || echo missing)  npm: $(npm -v 2>/dev/null || echo missing)"

echo "==> 配置 MySQL 库与用户"
# 使用 sudo mysql（Ubuntu 默认 unix_socket root）
mysql -e "CREATE DATABASE IF NOT EXISTS \`${DB_NAME}\` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
mysql -e "CREATE USER IF NOT EXISTS '${DB_USER}'@'localhost' IDENTIFIED BY '${DB_PASS}';" || true
mysql -e "ALTER USER '${DB_USER}'@'localhost' IDENTIFIED BY '${DB_PASS}';" || true
mysql -e "GRANT ALL PRIVILEGES ON \`${DB_NAME}\`.* TO '${DB_USER}'@'localhost'; FLUSH PRIVILEGES;"

echo "==> 应用目录: ${APP_ROOT}"
mkdir -p "${APP_ROOT}"
# 若脚本从仓库内执行，同步到 /opt/welfare
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
if [[ "${REPO_ROOT}" != "${APP_ROOT}" ]]; then
  rsync -a --delete \
    --exclude '.git' --exclude 'backend/.venv' --exclude 'frontend/node_modules' \
    --exclude 'backend/data' --exclude 'frontend/dist' \
    "${REPO_ROOT}/" "${APP_ROOT}/"
fi

echo "==> 后端 venv + 依赖"
cd "${APP_ROOT}/backend"
python3 -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
pip install -U pip
pip install -r requirements.txt

SECRET="$(openssl rand -hex 32)"
cat > "${APP_ROOT}/backend/.env" <<EOF
SECRET_KEY=${SECRET}
DATABASE_URL=mysql+pymysql://${DB_USER}:${DB_PASS}@127.0.0.1:3306/${DB_NAME}?charset=utf8mb4
CORS_ORIGINS=http://${DOMAIN},https://${DOMAIN},http://127.0.0.1,https://127.0.0.1
ACCESS_TOKEN_EXPIRE_MINUTES=1440
LIVE_CODE_EXPIRE_SECONDS=30
MAIL_CONSOLE=true
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
chown www-data:www-data "${APP_ROOT}/backend/.env"
chmod 640 "${APP_ROOT}/backend/.env"

echo "==> 建表 + 种子（首次启动）"
cd "${APP_ROOT}/backend"
# shellcheck disable=SC1091
source .venv/bin/activate
python - <<'PY'
from app.core.database import Base, engine, SessionLocal
from app.core.migrate import ensure_schema
from app.seed import seed_if_empty
import app.models  # noqa: F401
Base.metadata.create_all(bind=engine)
ensure_schema(engine)
db = SessionLocal()
try:
    seed_if_empty(db)
finally:
    db.close()
print("db ready")
PY
chown -R www-data:www-data "${APP_ROOT}/backend"

echo "==> 构建前端"
cd "${APP_ROOT}/frontend"
npm install
npm run build
chown -R www-data:www-data "${APP_ROOT}/frontend/dist"

echo "==> systemd 服务"
cp "${APP_ROOT}/deploy/welfare-api.service" /etc/systemd/system/welfare-api.service
# 若 APP_ROOT 不是 /opt/welfare，改 service 里路径
if [[ "${APP_ROOT}" != "/opt/welfare" ]]; then
  sed -i "s|/opt/welfare|${APP_ROOT}|g" /etc/systemd/system/welfare-api.service
fi
systemctl daemon-reload
systemctl enable --now welfare-api.service

echo "==> Nginx"
cp "${APP_ROOT}/deploy/nginx-welfare.conf" /etc/nginx/sites-available/welfare
sed -i "s|your-domain.com|${DOMAIN}|g" /etc/nginx/sites-available/welfare
sed -i "s|/opt/welfare|${APP_ROOT}|g" /etc/nginx/sites-available/welfare
ln -sfn /etc/nginx/sites-available/welfare /etc/nginx/sites-enabled/welfare
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl reload nginx

echo ""
echo "=============================================="
echo " 部署完成"
echo " 站点: http://服务器IP/  （或域名 ${DOMAIN}）"
echo " API 健康: http://127.0.0.1:19001/api/health"
echo " MySQL: 库=${DB_NAME} 用户=${DB_USER}"
echo " 密码已写入 ${APP_ROOT}/backend/.env （请妥善保管）"
echo " 演示账号见 README（admin / admin123 等）"
echo " 生产请改 SECRET_KEY、SMTP，并关闭演示弱密码"
echo " HTTPS: sudo certbot --nginx -d 你的域名"
echo "=============================================="
