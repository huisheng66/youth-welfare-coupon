"""业务指标与就绪探针（T22）。

- 轻量进程内指标：请求量 / 错误数 / 耗时分桶 / 核销结果分布 / outbox 积压 /
  最近备份结果；不引入 Prometheus 等外部依赖，先接现有日志方案。
- `/api/health`：liveness（保持轻量，生产零指纹）。
- `/api/ready`：readiness——数据库连通 + schema 版本与代码一致；数据库失效
  时不能继续报就绪。
- `/api/metrics`：仅超管，输出 JSON 指标快照（不含凭据与敏感内容）。
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections import Counter, deque
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

# ---- 进程内指标（单进程 uvicorn/多 worker 各自独立，聚合靠日志采集） ----
_LOCK = threading.Lock()
_REQ_COUNT = 0
_ERR_COUNT = 0
# 耗时分桶（秒）：<0.1 / <0.5 / <1 / <3 / >=3
_LATENCY_BUCKETS = Counter()
_REDEEM_RESULTS = Counter()  # ("success"|"failed", reason)
# request_id → 最近一条核销结果（有限窗口，供排查关联；不含敏感内容）
_RECENT_REDEEM: deque[dict] = deque(maxlen=50)
_STARTED_AT = time.monotonic()


def note_request(status_code: int, seconds: float) -> None:
    global _REQ_COUNT, _ERR_COUNT
    with _LOCK:
        _REQ_COUNT += 1
        if status_code >= 500:
            _ERR_COUNT += 1
        if seconds < 0.1:
            _LATENCY_BUCKETS["<0.1s"] += 1
        elif seconds < 0.5:
            _LATENCY_BUCKETS["<0.5s"] += 1
        elif seconds < 1:
            _LATENCY_BUCKETS["<1s"] += 1
        elif seconds < 3:
            _LATENCY_BUCKETS["<3s"] += 1
        else:
            _LATENCY_BUCKETS[">=3s"] += 1


def note_redeem(result: str, reason: str, request_id: str = "") -> None:
    with _LOCK:
        _REDEEM_RESULTS[f"{result}:{reason}"] += 1
        _RECENT_REDEEM.append(
            {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "result": result, "reason": reason, "rid": request_id}
        )


def snapshot() -> dict:
    with _LOCK:
        return {
            "uptime_seconds": int(time.monotonic() - _STARTED_AT),
            "requests_total": _REQ_COUNT,
            "errors_5xx_total": _ERR_COUNT,
            "latency_buckets": dict(_LATENCY_BUCKETS),
            "redeem_results": dict(_REDEEM_RESULTS),
            "recent_redeem": list(_RECENT_REDEEM),
        }


def outbox_backlog(db) -> dict:
    """outbox 积压：queued 总数、最早排队时间、失败数（T15 可靠邮件可见性）。"""
    from app.models.entities import EmailOutbox, OutboxStatus

    queued = db.query(EmailOutbox).filter(EmailOutbox.status == OutboxStatus.queued).count()
    failed = db.query(EmailOutbox).filter(EmailOutbox.status == OutboxStatus.failed).count()
    oldest = (
        db.query(EmailOutbox.created_at)
        .filter(EmailOutbox.status == OutboxStatus.queued)
        .order_by(EmailOutbox.created_at.asc())
        .first()
    )
    age = None
    if oldest and oldest[0] is not None:
        created = oldest[0]
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        age = int((datetime.now(timezone.utc) - created).total_seconds())
    return {"queued": queued, "failed": failed, "oldest_queued_age_seconds": age}


def last_backup_status(backup_dir: str | Path) -> dict:
    """读取 deploy/backup-mysql.sh 留下的状态文件；缺失视为从未备份。"""
    path = Path(backup_dir) / "last-backup-status.json"
    if not path.exists():
        return {"ok": None, "at": None, "note": "no backup status file"}
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return {"ok": None, "at": None, "note": "unreadable backup status file"}
    return {"ok": bool(data.get("ok")), "at": data.get("at"), "error": data.get("error"), "file": data.get("file")}


def check_ready(engine) -> dict:
    """readiness 检查：数据库连通 + alembic 版本与代码 head 一致。

    任何一项失败都不报就绪（验收：健康存活正常但数据库失效时 readiness 失败）。
    """
    checks: dict = {}
    ok = True
    try:
        from sqlalchemy import inspect, text

        insp = inspect(engine)
        tables = set(insp.get_table_names())
        checks["database_connected"] = True
        if "alembic_version" in tables:
            from app.core.migrate import get_migration_head

            with engine.connect() as conn:
                current = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            head = get_migration_head()
            checks["schema_version"] = current
            checks["schema_head"] = head
            if current != head:
                checks["schema_up_to_date"] = False
                ok = False
            else:
                checks["schema_up_to_date"] = True
        else:
            # 开发库（create_all 直建）允许无版本表；生产由启动门禁拦截
            from app.core.config import get_settings

            if get_settings().is_production:
                checks["schema_version"] = None
                checks["schema_up_to_date"] = False
                ok = False
            else:
                checks["schema_version"] = "dev-create_all"
                checks["schema_up_to_date"] = True
    except Exception as exc:  # noqa: BLE001 — 任何数据库异常都=未就绪
        checks["database_connected"] = False
        checks["error"] = exc.__class__.__name__
        ok = False
    return {"ok": ok, "checks": checks}
