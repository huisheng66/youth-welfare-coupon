"""T08：发布迁移矩阵验证（MySQL）。

覆盖计划验收：空库升级、完整历史库接入（stamp 预检）、缺表历史库拒绝、
重复升级幂等、worker 启动只读校验（落后/缺列拒绝启动、且不执行 DDL）。

运行方式与 test_mysql_concurrency.py 相同（MYSQL_TEST_URL 或自动供给）。
"""

from __future__ import annotations

import os
from urllib.parse import urlsplit

import pytest

from tests._mysql_fixture import (
    MySQLCaseEnv,
    admin_create_database,
    admin_drop_database,
    get_base_url,
)
from tests._helpers import reset_env_defaults  # noqa: F401

def _base_url() -> str:
    return get_base_url()


def _fresh_database() -> tuple[str, str]:
    import uuid

    base = _base_url()
    name = f"welfare_mig_{uuid.uuid4().hex[:10]}"
    admin_create_database(base, name)
    return base, name


def _with_url(url: str):
    """临时把全局 settings/engine 指向目标库，供 run_alembic_upgrade 使用。"""
    import app.core.database as dbmod
    from app.core.config import clear_settings_cache

    class _Ctx:
        def __enter__(self):
            self.old = os.environ.get("DATABASE_URL")
            os.environ["DATABASE_URL"] = url
            clear_settings_cache()
            dbmod.init_engine()
            return dbmod

        def __exit__(self, *exc):
            if self.old is None:
                os.environ.pop("DATABASE_URL", None)
            else:
                os.environ["DATABASE_URL"] = self.old
            clear_settings_cache()
            dbmod.init_engine()
            return False

    return _Ctx()


def _drop_column(url: str, table: str, column: str) -> None:
    from sqlalchemy import create_engine, text

    eng = create_engine(url)
    try:
        with eng.begin() as conn:
            conn.execute(text(f"ALTER TABLE {table} DROP COLUMN {column}"))
    finally:
        eng.dispose()


@pytest.fixture()
def my():
    try:
        env = MySQLCaseEnv(_base_url())
    except Exception as exc:  # noqa: BLE001 — 供给失败按文档 skip，不作为用例错误
        pytest.skip(f"MySQL 环境不可用：{exc.__class__.__name__}: {exc}")
    yield env
    env.close()


class TestMigrationMatrix:
    def tearDown(self) -> None:
        reset_env_defaults()

    def test_upgrade_is_idempotent(self, my) -> None:
        """重复执行 upgrade head：无错误、head 不变。"""
        from sqlalchemy import create_engine, inspect, text

        from app.core.migrate import get_migration_head, run_alembic_upgrade

        head = get_migration_head()
        with _with_url(my.url):
            run_alembic_upgrade()  # 已在 head（夹具建库时升过一次）
            run_alembic_upgrade()  # 再次执行应 no-op
        eng = create_engine(my.url)
        try:
            with eng.connect() as conn:
                cur = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            tables = set(inspect(eng).get_table_names())
        finally:
            eng.dispose()
        assert cur == head
        assert "accounts" in tables and "redemption_logs" in tables

    def test_legacy_full_database_gets_stamped_and_upgraded(self, my) -> None:
        """完整历史库（baseline 时代结构、无 alembic_version）可安全接入迁移链。"""
        from alembic import command
        from alembic.config import Config
        from sqlalchemy import create_engine, inspect, text
        from pathlib import Path

        from app.core.migrate import (
            LEGACY_BASELINE_REVISION,
            get_migration_head,
            run_alembic_upgrade,
        )

        base, name = _fresh_database()
        try:
            url = f"{base}/{name}?charset=utf8mb4"
            # 模拟旧 create_all 时代的历史库：先升到 baseline，再抹掉版本表
            cfg = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
            cfg.set_main_option("script_location", str(Path(__file__).resolve().parents[1] / "alembic"))
            with _with_url(url):
                command.upgrade(cfg, LEGACY_BASELINE_REVISION)
                eng = create_engine(url)
                try:
                    with eng.begin() as conn:
                        conn.execute(text("DROP TABLE alembic_version"))
                finally:
                    eng.dispose()
                run_alembic_upgrade()
            eng = create_engine(url)
            try:
                with eng.connect() as conn:
                    cur = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
                cols = {c["name"] for c in inspect(eng).get_columns("accounts")}
            finally:
                eng.dispose()
            assert cur == get_migration_head()
            assert "session_version" in cols
        finally:
            admin_drop_database(base, name)

    def test_partial_database_is_rejected_for_baseline(self, my) -> None:
        """缺业务表的历史库：stamp 预检拒绝，不执行任何 DDL。"""
        from sqlalchemy import create_engine, inspect, text

        from app.core.migrate import run_alembic_upgrade

        base, name = _fresh_database()
        try:
            url = f"{base}/{name}?charset=utf8mb4"
            eng = create_engine(url)
            try:
                with eng.begin() as conn:
                    conn.execute(
                        text(
                            "CREATE TABLE accounts (id VARCHAR(36) PRIMARY KEY, username VARCHAR(64))"
                        )
                    )
            finally:
                eng.dispose()
            with _with_url(url):
                with pytest.raises(RuntimeError) as ctx:
                    run_alembic_upgrade()
                assert "拒绝标记为 baseline" in str(ctx.value)
            eng = create_engine(url)
            try:
                tables = set(inspect(eng).get_table_names())
            finally:
                eng.dispose()
            # 未被 stamp，也没有创建任何业务表
            assert tables == {"accounts"}
        finally:
            admin_drop_database(base, name)

    def test_worker_verify_rejects_stale_schema_without_ddl(self, my) -> None:
        """缺关键列时 worker 只读校验失败，且校验过程不补列、不执行 DDL。"""
        from sqlalchemy import create_engine, inspect

        from app.core.migrate import verify_schema_current

        _drop_column(my.url, "accounts", "session_version")
        eng = create_engine(my.url)
        try:
            with pytest.raises(RuntimeError) as ctx:
                verify_schema_current(eng)
            assert "session_version" in str(ctx.value)
            # 校验失败后列仍然缺失（只读校验没有偷偷修 schema）
            cols = {c["name"] for c in inspect(eng).get_columns("accounts")}
            assert "session_version" not in cols
        finally:
            eng.dispose()

    def test_worker_verify_accepts_current_schema(self, my) -> None:
        from sqlalchemy import create_engine

        from app.core.migrate import verify_schema_current

        eng = create_engine(my.url)
        try:
            verify_schema_current(eng)  # 不抛异常即通过
        finally:
            eng.dispose()

    def test_verify_rejects_database_without_alembic_version(self, my) -> None:
        from sqlalchemy import create_engine, text

        from app.core.migrate import verify_schema_current

        base, name = _fresh_database()
        try:
            url = f"{base}/{name}?charset=utf8mb4"
            eng = create_engine(url)
            try:
                with eng.begin() as conn:
                    conn.execute(
                        text(
                            "CREATE TABLE accounts (id VARCHAR(36) PRIMARY KEY, username VARCHAR(64))"
                        )
                    )
                with pytest.raises(RuntimeError) as ctx:
                    verify_schema_current(eng)
                assert "未接入迁移" in str(ctx.value)
            finally:
                eng.dispose()
        finally:
            admin_drop_database(base, name)
