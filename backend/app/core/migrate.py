"""Lightweight schema patches for SQLite/dev (create_all does not alter columns)."""

from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

logger = logging.getLogger("app.migrate")


def run_alembic_upgrade() -> None:
    """以编程方式执行 `alembic upgrade head`，复用项目 engine。

    生产环境在应用启动前调用，确保 schema 与迁移版本一致；
    不依赖 alembic CLI，部署脚本只需启动服务即可。

    已有库平滑切换：若业务表已存在但尚未接入 alembic（无 alembic_version 表），
    先 `stamp head` 标记为基线，再执行 upgrade，避免 baseline 的 create_table
    因表已存在而失败。
    """
    from alembic import command
    from alembic.config import Config

    import app.core.database as db

    backend_dir = Path(__file__).resolve().parent.parent.parent
    cfg = Config(str(backend_dir / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend_dir / "alembic"))
    # env.py 会从 app.core.database 取 engine，无需在 ini 中配 url
    cfg.set_main_option("prepend_sys_path", str(backend_dir))

    engine = db.engine
    insp = inspect(engine)
    tables = set(insp.get_table_names())
    has_alembic_version = "alembic_version" in tables
    has_business_tables = bool(tables - {"alembic_version"})
    if not has_alembic_version and has_business_tables:
        # 历史库（create_all 建表）首次接入 alembic：标记为基线，不执行 DDL
        logger.info("legacy database detected — alembic stamp head as baseline")
        command.stamp(cfg, "head")

    logger.info("running alembic upgrade head")
    command.upgrade(cfg, "head")


def _add_column_if_missing(engine: Engine, table: str, column: str, ddl: str) -> None:
    insp = inspect(engine)
    if table not in insp.get_table_names():
        return
    cols = {c["name"] for c in insp.get_columns(table)}
    if column not in cols:
        with engine.begin() as conn:
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {ddl}"))


def _column_type_name(engine: Engine, table: str, column: str) -> str | None:
    insp = inspect(engine)
    if table not in insp.get_table_names():
        return None
    for c in insp.get_columns(table):
        if c["name"] == column:
            t = c.get("type")
            return str(t).upper() if t is not None else None
    return None


def _needs_decimal_upgrade(type_name: str | None) -> bool:
    if not type_name:
        return False
    u = type_name.upper()
    # Already decimal/numeric/float-ish
    if any(x in u for x in ("DECIMAL", "NUMERIC", "NUMBER", "REAL", "FLOAT", "DOUBLE")):
        return False
    # INTEGER / INT / BIGINT etc.
    if "INT" in u:
        return True
    return False


def _migrate_hours_to_decimal(engine: Engine) -> None:
    """Upgrade volunteer-hours columns from INTEGER to DECIMAL(12,2)."""
    dialect = engine.dialect.name
    targets = [
        ("coupon_templates", "cost_points", "0"),
        ("point_accounts", "balance", "0"),
        ("point_ledgers", "change", None),
        ("point_ledgers", "balance_after", "0"),
    ]
    for table, column, default in targets:
        tname = _column_type_name(engine, table, column)
        if tname is None:
            continue
        if not _needs_decimal_upgrade(tname):
            continue
        logger.info("migrating %s.%s %s -> DECIMAL(12,2)", table, column, tname)
        if dialect == "mysql" or dialect == "mariadb":
            default_sql = f" DEFAULT {default}" if default is not None else ""
            # `change` is reserved in MySQL
            col_sql = f"`{column}`"
            with engine.begin() as conn:
                conn.execute(
                    text(
                        f"ALTER TABLE `{table}` MODIFY COLUMN {col_sql} "
                        f"DECIMAL(12,2) NOT NULL{default_sql}"
                    )
                )
        elif dialect == "sqlite":
            # SQLite affinity: rewrite table for each unique table once
            pass
        else:
            # Postgres etc.
            with engine.begin() as conn:
                conn.execute(
                    text(
                        f"ALTER TABLE {table} ALTER COLUMN {column} TYPE NUMERIC(12,2) "
                        f"USING {column}::numeric"
                    )
                )

    if dialect == "sqlite":
        _sqlite_rebuild_hours_tables(engine)


def _sqlite_rebuild_hours_tables(engine: Engine) -> None:
    """Rebuild SQLite tables when hour columns are still INTEGER affinity."""
    need_templates = _needs_decimal_upgrade(_column_type_name(engine, "coupon_templates", "cost_points"))
    need_accounts = _needs_decimal_upgrade(_column_type_name(engine, "point_accounts", "balance"))
    need_ledgers = _needs_decimal_upgrade(
        _column_type_name(engine, "point_ledgers", "change")
    ) or _needs_decimal_upgrade(_column_type_name(engine, "point_ledgers", "balance_after"))

    with engine.begin() as conn:
        if need_templates:
            logger.info("sqlite rebuild coupon_templates for decimal cost_points")
            conn.execute(text("PRAGMA foreign_keys=OFF"))
            conn.execute(
                text(
                    """
                    CREATE TABLE coupon_templates__dec AS
                    SELECT id, name, description, merchant_id, valid_days,
                           CAST(cost_points AS REAL) AS cost_points,
                           is_active, created_at
                    FROM coupon_templates
                    """
                )
            )
            # Better: recreate with explicit types via temporary table matching ORM
            conn.execute(text("DROP TABLE coupon_templates"))
            conn.execute(
                text(
                    """
                    CREATE TABLE coupon_templates (
                        id VARCHAR(36) NOT NULL PRIMARY KEY,
                        name VARCHAR(128) NOT NULL,
                        description TEXT NOT NULL,
                        merchant_id VARCHAR(36) NOT NULL,
                        valid_days INTEGER NOT NULL,
                        cost_points NUMERIC(12, 2) NOT NULL DEFAULT 0,
                        is_active BOOLEAN NOT NULL,
                        created_at DATETIME NOT NULL,
                        FOREIGN KEY(merchant_id) REFERENCES merchants (id)
                    )
                    """
                )
            )
            conn.execute(
                text(
                    """
                    INSERT INTO coupon_templates
                    (id, name, description, merchant_id, valid_days, cost_points, is_active, created_at)
                    SELECT id, name, description, merchant_id, valid_days,
                           ROUND(CAST(cost_points AS REAL), 2), is_active, created_at
                    FROM coupon_templates__dec
                    """
                )
            )
            conn.execute(text("DROP TABLE coupon_templates__dec"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_coupon_templates_merchant_id ON coupon_templates (merchant_id)"))

        if need_accounts:
            logger.info("sqlite rebuild point_accounts for decimal balance")
            conn.execute(
                text(
                    """
                    CREATE TABLE point_accounts__dec AS
                    SELECT id, user_id, CAST(balance AS REAL) AS balance, updated_at
                    FROM point_accounts
                    """
                )
            )
            conn.execute(text("DROP TABLE point_accounts"))
            conn.execute(
                text(
                    """
                    CREATE TABLE point_accounts (
                        id VARCHAR(36) NOT NULL PRIMARY KEY,
                        user_id VARCHAR(36) NOT NULL UNIQUE,
                        balance NUMERIC(12, 2) NOT NULL DEFAULT 0,
                        updated_at DATETIME NOT NULL,
                        FOREIGN KEY(user_id) REFERENCES accounts (id)
                    )
                    """
                )
            )
            conn.execute(
                text(
                    """
                    INSERT INTO point_accounts (id, user_id, balance, updated_at)
                    SELECT id, user_id, ROUND(CAST(balance AS REAL), 2), updated_at
                    FROM point_accounts__dec
                    """
                )
            )
            conn.execute(text("DROP TABLE point_accounts__dec"))

        if need_ledgers:
            logger.info("sqlite rebuild point_ledgers for decimal change/balance_after")
            conn.execute(
                text(
                    """
                    CREATE TABLE point_ledgers__dec AS
                    SELECT id, user_id,
                           CAST(change AS REAL) AS change,
                           CAST(balance_after AS REAL) AS balance_after,
                           reason, operator_id, ref_type, ref_id, created_at
                    FROM point_ledgers
                    """
                )
            )
            conn.execute(text("DROP TABLE point_ledgers"))
            conn.execute(
                text(
                    """
                    CREATE TABLE point_ledgers (
                        id VARCHAR(36) NOT NULL PRIMARY KEY,
                        user_id VARCHAR(36) NOT NULL,
                        change NUMERIC(12, 2) NOT NULL,
                        balance_after NUMERIC(12, 2) NOT NULL DEFAULT 0,
                        reason VARCHAR(255) NOT NULL,
                        operator_id VARCHAR(36),
                        ref_type VARCHAR(32) NOT NULL DEFAULT '',
                        ref_id VARCHAR(36) NOT NULL DEFAULT '',
                        created_at DATETIME NOT NULL,
                        FOREIGN KEY(user_id) REFERENCES accounts (id),
                        FOREIGN KEY(operator_id) REFERENCES accounts (id)
                    )
                    """
                )
            )
            conn.execute(
                text(
                    """
                    INSERT INTO point_ledgers
                    (id, user_id, change, balance_after, reason, operator_id, ref_type, ref_id, created_at)
                    SELECT id, user_id,
                           ROUND(CAST(change AS REAL), 2),
                           ROUND(CAST(balance_after AS REAL), 2),
                           reason, operator_id, ref_type, ref_id, created_at
                    FROM point_ledgers__dec
                    """
                )
            )
            conn.execute(text("DROP TABLE point_ledgers__dec"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_point_ledgers_user_id ON point_ledgers (user_id)"))
        conn.execute(text("PRAGMA foreign_keys=ON"))


def ensure_schema(engine: Engine) -> None:
    _add_column_if_missing(engine, "coupon_templates", "cost_points", "cost_points NUMERIC(12,2) DEFAULT 0 NOT NULL")
    _add_column_if_missing(engine, "point_ledgers", "balance_after", "balance_after NUMERIC(12,2) DEFAULT 0 NOT NULL")
    _add_column_if_missing(engine, "point_ledgers", "operator_id", "operator_id VARCHAR(36)")
    _add_column_if_missing(engine, "point_ledgers", "ref_type", "ref_type VARCHAR(32) DEFAULT ''")
    _add_column_if_missing(engine, "point_ledgers", "ref_id", "ref_id VARCHAR(36) DEFAULT ''")
    _add_column_if_missing(engine, "accounts", "email", "email VARCHAR(128)")
    _add_column_if_missing(engine, "user_profiles", "student_no", "student_no VARCHAR(64) DEFAULT ''")
    # 旧字段 id_number_masked 保留在库中（SQLite 不便删列），业务已改用 student_no
    _add_column_if_missing(engine, "user_profiles", "bank_card_encrypted", "bank_card_encrypted TEXT")
    _add_column_if_missing(engine, "user_profiles", "bank_card_last4", "bank_card_last4 VARCHAR(4) DEFAULT ''")
    _add_column_if_missing(engine, "user_profiles", "bank_card_bank_name", "bank_card_bank_name VARCHAR(64) DEFAULT ''")
    _add_column_if_missing(engine, "user_profiles", "bank_card_bound_at", "bank_card_bound_at DATETIME")
    _migrate_hours_to_decimal(engine)


def apply_migrations(engine: Engine, *, production: bool) -> None:
    """按环境应用 schema 迁移。

    - 生产：执行 `alembic upgrade head`，schema 由版本化迁移管理；
      历史库需先 `alembic stamp head` 标记基线（见 baseline 迁移注释）。
    - 开发：保留 `create_all` + `ensure_schema` 兼容空库与历史库，
      避免本地迭代时频繁生成迁移。
    """
    if production:
        run_alembic_upgrade()
        return
    from app.core.database import Base
    import app.models  # noqa: F401  # 注册模型

    Base.metadata.create_all(bind=engine)
    ensure_schema(engine)
