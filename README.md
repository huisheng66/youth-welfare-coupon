# 青年福利券系统（一期）

身份核验 → **指定商家**优惠券发放 → 商家 Web 核销。

- 后端：Python FastAPI + SQLAlchemy  
  - 开发默认 **SQLite**（`backend/data/app.db`）  
  - 生产推荐 **MySQL 8**（`mysql+pymysql://...`）  
- 前端：Vue 3 + Vite + Element Plus  
- **不含**微信小程序  
- 银行卡：仅**核验通过后自愿绑定**，库内 **Fernet 加密**（可用独立 `FIELD_ENCRYPTION_KEY`）；接口默认只返回脱敏号，完整号仅超管可解密查看（记审计）  
- 安全硬化：生产关 OpenAPI / 演示 seed、CORS 白名单、登录限流、输入净化、安全响应头 → 见 [`优化.md`](优化.md)  
- 可靠性：写操作幂等键、账号激活一次性链接、邮件 outbox 退避重试、readiness/metrics 探针（v1.5.0，见 [`docs/release-v1.5.0.md`](docs/release-v1.5.0.md)）  
- 安全运维（依赖扫描 / ZAP / Token 说明）→ [`docs/security-ops.md`](docs/security-ops.md)；外部扫描工具清单 → [`docs/security-tools.md`](docs/security-tools.md)；CI 模板：[`docs/ci/security.yml`](docs/ci/security.yml)

**Ubuntu 生产部署（MySQL + Nginx）** → 见 [`deploy/README.md`](deploy/README.md) 与 `deploy/install-ubuntu.sh`。

## 目录

```
backend/    API 服务
frontend/   Web（管理端 / 用户端 / 商家端，按角色进入）
```

## 快速启动

### Windows 一键启动

```powershell
.\start.ps1
```

默认：前端 **https://127.0.0.1:5173/**（HTTPS，便于手机扫码），后端 http://127.0.0.1:19001/

### 1. 后端

```bash
cd backend
python -m venv .venv

# Windows
.venv\Scripts\activate
# Ubuntu
# source .venv/bin/activate

pip install -r requirements.txt
uvicorn app.main:app --reload --host 127.0.0.1 --port 19001
```

数据库：复制 `backend/.env.example` 为 `.env`。开发保持 SQLite；生产改为：

```env
DATABASE_URL=mysql+pymysql://welfare:密码@127.0.0.1:3306/welfare?charset=utf8mb4
```

- API 文档：http://127.0.0.1:19001/docs  
- 存活探针：http://127.0.0.1:19001/api/health  
- 就绪探针：http://127.0.0.1:19001/api/ready（数据库连通 + 迁移版本一致才报就绪，503=未就绪）  

表结构由 Alembic 迁移管理（开发环境启动时 `create_all` + 自动 stamp；生产由
`deploy/migrate-release.sh` 以迁移账号执行 `alembic upgrade head`，运行账号无 DDL 权限）。
开发环境默认写入演示数据（`SEED_DEMO_ACCOUNTS`）。生产请设 `APP_ENV=production` 并关闭演示 seed。

### 2. 前端

```bash
cd frontend
npm install
npm run dev
```

浏览器打开：https://127.0.0.1:5173/ （自签证书需点「继续访问」）  


### 演示账号

| 角色 | 用户名 | 邮箱（也可登录） | 密码 |
|------|--------|------------------|------|
| 超级管理员 | admin | admin@demo.local | admin123 |
| 发券管理员 | issuer | issuer@demo.local | issuer123 |
| 商家（餐饮） | merchant1 | merchant1@demo.local | merchant123 |
| 商家（书店） | merchant2 | merchant2@demo.local | merchant123 |
| 青年用户（已核验） | youth1 | youth1@demo.local | youth123 |
| 青年用户（待审核） | youth2 | youth2@demo.local | youth123 |

青年用户支持**邮箱注册（需验证码）**；登录可用邮箱或用户名；支持**忘记密码**。各角色可在「账号设置」中**改密 / 验证码绑定邮箱**。

## 安全回归（开发）

```powershell
# 后端全量测试（pytest；MySQL 集成用例未设 MYSQL_TEST_URL 时自动供给临时实例，失败自动 skip）
cd backend
.\.venv\Scripts\python.exe -m pytest tests\ -v

# 依赖 CVE（仓库根目录）
.\scripts\dep_audit.ps1

# API 已启动时
.\.venv\Scripts\python.exe scripts\security_audit.py
```

CI：`.github/workflows/security.yml` 在 push/PR 时自动跑后端全量 pytest + pip-audit + npm audit（ZAP/Nuclei 为手动触发）。

前端最小 E2E（Playwright，独立 e2e.db + 种子账号，自动拉起前后端）：

```bash
cd frontend
npx playwright install chromium   # 首次
npm run e2e                       # 登录跳转 / 出示动态券码 / 商家核销页
```

JWT 由 HttpOnly Cookie 承载（`localStorage` 仅存登录标记）；生产 `.env` 已关闭 Bearer 兼容（`AUTH_ALLOW_BEARER=false`）。Cookie 方案评估见 `docs/security-ops.md`。

### 邮箱验证码 / SMTP（腾讯企业邮）

默认 **未配置 SMTP** 时走控制台模式：验证码写入后端日志，接口响应里带 `debug_code`，前端会直接展示，便于本地联调。

**腾讯企业邮 / 企业微信邮箱**（推荐）在 `backend/.env` 配置：

```env
MAIL_SERVER=smtp.exmail.qq.com
MAIL_PORT=465
MAIL_SSL_TLS=true
MAIL_STARTTLS=false
MAIL_USERNAME=noreply@your-company.com
MAIL_PASSWORD=邮箱密码或客户端专用密码
MAIL_FROM=noreply@your-company.com
MAIL_FROM_NAME=青年福利券系统
MAIL_CONSOLE=false
```

1. 登录 [exmail.qq.com](https://exmail.qq.com/) 或企业微信管理后台，确认该账号已开启 **SMTP**  
2. 若管理员强制「客户端专用密码」，请用专用密码填 `MAIL_PASSWORD`  
3. 改完 `.env` 后**重启后端**  
4. 测通：

```powershell
cd backend
.\.venv\Scripts\python.exe scripts\test_smtp.py 你的收件邮箱@xx.com
```

或超管登录后：`GET /api/auth/email/smtp-status`、`POST /api/auth/email/test` `{"to":"..."}`。

相关接口：`POST /api/auth/email/send-code`、`POST /api/auth/forgot-password`、`POST /api/auth/reset-password-by-email`。注册与绑邮箱均需验证码。真实 SMTP 开启后**不会**再返回 `debug_code`。

## 推荐演示路径

1. `admin` 登录 → 仪表盘 / 商家 / 券模板（可设兑换时长）  
2. `issuer` 批量发券，或管理端「志愿时长」给用户入账  
3. `youth1` →「时长兑换」或「我的优惠券」出示**动态券码**（二维码约 30 秒刷新；核销后用户端立即提示成功）  
4. `merchant1` →「核销」→ **扫码**（摄像头 / 相册）或粘贴动态码 → 预览 → 确认核销  
5. 管理端导出核销流水 CSV  

### 商家扫码说明

- 支持：后置摄像头实时扫、相册识图、手动粘贴  
- 可开启「扫码后自动核销」；默认仅预览再确认  

### 手机访问电脑前端（同一 Wi‑Fi）

前端必须监听 `0.0.0.0`（已配置）。用 **WLAN 的 IPv4**，不要用 VMware/WSL 虚拟网卡地址。

```powershell
# 查电脑 Wi‑Fi IP（示例 192.168.1.9）
Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.InterfaceAlias -match 'WLAN|Wi-Fi' }

# 启动（推荐）
.\start.ps1
# 或手动：
# 后端: uvicorn ... --host 127.0.0.1 --port 19001
# 前端: npm run dev -- --host 0.0.0.0 --port 5173
```

手机请打开 **HTTPS**（摄像头要求安全上下文）：

`https://192.168.x.x:5173/`（换成你的 WLAN IP）

首次会提示证书不受信任：选 **高级 → 继续访问**。之后才能调摄像头。

若仍无法开摄像头：用页面上的 **拍照识别 / 相册选图**（走系统相机，不依赖网页摄像头 API）。

若一直转圈：

1. 确认前端是 `0.0.0.0:5173` + HTTPS  
2. Windows 防火墙放行 **入站 TCP 5173**  
3. 手机与电脑同一 Wi‑Fi  

API 经 Vite 代理到本机后端，手机**不必**直接访问 19001。

## 已实现能力

- 用户核验（申请快照 + 版本化审核）、指定商家发券/批量发券、商家核销（幂等键支持，超时重试不重复核销）  
- **统一导入**（xlsx / csv / txt / docx）：预检 → 确认执行 → 逐行结果三步向导（用户名单 / 按名单发券 / 按名单入账）；预检不写业务数据，执行时重新校验资格与唯一冲突；断点续执只重试失败行；文件内重复与跨字段歧义预检即拒；逐行错误明细 CSV 导出  
- **账号激活双轨**（T15）：含邮箱用户收一次性激活链接（48h，单次消费）自行设密；无邮箱/关闭通知用户领取一次性个人凭证（仅执行结果显示一次）；共用初始密码已废弃  
- **可靠邮件 outbox**：激活邮件与建号同事务入队，进程重启不丢；退避重试、上限转失败可人工重发（超管）  
- 动态短时券码（约 30 秒刷新 + 二维码；核销后用户端即时成功提示；断网/后台切换自动恢复）  
- **商家扫码核销**（摄像头 / 相册）；预览锁定 + 确认前重新校验；超时进入结果确认流程  
- CSV 导出（核销流水、券列表、用户、时长流水；筛选条件与列表一致）  
- 志愿服务时长入账（幂等）与用户自助兑换（幂等）；统计与导出统一业务时区划日（Asia/Shanghai）  
- 商家统计、核销预览、审计日志（request_id 全链路串联）  
- 账号设置改密；超管可重置密码、启停账号；强制首改密  
- 用户首页券/时长概览；商家核销页近期流水；待审批量通过/驳回（版本条件审核）  
- 仪表盘今日发券/核销（业务时区）；志愿时长全局流水；用户核验历史  
- 登录失败限流；过期券自动扫描；写操作幂等键（发券/时长/兑换/核销，7 天保留）  
- **可观测性**（T22）：`/api/ready` readiness；`/api/metrics`（仅超管：请求量/5xx/耗时分桶/核销原因分布/outbox 积压/最近备份状态）  

### 二期预留

- 微信小程序（复用 REST；JWT 已迁 HttpOnly Cookie，跨端建议走独立 token 流程）  

## 环境变量（后端）

复制 `backend/.env.example` 为 `backend/.env`：

```env
SECRET_KEY=请改成随机长字符串
DATABASE_URL=sqlite:///./data/app.db
CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
```

批量导入相关（详见 `backend/.env.example`）：

```env
IMPORT_MAX_ROWS=1000          # 单次导入行数上限，超出整文件拒绝
```

账号激活与邮件 outbox（T15，生产必须配置 PUBLIC_BASE_URL）：

```env
PUBLIC_BASE_URL=https://你的域名   # 激活邮件中的链接地址
ACTIVATION_TOKEN_EXPIRE_HOURS=48   # 激活链接有效期（小时）
OUTBOX_POLL_SECONDS=30             # outbox worker 轮询间隔
OUTBOX_MAX_ATTEMPTS=5              # 重试上限，超过转失败可人工重发
```

> `IMPORT_INITIAL_PASSWORD` 仅旧导入端点（阶段性保留）使用；新统一导入已改为激活链接 + 个人凭证双轨。

### 上云数据库

将 `DATABASE_URL` 改为例如：

```env
# PostgreSQL
DATABASE_URL=postgresql+psycopg2://user:password@host:5432/welfare

# MySQL
DATABASE_URL=mysql+pymysql://user:password@host:3306/welfare
```

并安装对应驱动（`psycopg2-binary` 或 `pymysql`）。表结构由 Alembic 迁移管理；
开发库启动时自动建表并 stamp，生产环境必须先以迁移账号执行
`bash deploy/migrate-release.sh`（见 `deploy/README.md`）再启动应用。

## 角色能力摘要

- **超管**：商家、账号、审计、全部业务；重置密码 / 启停账号  
- **发券管理员**：用户审核、**商家维护**、券模板、发券/作废、流水  
- **商家**：仅本店核销与本店流水、改密  
- **用户**：资料、提交核验、出示动态码、时长兑换、改密  

## 二期预留

- 微信小程序（复用现有 REST；JWT 已迁 HttpOnly Cookie，跨端建议走独立 token 流程）  

## 安全说明

- 用户主键为系统 UUID；银行卡号 **Fernet 加密落库**（密钥派生自 `SECRET_KEY`），更换密钥后旧密文无法解密  
- 券模板强制绑定商家；核销校验 `merchant_id`  
- 核销使用状态条件更新，降低并发重复核销风险  
