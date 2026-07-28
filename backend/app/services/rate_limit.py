"""Login / IP rate limiting with pluggable backends (memory, SQLite file, Redis)."""

from __future__ import annotations

import sqlite3
import threading
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Protocol

from app.core.config import Settings, get_settings


class RateLimiter(ABC):
    """check → (allowed, retry_after_sec); hit records failure; clear resets."""

    @abstractmethod
    def check(self, key: str) -> tuple[bool, int]:
        """Return (allowed, retry_after_seconds). retry_after=0 when allowed."""

    @abstractmethod
    def hit(self, key: str) -> None:
        ...

    @abstractmethod
    def clear(self, key: str) -> None:
        ...

    @abstractmethod
    def count(self, key: str) -> int:
        ...


class MemoryRateLimiter(RateLimiter):
    def __init__(self, window_sec: int = 300, max_hits: int = 8) -> None:
        self.window_sec = window_sec
        self.max_hits = max_hits
        self._hits: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def _prune(self, key: str, now: float) -> list[float]:
        recent = [t for t in self._hits.get(key, []) if now - t < self.window_sec]
        if recent:
            self._hits[key] = recent
        else:
            self._hits.pop(key, None)
        return recent

    def check(self, key: str) -> tuple[bool, int]:
        now = time.time()
        with self._lock:
            recent = self._prune(key, now)
            if len(recent) >= self.max_hits:
                oldest = min(recent)
                retry = max(1, int(self.window_sec - (now - oldest)))
                return False, retry
            return True, 0

    def hit(self, key: str) -> None:
        now = time.time()
        with self._lock:
            self._prune(key, now)
            self._hits.setdefault(key, []).append(now)

    def clear(self, key: str) -> None:
        with self._lock:
            self._hits.pop(key, None)

    def count(self, key: str) -> int:
        now = time.time()
        with self._lock:
            return len(self._prune(key, now))


class FileRateLimiter(RateLimiter):
    """SQLite-backed limiter shared across workers on one host."""

    def __init__(
        self,
        path: str,
        window_sec: int = 300,
        max_hits: int = 8,
    ) -> None:
        self.window_sec = window_sec
        self.max_hits = max_hits
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=10, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self) -> None:
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS rate_hits ("
                    "key TEXT NOT NULL, ts REAL NOT NULL)"
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_rate_hits_key_ts ON rate_hits(key, ts)"
                )
                conn.commit()
            finally:
                conn.close()

    def _prune_conn(self, conn: sqlite3.Connection, key: str, now: float) -> list[float]:
        cutoff = now - self.window_sec
        conn.execute("DELETE FROM rate_hits WHERE key = ? AND ts < ?", (key, cutoff))
        rows = conn.execute(
            "SELECT ts FROM rate_hits WHERE key = ? ORDER BY ts ASC", (key,)
        ).fetchall()
        return [float(r[0]) for r in rows]

    def check(self, key: str) -> tuple[bool, int]:
        now = time.time()
        with self._lock:
            conn = self._connect()
            try:
                recent = self._prune_conn(conn, key, now)
                conn.commit()
                if len(recent) >= self.max_hits:
                    oldest = recent[0]
                    retry = max(1, int(self.window_sec - (now - oldest)))
                    return False, retry
                return True, 0
            finally:
                conn.close()

    def hit(self, key: str) -> None:
        now = time.time()
        with self._lock:
            conn = self._connect()
            try:
                self._prune_conn(conn, key, now)
                conn.execute("INSERT INTO rate_hits(key, ts) VALUES (?, ?)", (key, now))
                conn.commit()
            finally:
                conn.close()

    def clear(self, key: str) -> None:
        with self._lock:
            conn = self._connect()
            try:
                conn.execute("DELETE FROM rate_hits WHERE key = ?", (key,))
                conn.commit()
            finally:
                conn.close()

    def count(self, key: str) -> int:
        now = time.time()
        with self._lock:
            conn = self._connect()
            try:
                recent = self._prune_conn(conn, key, now)
                conn.commit()
                return len(recent)
            finally:
                conn.close()


class RedisRateLimiter(RateLimiter):
    def __init__(
        self,
        redis_url: str,
        window_sec: int = 300,
        max_hits: int = 8,
        prefix: str = "rl:",
    ) -> None:
        try:
            import redis  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "REDIS_URL 已配置但未安装 redis 包，请 pip install redis"
            ) from exc
        self.window_sec = window_sec
        self.max_hits = max_hits
        self.prefix = prefix
        self._client = redis.Redis.from_url(redis_url, decode_responses=True)

    def _k(self, key: str) -> str:
        return f"{self.prefix}{key}"

    def check(self, key: str) -> tuple[bool, int]:
        rkey = self._k(key)
        now = time.time()
        pipe = self._client.pipeline()
        pipe.zremrangebyscore(rkey, 0, now - self.window_sec)
        pipe.zcard(rkey)
        pipe.zrange(rkey, 0, 0, withscores=True)
        _, count, oldest = pipe.execute()
        if int(count) >= self.max_hits:
            if oldest:
                oldest_ts = float(oldest[0][1])
                retry = max(1, int(self.window_sec - (now - oldest_ts)))
            else:
                retry = self.window_sec
            return False, retry
        return True, 0

    def hit(self, key: str) -> None:
        rkey = self._k(key)
        now = time.time()
        pipe = self._client.pipeline()
        pipe.zadd(rkey, {f"{now}:{threading.get_ident()}": now})
        pipe.zremrangebyscore(rkey, 0, now - self.window_sec)
        pipe.expire(rkey, self.window_sec + 5)
        pipe.execute()

    def clear(self, key: str) -> None:
        self._client.delete(self._k(key))

    def count(self, key: str) -> int:
        rkey = self._k(key)
        now = time.time()
        self._client.zremrangebyscore(rkey, 0, now - self.window_sec)
        return int(self._client.zcard(rkey) or 0)


_login_limiter: RateLimiter | None = None
_ip_limiter: RateLimiter | None = None
_limiter_lock = threading.Lock()


def build_rate_limiter(
    settings: Settings | None = None,
    *,
    window_sec: int | None = None,
    max_hits: int | None = None,
    purpose: str = "login",
) -> RateLimiter:
    s = settings or get_settings()
    window = window_sec if window_sec is not None else s.login_window_seconds
    max_h = max_hits if max_hits is not None else s.login_max_fails
    backend = (s.rate_limit_backend or "auto").strip().lower()
    redis_url = (s.redis_url or "").strip()

    if backend == "auto":
        if redis_url:
            backend = "redis"
        elif s.is_production:
            backend = "file"
        else:
            backend = "memory"

    if backend == "redis":
        if not redis_url:
            raise RuntimeError("rate_limit_backend=redis 需要 REDIS_URL")
        return RedisRateLimiter(redis_url, window_sec=window, max_hits=max_h, prefix=f"rl:{purpose}:")
    if backend == "file":
        path = s.rate_limit_file_path
        if purpose != "login":
            # separate tables via path suffix
            p = Path(path)
            path = str(p.with_name(f"{p.stem}_{purpose}{p.suffix or '.db'}"))
        return FileRateLimiter(path, window_sec=window, max_hits=max_h)
    return MemoryRateLimiter(window_sec=window, max_hits=max_h)


def get_login_limiter() -> RateLimiter:
    global _login_limiter
    with _limiter_lock:
        if _login_limiter is None:
            _login_limiter = build_rate_limiter(purpose="login")
        return _login_limiter


def get_ip_limiter() -> RateLimiter | None:
    """Global light IP limiter; None when disabled (max_requests <= 0)."""
    global _ip_limiter
    s = get_settings()
    if s.global_ip_max_requests <= 0:
        return None
    with _limiter_lock:
        if _ip_limiter is None:
            _ip_limiter = build_rate_limiter(
                purpose="ip",
                window_sec=s.global_ip_window_seconds,
                max_hits=s.global_ip_max_requests,
            )
        return _ip_limiter


def reset_limiters() -> None:
    """Test helper: drop cached limiter instances."""
    global _login_limiter, _ip_limiter
    with _limiter_lock:
        _login_limiter = None
        _ip_limiter = None
