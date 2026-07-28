# 网站 / API 安全测试工具（GitHub 精选）

面向本仓库（FastAPI + Vue）的可复用清单。仅在**自有/授权**环境扫描。

---

## 一、本机已接入

| 工具 | 仓库 | 用途 | 本项目用法 |
|------|------|------|------------|
| **业务自检** | 本仓库 | SQLi / 鉴权 / 越权 / 限流 | `backend/scripts/security_audit.py` |
| **硬化单测** | 本仓库 | 配置开关 / 净化 / 密钥 / 限流 | `backend/tests/test_security_hardening.py` |
| **依赖 CVE** | — | pip / npm | `scripts/dep_audit.ps1` |
| **Nuclei** | [projectdiscovery/nuclei](https://github.com/projectdiscovery/nuclei) | 模板化漏洞 / 暴露面扫描 | `scripts/external_scan.ps1` |
| **自定义模板** | 本仓库 `tools/nuclei-templates/` | 鉴权 401 / 登录 SQLi / 匿名管理面 | 随 external_scan 跑，期望 **0 findings** |
| **ffuf** | [ffuf/ffuf](https://github.com/ffuf/ffuf) | API 路径发现 | `tools/wordlists/api-paths.txt` |
| **sqlmap** | [sqlmapproject/sqlmap](https://github.com/sqlmapproject/sqlmap) | 登录 JSON 注入探测 | 本地 clone 到 `tools/sqlmap/`（gitignore） |
| **ZAP baseline** | [zaproxy/zaproxy](https://github.com/zaproxy/zaproxy) | 爬虫 + 被动/基线主动扫描 | `scripts/zap-baseline.ps1`（需 Docker） |

安装 Nuclei（已在本机验证）：

```powershell
go install -v github.com/projectdiscovery/nuclei/v3/cmd/nuclei@latest
# 二进制一般在 %USERPROFILE%\go\bin\nuclei.exe
nuclei -update-templates
```

---

## 二、强烈推荐（GitHub 高星 / 业界常用）

### 综合扫描

| 项目 | Stars 量级 | 说明 | 适合场景 |
|------|------------|------|----------|
| [projectdiscovery/nuclei](https://github.com/projectdiscovery/nuclei) | 很高 | YAML 模板，社区模板库巨大 | API / 暴露面 / CVE / misconfig |
| [projectdiscovery/nuclei-templates](https://github.com/projectdiscovery/nuclei-templates) | 很高 | Nuclei 模板库 | 与 nuclei 配套 |
| [zaproxy/zaproxy](https://github.com/zaproxy/zaproxy) | 很高 | OWASP ZAP 官方 | 全站爬虫、代理、CI baseline |
| [wapiti-scanner/wapiti](https://github.com/wapiti-scanner/wapiti) | 中高 | Python Web 漏洞扫描 | 黑盒站点（建议独立 venv，勿装进本项目后端 venv） |
| [sullo/nikto](https://github.com/sullo/nikto) | 高 | 经典 Web 服务器配置扫描 | 服务器杂项 / 危险文件 |

### 注入与业务逻辑

| 项目 | 说明 | 注意 |
|------|------|------|
| [sqlmapproject/sqlmap](https://github.com/sqlmapproject/sqlmap) | 自动 SQL 注入 | **仅授权目标**；本 API 已用 ORM + 参数化，作回归验证即可 |
| [codingo/NoSQLMap](https://github.com/codingo/NoSQLMap) | NoSQL 注入 | 本项目用 SQL，一般无关 |

### 模糊测试 / 发现路径

| 项目 | 说明 |
|------|------|
| [ffuf/ffuf](https://github.com/ffuf/ffuf) | 高速 HTTP 模糊测试（路径、参数） |
| [OJ/gobuster](https://github.com/OJ/gobuster) | 目录 / DNS / vhost 爆破 |
| [projectdiscovery/httpx](https://github.com/projectdiscovery/httpx) | HTTP 探测、技术栈、状态码批量 |

### 依赖与供应链

| 项目 | 说明 |
|------|------|
| [pypa/pip-audit](https://github.com/pypa/pip-audit) | Python 依赖 CVE（已接入 `dep_audit`） |
| [advisories-community / npm audit](https://docs.npmjs.com/cli/v10/commands/npm-audit) | 前端依赖 |
| [aquasecurity/trivy](https://github.com/aquasecurity/trivy) | 容器 / 文件系统 / 依赖综合扫描 |

### 编排 / 大型框架（可选）

| 项目 | 说明 |
|------|------|
| [six2dez/reconftw](https://github.com/six2dez/reconftw) | 自动化 recon 流水线（偏外网资产） |
| [pry0cc/axiom](https://github.com/pry0cc/axiom) | 分布式扫描基础设施 |
| [GhostTroops/scan4all](https://github.com/GhostTroops/scan4all) | 综合漏洞/指纹（较重） |

### 练习靶场（学原理，勿扫生产）

| 项目 | 说明 |
|------|------|
| [WebGoat/WebGoat](https://github.com/WebGoat/WebGoat) | OWASP 教学靶场 |
| [juice-shop/juice-shop](https://github.com/juice-shop/juice-shop) | 现代 Web 漏洞靶场 |
| [digininja/DVWA](https://github.com/digininja/DVWA) | 经典 PHP 靶场 |

---

## 三、对本系统的推荐组合

```text
日常 / PR
  ├─ tests/test_security_hardening.py
  ├─ scripts/dep_audit.ps1
  └─（可选）docs/ci/security.yml → GitHub Actions

发版前 / 本地 API 起着时
  ├─ backend/scripts/security_audit.py (+ extra)
  ├─ scripts/external_scan.ps1   # Nuclei
  └─ scripts/zap-baseline.ps1    # 有 Docker 时

半年 / staging
  └─ ZAP baseline 完整报告归档（见 security-ops.md）
```

**不要**把 `wapiti3` / `mitmproxy` 装进 `backend/.venv`（会与 `cryptography` 等生产依赖冲突）。扫描工具用独立虚拟环境或 Docker。

---

## 四、Nuclei 扫描注意点（本项目实测）

1. **全局限流** `GLOBAL_IP_MAX_REQUESTS` 会对扫描 IP 返回 429；扫描时可将该值调大或设为 `0`，否则部分模板会误报「缺安全头」（实际看到的是 429 响应）。
2. 开发环境 **`/docs` 暴露** 会被 `swagger-api` 模板检出 → 生产 `OPENAPI_ENABLED=false` 已处理。
3. `Server: uvicorn` 技术指纹属 info 级，可接受；生产前建议 Nginx 反代并隐藏后端细节。
4. 报告输出目录：`reports/`（已 gitignore）。

示例：

```powershell
# API 需已启动
$env:GLOBAL_IP_MAX_REQUESTS = "0"   # 扫描会话内可在 .env 关闭后重启 API
.\scripts\external_scan.ps1 -Target http://127.0.0.1:19001
```

---

## 五、与业务自检的分工

| 层级 | 工具 | 强项 |
|------|------|------|
| 业务语义 | `security_audit.py` | 角色越权、银行卡解密、登录 429、演示账号路径 |
| 通用 Web | Nuclei / ZAP | 暴露文档、缺头、已知 CVE、爬虫面 |
| 依赖 | pip-audit / npm audit | 供应链 CVE |
| 注入深度 | sqlmap（可选） | 二次确认登录/搜索参数 |

---

## 六、参考链接

- Nuclei: https://github.com/projectdiscovery/nuclei  
- Nuclei templates: https://github.com/projectdiscovery/nuclei-templates  
- OWASP ZAP: https://github.com/zaproxy/zaproxy  
- sqlmap: https://github.com/sqlmapproject/sqlmap  
- ffuf: https://github.com/ffuf/ffuf  
- Wapiti: https://github.com/wapiti-scanner/wapiti  
- Trivy: https://github.com/aquasecurity/trivy  
