"""MySQL 集成/并发回归夹具（T20）。

两种供给方式：
1. 环境变量 ``MYSQL_TEST_URL``（推荐 CI）：直接使用现成 MySQL 服务，
   例如 ``mysql+pymysql://root:pass@127.0.0.1:3306/welfare_ci``。
2. 自动供给（本地开发）：在 ASCII 临时目录初始化一次性 mysqld 实例
   （随机回环端口、独立 datadir），测试结束自动关闭并清理。
   注意 mysqld 对含非 ASCII 字符的工作路径敏感，必须放在纯 ASCII 目录。

夹具为每个用例创建全新数据库并执行真实 ``alembic upgrade head`` 建表，
因此迁移链在每个用例上都被 MySQL 实际验证。MySQL 不可用时用例 skip，
不阻塞常规回归。
"""

from __future__ import annotations

import atexit
import os
import shutil
import socket
import subprocess
import tempfile
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit

BACKEND_ROOT = Path(__file__).resolve().parents[1]

# 常见 Windows / Linux 安装位置（按顺序探测）
_MYSQLD_CANDIDATES = (
    r"C:\Program Files\MySQL\MySQL Server 8.4\bin\mysqld.exe",
    r"C:\Program Files\MySQL\MySQL Server 8.0\bin\mysqld.exe",
    "/usr/sbin/mysqld",
    "/usr/local/mysql/bin/mysqld",
)


def find_mysqld() -> str | None:
    override = os.environ.get("MYSQLD_BIN")
    if override and Path(override).is_file():
        return override
    for cand in _MYSQLD_CANDIDATES:
        if Path(cand).is_file():
            return cand
    return shutil.which("mysqld")


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = int(s.getsockname()[1])
    s.close()
    return port


def _wait_for_port(port: int, timeout: float = 60.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                return True
        except OSError:
            time.sleep(0.4)
    return False


class TempMySQLServer:
    """一次性 mysqld 实例。``url`` 为测试专用根连接（不含具体业务库）。

    F06 修复：``--initialize-insecure`` 只创建 ``root@localhost``，在
    ``--skip-name-resolve`` 下从 127.0.0.1 的 TCP 连接不匹配该账户
    （``Host '127.0.0.1' is not allowed to connect``）。通过 ``--init-file``
    在服务启动时显式创建可用于 TCP 的测试账户。
    """

    TEST_USER = "welfare_t20"
    TEST_PASSWORD = "welfare_t20_local"

    def __init__(self) -> None:
        mysqld = find_mysqld()
        if not mysqld:
            raise RuntimeError("未找到 mysqld 可执行文件（可设置 MYSQLD_BIN）")
        self.mysqld = mysqld
        # mysqld 在非 ASCII 路径下可能无法完成启动，必须用纯 ASCII 目录
        self.tmpdir = tempfile.mkdtemp(prefix="welfare-mysql-")
        if not self.tmpdir.isascii():
            raise RuntimeError(f"临时目录含非 ASCII 字符，mysqld 无法使用: {self.tmpdir}")
        self.datadir = Path(self.tmpdir) / "data"
        self.port = _free_port()
        self.proc: subprocess.Popen | None = None

        init = subprocess.run(
            [
                mysqld,
                "--no-defaults",
                "--initialize-insecure",
                f"--datadir={self.datadir.as_posix()}",
                "--console",
            ],
            capture_output=True,
            text=True,
            timeout=180,
        )
        if init.returncode != 0:
            raise RuntimeError(f"mysqld --initialize 失败: {init.stderr[-800:]}")

        # 启动时创建可从 127.0.0.1 TCP 连入的测试账户（init-file 以服务端身份执行）
        init_sql = Path(self.tmpdir) / "bootstrap-users.sql"
        init_sql.write_text(
            f"CREATE USER IF NOT EXISTS '{self.TEST_USER}'@'127.0.0.1' "
            f"IDENTIFIED BY '{self.TEST_PASSWORD}';\n"
            f"CREATE USER IF NOT EXISTS '{self.TEST_USER}'@'localhost' "
            f"IDENTIFIED BY '{self.TEST_PASSWORD}';\n"
            f"GRANT ALL PRIVILEGES ON *.* TO '{self.TEST_USER}'@'127.0.0.1';\n"
            f"GRANT ALL PRIVILEGES ON *.* TO '{self.TEST_USER}'@'localhost';\n"
            "FLUSH PRIVILEGES;\n",
            encoding="utf-8",
        )

        log_handle = open(Path(self.tmpdir) / "mysqld-stdout.log", "w", encoding="utf-8")
        self.proc = subprocess.Popen(
            [
                mysqld,
                "--no-defaults",
                f"--datadir={self.datadir.as_posix()}",
                f"--port={self.port}",
                "--bind-address=127.0.0.1",
                "--skip-name-resolve",
                "--character-set-server=utf8mb4",
                "--collation-server=utf8mb4_0900_ai_ci",
                "--transaction-isolation=REPEATABLE-READ",
                f"--init-file={init_sql.as_posix()}",
                "--console",
            ],
            stdout=log_handle,
            stderr=subprocess.STDOUT,
        )
        self._log_handle = log_handle
        if not _wait_for_port(self.port):
            log = (Path(self.tmpdir) / "mysqld-stdout.log").read_text(encoding="utf-8", errors="replace")
            raise RuntimeError(f"mysqld 未在 {self.port} 端口就绪。日志尾部: {log[-800:]}")
        # 连通性验证：认证失败在这里转成明确的 RuntimeError，由夹具转为 skip
        self._verify_connectable()

    def _verify_connectable(self) -> None:
        from sqlalchemy import create_engine

        eng = create_engine(self.base_url)
        try:
            with eng.connect():
                pass
        except Exception as exc:  # noqa: BLE001
            log = (Path(self.tmpdir) / "mysqld-stdout.log").read_text(encoding="utf-8", errors="replace")
            raise RuntimeError(
                f"临时 MySQL 实例无法连接（{exc.__class__.__name__}: {exc}）。"
                f"服务端日志尾部: {log[-800:]}"
            ) from exc
        finally:
            eng.dispose()

    @property
    def base_url(self) -> str:
        return (
            f"mysql+pymysql://{self.TEST_USER}:{self.TEST_PASSWORD}"
            f"@127.0.0.1:{self.port}"
        )

    def shutdown(self) -> None:
        if self.proc is not None:
            # Windows 上 mysqld 以父子进程对运行（启动器 + 实际服务），
            # terminate() 只杀父进程，必须按进程树终止（F06 跟进修复）
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/T", "/F", "/PID", str(self.proc.pid)],
                    capture_output=True,
                )
            else:
                self.proc.terminate()
            try:
                self.proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self.proc.kill()
            self.proc = None
        if getattr(self, "_log_handle", None) is not None:
            self._log_handle.close()
            self._log_handle = None
        shutil.rmtree(self.tmpdir, ignore_errors=True)


def make_mysql_url(base_url: str, database: str) -> str:
    return f"{base_url}/{database}?charset=utf8mb4"


_SHARED_SERVER: list[TempMySQLServer | None] = [None]


def get_base_url() -> str:
    """MySQL 测试根连接（不含库名）：MYSQL_TEST_URL 优先，否则自动供给一次性实例。

    自动供给的实例在 pytest 进程退出时经 atexit 自动关闭，避免残留 mysqld。
    """
    url = os.environ.get("MYSQL_TEST_URL", "")
    if url:
        parts = urlsplit(url if "://" in url else f"mysql+pymysql://{url}")
        return f"{parts.scheme}://{parts.netloc}"
    if _SHARED_SERVER[0] is None:
        _SHARED_SERVER[0] = TempMySQLServer()
        atexit.register(_shutdown_shared_server)
    return _SHARED_SERVER[0].base_url


def _shutdown_shared_server() -> None:
    if _SHARED_SERVER[0] is not None:
        _SHARED_SERVER[0].shutdown()
        _SHARED_SERVER[0] = None


def admin_create_database(base_url: str, database: str) -> None:
    from sqlalchemy import text
    from sqlalchemy import create_engine as _ce

    eng = _ce(base_url)
    try:
        with eng.connect() as conn:
            conn.execute(
                text(
                    f"CREATE DATABASE `{database}` CHARACTER SET utf8mb4 "
                    "COLLATE utf8mb4_unicode_ci"
                )
            )
            conn.commit()
    finally:
        eng.dispose()


def admin_drop_database(base_url: str, database: str) -> None:
    from sqlalchemy import text
    from sqlalchemy import create_engine as _ce

    eng = _ce(base_url)
    try:
        with eng.connect() as conn:
            conn.execute(text(f"DROP DATABASE IF EXISTS `{database}`"))
            conn.commit()
    finally:
        eng.dispose()


def upgrade_database_to_head(url: str) -> None:
    """用项目迁移链把目标 MySQL 库升到 head（真实执行 alembic upgrade）。"""
    import app.core.database as dbmod
    from app.core.config import clear_settings_cache
    from app.core.migrate import run_alembic_upgrade

    old_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    try:
        clear_settings_cache()
        dbmod.init_engine()
        run_alembic_upgrade()
    finally:
        if old_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = old_url
        clear_settings_cache()
        dbmod.init_engine()


class MySQLCaseEnv:
    """单个测试用例的 MySQL 环境：独立数据库 + engine + session 工厂。"""

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url
        self.database = f"welfare_t20_{uuid.uuid4().hex[:10]}"
        self.url = make_mysql_url(base_url, self.database)
        admin_create_database(base_url, self.database)
        upgrade_database_to_head(self.url)

        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        self.engine = create_engine(self.url, pool_pre_ping=True, pool_size=5, max_overflow=5)
        self.Session = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)

    def session(self):
        return self.Session()

    def close(self) -> None:
        self.engine.dispose()
        admin_drop_database(self.base_url, self.database)
