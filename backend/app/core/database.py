from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings

settings = get_settings()
url = settings.database_url

# SQLite 需要 check_same_thread；MySQL/Postgres 用连接池保活
connect_args: dict = {}
engine_kwargs: dict = {"pool_pre_ping": True}

if url.startswith("sqlite"):
    connect_args["check_same_thread"] = False
else:
    # MySQL / 其它：避免长时间空闲被服务端断开
    engine_kwargs.update(
        {
            "pool_recycle": 28000,
            "pool_size": 5,
            "max_overflow": 10,
        }
    )

engine = create_engine(url, connect_args=connect_args, **engine_kwargs)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
