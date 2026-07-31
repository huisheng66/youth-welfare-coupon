from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import Settings, get_settings


class Base(DeclarativeBase):
    pass


# 模块级 engine / SessionLocal：首次 import 按默认 settings 构造，
# init_engine 可重建（生产 create_app 内调用，测试可覆盖）。
# 调用方应使用 `import app.core.database as db; db.engine` 访问，
# 以拿到 init_engine 重建后的最新实例，避免 `from ... import engine` 的旧引用。
engine = None
SessionLocal = None


def _build_engine(settings: Settings):
    url = settings.database_url
    # SQLite 需要 check_same_thread；MySQL/Postgres 用连接池保活
    connect_args: dict = {}
    engine_kwargs: dict = {"pool_pre_ping": True}
    if url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
    else:
        engine_kwargs.update(
            {
                "pool_recycle": 28000,
                "pool_size": 5,
                "max_overflow": 10,
            }
        )
    return create_engine(url, connect_args=connect_args, **engine_kwargs)


def init_engine(settings: Settings | None = None) -> None:
    """按 settings 构造 engine 与 SessionLocal，覆盖模块级变量。

    - 生产：`create_app()` 内调用，确保 engine 按启动时 settings 构造。
    - 测试：可传入内存 SQLite settings 重建，不污染开发库。
    """
    global engine, SessionLocal
    s = settings or get_settings()
    engine = _build_engine(s)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


# 首次 import 时按默认 settings 构造（兼容 `from app.core.database import engine` 旧路径）
init_engine()


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
