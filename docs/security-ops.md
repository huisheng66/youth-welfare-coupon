# 安全运维（第 4 阶段）

覆盖：Token 存储风险与 Cookie 方案评估（7b）、依赖扫描（7c）、OWASP ZAP 基线（7e）。  
日常硬化（OpenAPI / CORS / 限流 / 输入净化等）见仓库根目录 [`优化.md`](../优化.md)。

---

## 7b. JWT 存储与 XSS 风险

### 现状

- 登录成功后，前端把 `access_token` 写入 **`localStorage`**（见 `frontend/src/auth.js`）。
- 请求头：`Authorization: Bearer <token>`（axios 拦截器）。
- **任意 XSS**（若用户可控 HTML 被 `v-html` 或第三方脚本注入）可直接读走 Token，冒充用户调用 API。

### 已采取的缓解

- 服务端对姓名/组织/备注/材料等字段 **剥离 `<>`**，降低存储型 XSS。
- 前端约定：**不对用户字段使用 `v-html`**（`tests` 中有静态扫描）。
- 安全响应头：`X-Content-Type-Options`、`X-Frame-Options`、`Referrer-Policy`。
- 生产关闭 OpenAPI、收紧 CORS，减小攻击面。

### HttpOnly Cookie 方案评估（可选后续）

| 项 | 说明 |
|----|------|
| 收益 | JS 无法直接读取 Cookie，缓解「XSS 偷 Token」；可配合 `SameSite=Lax/Strict` |
| 前置 | **全站 HTTPS**（否则 Secure Cookie 不可用或降级不安全） |
| 改动面 | 后端 `login` 设 Cookie；前端去掉 `localStorage` token；CSRF 防护（双重 Cookie 或 CSRF token）；跨域前端需 `credentials: 'include'` + 精确 CORS |
| 风险 | 现网若仍有 HTTP 调试/局域网扫码，Cookie 方案易踩坑；与手机扫码跨源场景需单独设计 |
| 建议 | **维持 Bearer + localStorage**，直到生产强制 HTTPS 且前端同源部署稳定；再单独立项迁移 |

**结论（本期）**：不迁移 Cookie；以文档 + 防 XSS + 安全头为主。迁移触发条件：生产 HTTPS 稳定 ≥ 1 个月，且安全评审通过。

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

## 相关路径

| 路径 | 说明 |
|------|------|
| `优化.md` | 总计划与 DoD |
| `deploy/README.md` | 生产部署安全清单 |
| `scripts/dep_audit.ps1` / `.sh` | 依赖扫描 |
| `scripts/zap-baseline.ps1` / `.sh` | ZAP 基线封装 |
| `docs/ci/security.yml` | CI 工作流模板（复制到 `.github/workflows/` 启用） |
