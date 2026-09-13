# 安全运维（第 4 阶段）

覆盖：Token 存储与 HttpOnly Cookie 迁移结果（7b）、依赖扫描（7c）、OWASP ZAP 基线（7e）。  
日常硬化（OpenAPI / CORS / 限流 / 输入净化等）见仓库根目录 [`优化.md`](../优化.md)。

---

## 7b. JWT 存储与 XSS 风险（已完成 HttpOnly Cookie 迁移）

> 2026-09-06 起（优化1 第 2 项），JWT 已从 localStorage 迁移到 **HttpOnly Cookie**。
> 本节描述迁移后的现状；旧的 Bearer + localStorage 方案仅作过渡回落保留。

### 现状（迁移后）

- 登录成功后，后端通过 `Set-Cookie` 下发 token：**HttpOnly + SameSite=Lax**，
  `Secure` 随环境开关（生产 HTTPS 下开启）——见 `backend/app/core/cookie.py`，
  Cookie 名 / 域 / SameSite 可用 `AUTH_COOKIE_*` 配置项调整。
- 前端 **JS 不可读 token**（HttpOnly）；`frontend/src/auth.js` 的 localStorage 只存
  脱敏的账号资料（姓名/角色等展示字段），不含 token；axios 全局
  `withCredentials: true`（`frontend/src/api.js`）。
- `get_current_account`（`backend/app/core/deps.py`）优先读 Cookie，过渡期回落
  `Authorization: Bearer`（为二期小程序等非浏览器客户端保留）。
- 登出后端清 Cookie（`clear_auth_cookie`）+ 递增 session_version 废止旧会话。
- CSRF：写方法（POST/PUT/PATCH/DELETE）强制携带 `X-Requested-With` 头
  （浏览器原生跨站表单不会带），配合 SameSite=Lax 双层防护——见
  `backend/app/main.py` `CsrfProtectMiddleware`。

### XSS 剩余风险与缓解

迁移后即便出现 XSS，也无法**窃取 token 离站重放**；但 XSS 仍可在受害浏览器内
直接发起同源请求（无法彻底消除），需继续压低注入面：

- 服务端对姓名/组织/备注/材料等字段 **剥离 `<>`**，降低存储型 XSS。
- 前端约定：**不对用户字段使用 `v-html`**（`tests` 中有静态扫描）。
- 安全响应头：`X-Content-Type-Options`、`X-Frame-Options`、`Referrer-Policy`；
  CSP 由 Nginx 层下发（见 `deploy/nginx-welfare.conf`）。
- 生产关闭 OpenAPI、收紧 CORS，减小攻击面。

### 已知限制

- CSRF 头校验是「约定头」方案，不是凭证式 CSRF token；过渡期回落的
  `Authorization: Bearer` 请求不受 SameSite 保护（Bearer 头本身天然免疫 CSRF，
  但前提是 token 不落 JS 可读存储——非浏览器客户端自行保管）。
- 若未来前后端跨子域部署，需配 `AUTH_COOKIE_DOMAIN=.example.com` 并复核 CORS。

---

## 7c. 依赖漏洞扫描

### 本地一键

```powershell
# Windows（仓库根目录）
.\scripts\dep_audit.ps1
```

```bash
# Linux / macOS / CI
bash scripts/dep_audit.sh
```

脚本会：

1. `pip install pip-audit`（若缺失）并对 `backend/requirements.txt` 跑 **pip-audit**
2. 在 `frontend/` 跑 **`npm audit --production --audit-level=high`**

退出码：有 high/critical 级未处理问题时非 0（便于 CI 失败）。

### GitHub Actions

工作流模板：[`docs/ci/security.yml`](ci/security.yml)

启用方式（需具备 workflow 写权限的 token / PAT）：

```bash
mkdir -p .github/workflows
cp docs/ci/security.yml .github/workflows/security.yml
git add .github/workflows/security.yml && git commit -m "Enable security CI workflow" && git push
```

- 推送 / PR 到 `master` 时跑：后端单元测试 + pip-audit + npm audit  
- 不替代上线前的 `security_audit.py`（需运行中的 API）  
- 仓库当前凭证若无 `workflow` scope，无法直接 push `.github/workflows/*`，故模板放在 `docs/ci/`

### 处理原则

1. **Critical / High**：尽快升级或换包；无法升级时在 issue 写明缓解与接受风险  
2. **Moderate / Low**：排期处理  
3. 锁版本：`requirements.txt` / `package-lock.json` 保持可复现

---

## 7e. OWASP ZAP 基线（半年一次或大版本前）

### 目标

对 **staging**（勿直接扫生产写操作）做 baseline spider + 被动/轻量主动扫描，归档报告。

### 前置

- Staging 已部署，HTTPS，演示数据或隔离库  
- 已知测试账号；扫描期间可接受日志噪音  
- 本机或 CI 可跑 Docker

### 推荐命令（Docker）

```bash
# 将 TARGET 换成 staging 根 URL，例如 https://staging.example.com
export TARGET="https://staging.example.com"
mkdir -p reports
docker run --rm -v "$(pwd)/reports:/zap/wrk/:rw" -t ghcr.io/zaproxy/zaproxy:stable \
  zap-baseline.py -t "$TARGET" -r zap-baseline-report.html -I
```

- `-I`：有告警仍返回 0（先出报告再人工 triage）；正式门禁可去掉 `-I` 并配置规则  
- 报告输出：`reports/zap-baseline-report.html`

Windows PowerShell 示例见 `scripts/zap-baseline.ps1`。

### 归档清单

每次扫描后在 issue / 网盘保留：

- [ ] 日期、TARGET、Git commit  
- [ ] HTML/JSON 报告  
- [ ] High+ 项处理结论（修复 / 误报 / 接受风险）  
- [ ] 复测记录  

建议节奏：**每半年**或**大版本上线前**。

### 与现有脚本关系

| 工具 | 用途 |
|------|------|
| `backend/scripts/security_audit.py` | 业务向：SQLi/鉴权/越权/限流（需 API） |
| `backend/tests/test_security_hardening.py` | 配置与硬化单元测试 |
| `scripts/dep_audit.*` | 依赖 CVE |
| ZAP baseline | 通用 Web 面：头、TLS、爬虫发现的注入/杂项 |

---

## 7f. 账号激活与邮件 outbox（T15，2026-09-06）

### 凭证方案（替代统一初始密码）

- 名单导入后：含邮箱用户收一次性激活链接（48h，单次消费，token 只存
  HMAC-SHA256 摘要）；无邮箱/关闭通知用户在执行结果中领取**一次性个人凭证**
  （随机 12 位，仅当次响应可见，不落库、不进日志、批次 CSV 不含密码列）。
- 待激活账号的密码哈希为每批随机占位（bcrypt 一次/批），不可用任何已知
  密码登录；激活成功即置新密码并递增 session_version（废止激活前会话）。
- 统一初始密码 `IMPORT_INITIAL_PASSWORD` 仅旧导入端点（阶段性保留）使用。

### 邮件 outbox 语义

- 激活邮件与账号创建**同一事务**入队（进程重启不丢）；worker 进程内领取，
  条件 UPDATE 单胜者；失败按 1/5/15/60 分钟退避，5 次后转 `failed`（可
  人工重发：`POST /api/outbox/{id}/resend`，仅超管）。
- 状态只报告三种终态语义：`queued` 已排队 / `sent` SMTP 已受理（≠用户已收件）/
  `failed` 失败；`GET /api/outbox` 不回邮件正文；**发送成功即清空正文**
  （激活链接含一次性 token，不长期留库；失败任务保留正文供重发）。
- 邮件正文所有用户可控字段 HTML 转义；状态、错误与日志不含初始密码或
  激活 token 明文。

### 运维要点

- 生产必须配置 `PUBLIC_BASE_URL`（激活链接指向用户可访问的前端地址）。
- 排障：`GET /api/outbox?status=failed` 查看永久失败；重发后回 `queued`
  立即投递；worker 随应用 lifespan 启停，无需独立进程。

---

## 相关路径

| 路径 | 说明 |
|------|------|
| `优化.md` | 总计划与 DoD |
| `deploy/README.md` | 生产部署安全清单 |
| `scripts/dep_audit.ps1` / `.sh` | 依赖扫描 |
| `scripts/external_scan.ps1` | Nuclei + 业务自检一键扫 |
| `scripts/zap-baseline.ps1` / `.sh` | ZAP 基线封装 |
| `docs/security-tools.md` | GitHub 安全测试项目推荐清单 |
| `docs/ci/security.yml` | CI 工作流模板（复制到 `.github/workflows/` 启用） |
