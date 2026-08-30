"""
Automated tests for 优化.md security hardening (P0–P1 + headers).

Run from backend/:
  .\\.venv\\Scripts\\python.exe -m pytest tests/test_security_hardening.py -v
  # or without pytest:
  .\\.venv\\Scripts\\python.exe tests/test_security_hardening.py
"""

from __future__ import annotations

import os
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
        self.assertIn("https://api.qrserver.com", conf)
        self.assertIn("gzip on", conf)
        self.assertIn("location ^~ /assets/", conf)
        self.assertIn("expires 1y", conf)


class TestAlembicUpgradePath(unittest.TestCase):
    def test_legacy_database_gets_post_baseline_indexes(self) -> None:
        from alembic import command
        from alembic.config import Config
        from sqlalchemy import inspect, text

        import app.core.database as dbmod
        from app.core.config import get_settings
        from app.core.migrate import LEGACY_BASELINE_REVISION, run_alembic_upgrade

        with tempfile.TemporaryDirectory() as td:
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

            indexes = {i["name"] for i in inspect(dbmod.engine).get_indexes("coupon_instances")}
            self.assertIn("ix_coupon_instances_status_expires_at", indexes)
            with dbmod.engine.connect() as conn:
                revision = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            self.assertEqual(revision, "7f21c3a8e6b1")
            dbmod.engine.dispose()

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
        # Template lives under docs/ci (OAuth tokens without workflow scope cannot push .github/workflows)
        wf = BACKEND_ROOT.parent / "docs" / "ci" / "security.yml"
        self.assertTrue(wf.is_file())
        text = wf.read_text(encoding="utf-8")
        self.assertIn("pip_audit", text)
        self.assertIn("npm audit", text)
        # CI 必须跑全量测试套件（含 hardening / import / performance），不是单文件
        self.assertIn("requirements-dev.txt", text)
        self.assertIn("pytest tests/", text)


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
