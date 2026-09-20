"""开发路径 schema 统一走 alembic 的回归测试。

开发环境不再使用 create_all + ensure_schema 双轨：apply_migrations(dev)
等价于 `alembic upgrade head`（空库全量建表 / 历史 create_all 库 stamp
baseline 后增量），随后只读校验。本文件锁住三个契约：

1. 空库 → 迁移链能独立建出与 ORM metadata 一致的全部表；
2. 历史 create_all 库（无 alembic_version）→ 自动 stamp + upgrade；
3. dev 启动后 verify_schema_current 必须通过（启动即失败，快速暴露漂移）。

Run from backend/:
  .venv/bin/python -m pytest tests/test_dev_migrations.py -v
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]


class TestDevMigrationsViaAlembic(unittest.TestCase):
    def setUp(self) -> None:
        self._td = tempfile.mkdtemp()
        self._db_path = Path(self._td) / "dev.db"

    def tearDown(self) -> None:
        # 先释放 SQLite 文件句柄再删临时目录（Windows 下直接 rmtree 会报 WinError）
        import app.core.database as dbmod
        from tests._helpers import fresh_settings

        dbmod.engine.dispose()
        shutil.rmtree(self._td, ignore_errors=True)
        s = fresh_settings(APP_ENV="development", DATABASE_URL="sqlite:///./data/app.db")
        dbmod.init_engine(s)

    def _init_engine_at_temp_db(self, **extra_env: str) -> None:
        import app.core.database as dbmod
        from tests._helpers import fresh_settings

        s = fresh_settings(
            APP_ENV="development",
            DATABASE_URL=f"sqlite:///{self._db_path.as_posix()}",
            SEED_DEMO_ACCOUNTS="true",
            GLOBAL_IP_MAX_REQUESTS="0",
            RATE_LIMIT_BACKEND="memory",
            **extra_env,
        )
        dbmod.init_engine(s)

    def _db_tables(self) -> set[str]:
        from sqlalchemy import inspect

        import app.core.database as dbmod

        return set(inspect(dbmod.engine).get_table_names()) - {"alembic_version"}

    def test_empty_database_builds_metadata_equivalent_schema(self) -> None:
        """空库 → 迁移链独立建表，表集合与 ORM metadata 完全一致。"""
        from sqlalchemy import text

        import app.core.database as dbmod
        import app.models  # noqa: F401  注册 ORM 模型
        from app.core.database import Base
        from app.core.migrate import apply_migrations, verify_schema_current

        self._init_engine_at_temp_db()
        apply_migrations(dbmod.engine, production=False)
        verify_schema_current(dbmod.engine)

        expected = set(Base.metadata.tables.keys())
        actual = self._db_tables()
        self.assertEqual(
            actual,
            expected,
            f"迁移链与 ORM metadata 不一致；缺失: {sorted(expected - actual)}，多出: {sorted(actual - expected)}",
        )

        with dbmod.engine.connect() as conn:
            revision = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        self.assertEqual(revision, _head())

    def test_legacy_create_all_database_is_stamped_and_upgraded(self) -> None:
        """历史 create_all 库（无 alembic_version）→ 预检 stamp baseline → 增量升级。"""
        import app.core.database as dbmod
        import app.models  # noqa: F401
        from sqlalchemy import inspect, text

        from app.core.database import Base
        from app.core.migrate import apply_migrations, verify_schema_current

        self._init_engine_at_temp_db()
        Base.metadata.create_all(bind=dbmod.engine)
        self.assertNotIn("alembic_version", set(inspect(dbmod.engine).get_table_names()))

        apply_migrations(dbmod.engine, production=False)
        verify_schema_current(dbmod.engine)

        # 业务表数据仍在（stamp/upgrade 不动数据），关键新列存在
        cols = {c["name"] for c in inspect(dbmod.engine).get_columns("accounts")}
        self.assertIn("session_version", cols)
        with dbmod.engine.connect() as conn:
            revision = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        self.assertEqual(revision, _head())

    def test_ensure_schema_era_db_at_old_revision_upgrades(self) -> None:
        """回归：ensure_schema 时代开发库停在 d8f2a06c4b11，但 photo/坐标列已存在。

        旧启动路径（create_all + ensure_schema）ALTER 了列却不推进 alembic_version，
        迁移链改为唯一来源后 upgrade 会 duplicate column 崩溃，开发库无法启动。
        迁移必须幂等：列已在则跳过，只把版本推进到 head。
        """
        import app.core.database as dbmod
        import app.models  # noqa: F401
        from sqlalchemy import inspect, text

        from app.core.migrate import apply_migrations, verify_schema_current

        self._init_engine_at_temp_db()
        # 建到 d8f2a06c4b11，再手工补上下一迁移的列（模拟 ensure_schema 的副作用）
        self._stamp_and_upgrade_to("d8f2a06c4b11")
        with dbmod.engine.begin() as conn:
            conn.execute(text("ALTER TABLE merchants ADD COLUMN photo_blob BLOB"))
            conn.execute(
                text("ALTER TABLE merchants ADD COLUMN photo_content_type VARCHAR(50) NOT NULL DEFAULT ''")
            )
            conn.execute(text("ALTER TABLE merchants ADD COLUMN photo_updated_at DATETIME"))
            conn.execute(text("ALTER TABLE merchants ADD COLUMN longitude VARCHAR(32) NOT NULL DEFAULT ''"))
            conn.execute(text("ALTER TABLE merchants ADD COLUMN latitude VARCHAR(32) NOT NULL DEFAULT ''"))

        apply_migrations(dbmod.engine, production=False)
        verify_schema_current(dbmod.engine)

        cols = {c["name"] for c in inspect(dbmod.engine).get_columns("merchants")}
        self.assertIn("photo_blob", cols)
        with dbmod.engine.connect() as conn:
            revision = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        self.assertEqual(revision, _head())

    def _stamp_and_upgrade_to(self, revision: str) -> None:
        from alembic import command
        from alembic.config import Config

        cfg = Config(str(BACKEND_ROOT / "alembic.ini"))
        cfg.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
        cfg.set_main_option("prepend_sys_path", str(BACKEND_ROOT))
        command.upgrade(cfg, revision)

    def test_dev_startup_seeds_and_serves(self) -> None:
        """迁移建库后走完整启动路径（seed + 接口可用），模拟 dev uvicorn 冷启动。"""
        import app.core.database as dbmod
        from app.core.migrate import apply_migrations
        from app.seed import seed_if_empty

        self._init_engine_at_temp_db()
        apply_migrations(dbmod.engine, production=False)
        session = dbmod.SessionLocal()
        try:
            seed_if_empty(session)
        finally:
            session.close()

        from app.main import create_app
        from fastapi.testclient import TestClient
        from tests._helpers import skip_app_lifespan

        app = create_app()
        skip_app_lifespan(app)
        with TestClient(app, headers={"X-Requested-With": "XMLHttpRequest"}) as client:
            r = client.post("/api/auth/login", json={"username": "admin", "password": "".join(("admin", "123"))})
            self.assertEqual(r.status_code, 200, r.text)


def _head() -> str:
    from app.core.migrate import get_migration_head

    return get_migration_head()


if __name__ == "__main__":
    unittest.main()
