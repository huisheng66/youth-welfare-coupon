"""共享测试工具：fresh settings + 临时 SQLite engine + 已 seed 的 app。

Run from backend/:
  .\\.venv\\Scripts\\python.exe -m pytest tests/ -v
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def fresh_settings(**env: str):
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


def reset_env_defaults() -> None:
    """恢复非生产默认值，避免污染其它测试。"""
    fresh_settings(
        APP_ENV="development",
        SECRET_KEY="dev-secret-change-me-in-production",
        OPENAPI_ENABLED="true",
        CORS_ALLOW_LAN="true",
        SEED_DEMO_ACCOUNTS="true",
        ALLOW_INSECURE_SECRET="false",
        FIELD_ENCRYPTION_KEY="",
        FIELD_ENCRYPTION_KEY_PREVIOUS="",
        RATE_LIMIT_BACKEND="memory",
        GLOBAL_IP_MAX_REQUESTS="0",
        DATABASE_URL="sqlite:///./data/app.db",
        LOGIN_MAX_FAILS="8",
        LOGIN_WINDOW_SECONDS="300",
    )


def skip_app_lifespan(app) -> None:
    """用空 lifespan 覆盖 app，跳过 startup 副作用（建表/seed/expire 等）。

    替代旧 `app.router.on_startup.clear()`：lifespan 模式下 on_startup 已无效，
    需覆盖 `app.router.lifespan_context` 才能真正跳过。
    """
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _noop_lifespan(_):
        yield

    app.router.lifespan_context = _noop_lifespan


class TempApp:
    """临时 FastAPI app + 独立 SQLite 文件库，已 seed 演示数据。

    用法：
        with TempApp() as ta:
            client = ta.client()
            token = ta.login("admin", "admin123")
            r = client.get("/api/...", headers=ta.bearer(token))
    """

    def __init__(self) -> None:
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = Path(self.tmpdir) / "t.db"
        fresh_settings(
            APP_ENV="development",
            SECRET_KEY="test-secret-key-for-business-tests-32b",
            DATABASE_URL=f"sqlite:///{self.db_path.as_posix()}",
            SEED_DEMO_ACCOUNTS="true",
            RATE_LIMIT_BACKEND="memory",
            GLOBAL_IP_MAX_REQUESTS="0",
            OPENAPI_ENABLED="false",
            LOGIN_MAX_FAILS="50",  # 测试期间避免 429
            LOGIN_WINDOW_SECONDS="300",
            FIELD_ENCRYPTION_KEY="test-field-key-dedicated-xxx",
            # 禁用 SMTP，强制 console 模式（issue_email_code 返回 debug_code，不触发真实邮件发送）
            MAIL_SERVER=None,
            MAIL_USERNAME=None,
            MAIL_PASSWORD=None,
            MAIL_FROM=None,
        )
        # 用 init_engine 按测试 settings 重建 engine / SessionLocal，
        # 所有调用方经 `import app.core.database as db` 即可拿到测试 engine
        import app.core.database as dbmod
        from app.core.config import get_settings

        dbmod.init_engine(get_settings())
        self._dbmod = dbmod
        self.engine = dbmod.engine
        self.Session = dbmod.SessionLocal

        from app.core.database import Base
        import app.models  # noqa: F401  保证 mapper 注册

        Base.metadata.create_all(bind=self.engine)
        from app.seed import seed_if_empty
        from app.services.rate_limit import reset_limiters

        reset_limiters()
        s = self.Session()
        try:
            seed_if_empty(s)
        finally:
            s.close()

        from app.main import create_app

        self.app = create_app()
        # 跳过 lifespan startup 副作用（已手动建表 + seed）
        skip_app_lifespan(self.app)
        self._client = None

    # ---- context manager ----
    def __enter__(self) -> "TempApp":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ---- client ----
    def client(self):
        from fastapi.testclient import TestClient

        # 默认带 X-Requested-With，绕过 CSRF 中间件（前端 axios 全局也会加）
        return TestClient(self.app, headers={"X-Requested-With": "XMLHttpRequest"})

    # ---- auth helpers ----
    def login(self, username: str, password: str) -> str:
        """登录并返回 access_token。"""
        with self.client() as c:
            r = c.post("/api/auth/login", json={"username": username, "password": password})
            assert r.status_code == 200, f"login {username} failed: {r.status_code} {r.text}"
            return r.json()["access_token"]

    @staticmethod
    def bearer(token: str) -> dict:
        return {"Authorization": f"Bearer {token}"}

    # ---- db direct access ----
    def session(self):
        return self.Session()

    # ---- cleanup ----
    def close(self) -> None:
        try:
            from app.services.rate_limit import reset_limiters as _rl

            _rl()
        except Exception:
            pass
        if self.engine is not None:
            self.engine.dispose()
        shutil.rmtree(self.tmpdir, ignore_errors=True)
