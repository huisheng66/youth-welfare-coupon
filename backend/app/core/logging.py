"""结构化日志：生产 JSON Lines + request_id 贯穿，开发人类可读。

设计：
- 不引入第三方依赖，用标准库 json + logging 实现 JSON formatter。
- request_id 通过 contextvars 在中间件注入，_RequestIdFilter 自动塞进每条 LogRecord。
- 调用方继续用 `logging.getLogger(__name__)`，无需改造；只需在启动时调 setup_logging()。
- 结构化字段：`logger.info("login.success", extra={"user_id": "x"})` → JSON 多出 user_id 字段。

生产日志为 JSON Lines，可按 `request_id=xxx` 串联单次请求全链路。
"""

from __future__ import annotations

import contextvars
import json
import logging
import sys
from datetime import datetime, timezone

# 请求级上下文：中间件 set，filter 读取注入 LogRecord
request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")


class _RequestIdFilter(logging.Filter):
    """把 contextvars 里的 request_id 注入每条 LogRecord。"""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get("-")
        return True


# LogRecord 内置属性，序列化 extra 时跳过这些
_RESERVED = frozenset(
    {
        "name", "msg", "args", "levelname", "levelno", "pathname", "filename", "module",
        "exc_info", "exc_text", "stack_info", "lineno", "funcName", "created", "msecs",
        "relativeCreated", "thread", "threadName", "processName", "process", "taskName",
        "request_id",
    }
)


class _JsonFormatter(logging.Formatter):
    """生产用 JSON Lines：每条日志一行 JSON，含 ts/level/logger/msg/request_id + extra。"""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
        }
        # extra 字段：调用方通过 extra={...} 传入的结构化字段
        for key, val in record.__dict__.items():
            if key in payload or key in _RESERVED or key.startswith("_"):
                continue
            payload[key] = val
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def setup_logging() -> None:
    """配置根 logger：生产 JSON Lines，开发人类可读。

    在 create_app() 启动早期调用一次；uvicorn 子 logger 也走同一 handler。
    """
    from app.core.config import get_settings

    settings = get_settings()
    root = logging.getLogger()
    root.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(_RequestIdFilter())
    if settings.is_production:
        handler.setFormatter(_JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)-7s [%(name)s] rid=%(request_id)s %(message)s"
            )
        )
    root.addHandler(handler)
    root.setLevel(logging.INFO)

    # uvicorn/access 日志也复用同一 handler，保持 request_id 一致
    for name in ("uvicorn", "uvicorn.access", "uvicorn.error"):
        lg = logging.getLogger(name)
        lg.handlers.clear()
        lg.propagate = True
