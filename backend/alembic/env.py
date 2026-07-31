"""Alembic 运行环境。

复用项目自身的 engine 与 Base.metadata：
- engine 来自 `app.core.database.engine`（按 settings.database_url 构造，与运行时一致）。
- metadata 来自 `app.models.entities` 导入后挂载到 `Base.metadata` 的所有表。

因此 `alembic revision --autogenerate` 与 `alembic upgrade head` 都直接作用于业务库，
无需在 alembic.ini 中维护一份单独的连接配置。
"""

from __future__ import annotations

import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context

# 确保 backend/ 在 sys.path 中，便于 `from app...` 导入
BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.config import get_settings  # noqa: E402
from app.core.database import Base, engine as app_engine  # noqa: E402
import app.models  # noqa: F401,E402  # 注册所有 ORM 模型到 Base.metadata

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 用项目 settings 覆盖 alembic.ini 中的 sqlalchemy.url，确保 CLI 与运行时一致
config.set_main_option("sqlalchemy.url", get_settings().database_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """离线模式：仅生成 SQL 脚本，不连接数据库。"""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """在线模式：直接复用项目 engine，避免重复创建连接池。"""
    connectable = app_engine

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
