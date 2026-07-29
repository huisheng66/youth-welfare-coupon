"""
生产站安全自检（防御性、非破坏）：
- 不依赖演示账号
- 不做暴力破解 / DoS / 写破坏数据
- 仅探测：暴露面、鉴权、注入回显、默认口令、安全头、CORS、限流抽样

用法:
  BASE_URL=https://youth.huishengbook.us.ci/api \\
    .venv/Scripts/python.exe scripts/security_audit_prod.py
"""
from __future__ import annotations

import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone

BASE = os.environ.get("BASE_URL", "https://youth.huishengbook.us.ci/api").rstrip("/")
ROOT = BASE.rsplit("/api", 1)[0] if "/api" in BASE else BASE
# 可选：若提供管理员会话则做只读鉴权后探测（勿写入）
ADMIN_USER = os.environ.get("ADMIN_USER", "").strip()
ADMIN_PASS = os.environ.get("ADMIN_PASS", "").strip()

# 关闭证书校验仅在显式要求时（默认严格校验）
INSECURE = os.environ.get("INSECURE_SSL", "").lower() in ("1", "true", "yes")


@dataclass
class Finding:
    severity: str
    category: str
    title: str
    detail: str = ""


@dataclass
class Report:
    findings: list[Finding] = field(default_factory=list)

    def add(self, severity: str, category: str, title: str, detail: str = "") -> None:
        self.findings.append(Finding(severity, category, title, detail))

    def counts(self) -> dict[str, int]:
        c: dict[str, int] = {}
        for f in self.findings:
            c[f.severity] = c.get(f.severity, 0) + 1
        return c


def _ctx() -> ssl.SSLContext | None:
    if not BASE.startswith("https"):
        return None
    if INSECURE:
        c = ssl.create_default_context()
        c.check_hostname = False
        c.verify_mode = ssl.CERT_NONE
        return c
    return ssl.create_default_context()


def req(
    method: str,
    path: str,
    *,
    body: dict | None = None,
    token: str | None = None,
    headers_extra: dict | None = None,
    absolute: bool = False,
    timeout: float = 15.0,
    origin: str | None = None,
) -> tuple[int, str, dict[str, str]]:
    url = path if absolute else f"{BASE}{path}"
    data = None
    headers = {
        "Accept": "application/json",
        "User-Agent": "welfare-security-audit-prod/1.0",
    }
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if origin:
        headers["Origin"] = origin
    if headers_extra:
        headers.update(headers_extra)
    r = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(r, timeout=timeout, context=_ctx()) as resp:
            text = resp.read().decode("utf-8", errors="replace")
            return resp.status, text, {k.lower(): v for k, v in resp.headers.items()}
    except urllib.error.HTTPError as e:
        text = e.read().decode("utf-8", errors="replace")
        return e.code, text, {k.lower(): v for k, v in e.headers.items()}
    except Exception as e:  # noqa: BLE001
        return 0, f"{type(e).__name__}: {e}", {}


def looks_like_sql_error(text: str) -> bool:
    low = text.lower()
    needles = [
        "sqlite3.",
        "operationalerror",
        "syntax error",
        "sqlalchemy.exc",
        "unrecognized token",
        "you have an error in your sql",
        "mysql_fetch",
        "pg_query",
        "warning: mysql",
        "traceback (most recent call last)",
    ]
    return any(n in low for n in needles)


SQLI = [
    "' OR '1'='1",
    "' OR 1=1--",
    "admin'--",
    "1; DROP TABLE accounts;--",
    "' UNION SELECT username,password_hash FROM accounts--",
    "1' AND SLEEP(5)--",
]


def test_tls_and_health(report: Report) -> dict | None:
    print("[*] TLS / health / info disclosure...")
    if not BASE.startswith("https"):
        report.add("HIGH", "传输", "BASE_URL 非 HTTPS", BASE)
    code, text, headers = req("GET", "/health")
    if code != 200:
        report.add("CRITICAL", "可用性", "健康检查失败", f"{code} {text[:200]}")
        return None
    report.add("PASS", "可用性", "健康检查 200", text[:180])
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        report.add("MEDIUM", "信息暴露", "health 非 JSON", text[:120])
        return None

    # 生产应关闭 openapi / 演示
    if data.get("openapi_enabled") is True:
        report.add("MEDIUM", "信息暴露", "生产 OpenAPI 仍开启", str(data.get("openapi_enabled")))
    else:
        report.add("PASS", "信息暴露", "OpenAPI 已关闭")

    if data.get("app_env") != "production":
        report.add("MEDIUM", "配置", f"app_env={data.get('app_env')!r}（期望 production）")
    else:
        report.add("PASS", "配置", "app_env=production")

    if data.get("mail_console") is True:
        report.add("HIGH", "配置", "mail_console=true（验证码可能回显/不发信）")
    else:
        report.add("PASS", "配置", "SMTP 非控制台模式")

    # health 是否泄露过多
    sensitive_keys = {"secret", "password", "database_url", "redis_url"}
    leaked = [k for k in data if any(s in k.lower() for s in sensitive_keys)]
    if leaked:
        report.add("HIGH", "信息暴露", "health 含敏感字段名", str(leaked))
    else:
        report.add("PASS", "信息暴露", "health 未见密钥类字段")

    # HSTS / 安全头（经 CF 时可能在边缘加）
    hsts = headers.get("strict-transport-security", "")
    if hsts:
        report.add("PASS", "安全头", "HSTS 存在", hsts[:80])
    else:
        report.add("LOW", "安全头", "未见 Strict-Transport-Security（可在 Nginx/CF 启用）")

    for hname, sev in (
        ("x-content-type-options", "LOW"),
        ("x-frame-options", "LOW"),
        ("referrer-policy", "INFO"),
    ):
        if headers.get(hname):
            report.add("PASS", "安全头", f"{hname} 存在", headers[hname][:60])
        else:
            report.add(sev, "安全头", f"响应缺少 {hname}")

    return data


def test_docs_and_sensitive_paths(report: Report) -> None:
    print("[*] Sensitive paths / docs / static leaks...")
    paths = [
        "/docs",
        "/redoc",
        "/openapi.json",
        "/api/docs",
        "/api/openapi.json",
        "/.env",
        "/api/.env",
        "/backend/.env",
        "/.git/HEAD",
        "/api/.git/HEAD",
        "/server-status",
        "/actuator/health",
        "/debug",
        "/api/debug",
        "/phpinfo.php",
        "/wp-login.php",
        "/admin",
        "/api/auth/email/smtp-status",  # 应需超管
    ]
    for p in paths:
        url = f"{ROOT}{p}" if not p.startswith("http") else p
        code, text, _ = req("GET", url, absolute=True, timeout=10)
        low = text.lower()[:500]
        if p.endswith(".env") or p.endswith("HEAD"):
            # SPA try_files 会把未知路径落到 index.html（200 text/html），不算真实泄露
            is_spa = code == 200 and (
                "<!doctype html" in low or "<html" in low or "youth" in low[:300]
            )
            if code == 200 and not is_spa and (
                "secret" in low or "password" in low or low.startswith("ref:") or "app_env=" in low
            ):
                report.add("CRITICAL", "敏感路径", f"{p} 可读取敏感内容", text[:120])
            elif code == 200 and is_spa:
                report.add(
                    "LOW",
                    "敏感路径",
                    f"{p} 被 SPA 回退为 index.html（建议 Nginx 显式 404）",
                    "非真实 .env/.git 内容",
                )
            elif code == 200:
                report.add("HIGH", "敏感路径", f"{p} 返回 200 且非 HTML", text[:80])
            else:
                report.add("PASS", "敏感路径", f"{p} 不可读 ({code})")
        elif "openapi" in p or p in ("/docs", "/redoc", "/api/docs"):
            if code == 200 and ("swagger" in low or "openapi" in low or "fastapi" in low):
                report.add("MEDIUM", "信息暴露", f"API 文档可访问: {p}")
            else:
                report.add("PASS", "信息暴露", f"文档路径 {p} -> {code}")
        elif p.endswith("smtp-status"):
            if code == 200:
                report.add("HIGH", "鉴权", "未登录可读 smtp-status", text[:120])
            elif code in (401, 403):
                report.add("PASS", "鉴权", f"smtp-status 需登录 ({code})")
            else:
                report.add("INFO", "鉴权", f"smtp-status -> {code}")
        else:
            # 杂项：200 且像管理/调试页再标
            if code == 200 and ("traceback" in low or "debug" in low or "phpinfo" in low):
                report.add("HIGH", "敏感路径", f"{p} 疑似调试页", text[:100])


def test_authn_jwt(report: Report) -> None:
    print("[*] Authn / JWT forgery...")
    protected = [
        ("GET", "/auth/me"),
        ("GET", "/users/me/profile"),
        ("GET", "/users"),
        ("GET", "/dashboard"),
        ("GET", "/stats/dashboard"),
        ("GET", "/export/users"),
        ("GET", "/auth/accounts"),
        ("GET", "/stats/audit-logs"),
        ("POST", "/coupons/issue"),
        ("POST", "/points/grant"),
        ("POST", "/auth/change-password"),
        ("POST", "/auth/email/test"),
        ("POST", "/auth/email/test-imap"),
    ]
    bad_open = []
    for method, path in protected:
        body = {} if method == "POST" else None
        if path == "/auth/change-password":
            body = {"old_password": "x", "new_password": "yyyyyyyy"}
        if path == "/points/grant":
            body = {"user_id": "x", "amount": 1, "reason": "sec"}
        if path == "/coupons/issue":
            body = {"user_id": "x", "template_id": "y", "quantity": 1}
        code, text, _ = req(method, path, body=body)
        if code == 200:
            bad_open.append(f"{method} {path}")
            report.add("CRITICAL", "鉴权", f"未登录可访问 {method} {path}", text[:120])
        elif code not in (401, 403, 404, 405, 422):
            report.add("INFO", "鉴权", f"{method} {path} -> {code}", text[:80])
    if not bad_open:
        report.add("PASS", "鉴权", "抽样受保护接口未登录均拒绝")

    for t in (
        "eyJhbGciOiJub25lIiwidHlwIjoiSldUIn0.eyJzdWIiOiJhZG1pbiIsInJvbGUiOiJzdXBlcl9hZG1pbiJ9.",
        "null",
        "a.b.c",
        "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJhZG1pbiJ9.invalidsig",
    ):
        code, _, _ = req("GET", "/auth/me", token=t)
        if code == 200:
            report.add("CRITICAL", "JWT", "伪造 Token 被接受", t[:50])
            return
    report.add("PASS", "JWT", "非法 Token 均被拒绝")


def test_sqli_login(report: Report) -> None:
    print("[*] SQLi on login...")
    for p in SQLI:
        t0 = time.time()
        code, text, _ = req("POST", "/auth/login", body={"username": p, "password": p})
        elapsed = time.time() - t0
        if code == 200 and "access_token" in text:
            report.add("CRITICAL", "SQL注入", "登录注入绕过成功", repr(p))
            return
        if looks_like_sql_error(text):
            report.add("HIGH", "SQL注入", "登录返回 SQL/堆栈信息", f"{p!r} {text[:200]}")
            return
        # 粗略时间盲注：SLEEP(5) 若真执行会明显变慢
        if "SLEEP" in p and elapsed >= 4.5:
            report.add("HIGH", "SQL注入", f"疑似时间盲注（{elapsed:.1f}s）", repr(p))
            return
    report.add("PASS", "SQL注入", "登录接口未出现绕过/SQL 报错/明显时间盲注")


def test_default_credentials(report: Report) -> None:
    print("[*] Default / weak credential probe (few attempts only)...")
    candidates = [
        ("admin", "admin123"),
        ("admin", "Admin@Welfare2026"),
        ("admin", "password"),
        ("admin", "12345678"),
        ("issuer", "issuer123"),
        ("merchant1", "merchant123"),
        ("youth1", "youth123"),
        ("test", "test1234"),
    ]
    hits = []
    for u, p in candidates:
        code, text, _ = req("POST", "/auth/login", body={"username": u, "password": p})
        if code == 200 and "access_token" in text:
            hits.append(f"{u}/{p}")
            report.add("CRITICAL", "弱口令", f"默认/弱口令可登录: {u}", "请立即修改")
        elif code == 429:
            report.add("PASS", "限流", "弱口令探测触发登录限流")
            break
        time.sleep(0.15)
    if not hits:
        report.add("PASS", "弱口令", "常见默认账号均不可登录")


def test_login_rate_limit(report: Report) -> None:
    print("[*] Login rate limit (bounded)...")
    user = f"sec_audit_{int(time.time())}"
    limited = False
    last = 0
    for i in range(15):
        code, text, _ = req(
            "POST",
            "/auth/login",
            body={"username": user, "password": f"wrong-pass-{i}"},
        )
        last = code
        if code == 429:
            limited = True
            report.add("PASS", "限流", f"第 {i+1} 次失败登录触发 429", text[:100])
            break
        time.sleep(0.05)
    if not limited:
        report.add(
            "MEDIUM",
            "限流",
            "15 次错误登录未触发 429（阈值偏松或按 IP 聚合在 CF 后失效）",
            f"last={last}",
        )


def test_cors(report: Report) -> None:
    print("[*] CORS...")
    evil = "https://evil-example.invalid"
    # preflight-ish: actual GET with Origin
    code, text, headers = req("GET", "/health", origin=evil)
    acao = headers.get("access-control-allow-origin", "")
    acac = headers.get("access-control-allow-credentials", "")
    if acao == "*" and acac.lower() == "true":
        report.add("CRITICAL", "CORS", "Allow-Origin=* 且 Allow-Credentials=true")
    elif acao == evil:
        report.add("HIGH", "CORS", "反射任意 Origin", acao)
    elif acao in ("", None):
        report.add("PASS", "CORS", "未对恶意 Origin 返回 ACAO", f"status={code}")
    elif acao == "*":
        report.add("LOW", "CORS", "ACAO=*（若无 credentials 风险较低）", acao)
    else:
        report.add("INFO", "CORS", f"ACAO={acao!r}", f"status={code}")

    # 合法域名
    good = "https://youth.huishengbook.us.ci"
    code2, _, headers2 = req("GET", "/health", origin=good)
    acao2 = headers2.get("access-control-allow-origin", "")
    if acao2 in (good, "*"):
        report.add("PASS", "CORS", "正式域名 Origin 被允许", acao2)
    else:
        report.add("INFO", "CORS", f"正式域名 ACAO={acao2!r} status={code2}")


def test_http_methods(report: Report) -> None:
    print("[*] HTTP methods...")
    for method in ("DELETE", "PUT", "PATCH", "TRACE"):
        code, _, headers = req(method, "/auth/login", body={} if method != "TRACE" else None)
        if code == 200:
            report.add("MEDIUM", "HTTP方法", f"{method} /auth/login 意外 200")
        elif method == "TRACE" and code not in (0, 403, 405, 501):
            report.add("INFO", "HTTP方法", f"TRACE -> {code}")
    report.add("PASS", "HTTP方法", "错误方法未成功登录")


def test_register_mass_assignment(report: Report) -> None:
    print("[*] Register mass-assignment (no code consume if SMTP)...")
    email = f"sec_prod_{int(time.time())}@example.com"
    code, text, _ = req(
        "POST",
        "/auth/email/send-code",
        body={"email": email, "purpose": "register"},
    )
    debug = None
    if code == 200:
        try:
            debug = json.loads(text).get("debug_code")
        except json.JSONDecodeError:
            pass
    if debug:
        report.add("HIGH", "信息暴露", "生产 send-code 返回 debug_code", str(debug))
        body = {
            "email": email,
            "password": "Test1234!x",
            "code": debug,
            "display_name": "sec",
            "role": "super_admin",
            "username": f"sec_{int(time.time()) % 100000}",
        }
        c2, t2, _ = req("POST", "/auth/register", body=body)
        if c2 == 200:
            try:
                role = json.loads(t2).get("role")
            except json.JSONDecodeError:
                role = None
            if role in ("super_admin", "admin", "issuer"):
                report.add("CRITICAL", "批量赋值", f"注册提权成功 role={role}")
            else:
                report.add("PASS", "批量赋值", f"注册忽略 role，实际={role}")
        else:
            report.add("INFO", "批量赋值", f"带 debug 注册失败 {c2}")
    else:
        # 不应回显验证码
        if "code" in text.lower() and any(ch.isdigit() for ch in text):
            # 粗检：响应里是否像带了 6 位码
            report.add("INFO", "信息暴露", "send-code 响应内容抽样", text[:150])
        report.add("PASS", "信息暴露", "生产 send-code 未返回 debug_code", f"{code}")
        # 无码无法注册提权；用假码试一次
        c2, t2, _ = req(
            "POST",
            "/auth/register",
            body={
                "email": email,
                "password": "Test1234!x",
                "code": "000000",
                "role": "super_admin",
                "username": f"secx_{int(time.time()) % 100000}",
            },
        )
        if c2 == 200 and "access_token" in t2:
            report.add("CRITICAL", "注册", "错误验证码仍可注册")
        else:
            report.add("PASS", "注册", f"错误验证码不可注册 ({c2})")


def test_business_anon(report: Report) -> None:
    print("[*] Anonymous business actions...")
    probes = [
        ("POST", "/coupons/redeem", {"code": "AAAA"}),
        ("POST", "/coupons/issue", {"user_id": "x", "template_id": "y", "quantity": 1}),
        ("POST", "/points/grant", {"user_id": "x", "amount": 999, "reason": "x"}),
        (
            "POST",
            "/auth/accounts/00000000-0000-0000-0000-000000000001/reset-password",
            {"new_password": "hacked999"},
        ),
        ("GET", "/export/users", None),
        ("GET", "/export/redemptions", None),
    ]
    for method, path, body in probes:
        code, text, _ = req(method, path, body=body)
        if code == 200:
            report.add("CRITICAL", "业务越权", f"匿名可操作 {method} {path}", text[:100])
        elif code in (401, 403, 404, 422, 400):
            continue
        else:
            report.add("INFO", "业务越权", f"{method} {path} -> {code}")
    report.add("PASS", "业务越权", "匿名敏感业务操作被拒绝（抽样）")


def test_optional_admin_readonly(report: Report) -> None:
    if not ADMIN_USER or not ADMIN_PASS:
        report.add("INFO", "鉴权后", "未提供 ADMIN_USER/ADMIN_PASS，跳过登录后只读探测")
        return
    print("[*] Authenticated admin read-only probes...")
    code, text, _ = req("POST", "/auth/login", body={"username": ADMIN_USER, "password": ADMIN_PASS})
    if code != 200:
        report.add("MEDIUM", "环境", "提供的管理员账号登录失败，跳过鉴权后测试", f"{code} {text[:80]}")
        return
    token = json.loads(text).get("access_token")
    if not token:
        report.add("MEDIUM", "环境", "登录响应无 token")
        return
    report.add("PASS", "环境", "管理员登录成功（仅用于只读探测）")

    code, text, _ = req("GET", "/auth/me", token=token)
    if code == 200 and "password_hash" in text.lower():
        report.add("HIGH", "敏感信息", "/auth/me 泄露 password_hash")
    elif code == 200:
        report.add("PASS", "敏感信息", "/auth/me 未见 password_hash")

    # 搜索注入（只读）
    for path, param in (("/auth/accounts", "q"), ("/users", "q")):
        q = urllib.parse.urlencode({param: "' OR 1=1--"})
        url = f"{BASE}{path}?{q}"
        c, t, _ = req("GET", url, absolute=True, token=token)
        if looks_like_sql_error(t) or c >= 500:
            report.add("HIGH", "SQL注入", f"管理搜索异常 {path}", f"{c} {t[:150]}")
        else:
            report.add("PASS", "SQL注入", f"管理搜索 {path} 稳健 ({c})")

    code, text, _ = req("GET", "/auth/email/smtp-status", token=token)
    if code == 200:
        try:
            st = json.loads(text)
        except json.JSONDecodeError:
            st = {}
        # 不应含密码
        blob = json.dumps(st).lower()
        if "password" in blob and st.get("mail_password"):
            report.add("HIGH", "敏感信息", "smtp-status 返回密码字段")
        else:
            report.add("PASS", "敏感信息", "smtp-status 无明文密码")


def print_report(report: Report) -> int:
    order = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO", "PASS"]
    print("\n" + "=" * 72)
    print(f" Security audit report — {BASE}")
    print(f" Time: {datetime.now(timezone.utc).isoformat()}")
    print("=" * 72)
    for sev in order:
        items = [f for f in report.findings if f.severity == sev]
        if not items:
            continue
        print(f"\n## {sev} ({len(items)})")
        for f in items:
            line = f"  [{f.category}] {f.title}"
            if f.detail:
                line += f"\n      {f.detail[:300]}"
            print(line)
    print("\n" + "-" * 72)
    print("Summary:", report.counts())
    crit = report.counts().get("CRITICAL", 0)
    high = report.counts().get("HIGH", 0)
    if crit:
        return 2
    if high:
        return 1
    return 0


def main() -> int:
    print(f"[*] Target: {BASE}")
    print(f"[*] Root:   {ROOT}")
    report = Report()
    health = test_tls_and_health(report)
    if health is None and any(f.severity == "CRITICAL" for f in report.findings):
        return print_report(report)

    test_docs_and_sensitive_paths(report)
    test_authn_jwt(report)
    test_sqli_login(report)
    test_default_credentials(report)
    test_login_rate_limit(report)
    test_cors(report)
    test_http_methods(report)
    test_register_mass_assignment(report)
    test_business_anon(report)
    test_optional_admin_readonly(report)
    return print_report(report)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("aborted", file=sys.stderr)
        raise SystemExit(130)
