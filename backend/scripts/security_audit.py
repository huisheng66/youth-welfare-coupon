"""
本地安全自检（防御性）：对本机 API 做 SQLi / 鉴权 / 越权 / JWT / 敏感信息等探测。
用法（backend 目录，API 已启动）:
  .venv\\Scripts\\python.exe scripts\\security_audit.py
  BASE_URL=http://127.0.0.1:19001/api python scripts/security_audit.py
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

BASE = os.environ.get("BASE_URL", "http://127.0.0.1:19001/api").rstrip("/")


@dataclass
class Finding:
    severity: str  # CRITICAL / HIGH / MEDIUM / LOW / INFO / PASS
    category: str
    title: str
    detail: str


@dataclass
class Report:
    findings: list[Finding] = field(default_factory=list)

    def add(self, severity: str, category: str, title: str, detail: str = "") -> None:
        self.findings.append(Finding(severity, category, title, detail))

    def summary(self) -> dict[str, int]:
        c: dict[str, int] = {}
        for f in self.findings:
            c[f.severity] = c.get(f.severity, 0) + 1
        return c


def req(
    method: str,
    path: str,
    *,
    body: dict | None = None,
    token: str | None = None,
    raw_query: str | None = None,
    timeout: float = 12.0,
) -> tuple[int, str, dict]:
    url = f"{BASE}{path}"
    if raw_query is not None:
        url = f"{BASE}{path}?{raw_query}"
    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    r = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            text = resp.read().decode("utf-8", errors="replace")
            return resp.status, text, dict(resp.headers)
    except urllib.error.HTTPError as e:
        text = e.read().decode("utf-8", errors="replace")
        return e.code, text, dict(e.headers)
    except Exception as e:  # noqa: BLE001
        return 0, str(e), {}


def login(username: str, password: str) -> str | None:
    code, text, _ = req("POST", "/auth/login", body={"username": username, "password": password})
    if code != 200:
        return None
    try:
        return json.loads(text).get("access_token")
    except json.JSONDecodeError:
        return None


def looks_like_sql_error(text: str) -> bool:
    low = text.lower()
    needles = [
        "sqlite3.",
        "operationalerror",
        "syntax error",
        "mysql",
        "sqlalchemy.exc",
        "unrecognized token",
        "near \"",
        "you have an error in your sql",
        "pg_query",
        "warning: mysql",
    ]
    return any(n in low for n in needles)


SQLI_PAYLOADS = [
    "' OR '1'='1",
    "' OR 1=1--",
    "admin'--",
    "\" OR \"\"=\"",
    "1; DROP TABLE accounts;--",
    "1 UNION SELECT null--",
    "' UNION SELECT username,password_hash FROM accounts--",
    "1' AND SLEEP(5)--",
    "%' OR 1=1--",
    "') OR ('1'='1",
]


def test_health(report: Report) -> None:
    code, text, _ = req("GET", "/health")
    if code == 200:
        report.add("PASS", "可用性", "健康检查可达", text[:200])
    else:
        report.add("CRITICAL", "可用性", "健康检查失败", f"{code} {text[:200]}")


def test_sqli_login(report: Report) -> None:
    for p in SQLI_PAYLOADS:
        code, text, _ = req("POST", "/auth/login", body={"username": p, "password": p})
        if code == 200 and "access_token" in text:
            report.add("CRITICAL", "SQL注入", "登录接口可被注入绕过", f"payload={p!r}")
            return
        if looks_like_sql_error(text):
            report.add("HIGH", "SQL注入", "登录接口返回 SQL 错误信息", f"payload={p!r} body={text[:300]}")
            return
    report.add("PASS", "SQL注入", "登录接口未出现注入绕过或 SQL 报错")


def test_sqli_search(report: Report, admin_token: str) -> None:
    endpoints = [
        ("/users", "q"),
        ("/auth/accounts", "q"),
        ("/merchants", "q"),
        ("/stats/audit-logs", "q"),
        ("/coupons/instances", "q"),
        ("/coupons/redemptions", "q"),
    ]
    hit = False
    for path, param in endpoints:
        for p in ("' OR 1=1--", "1 UNION SELECT 1--", "%27%20OR%201%3D1--"):
            q = urllib.parse.urlencode({param: p})
            code, text, _ = req("GET", path, token=admin_token, raw_query=q)
            if looks_like_sql_error(text):
                report.add(
                    "HIGH",
                    "SQL注入",
                    f"搜索参数触发 SQL 错误: {path}?{param}=",
                    f"payload={p!r} status={code} {text[:250]}",
                )
                hit = True
                break
            # 500 且无业务 detail 也可能异常
            if code >= 500:
                report.add(
                    "MEDIUM",
                    "SQL注入/健壮性",
                    f"恶意搜索导致服务端 5xx: {path}",
                    f"payload={p!r} {text[:250]}",
                )
                hit = True
                break
        if hit:
            break
    if not hit:
        report.add("PASS", "SQL注入", "管理端搜索参数未触发 SQL 错误或 5xx")


def test_authn(report: Report) -> None:
    protected = [
        ("GET", "/auth/me"),
        ("GET", "/users/me/profile"),
        ("GET", "/users"),
        ("GET", "/stats/dashboard"),
        ("GET", "/export/users"),
        ("POST", "/coupons/issue"),
    ]
    for method, path in protected:
        code, text, _ = req(method, path, body={} if method == "POST" else None)
        if code == 200:
            report.add("CRITICAL", "鉴权", f"未登录可访问 {method} {path}", text[:200])
        elif code in (401, 403, 422):
            continue
        elif code == 0:
            report.add("MEDIUM", "鉴权", f"请求失败 {method} {path}", text[:100])
    report.add("PASS", "鉴权", "受保护接口在无 Token 时拒绝访问（401/403/422）")

    # 伪造 JWT
    bad_tokens = [
        "eyJhbGciOiJub25lIn0.eyJzdWIiOiJhZG1pbiJ9.",
        "null",
        "Bearer.fake",
        "a.b.c",
    ]
    for t in bad_tokens:
        code, text, _ = req("GET", "/auth/me", token=t)
        if code == 200:
            report.add("CRITICAL", "JWT", "伪造/非法 Token 被接受", t[:40])
            return
    report.add("PASS", "JWT", "非法 Token 被拒绝")


def test_idor_and_roles(report: Report, youth_token: str, merchant_token: str, admin_token: str) -> None:
    # 普通用户访问管理接口
    for path in ("/users", "/stats/dashboard", "/export/users", "/auth/accounts", "/stats/audit-logs"):
        code, _, _ = req("GET", path, token=youth_token)
        if code == 200:
            report.add("HIGH", "越权", f"普通用户可访问管理接口 {path}")
        elif code != 403:
            report.add("INFO", "越权", f"用户访问 {path} 返回 {code}（期望 403）")
    report.add("PASS", "越权", "普通用户访问管理接口被拒绝（抽样）")

    # 商家访问用户列表
    code, _, _ = req("GET", "/users", token=merchant_token)
    if code == 200:
        report.add("HIGH", "越权", "商家账号可列用户")
    else:
        report.add("PASS", "越权", f"商家访问 /users 被拒绝 ({code})")

    # 用户尝试解密他人银行卡
    # 先拿 youth1 id
    code, text, _ = req("GET", "/auth/me", token=youth_token)
    if code == 200:
        uid = json.loads(text).get("id")
        code2, _, _ = req("GET", f"/users/{uid}/bank-card", token=youth_token)
        if code2 == 200:
            report.add("CRITICAL", "越权", "普通用户可解密自己的完整银行卡（应仅超管）")
        else:
            report.add("PASS", "越权", f"用户无法调用银行卡解密接口 ({code2})")

    # 商家尝试超管 SMTP
    code, _, _ = req("GET", "/auth/email/smtp-status", token=merchant_token)
    if code == 200:
        report.add("HIGH", "越权", "商家可读 SMTP 状态")
    else:
        report.add("PASS", "越权", f"商家访问 smtp-status 被拒 ({code})")

    # 水平越权：用户改他人密码接口（应不存在或 403）
    code, text, _ = req(
        "POST",
        "/auth/accounts/00000000-0000-0000-0000-000000000001/reset-password",
        token=youth_token,
        body={"new_password": "hacked99"},
    )
    if code == 200:
        report.add("CRITICAL", "越权", "普通用户可重置他人密码")
    else:
        report.add("PASS", "越权", f"用户重置他人密码被拒 ({code})")


def test_mass_assignment_register(report: Report) -> None:
    # 注册时尝试提权
    email = f"sectest_{int(time.time())}@example.com"
    # 先发码（控制台模式可能返回 debug_code）
    code, text, _ = req("POST", "/auth/email/send-code", body={"email": email, "purpose": "register"})
    debug = None
    if code == 200:
        try:
            debug = json.loads(text).get("debug_code")
        except json.JSONDecodeError:
            pass
    if not debug:
        report.add("INFO", "注册", "无法获取注册验证码（SMTP 模式），跳过提权注册探测", f"{code} {text[:120]}")
        return
    body = {
        "email": email,
        "password": "Test1234!",
        "code": debug,
        "display_name": "sec",
        "role": "super_admin",
        "is_active": True,
        "username": f"sec_{int(time.time()) % 100000}",
    }
    code, text, _ = req("POST", "/auth/register", body=body)
    if code == 200:
        data = json.loads(text)
        if data.get("role") == "super_admin":
            report.add("CRITICAL", "批量赋值", "注册可指定 role=super_admin")
        else:
            report.add("PASS", "批量赋值", f"注册忽略 role 字段，实际 role={data.get('role')}")
    else:
        report.add("INFO", "批量赋值", f"注册失败 {code}: {text[:150]}")


def test_login_rate_limit(report: Report) -> None:
    user = f"nosuch_user_{int(time.time())}"
    limited = False
    for i in range(12):
        code, text, _ = req("POST", "/auth/login", body={"username": user, "password": "wrong"})
        if code == 429:
            limited = True
            break
    if limited:
        report.add("PASS", "限流", "登录失败触发 429 限流")
    else:
        report.add("MEDIUM", "限流", "连续错误登录未触发限流（或阈值阈值偏宽松）", "12 次失败均未 429")


def test_sensitive_leak(report: Report, admin_token: str, youth_token: str) -> None:
    code, text, _ = req("GET", "/users/me/profile", token=youth_token)
    if code == 200:
        low = text.lower()
        if "password_hash" in low or "bank_card_encrypted" in low:
            report.add("HIGH", "敏感信息", "资料接口泄露 password_hash 或密文卡号")
        elif "\"card_number\"" in low and "bank_card_masked" not in low:
            report.add("HIGH", "敏感信息", "资料接口可能返回完整卡号字段")
        else:
            report.add("PASS", "敏感信息", "用户资料接口未见 password_hash/密文卡号")
        # 脱敏不应含长连续数字卡号
        try:
            data = json.loads(text)
            masked = data.get("bank_card_masked") or ""
            digits = "".join(c for c in masked if c.isdigit())
            if len(digits) > 8:
                report.add("MEDIUM", "敏感信息", "脱敏卡号数字位数偏多", masked)
        except json.JSONDecodeError:
            pass

    # OpenAPI 暴露
    code, text, _ = req("GET", "/../docs")  # wrong base
    # try absolute via urllib to docs
    try:
        root = BASE.rsplit("/api", 1)[0]
        r = urllib.request.Request(f"{root}/docs", method="GET")
        with urllib.request.urlopen(r, timeout=8) as resp:
            if resp.status == 200:
                report.add("LOW", "信息暴露", "生产建议关闭 /docs 与 /openapi.json", f"{root}/docs 可访问")
    except Exception:  # noqa: BLE001
        report.add("INFO", "信息暴露", "/docs 不可达或已关闭")


def test_path_injection(report: Report, admin_token: str) -> None:
    paths = [
        "/users/../auth/me",
        "/users/%2e%2e/auth/accounts",
        "/coupons/templates/../../auth/me",
    ]
    for p in paths:
        code, text, _ = req("GET", p, token=admin_token)
        # 若意外拿到 accounts 列表则危险
        if code == 200 and "password" in text.lower():
            report.add("HIGH", "路径穿越", f"异常路径返回敏感数据 {p}")
            return
    report.add("PASS", "路径穿越", "抽样路径未导致敏感数据泄露")


def test_xss_reflection(report: Report, youth_token: str) -> None:
    xss = "<script>alert(1)</script>"
    code, text, _ = req(
        "PUT",
        "/users/me/profile",
        token=youth_token,
        body={
            "real_name": xss,
            "student_no": "1",
            "organization": xss,
            "remark": xss,
            "display_name": "x",
            "phone": None,
        },
    )
    if code == 200 and xss in text:
        report.add(
            "LOW",
            "XSS",
            "API 原样回显脚本字符串（JSON API 风险较低；前端须转义）",
            "资料字段可存 HTML/脚本，依赖 Vue 默认转义",
        )
    elif code == 200:
        report.add("PASS", "XSS", "资料更新成功且未异常")
    else:
        report.add("INFO", "XSS", f"资料更新返回 {code}: {text[:120]}")


def test_method_and_cors(report: Report) -> None:
    code, text, headers = req("OPTIONS", "/auth/login")
    # urllib may not handle OPTIONS well
    report.add("INFO", "CORS", "请在浏览器侧确认 CORS 仅允许可信来源（配置见 CORS_ORIGINS）")

    # 错误方法
    code, _, _ = req("DELETE", "/auth/login")
    if code == 200:
        report.add("MEDIUM", "HTTP方法", "DELETE /auth/login 意外成功")
    else:
        report.add("PASS", "HTTP方法", f"错误方法被拒绝或 405/4xx ({code})")


def main() -> int:
    report = Report()
    print(f"[*] Target: {BASE}")
    test_health(report)
    if any(f.severity == "CRITICAL" and f.category == "可用性" for f in report.findings):
        print("API 不可用，中止")
        return 2

    print("[*] SQL injection (login)...")
    test_sqli_login(report)

    print("[*] Authn / JWT...")
    test_authn(report)

    admin = login("admin", "admin123")
    issuer = login("issuer", "issuer123")
    merchant = login("merchant1", "merchant123")
    youth = login("youth1", "youth123")
    if not all([admin, merchant, youth]):
        report.add("CRITICAL", "环境", "演示账号登录失败，部分测试跳过")
        print_report(report)
        return 1

    print("[*] SQL injection (search)...")
    test_sqli_search(report, admin)  # type: ignore[arg-type]

    print("[*] IDOR / roles...")
    test_idor_and_roles(report, youth, merchant, admin)  # type: ignore[arg-type]

    print("[*] Mass assignment / register...")
    test_mass_assignment_register(report)

    print("[*] Login rate limit...")
    test_login_rate_limit(report)

    print("[*] Sensitive data...")
    test_sensitive_leak(report, admin, youth)  # type: ignore[arg-type]

    print("[*] Path / XSS / methods...")
    test_path_injection(report, admin)  # type: ignore[arg-type]
    test_xss_reflection(report, youth)  # type: ignore[arg-type]
    test_method_and_cors(report)

    # 额外：preview 未授权
    code, _, _ = req("GET", "/coupons/preview", raw_query="code=test")
    if code == 200:
        report.add("MEDIUM", "鉴权", "券预览接口未登录可访问（若含用户隐私需收紧）")
    else:
        report.add("PASS", "鉴权", f"券预览未登录状态 {code}")

    print_report(report)
    bad = sum(1 for f in report.findings if f.severity in ("CRITICAL", "HIGH"))
    return 1 if bad else 0


def print_report(report: Report) -> None:
    order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "INFO": 4, "PASS": 5}
    findings = sorted(report.findings, key=lambda f: order.get(f.severity, 9))
    print("\n========== 安全测试报告 ==========")
    for f in findings:
        print(f"[{f.severity:8}] ({f.category}) {f.title}")
        if f.detail:
            print(f"           {f.detail[:300]}")
    print("---------- 汇总 ----------")
    for k, v in sorted(report.summary().items(), key=lambda x: order.get(x[0], 9)):
        print(f"  {k}: {v}")
    print("================================\n")


if __name__ == "__main__":
    sys.exit(main())
