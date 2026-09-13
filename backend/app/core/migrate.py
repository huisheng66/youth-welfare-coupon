"""Lightweight schema patches for SQLite/dev (create_all does not alter columns)."""

from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

logger = logging.getLogger("app.migrate")

LEGACY_BASELINE_REVISION = "2c984c17c453"

# 无 alembic_version 的历史库必须具备全部业务表才允许标记为 baseline，
# 防止把空库/半截库误标后跳过真正的建表迁移
REQUIRED_LEGACY_TABLES = frozenset(
    {
        "accounts",
        "merchants",
        "user_profiles",
        "user_verifications",
        "coupon_templates",
        "coupon_instances",
        "redemption_logs",
        "audit_logs",
        "point_accounts",
        "point_ledgers",
        "email_codes",
    }
)

# worker 启动只读校验所需的关键列（新迁移引入、影响认证/审计语义的列）
REQUIRED_SCHEMA_COLUMNS = {
    "accounts": ("session_version", "must_change_password"),
    "redemption_logs": ("reason",),
    "user_profiles": ("profile_version",),
    "user_verifications": ("snapshot_version", "source"),
    "coupon_instances": ("template_name", "template_description"),
}


def run_alembic_upgrade() -> None:
    """以编程方式执行 `alembic upgrade head`，复用项目 engine。

    这是发布步骤的 DDL 入口（CLI：`alembic upgrade head` 或
    `python -c "from app.core.migrate import run_alembic_upgrade; run_alembic_upgrade()"`），
    由迁移账号在部署流程中单独执行；常驻 worker 启动只做
    `verify_schema_current` 只读校验，不再执行任何 DDL（T08）。

    已有库平滑切换：若业务表已存在但尚未接入 alembic（无 alembic_version 表），
    先做表结构预检，通过后标记到固定 baseline revision，再执行 upgrade head。
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
        if _legacy_schema_is_current(engine):
            # 完整 create_all + ensure_schema 历史库：schema 已与当前模型一致
            # （含全部 ORM 索引）。直接 stamp head——若 stamp 到 baseline 再
            # upgrade，增量迁移的 CREATE INDEX 会与已存在的索引冲突。
            logger.info("legacy database is schema-complete — alembic stamp head")
            command.stamp(cfg, get_migration_head())
        else:
            # 停在旧版本的历史库（如仅建到 baseline）：验证表结构完整，
            # 标记到固定 baseline 后由增量迁移补齐
            _precheck_legacy_for_baseline(engine)
            logger.info(
                "legacy database detected — alembic stamp %s as baseline",
                LEGACY_BASELINE_REVISION,
            )
            command.stamp(cfg, LEGACY_BASELINE_REVISION)

    logger.info("running alembic upgrade head")
    command.upgrade(cfg, "head")


def _legacy_schema_is_current(engine: Engine) -> bool:
    """判断无 alembic_version 的历史库是否已具备当前模型全部表/列/索引。

    只做包含性检查（库里允许有已废弃的遗留表/列），类型不比较（跨方言）。
    ensure_schema 时代的开发库每次启动都会补齐列与索引，因此它们必然通过。
    """
    from app.core.database import Base
    import app.models  # noqa: F401  注册模型

    insp = inspect(engine)
    tables = set(insp.get_table_names()) - {"alembic_version"}
    for table in Base.metadata.sorted_tables:
        if table.name not in tables:
            return False
        columns = {c["name"] for c in insp.get_columns(table.name)}
        if any(c.name not in columns for c in table.columns):
            return False
        indexes = {i["name"] for i in insp.get_indexes(table.name)}
        if any(idx.name not in indexes for idx in table.indexes):
            return False
    return True


def _precheck_legacy_for_baseline(engine: Engine) -> None:
    insp = inspect(engine)
    tables = set(insp.get_table_names()) - {"alembic_version"}
    missing = REQUIRED_LEGACY_TABLES - tables
    if missing:
        raise RuntimeError(
            "检测到无 alembic_version 的数据库，但缺少业务表 "
            f"{sorted(missing)}；它既不是空库也不是完整历史库，"
            "拒绝标记为 baseline。请人工确认该库状态后再选择重建或修复。"
        )


def get_migration_head() -> str:
    from alembic.script import ScriptDirectory

    backend_dir = Path(__file__).resolve().parent.parent.parent
    script = ScriptDirectory(str(backend_dir / "alembic"))
    heads = script.get_heads()
    if len(heads) != 1:
        raise RuntimeError(f"迁移链存在多个 head，无法校验: {heads}")
    return heads[0]


def verify_schema_current(engine: Engine) -> None:
    """只读校验 schema 与迁移 head 一致（worker 启动门禁，不执行 DDL）。

    - 缺 alembic_version → 拒绝启动（未接入迁移的库不允许直接运行）；
    - alembic_version 落后于 head → 拒绝启动；
    - 关键列缺失（如 accounts.session_version）→ 拒绝启动。
    """
    insp = inspect(engine)
    tables = set(insp.get_table_names())
    if "alembic_version" not in tables:
        raise RuntimeError(
            "数据库未接入迁移（缺 alembic_version 表）。"
            "请先用迁移账号执行发布迁移：alembic upgrade head（见 deploy/migrate-release.sh）"
        )
    with engine.connect() as conn:
        current = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    head = get_migration_head()
    if current != head:
        raise RuntimeError(
            f"数据库迁移版本落后：库内 {current}，代码要求 {head}。"
            "请先执行发布迁移 alembic upgrade head，再启动应用。"
        )
    for table, columns in REQUIRED_SCHEMA_COLUMNS.items():
        if table not in tables:
            raise RuntimeError(f"数据库缺少业务表 {table}，请确认迁移已执行")
        present = {c["name"] for c in insp.get_columns(table)}
        missing = [c for c in columns if c not in present]
        if missing:
            raise RuntimeError(
                f"表 {table} 缺少必需列 {missing}，schema 与代码不一致；"
                "请执行 alembic upgrade head 修复后再启动。"
            )
    logger.info("schema verified: alembic at %s", head)


def apply_migrations(engine: Engine, *, production: bool) -> None:
    """按环境应用 schema 迁移。

    - 生产：worker 启动只做 `verify_schema_current` 只读校验（DDL 由发布期
      `deploy/migrate-release.sh` 以迁移账号执行，见 T08）。
    - 开发：同样走 alembic（`run_alembic_upgrade`：空库从迁移链全量建表，
      历史 create_all 库预检后自动 stamp baseline 再 upgrade），并在启动时
      做只读校验兜底。schema 唯一来源是迁移链——给模型加列必须配套生成
      alembic 迁移，不再有 create_all/手写 ALTER 的双轨漂移。
    """
    if production:
        verify_schema_current(engine)
        return
    # alembic env.py 固定取 app.core.database.engine 全局 engine，
    # 因此开发路径要求先 init_engine；传入其他 engine 属调用方错误
    import app.core.database as _db

    if engine is not _db.engine:
        raise RuntimeError("apply_migrations 需传入 app.core.database.engine（alembic env.py 固定使用全局 engine）")
    run_alembic_upgrade()
    verify_schema_current(engine)
