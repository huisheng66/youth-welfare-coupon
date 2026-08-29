# 青年福利券系统（一期）

身份核验 → **指定商家**优惠券发放 → 商家 Web 核销。

- 后端：Python FastAPI + SQLAlchemy  
  - 开发默认 **SQLite**（`backend/data/app.db`）  
  - 生产推荐 **MySQL 8**（`mysql+pymysql://...`）  
- 前端：Vue 3 + Vite + Element Plus  
- **不含**微信小程序  
- 银行卡：仅**核验通过后自愿绑定**，库内 **Fernet 加密**（可用独立 `FIELD_ENCRYPTION_KEY`）；接口默认只返回脱敏号，完整号仅超管可解密查看（记审计）  
- 安全硬化：生产关 OpenAPI / 演示 seed、CORS 白名单、登录限流、输入净化、安全响应头 → 见 [`优化.md`](优化.md)  
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
- 健康检查：http://127.0.0.1:19001/api/health  

首次启动会自动建表；开发环境默认写入演示数据（`SEED_DEMO_ACCOUNTS`）。生产请设 `APP_ENV=production` 并关闭演示 seed。

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
# 硬化单元测试
cd backend
.\.venv\Scripts\python.exe tests\test_security_hardening.py

# 依赖 CVE（仓库根目录）
.\scripts\dep_audit.ps1

# API 已启动时
.\.venv\Scripts\python.exe scripts\security_audit.py
```

JWT 现存在浏览器 `localStorage`，须防 XSS；生产请 HTTPS。Cookie 方案评估见 `docs/security-ops.md`。

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

- 用户核验、指定商家发券/批量发券、商家核销  
- **按文件批量导入**（xlsx / csv / txt / docx）：用户名单（导入即核验通过、统一初始密码）、按名单发券、按名单入账志愿时长，支持仅校验试运行  
- 动态短时券码（约 30 秒刷新 + 二维码；核销后用户端即时成功提示）  
- **商家扫码核销**（摄像头 / 相册）  
- CSV 导出（核销流水、券列表）  
- 志愿服务时长入账与用户自助兑换  
- 商家统计、核销预览、审计日志  
- **账号设置改密**（各角色）；超管可重置密码、启停账号  
- 用户首页券/时长概览与快捷出示；商家核销页近期流水  
- 待审**批量通过/驳回**；券列表 / 核销流水筛选分页与导出  
- 仪表盘今日发券/核销；志愿时长全局流水；用户核验历史  
- 演示账号自动补发未使用券，便于扫码演示  
- 登录失败限流；过期券自动扫描；用户 CSV 导出  
- 商家/模板/审计筛选；404 页；兑换后可直接出示券码  

### 二期预留

- 微信小程序（复用 REST + JWT）  

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
IMPORT_INITIAL_PASSWORD=youth123456  # 导入用户的统一初始密码（需 ≥8 位且含字母数字）
```

### 上云数据库

将 `DATABASE_URL` 改为例如：

```env
# PostgreSQL
DATABASE_URL=postgresql+psycopg2://user:password@host:5432/welfare

# MySQL
DATABASE_URL=mysql+pymysql://user:password@host:3306/welfare
```

并安装对应驱动（`psycopg2-binary` 或 `pymysql`）。表结构由启动时 `create_all` 创建（生产建议再接入 Alembic 迁移）。

## 角色能力摘要

- **超管**：商家、账号、审计、全部业务；重置密码 / 启停账号  
- **发券管理员**：用户审核、**商家维护**、券模板、发券/作废、流水  
- **商家**：仅本店核销与本店流水、改密  
- **用户**：资料、提交核验、出示动态码、时长兑换、改密  

## 二期预留

- 微信小程序（复用现有 REST + JWT）  
- 志愿服务时长账户表 `point_accounts` / `point_ledgers` 已预留  

## 安全说明

- 用户主键为系统 UUID；银行卡号 **Fernet 加密落库**（密钥派生自 `SECRET_KEY`），更换密钥后旧密文无法解密  
- 券模板强制绑定商家；核销校验 `merchant_id`  
- 核销使用状态条件更新，降低并发重复核销风险  
