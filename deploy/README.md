# Ubuntu + MySQL 部署说明

本系统开发机可用 **SQLite**；上线 Ubuntu 推荐 **MySQL 8 + Nginx + systemd**。

## 架构

```
浏览器 → Nginx(:80/:443)
           ├─ /          → frontend/dist（Vue 静态）
           └─ /api/*     → uvicorn 127.0.0.1:19001
                              └─ MySQL welfare 库
```

## 一键脚本（推荐）

在 Ubuntu 22.04 / 24.04：

```bash
# 把代码放到 /opt/welfare（或 git clone）
sudo bash deploy/install-ubuntu.sh
# 可选环境变量：
# DOMAIN=coupon.example.com DB_PASS='强密码' sudo -E bash deploy/install-ubuntu.sh
```

脚本会：安装 MySQL/Nginx/Python/Node、建库、写 `.env`、`pip install`、`npm run build`、启用 `welfare-api` 服务。

## 手动步骤摘要

### 1. MySQL

```bash
sudo apt install -y mysql-server
sudo mysql < deploy/setup-mysql.sql   # 先改脚本里的密码
```

`backend/.env`（生产建议）：

```env
APP_ENV=production
DATABASE_URL=mysql+pymysql://welfare:你的密码@127.0.0.1:3306/welfare?charset=utf8mb4
SECRET_KEY=请换成 openssl rand -hex 32
FIELD_ENCRYPTION_KEY=请换成另一串 openssl rand -hex 32
CORS_ORIGINS=https://你的域名
CORS_ALLOW_LAN=false
OPENAPI_ENABLED=false
SEED_DEMO_ACCOUNTS=false
RATE_LIMIT_BACKEND=file
# 可选 Redis：RATE_LIMIT_BACKEND=redis 与 REDIS_URL=redis://127.0.0.1:6379/0
```

密码若含 `@ # %` 等，需做 URL 编码后再写入连接串。

**注意**：`APP_ENV=production` 时若仍使用默认 `SECRET_KEY`，进程会**拒绝启动**。  
`SEED_DEMO_ACCOUNTS=false` 时不会创建 `admin/admin123` 等演示弱口令。

### 2. 后端

```bash
cd /opt/welfare/backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
# 首次启动自动建表 + 演示数据
uvicorn app.main:app --host 127.0.0.1 --port 19001
```

systemd 单元见 `welfare-api.service`。

### 3. 前端

```bash
cd /opt/welfare/frontend
npm install
npm run build
# 产物在 dist/，由 Nginx root 指向
```

前端请求 `baseURL: '/api'`，与 Nginx 反代一致，**无需改代码**。

### 4. Nginx

```bash
sudo cp deploy/nginx-welfare.conf /etc/nginx/sites-available/welfare
# 改 server_name 与 root 路径
sudo ln -s /etc/nginx/sites-available/welfare /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

HTTPS：

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d 你的域名
```

## 常用运维

```bash
sudo systemctl status welfare-api
sudo journalctl -u welfare-api -f
sudo systemctl restart welfare-api
curl -s http://127.0.0.1:19001/api/health
```

## 从 SQLite 迁到 MySQL

1. 新环境用 MySQL 空库启动，自动建表  
2. 演示数据会 seed；正式数据需自行导出/导入或业务重录  
3. 不提供自动 SQLite→MySQL 迁移脚本（表结构简单，建议干净部署）

## 安全清单

- [ ] `APP_ENV=production`，强随机 `SECRET_KEY` + 独立 `FIELD_ENCRYPTION_KEY`（备份 `.env`）  
- [ ] `SEED_DEMO_ACCOUNTS=false`；若曾开演示 seed，立刻改掉所有弱口令  
- [ ] `OPENAPI_ENABLED=false`；Nginx 对 `/docs` `/openapi.json` 返回 404  
- [ ] `CORS_ALLOW_LAN=false`，`CORS_ORIGINS` 仅正式 https 域名  
- [ ] 配置真实 SMTP，`MAIL_CONSOLE=false`  
- [ ] 登录限流：单机用 `RATE_LIMIT_BACKEND=file`，多机用 Redis  
- [ ] 防火墙只开放 80/443，MySQL 不对外  
- [ ] 定期备份：`mysqldump welfare > backup.sql`  
- [ ] JWT 现存在前端 `localStorage`：须防 XSS；勿对用户字段使用 `v-html`
