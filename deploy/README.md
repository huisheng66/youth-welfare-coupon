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
# DOMAIN=192.168.x.x SKIP_FRONTEND_BUILD=1 BOOTSTRAP_ADMIN_PASS='强密码' sudo -E bash deploy/install-ubuntu.sh
```

脚本会：安装 MySQL/Nginx/Python、建库、写 `.env`、`pip install`、构建前端（或使用预构建 `dist`）、启用 `welfare-api`、引导创建首个超管。

| 变量 | 说明 |
|------|------|
| `DOMAIN` | Nginx `server_name` 与 CORS（IP 仅写 `http://IP`） |
| `DB_PASS` | MySQL 业务账号密码（默认随机） |
| `SKIP_FRONTEND_BUILD=1` | 使用包内 `frontend/dist`，不装 Node |
| `BOOTSTRAP_ADMIN_USER/PASS` | 首个超管（库中已有 super_admin 则跳过） |
| `PRESERVE_ENV=1` | 升级时保留已有 `backend/.env` |

从 Windows/WSL 打包上传：`deploy/pack-and-upload.sh` → 服务器 `sudo -E bash run-on-server.sh`。

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

## 脚本分类

`deploy/` 下脚本分两类：**长期运维脚本**（保留原位，新人优先熟悉这些）与**一次性补丁脚本**（已归档至 `deploy/archive/`，仅作历史参考，**不要在新环境执行**）。

### 长期运维脚本（原位）

| 脚本 | 用途 | 备注 |
|------|------|------|
| `install-ubuntu.sh` | Ubuntu 一键部署骨架（MySQL + API + 前端 + Nginx） | 首选入口；支持 `DOMAIN`/`DB_PASS`/`SKIP_FRONTEND_BUILD` 等 |
| `remote-deploy.sh` | 服务器端解压 + 调用 `install-ubuntu.sh` | 由 `run-on-server.sh` / `run-on-public.sh` 触发 |
| `run-on-server.sh` | 内网机部署封装 | 配合 `pack-and-upload.sh` |
| `run-on-public.sh` | 公网机 root 部署封装 | 配合 `pack-and-upload-public.sh` |
| `pack-and-upload.sh` | 开发机→内网服务器打包上传 | WSL 调用 |
| `pack-and-upload-public.sh` | 开发机→公网服务器打包上传 | WSL 调用 |
| `sync-frontend-prod.sh` | 仅同步 `frontend/dist` 到生产 | 不动 `.env`/数据库 |
| `wait-deploy.sh` | 轮询等待部署完成 | 辅助脚本 |
| `remote-status.sh` | 远程服务/端口/`.env`/健康检查 | 日常巡检 |
| `remote-probe-pub.sh` | 公网机 nginx/`/opt`/mysql 诊断 | 排障 |
| `verify-prod.sh` | 生产接口/页面探测 | 部署后验收 |
| `verify-theme.sh` | 验证品牌色是否生效 | 主题发布后用 |
| `ssh-probe.sh` | SSH 密钥/账号连通性探测 | 排障 |
| `_server_sec_check.sh` | 主机安全巡检（`.env` 权限/端口/ufw/fail2ban） | 安全审计，长期 |
| `harden-nginx-prod.sh` | Nginx 加固（敏感路径 404、HSTS、隐藏文件拦截） | 上线必跑 |
| `cloudflare-origin-protect.sh` | Cloudflare 源站防护（real_ip + UFW 仅放行 CF） | 经 CF 接入时用 |
| `enable-nginx-request-time.sh` | 启用带 `request_time` 的 access log | 性能排障 |
| `fix-nginx-welfare.sh` | 修复/重写 welfare 站点 nginx 配置 | 配置变更时用 |
| `bind-youth-domain.sh` | 绑定 `youth.huishengbook.us.ci` 到站点 | 域名切换时用 |
| `config-smtp-prod.sh` | 写生产 SMTP 配置到 `.env` | 邮件接入时用 |
| `deploy-imap.sh` | 写 IMAP 配置并重启服务 | 收信接入时用 |
| `nginx-welfare.conf` | Nginx 站点配置模板 | 被 `install-ubuntu.sh` 引用 |
| `setup-mysql.sql` | MySQL 建库脚本 | 被 `install-ubuntu.sh` 引用 |
| `welfare-api.service` | systemd 单元 | 被 `install-ubuntu.sh` 引用 |

### 一次性补丁脚本（`deploy/archive/`）

以下脚本均为历史一次性补丁/诊断，对应修复**已合入主线代码**，保留仅供追溯。新环境**不要执行**——直接走 `install-ubuntu.sh` 即可。

| 脚本 | 历史用途 |
|------|------|
| `_deploy_xff_fix.sh` | 部署 XFF/IP 伪造修复 + Cloudflare 源站防护补丁 |
| `_verify_xff_fix.sh` | 验证 XFF 修复是否生效 |
| `_deploy_decimal_points.sh` | 部署积分时长 INTEGER→DECIMAL 升级 |
| `_deploy_issue_admin_fix.sh` | 部署 `issue-admins` 接口 422 修复 |
| `_debug_issue_admin.sh` | 调试 `issue-admins` 422 请求样本 |
| `_deploy_timeout_fix.sh` | 部署前端 + Nginx 计时日志修复（计时逻辑已迁至 `enable-nginx-request-time.sh`） |
| `_deploy_youth_brand.sh` | 部署 youth 品牌重塑（前端 + 后端模块） |
| `_cors_https_only.sh` | 把生产 `CORS_ORIGINS` 改为仅 HTTPS |
| `_check_nginx.sh` | 一次性 nginx 配置/`.env` 探测 |
| `_check_pwd_logs.sh` | 排查改密 499 日志（特定时间段） |
| `_check_scan_claims.sh` | 扫描 claim 一次性安全核查 |
| `_pentest_host.sh` | 一次性渗透测试主机配置采集 |

> 归档脚本头部均已加 `# 一次性补丁：已合入主线，保留作历史参考` 标记。如需清理，可整目录删除而不影响部署。

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
- [ ] JWT 已迁至 HttpOnly Cookie；过渡期仍允许 `Authorization: Bearer`，上线 1–2 版本后关闭 `AUTH_ALLOW_BEARER=false`
- [ ] 定期跑依赖扫描：`scripts/dep_audit.ps1` 或 CI workflow `Security`  
- [ ] 半年或大版本前对 staging 跑 ZAP baseline（见 `docs/security-ops.md`）

Token / Cookie 方案评估、依赖与 ZAP 细节 → [`docs/security-ops.md`](../docs/security-ops.md)。
