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

T09 起账号按职责拆分（均仅 `localhost` 来源，见 `setup-mysql.sql`）：
`welfare_app`（运行，仅 DML）/ `welfare_migrate`（迁移，仅发布期执行 DDL）/
`welfare_backup`（备份，只读+锁表）。历史 ALL 权限的 `welfare` 账号在切换后删除。

`backend/.env`（生产建议，DATABASE_URL 使用运行账号 welfare_app）：

```env
APP_ENV=production
DATABASE_URL=mysql+pymysql://welfare_app:你的密码@127.0.0.1:3306/welfare?charset=utf8mb4
SECRET_KEY=请换成 openssl rand -hex 32
FIELD_ENCRYPTION_KEY=请换成另一串 openssl rand -hex 32
CORS_ORIGINS=https://你的域名
CORS_ALLOW_LAN=false
OPENAPI_ENABLED=false
SEED_DEMO_ACCOUNTS=false
RATE_LIMIT_BACKEND=file
# T15：账号激活邮件——生产必须配置为用户可访问的前端地址
PUBLIC_BASE_URL=https://你的域名
ACTIVATION_TOKEN_EXPIRE_HOURS=48
OUTBOX_POLL_SECONDS=30
OUTBOX_MAX_ATTEMPTS=5
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
curl -s http://127.0.0.1:19001/api/health    # 存活探针（liveness）
curl -s http://127.0.0.1:19001/api/ready     # 就绪探针：503 = 数据库失效或迁移版本落后，
                                             # LB/监控应据此摘除实例
curl -s http://127.0.0.1:19001/api/metrics \  # 业务指标（需超管登录后携带 Cookie）
  -H "X-Requested-With: XMLHttpRequest"
```

`/api/metrics` 关注点：`outbox_backlog.queued` 持续增长 → 检查 SMTP 配置；
`last_backup.ok = false` → 备份失败需排查；`redeem_results` 中失败原因分布
异常升高 → 对应排查（`already_used` 多为重复扫码，`invalid_live_code` 多为
券码过期后重扫）。

## 脚本分类

`deploy/` 下脚本分两类：**长期运维脚本**（保留原位，新人优先熟悉这些）与**一次性补丁脚本**（已归档至 `deploy/archive/`，仅作历史参考，**不要在新环境执行**）。

### 长期运维脚本（原位）

| 脚本 | 用途 | 备注 |
|------|------|------|
| `install-ubuntu.sh` | Ubuntu 一键部署骨架（MySQL + API + 前端 + Nginx） | 首选入口；支持 `DOMAIN`/`APP_DB_PASS`/`SKIP_FRONTEND_BUILD` 等；自动拆分三个最小权限数据库账号 |
| `migrate-release.sh` | 发布期执行 `alembic upgrade head`（迁移账号，worker 启动不执行 DDL） | `MIGRATE_DATABASE_URL` 或离散 `MIGRATE_DB_*` 变量；幂等可重复执行 |
| `backup-mysql.sh` | MySQL 每日备份（备份账号；先写临时文件，gzip+内容校验通过后原子发布，按天保留） | cron 安装在 `/etc/cron.d/welfare-backup` 并注入 `BACKUP_DATABASE_URL`；`BACKUP_DIR`/`RETAIN_DAYS` 可覆盖 |
| `restore-mysql.sh` | 恢复指定备份到隔离库并校验（业务表数、余额=账本、券状态分布） | `bash deploy/restore-mysql.sh <dump.sql.gz> <目标库> <URL>`；任何对账不一致退出码非 0 |
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

## 备份与恢复

`install-ubuntu.sh` 会安装 cron（每日 03:17）执行 `deploy/backup-mysql.sh`：

- 备份内容：`mysqldump --single-transaction --no-tablespaces` 全库 gzip + `backend/.env` 副本（字段加密钥 `FIELD_ENCRYPTION_KEY` 必须随库备份，否则银行卡密文不可解密）
- 状态留痕：成败均写 `last-backup-status.json`（`/api/metrics.last_backup` 可查；失败自动留 error）
- 失败保护：先写临时文件，gzip 完整性与转储内容校验通过后才原子改名发布；校验失败不发布、不触发保留期清理，退出码非 0
- 位置：`/opt/welfare/backups/`，默认保留 14 天（`RETAIN_DAYS` 可覆盖）
- 日志：`/var/log/welfare-backup.log`
- 手动执行：`bash /opt/welfare/deploy/backup-mysql.sh`

**恢复步骤**（新机器或本机回滚）：

```bash
# 1. 安装骨架（或已有环境跳过）；解压备份
gunzip welfare-YYYYMMDD-HHMMSS.sql.gz

# 2. 恢复数据库到隔离空库并自动校验（推荐）
bash deploy/restore-mysql.sh welfare-YYYYMMDD-HHMMSS.sql.gz welfare_restore   'mysql+pymysql://root:密码@127.0.0.1:3306/welfare_restore?charset=utf8mb4'
# 校验 PASS 后再切换应用连接；手工恢复可用 mysql -u root -p welfare < welfare-*.sql

# 3. 恢复 .env（先 diff 现有 .env，仅当加密钥丢失/回滚时覆盖）
cp env-YYYYMMDD-HHMMSS.txt /opt/welfare/backend/.env && chmod 640 /opt/welfare/backend/.env

# 4. 重启并验证
systemctl restart welfare-api
curl -s http://127.0.0.1:19001/api/health
```

> 恢复演练：建议每季度在测试机用 `deploy/restore-mysql.sh` 走一遍上述流程（2026-09-05 已在临时 MySQL 8.4 实例完成备份→恢复→对账 PASS 演练，见 log.md）；`.env` 与数据库必须成对恢复，单换其一会导致加密字段不可读或密钥错配。

## 凭据注入与轮换（2026-08）

历史版本曾把服务器密码硬编码进脚本并进入 git 历史（内网/公网 SSH 密码、超管初始密码、企业邮箱 SMTP 密码）。脚本现已全部改为**环境变量注入**（缺失即报错退出，不再有默认值）；`deploy/archive/` 归档脚本就地脱敏。**git 历史中的泄露仍在——以下凭据务必全部轮换**：

| 凭据 | 注入变量 | 使用脚本（均需先 export） |
|---|---|---|
| 内网服务器 SSH 密码 | `SSH_PASS` | `pack-and-upload.sh`、`sync-frontend-prod.sh` |
| 公网服务器 root SSH 密码 | `SSH_PASS` | `pack-and-upload-public.sh` |
| 首个超管初始密码 | `BOOTSTRAP_ADMIN_PASS` | `run-on-public.sh` |
| 超管登录密码（自检用，可选） | `ADMIN_PASS`（未设则跳过登录自检） | `verify-prod.sh`、`bind-youth-domain.sh`、`fix-nginx-welfare.sh`、`config-smtp-prod.sh` |
| 企业邮箱 SMTP 专用密码 | `SMTP_PASSWORD` | `config-smtp-prod.sh` |

- 防回归：`backend/tests/test_security_hardening.py::TestDeployNoHardcodedSecrets` 会扫描全部 shell 脚本，禁止 `sshpass -p <字面量>`、字面密码赋值与真实管理员口令再次入库。
- 推荐：公网机已装公钥，改用 **SSH 密钥登录并禁用密码登录**（`PasswordAuthentication no`）；SMTP 用「客户端专用密码」并定期重置。
- 轮换检查：改密后跑 `bash deploy/verify-prod.sh <base-url>`（带 `ADMIN_PASS=新密码`）确认旧行为已失效。

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
- [ ] T15：`PUBLIC_BASE_URL` 已配置为用户可访问的前端地址；导入用户后抽查激活邮件可达性
- [ ] 定期跑依赖扫描：`scripts/dep_audit.ps1` 或 CI workflow `Security`  
- [ ] 半年或大版本前对 staging 跑 ZAP baseline（见 `docs/security-ops.md`）

Token / Cookie 方案评估、依赖与 ZAP 细节 → [`docs/security-ops.md`](../docs/security-ops.md)。
