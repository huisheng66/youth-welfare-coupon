"""
Automated tests for 优化.md security hardening (P0–P1 + headers).

Run from backend/:
  .\\.venv\\Scripts\\python.exe -m pytest tests/test_security_hardening.py -v
  # or without pytest:
  .\\.venv\\Scripts\\python.exe tests/test_security_hardening.py
"""

from __future__ import annotations

import os
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

# Ensure backend root on path
BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from tests._helpers import skip_app_lifespan  # noqa: E402


def _fresh_settings(**env: str):
    """Set env vars and clear settings / crypto / limiter caches."""
    from app.core.config import clear_settings_cache
    from app.services.crypto import clear_crypto_cache
    from app.services.rate_limit import reset_limiters

    for k, v in env.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    clear_settings_cache()
    clear_crypto_cache()
    reset_limiters()
    from app.core.config import get_settings

    return get_settings()


class TestProductionGuards(unittest.TestCase):
    def tearDown(self) -> None:
        # Restore non-production defaults for other tests
        _fresh_settings(
            APP_ENV="development",
            SECRET_KEY="dev-secret-change-me-in-production",
            OPENAPI_ENABLED="true",
            CORS_ALLOW_LAN="true",
            SEED_DEMO_ACCOUNTS="true",
            ALLOW_INSECURE_SECRET="false",
            FIELD_ENCRYPTION_KEY="",
            RATE_LIMIT_BACKEND="memory",
            GLOBAL_IP_MAX_REQUESTS="0",
        )

    def test_openapi_disabled_returns_404(self) -> None:
        _fresh_settings(
            APP_ENV="production",
            SECRET_KEY="production-strong-secret-key-32b",
            OPENAPI_ENABLED="false",
            SEED_DEMO_ACCOUNTS="false",
            CORS_ALLOW_LAN="false",
            GLOBAL_IP_MAX_REQUESTS="0",
            DATABASE_URL="sqlite:///:memory:",
        )
        from app.main import create_app
        from fastapi.testclient import TestClient

        app = create_app()
        # Disable startup seed/DB side effects for docs-only check
        skip_app_lifespan(app)
        client = TestClient(app)
        docs = client.get("/docs")
        self.assertEqual(docs.status_code, 404)
        self.assertEqual(
            docs.headers.get("strict-transport-security"),
            "max-age=31536000; includeSubDomains",
        )
        self.assertEqual(client.get("/openapi.json").status_code, 404)
        self.assertEqual(client.get("/redoc").status_code, 404)
        # 生产健康检查只暴露存活状态，不泄露环境/数据库/SMTP 指纹
        health = client.get("/api/health")
        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.json(), {"status": "ok"})

    def test_openapi_enabled_in_dev(self) -> None:
        _fresh_settings(
            APP_ENV="development",
            OPENAPI_ENABLED="true",
            GLOBAL_IP_MAX_REQUESTS="0",
            DATABASE_URL="sqlite:///:memory:",
        )
        from app.main import create_app
        from fastapi.testclient import TestClient

        app = create_app()
        skip_app_lifespan(app)
        client = TestClient(app)
        # FastAPI returns 200 HTML for /docs when enabled
        self.assertEqual(client.get("/docs").status_code, 200)
        self.assertEqual(client.get("/openapi.json").status_code, 200)

    def test_cors_rejects_evil_origin_without_lan(self) -> None:
        _fresh_settings(
            APP_ENV="production",
            SECRET_KEY="production-strong-secret-key-32b",
            CORS_ORIGINS="https://coupon.example.com",
            CORS_ALLOW_LAN="false",
            OPENAPI_ENABLED="false",
            SEED_DEMO_ACCOUNTS="false",
            GLOBAL_IP_MAX_REQUESTS="0",
            DATABASE_URL="sqlite:///:memory:",
        )
        from app.main import create_app
        from fastapi.testclient import TestClient

        app = create_app()
        skip_app_lifespan(app)
        client = TestClient(app)
        r = client.options(
            "/api/health",
            headers={
                "Origin": "https://evil.com",
                "Access-Control-Request-Method": "GET",
            },
        )
        # Starlette CORS: disallowed origin → no ACAO header
        self.assertNotEqual(r.headers.get("access-control-allow-origin"), "https://evil.com")
        self.assertIsNone(r.headers.get("access-control-allow-origin"))

        r2 = client.get("/api/health", headers={"Origin": "https://evil.com"})
        self.assertIsNone(r2.headers.get("access-control-allow-origin"))

        r3 = client.get("/api/health", headers={"Origin": "https://coupon.example.com"})
        self.assertEqual(r3.headers.get("access-control-allow-origin"), "https://coupon.example.com")

    def test_production_default_secret_blocked(self) -> None:
        from app.core.config import Settings, assert_secure_startup

        s = Settings(
            app_env="production",
            secret_key="dev-secret-change-me-in-production",
            allow_insecure_secret=False,
        )
        with self.assertRaises(RuntimeError):
            assert_secure_startup(s)

        s_ok = Settings(
            app_env="production",
            secret_key="production-strong-secret-key-32b",
            allow_insecure_secret=False,
        )
        assert_secure_startup(s_ok)  # no raise

    def test_seed_demo_gated(self) -> None:
        settings = _fresh_settings(
            APP_ENV="production",
            SECRET_KEY="production-strong-secret-key-32b",
            SEED_DEMO_ACCOUNTS="false",
        )
        self.assertFalse(settings.effective_seed_demo_accounts)
        settings2 = _fresh_settings(APP_ENV="development", SEED_DEMO_ACCOUNTS="true")
        self.assertTrue(settings2.effective_seed_demo_accounts)


class TestSanitize(unittest.TestCase):
    def test_strip_script(self) -> None:
        from app.services.sanitize import sanitize_note, sanitize_plain_text

        raw = "<script>alert(1)</script>"
        cleaned = sanitize_plain_text(raw)
        self.assertNotIn("<", cleaned)
        self.assertNotIn(">", cleaned)
        self.assertNotIn("script", cleaned.lower() + "x")  # tags stripped
        # After tag strip, "alert(1)" may remain — that is OK (not executable HTML)
        self.assertNotEqual(cleaned, raw)
        note = sanitize_note(raw)
        self.assertNotIn("<script>", note)
        self.assertNotIn("</script>", note)

    def test_profile_schema_sanitizes(self) -> None:
        from app.schemas.user import ProfileUpdateIn, SubmitVerificationIn

        body = ProfileUpdateIn(
            real_name="<script>alert(1)</script>",
            organization="Org<>X",
            remark="hi<script>x</script>",
            display_name="<b>bad</b>",
            student_no="2024<>",
        )
        self.assertNotIn("<", body.real_name)
        self.assertNotIn(">", body.real_name)
        self.assertNotIn("<", body.organization)
        self.assertNotIn("<", body.remark)
        self.assertNotIn("<", body.display_name or "")
        mat = SubmitVerificationIn(material_note="<script>alert(1)</script> note")
        self.assertNotIn("<script>", mat.material_note)

    def test_password_min_8(self) -> None:
        from pydantic import ValidationError

        from app.schemas.auth import ChangePasswordIn, RegisterIn, ResetPasswordByEmailIn

        with self.assertRaises(ValidationError):
            ChangePasswordIn(old_password="oldpass1", new_password="short")
        ChangePasswordIn(old_password="oldpass1", new_password="longenough")

        with self.assertRaises(ValidationError):
            ResetPasswordByEmailIn(
                email="a@b.com", code="123456", new_password="1234567"
            )


class TestCryptoKeySplit(unittest.TestCase):
    def tearDown(self) -> None:
        _fresh_settings(
            SECRET_KEY="dev-secret-change-me-in-production",
            FIELD_ENCRYPTION_KEY="",
            FIELD_ENCRYPTION_KEY_PREVIOUS="",
            APP_ENV="development",
        )

    def test_field_key_survives_jwt_rotation(self) -> None:
        _fresh_settings(
            SECRET_KEY="jwt-secret-version-one-aaaa",
            FIELD_ENCRYPTION_KEY="dedicated-field-key-bbbbbbbb",
        )
        from app.services.crypto import clear_crypto_cache, decrypt_text, encrypt_text

        clear_crypto_cache()
        cipher = encrypt_text("6222021234567890123")

        # Rotate only JWT secret
        _fresh_settings(
            SECRET_KEY="jwt-secret-version-two-zzzz",
            FIELD_ENCRYPTION_KEY="dedicated-field-key-bbbbbbbb",
        )
        clear_crypto_cache()
        plain = decrypt_text(cipher)
        self.assertEqual(plain, "6222021234567890123")

    def test_fallback_uses_secret_key(self) -> None:
        _fresh_settings(
            SECRET_KEY="only-secret-for-both-xxxx",
            FIELD_ENCRYPTION_KEY="",
        )
        from app.services.crypto import clear_crypto_cache, decrypt_text, encrypt_text

        clear_crypto_cache()
        with self.assertWarns(DeprecationWarning):
            # encrypt triggers MultiFernet build which warns
            clear_crypto_cache()
            cipher = encrypt_text("6222021234567890123")
        plain = decrypt_text(cipher)
        self.assertEqual(plain, "6222021234567890123")


class TestRateLimiter(unittest.TestCase):
    def test_memory_blocks_after_threshold(self) -> None:
        from app.services.rate_limit import MemoryRateLimiter

        lim = MemoryRateLimiter(window_sec=60, max_hits=3)
        key = "ip|user"
        for _ in range(3):
            ok, _ = lim.check(key)
            self.assertTrue(ok)
            lim.hit(key)
        ok, retry = lim.check(key)
        self.assertFalse(ok)
        self.assertGreaterEqual(retry, 1)
        lim.clear(key)
        ok, _ = lim.check(key)
        self.assertTrue(ok)
        self.assertEqual(lim.count(key), 0)

    def test_file_shared_across_instances(self) -> None:
        """Simulate multi-worker: two limiter instances, same SQLite file."""
        from app.services.rate_limit import FileRateLimiter

        with tempfile.TemporaryDirectory() as td:
            path = str(Path(td) / "rl.db")
            a = FileRateLimiter(path, window_sec=60, max_hits=5)
            b = FileRateLimiter(path, window_sec=60, max_hits=5)
            key = "10.0.0.1|attacker"
            for i in range(5):
                # alternate workers
                lim = a if i % 2 == 0 else b
                ok, _ = lim.check(key)
                self.assertTrue(ok, f"hit {i} should be allowed")
                lim.hit(key)
            ok, retry = a.check(key)
            self.assertFalse(ok)
            self.assertGreaterEqual(retry, 1)
            ok2, _ = b.check(key)
            self.assertFalse(ok2)
            a.clear(key)
            self.assertTrue(b.check(key)[0])

    def test_file_acquire_is_atomic_across_instances(self) -> None:
        from concurrent.futures import ThreadPoolExecutor

        from app.services.rate_limit import FileRateLimiter

        with tempfile.TemporaryDirectory() as td:
            path = str(Path(td) / "rl.db")
            limiters = [FileRateLimiter(path, window_sec=60, max_hits=5) for _ in range(4)]
            key = "atomic-client"

            def acquire(i: int) -> bool:
                return limiters[i % len(limiters)].acquire(key)[0]

            with ThreadPoolExecutor(max_workers=12) as pool:
                allowed = list(pool.map(acquire, range(20)))

            self.assertEqual(sum(allowed), 5)
            self.assertEqual(limiters[0].count(key), 5)

    def test_login_endpoint_returns_429(self) -> None:
        """Hit shipped /api/auth/login until 429; success path clears counter."""
        td = tempfile.mkdtemp()
        engine = None
        try:
            db_path = Path(td) / "t.db"
            rl_path = Path(td) / "rl.db"
            _fresh_settings(
                APP_ENV="development",
                SECRET_KEY="test-secret-key-for-login-rl-01",
                DATABASE_URL=f"sqlite:///{db_path.as_posix()}",
                SEED_DEMO_ACCOUNTS="true",
                RATE_LIMIT_BACKEND="file",
                RATE_LIMIT_FILE_PATH=str(rl_path),
                LOGIN_MAX_FAILS="3",
                LOGIN_WINDOW_SECONDS="300",
                GLOBAL_IP_MAX_REQUESTS="0",
                OPENAPI_ENABLED="false",
            )
            import app.core.database as dbmod
            from sqlalchemy import create_engine
            from sqlalchemy.orm import sessionmaker
            from sqlalchemy.pool import StaticPool

            engine = create_engine(
                f"sqlite:///{db_path.as_posix()}",
                connect_args={"check_same_thread": False},
                poolclass=StaticPool,
            )
            Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
            dbmod.engine = engine
            dbmod.SessionLocal = Session

            from app.core.database import Base
            import app.models  # noqa: F401

            Base.metadata.create_all(bind=engine)
            from app.seed import seed_if_empty

            s = Session()
            try:
                seed_if_empty(s)
            finally:
                s.close()

            from app.main import create_app
            from app.services.rate_limit import get_login_limiter, reset_limiters
            from fastapi.testclient import TestClient

            reset_limiters()
            app = create_app()
            skip_app_lifespan(app)
            with TestClient(app, headers={"X-Requested-With": "XMLHttpRequest"}) as client:
                user = "admin"
                for i in range(3):
                    r = client.post(
                        "/api/auth/login",
                        json={"username": user, "password": "wrong-password-xx"},
                    )
                    self.assertEqual(r.status_code, 400, f"fail {i}: {r.text}")

                r429 = client.post(
                    "/api/auth/login",
                    json={"username": user, "password": "wrong-password-xx"},
                )
                self.assertEqual(r429.status_code, 429, r429.text)
                self.assertIn("Retry-After", r429.headers)

                lim = get_login_limiter()
                # key 格式需与 auth._login_user_key / _login_ip_key 一致
                lim.clear(f"u:{user}")
                for ip in ("testclient", "127.0.0.1", "unknown"):
                    lim.clear(f"ip:{ip}")

                ok = client.post(
                    "/api/auth/login",
                    json={"username": user, "password": "admin123"},
                )
                self.assertEqual(ok.status_code, 200, ok.text)
                self.assertIn("access_token", ok.json())
                # Success cleared the counter — one more fail is 400 not 429
                r_again = client.post(
                    "/api/auth/login",
                    json={"username": user, "password": "still-wrong"},
                )
                self.assertEqual(r_again.status_code, 400)
        finally:
            try:
                from app.services.rate_limit import reset_limiters as _rl

                _rl()
            except Exception:
                pass
            if engine is not None:
                engine.dispose()
            import shutil

            shutil.rmtree(td, ignore_errors=True)


class TestSecurityHeadersAndHealth(unittest.TestCase):
    def tearDown(self) -> None:
        _fresh_settings(
            APP_ENV="development",
            SECRET_KEY="dev-secret-change-me-in-production",
            GLOBAL_IP_MAX_REQUESTS="0",
            RATE_LIMIT_BACKEND="memory",
            SEED_DEMO_ACCOUNTS="false",
            DATABASE_URL="sqlite:///:memory:",
        )

    def test_headers_and_health(self) -> None:
        _fresh_settings(
            APP_ENV="development",
            OPENAPI_ENABLED="false",
            GLOBAL_IP_MAX_REQUESTS="0",
            SEED_DEMO_ACCOUNTS="false",
            RATE_LIMIT_BACKEND="memory",
            DATABASE_URL="sqlite:///:memory:",
        )
        from app.main import create_app
        from fastapi.testclient import TestClient

        app = create_app()
        skip_app_lifespan(app)
        client = TestClient(app)
        r = client.get("/api/health")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json().get("status"), "ok")
        self.assertEqual(r.headers.get("x-content-type-options"), "nosniff")
        self.assertEqual(r.headers.get("x-frame-options"), "DENY")
        self.assertEqual(r.headers.get("referrer-policy"), "strict-origin-when-cross-origin")
        self.assertEqual(r.headers.get("permissions-policy"), "camera=(self), microphone=(), geolocation=()")

        valid = client.get("/api/health", headers={"X-Request-ID": "trace-123"})
        self.assertEqual(valid.headers.get("x-request-id"), "trace-123")
        invalid = client.get("/api/health", headers={"X-Request-ID": "../../bad id"})
        self.assertRegex(invalid.headers.get("x-request-id", ""), r"^[0-9a-f]{12}$")

        auth = client.get("/api/auth/me")
        self.assertEqual(auth.status_code, 401)
        self.assertEqual(auth.headers.get("cache-control"), "no-store")
        self.assertEqual(auth.headers.get("pragma"), "no-cache")


class TestCsvExportSafety(unittest.TestCase):
    def test_formula_prefixes_are_neutralized(self) -> None:
        from app.api.export import _safe_csv_cell

        for value in (
            "=1+1",
            "+SUM(A1:A2)",
            "-2+3",
            "@cmd",
            "  =HYPERLINK(\"https://example.invalid\")",
            "\t=1+1",
            "\r@cmd",
        ):
            self.assertEqual(_safe_csv_cell(value), "'" + value)
        self.assertEqual(_safe_csv_cell("normal text"), "normal text")
        self.assertEqual(_safe_csv_cell("  normal text"), "  normal text")
        self.assertEqual(_safe_csv_cell(12), 12)


class TestFrontendNoVHtml(unittest.TestCase):
    def test_no_vhtml_on_user_fields(self) -> None:
        frontend_src = BACKEND_ROOT.parent / "frontend" / "src"
        self.assertTrue(frontend_src.is_dir())
        hits: list[str] = []
        for path in frontend_src.rglob("*.vue"):
            text = path.read_text(encoding="utf-8")
            if "v-html" in text:
                hits.append(str(path.relative_to(frontend_src.parent)))
        for path in frontend_src.rglob("*.js"):
            text = path.read_text(encoding="utf-8")
            if "v-html" in text:
                hits.append(str(path.relative_to(frontend_src.parent)))
        self.assertEqual(hits, [], f"v-html found: {hits}")


class TestEnvExampleDocumentsKeys(unittest.TestCase):
    def test_env_example_has_dual_keys(self) -> None:
        example = (BACKEND_ROOT / ".env.example").read_text(encoding="utf-8")
        self.assertIn("FIELD_ENCRYPTION_KEY", example)
        self.assertIn("SECRET_KEY", example)
        self.assertIn("OPENAPI_ENABLED", example)
        self.assertIn("CORS_ALLOW_LAN", example)
        self.assertIn("SEED_DEMO_ACCOUNTS", example)
        self.assertIn("APP_ENV", example)

    def test_nginx_blocks_docs(self) -> None:
        conf = (BACKEND_ROOT.parent / "deploy" / "nginx-welfare.conf").read_text(encoding="utf-8")
        self.assertIn("location = /docs", conf)
        self.assertIn("return 404", conf)
        self.assertIn("X-Content-Type-Options", conf)
        self.assertIn("Content-Security-Policy", conf)
        # 券码只在本机渲染，CSP 不得放行第三方 QR 服务
        self.assertNotIn("qrserver.com", conf)
        self.assertIn("gzip on", conf)
        self.assertIn("location ^~ /assets/", conf)
        self.assertIn("expires 1y", conf)


class TestAlembicUpgradePath(unittest.TestCase):
    def test_legacy_database_gets_post_baseline_indexes(self) -> None:
        from alembic import command
        from alembic.config import Config
        from alembic.script import ScriptDirectory
        from sqlalchemy import inspect, text

        import app.core.database as dbmod
        from app.core.config import get_settings
        from app.core.migrate import LEGACY_BASELINE_REVISION, run_alembic_upgrade

        td = tempfile.mkdtemp()
        try:
            db_path = Path(td) / "legacy.db"
            _fresh_settings(
                APP_ENV="development",
                DATABASE_URL=f"sqlite:///{db_path.as_posix()}",
                GLOBAL_IP_MAX_REQUESTS="0",
            )
            dbmod.init_engine(get_settings())
            cfg = Config(str(BACKEND_ROOT / "alembic.ini"))
            cfg.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
            cfg.set_main_option("prepend_sys_path", str(BACKEND_ROOT))
            command.upgrade(cfg, LEGACY_BASELINE_REVISION)
            with dbmod.engine.begin() as conn:
                conn.execute(text("DROP TABLE alembic_version"))

            run_alembic_upgrade()

            # head 从迁移图推导：新增增量迁移落地后本用例无需同步改版本号
            heads = ScriptDirectory(str(BACKEND_ROOT / "alembic")).get_heads()
            self.assertEqual(len(heads), 1, f"迁移链必须保持单一 head，实际: {heads}")
            indexes = {i["name"] for i in inspect(dbmod.engine).get_indexes("coupon_instances")}
            self.assertIn("ix_coupon_instances_status_expires_at", indexes)
            account_cols = {c["name"] for c in inspect(dbmod.engine).get_columns("accounts")}
            self.assertIn("session_version", account_cols)
            self.assertIn("must_change_password", account_cols)
            with dbmod.engine.connect() as conn:
                revision = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            self.assertEqual(revision, heads[0])
        finally:
            # 必须先释放 SQLite 文件句柄再删临时目录，否则 Windows 下 rmtree 报 WinError 32
            dbmod.engine.dispose()
            shutil.rmtree(td, ignore_errors=True)
            _fresh_settings(APP_ENV="development", DATABASE_URL="sqlite:///./data/app.db")
            dbmod.init_engine(get_settings())


class TestPhase4Artifacts(unittest.TestCase):
    """7b/7c/7e: docs, dep audit scripts, ZAP helpers, CI workflow."""

    def test_security_ops_docs(self) -> None:
        root = BACKEND_ROOT.parent
        ops = (root / "docs" / "security-ops.md").read_text(encoding="utf-8")
        self.assertIn("localStorage", ops)
        self.assertIn("HttpOnly", ops)
        self.assertIn("pip-audit", ops)
        self.assertIn("ZAP", ops)

    def test_dep_audit_scripts_exist(self) -> None:
        root = BACKEND_ROOT.parent
        self.assertTrue((root / "scripts" / "dep_audit.ps1").is_file())
        self.assertTrue((root / "scripts" / "dep_audit.sh").is_file())
        self.assertTrue((root / "scripts" / "zap-baseline.ps1").is_file())
        self.assertTrue((root / "scripts" / "zap-baseline.sh").is_file())

    def test_github_security_workflow(self) -> None:
        # 模板在 docs/ci（历史遗留：旧 OAuth 令牌无 workflow scope 时无法直接推 .github）；
        # 现已落地为 .github/workflows/security.yml，两份必须保持一致
        wf = BACKEND_ROOT.parent / "docs" / "ci" / "security.yml"
        self.assertTrue(wf.is_file())
        text = wf.read_text(encoding="utf-8")
        self.assertIn("pip_audit", text)
        self.assertIn("npm audit", text)
        # CI 必须跑全量测试套件（含 hardening / import / performance），不是单文件
        self.assertIn("requirements-dev.txt", text)
        self.assertIn("pytest tests/", text)

        live = BACKEND_ROOT.parent / ".github" / "workflows" / "security.yml"
        self.assertTrue(live.is_file(), "CI workflow 必须在 .github/workflows 下真正生效")
        self.assertEqual(
            live.read_text(encoding="utf-8"),
            text,
            "docs/ci/security.yml 与 .github/workflows/security.yml 必须同步",
        )


class TestDeployNoHardcodedSecrets(unittest.TestCase):
    """deploy/、scripts/ 的 shell 脚本禁止字面密码，一律经环境变量注入。

    历史版本曾把 SSH/SMTP/管理员密码硬编码进脚本并进入 git 历史（已要求轮换，
    见 deploy/README.md「凭据注入与轮换」）。以下结构规则防止再次引入。
    """

    @staticmethod
    def _sh_files() -> list[Path]:
        root = BACKEND_ROOT.parent
        files: list[Path] = []
        for sub in ("deploy", "scripts"):
            base = root / sub
            if base.is_dir():
                files.extend(sorted(base.rglob("*.sh")))
        return files

    def test_sshpass_never_receives_literal(self) -> None:
        pattern = re.compile(r"sshpass\s+(?:-\S+\s+)*-p\s*['\"](?!\$)")
        for path in self._sh_files():
            for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                self.assertIsNone(
                    pattern.search(line),
                    f"{path.relative_to(BACKEND_ROOT.parent)}:{lineno}: sshpass 密码须来自环境变量",
                )

    def test_password_assignments_are_env_derived(self) -> None:
        assign = re.compile(
            r"^\s*(?:export\s+)?([A-Z0-9_]*(?:PASS|PASSWORD|TOKEN|SECRET)[A-Z0-9_]*)\s*=\s*(.+?)\s*$"
        )
        for path in self._sh_files():
            for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                m = assign.match(line)
                if not m:
                    continue
                name, value = m.group(1), m.group(2)
                if name.endswith(("_MINUTES", "_SECONDS", "_DAYS")):
                    continue  # 过期时长等含 TOKEN/SECRET 字样但非机密的配置
                stripped = value.strip().strip('"').strip("'")
                ok = (
                    stripped.startswith("$")
                    or stripped == ""
                    or (value.startswith('"') and "${" in value)
                )
                self.assertTrue(
                    ok,
                    f"{path.relative_to(BACKEND_ROOT.parent)}:{lineno}: {name} 疑似字面密码赋值",
                )

    def test_set_kv_password_is_env_derived(self) -> None:
        # config-smtp-prod.sh 的 set_kv KEY VALUE 形式
        pattern = re.compile(r"set_kv\s+[A-Za-z_]*PASSWORD[A-Za-z_]*\s+['\"](?!\$)")
        for path in self._sh_files():
            for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                self.assertIsNone(
                    pattern.search(line),
                    f"{path.relative_to(BACKEND_ROOT.parent)}:{lineno}: set_kv 密码须来自环境变量",
                )

    def test_no_leaked_admin_password_prefix(self) -> None:
        """曾泄露的超管密码前缀不得再出现在 deploy 与后端审计脚本中。"""
        root = BACKEND_ROOT.parent
        targets = list((root / "deploy").rglob("*")) if (root / "deploy").is_dir() else []
        targets += list((root / "backend" / "scripts").glob("*.py"))
        for path in targets:
            if not path.is_file() or path.suffix not in {".sh", ".py", ".md", ".sql", ".conf"}:
                continue
            self.assertNotIn(
                "Admin@",
                path.read_text(encoding="utf-8", errors="ignore"),
                f"{path.relative_to(root)}: 疑似残留真实管理员口令",
            )


class TestSensitiveFileGuard(unittest.TestCase):
    """T07：本地敏感文件不得被普通批量 add 意外纳入版本库；示例配置保持可追踪。"""

    @staticmethod
    def _git_ignored(rel: str) -> bool:
        import subprocess

        proc = subprocess.run(
            ["git", "check-ignore", "-q", rel],
            cwd=str(BACKEND_ROOT.parent),
            capture_output=True,
        )
        return proc.returncode == 0

    def test_local_secrets_are_ignored(self) -> None:
        for rel in (
            ".env",
            ".env.local",
            "secrets/mail-credentials.txt",
            "db-backup.sql",
            "deploy/smtp.local.sh",
        ):
            self.assertTrue(self._git_ignored(rel), f"{rel} 必须被 .gitignore 忽略")

    def test_example_config_stays_trackable(self) -> None:
        self.assertFalse(self._git_ignored("backend/.env.example"), "示例配置必须保持可追踪")

    def test_secret_scan_detects_and_redacts(self) -> None:
        import importlib.util

        script = BACKEND_ROOT.parent / "scripts" / "scan_staged_secrets.py"
        self.assertTrue(script.is_file(), "暂存密钥扫描脚本必须存在")
        spec = importlib.util.spec_from_file_location("scan_staged_secrets", script)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        targets = [
            ("app/config.py", 12, 'SECRET_KEY = "a-really-long-hardcoded-secret-xx"'),
            ("deploy/x.sh", 3, 'DB_PASSWORD="literal-pass-123"'),
        ]
        findings = mod.scan(targets)
        self.assertEqual(len(findings), 2, findings)
        # 输出脱敏：只有路径、行号与规则名，绝不回显疑似凭据内容
        joined = "\n".join(findings)
        self.assertNotIn("a-really-long-hardcoded-secret", joined)
        self.assertNotIn("literal-pass-123", joined)
        # 环境变量注入与 allow 标记不报
        clean = mod.scan(
            [
                ("deploy/x.sh", 3, 'DB_PASSWORD="${DB_PASSWORD}" # secret-scan:allow demo'),
                ("app/x.py", 1, 'SECRET_KEY = os.environ["SECRET_KEY"]'),
            ]
        )
        self.assertEqual(clean, [])

    def test_secret_scan_covers_project_credential_formats(self) -> None:
        """F04：项目实际使用的 mysql+pymysql:// 与 SSH_PASS 形式必须被扫描覆盖。"""
        import importlib.util

        script = BACKEND_ROOT.parent / "scripts" / "scan_staged_secrets.py"
        spec = importlib.util.spec_from_file_location("scan_staged_secrets", script)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        targets = [
            ("app/config.py", 9, 'DATABASE_URL="mysql+pymysql://review:synthetic-pass-99@localhost:3306/welfare"'),
            ("deploy/run.sh", 4, 'SSH_PASS="synthetic-pass-99"'),
            ("deploy/run.sh", 5, 'DB_PASS="synthetic-pass-99"'),
        ]
        findings = mod.scan(targets)
        self.assertEqual(len(findings), 3, findings)
        rules = {f.split(": ", 1)[1] for f in findings}
        self.assertIn("db-url-with-credentials", rules)
        self.assertIn("password-assign-literal", rules)
        # 合成凭据不得回显
        self.assertNotIn("synthetic-pass-99", "\n".join(findings))

    def test_secret_scan_exit_codes_as_gate(self) -> None:
        """F04 补测：以子进程验证扫描脚本退出码——命中 1、干净 0。"""
        import subprocess
        import tempfile as _tempfile

        script = BACKEND_ROOT.parent / "scripts" / "scan_staged_secrets.py"
        with _tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            def git(*args: str) -> None:
                subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)

            git("init", "-q")
            git("config", "user.email", "test@example.invalid")
            git("config", "user.name", "test")
            git("config", "commit.gpgsign", "false")
            (repo / "README.md").write_text("demo\n", encoding="utf-8")
            git("add", "README.md")
            git("commit", "-qm", "init")

            # 干净暂存区 → 退出 0
            proc = subprocess.run(
                ["python", str(script), "--cwd", str(repo)],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
            )
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

            # 暂存一个含 mysql+pymysql 凭据的文件 → 退出 1 且不回显内容
            (repo / "config.py").write_text(
                'DATABASE_URL = "mysql+pymysql://review:synthetic-pass-99@localhost:3306/welfare"\n',
                encoding="utf-8",
            )
            git("add", "config.py")
            proc = subprocess.run(
                ["python", str(script), "--cwd", str(repo)],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
            )
            self.assertEqual(proc.returncode, 1, proc.stdout)
            self.assertIn("db-url-with-credentials", proc.stdout)
            self.assertNotIn("synthetic-pass-99", proc.stdout)


class TestProfileWritePathSanitizes(unittest.TestCase):
    """Drive real schema + sanitize path used by PUT /users/me/profile."""

    def test_update_payload_never_stores_raw_script(self) -> None:
        from app.schemas.user import ProfileUpdateIn
        from app.services.sanitize import contains_raw_markup

        payload = {
            "real_name": "<script>alert(1)</script>",
            "organization": "<img onerror=alert(1)>",
            "remark": "<>xss",
            "display_name": "<svg/onload=alert(1)>",
            "student_no": "S<script>",
            "phone": None,
        }
        body = ProfileUpdateIn(**payload)
        for field in ("real_name", "organization", "remark", "display_name", "student_no"):
            val = getattr(body, field)
            if val is None:
                continue
            self.assertFalse(contains_raw_markup(val), f"{field} still has markup: {val!r}")
            self.assertNotIn("<script>", val)
            self.assertNotEqual(val, payload[field])


def main() -> int:
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromModule(sys.modules[__name__])
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
