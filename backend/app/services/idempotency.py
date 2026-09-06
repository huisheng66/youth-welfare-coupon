"""写操作幂等与结果重放（T13）。

契约：
- 客户端在发券、时长调整、兑换等写接口携带 `Idempotency-Key` 头（可选）；
- 键按 操作者 + 操作类型 + key 限定范围，不同操作者/不同动作互不冲突；
- 同 key 同请求 → 重放原结果（不重复执行）；同 key 不同请求 → 409 冲突；
  同 key 并发提交 → 数据库唯一约束保证只执行一次，败者重放胜者结果；
- 幂等记录与业务写入同一事务提交，不会出现“记为完成但业务未落库”；
  业务失败（4xx）不留下幂等记录，修正请求后可重用同一 key；
- 记录只保存请求摘要（SHA-256）与结果 JSON，不保存敏感原始请求体；
- 默认保留 7 天（IDEMPOTENCY_RETENTION_DAYS），由 sweep_expired 定期清理；
  短期请求幂等与长期业务批次留档（T14）是两套机制。
"""

from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.entities import IdempotencyRecord

MAX_KEY_LENGTH = 128
HEADER_NAME = "Idempotency-Key"

# 清理节流（monotonic 时间戳），与过期券扫描同一模式
_last_sweep = 0.0


def fingerprint(payload: Any) -> str:
    """请求摘要：规范化 JSON（键排序、紧凑分隔）的 SHA-256。原始请求不入库。"""
    canonical = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def extract_key(request: Request) -> str | None:
    """读取并校验 Idempotency-Key；未携带返回 None（端点保持旧行为）。"""
    key = (request.headers.get(HEADER_NAME) or "").strip()
    if not key:
        return None
    if len(key) > MAX_KEY_LENGTH:
        raise HTTPException(status_code=400, detail="Idempotency-Key 过长")
    return key


def _find(db: Session, *, actor_id: str, action: str, key: str) -> IdempotencyRecord | None:
    return (
        db.query(IdempotencyRecord)
        .filter(
            IdempotencyRecord.actor_id == actor_id,
            IdempotencyRecord.action == action,
            IdempotencyRecord.key == key,
        )
        .first()
    )


def replay(db: Session, *, actor_id: str, action: str, key: str, request_hash: str) -> Any | None:
    """命中既有记录：同摘要返回存储的结果；不同摘要拒绝（409）。未命中返回 None。"""
    rec = _find(db, actor_id=actor_id, action=action, key=key)
    if rec is None:
        return None
    if rec.request_hash != request_hash:
        raise HTTPException(
            status_code=409,
            detail="相同 Idempotency-Key 提交了不同的请求内容；如需新操作请更换新的 key",
        )
    return json.loads(rec.result_json)


def store(
    db: Session,
    *,
    actor_id: str,
    action: str,
    key: str,
    request_hash: str,
    result: Any,
) -> None:
    """与业务写入同事务登记幂等记录（调用方随后经 commit_idempotent 提交）。"""
    db.add(
        IdempotencyRecord(
            key=key,
            actor_id=actor_id,
            action=action,
            request_hash=request_hash,
            status="completed",
            result_json=json.dumps(result, ensure_ascii=False, default=str),
        )
    )


def commit_idempotent(
    db: Session,
    *,
    actor_id: str,
    action: str,
    key: str | None,
    request_hash: str,
) -> Any | None:
    """提交事务；唯一约束竞争（并发同 key）时回滚并重读胜者结果。

    返回 None 表示本次正常提交；返回非 None 表示应重放该结果（本次未重复执行）。
    胜者记录尚不可见（对方未提交）时返回 409“处理中”，客户端可稍后以同 key 重试。
    """
    try:
        db.commit()
        return None
    except IntegrityError:
        db.rollback()
    if not key:
        raise
    winner = _find(db, actor_id=actor_id, action=action, key=key)
    if winner is None:
        # 并发胜者尚未提交：保证只执行一次，提示稍后重试而不是再次执行
        raise HTTPException(
            status_code=409,
            detail="相同 Idempotency-Key 的请求正在处理中，请稍后以相同 key 重试",
        )
    if winner.request_hash != request_hash:
        raise HTTPException(
            status_code=409,
            detail="相同 Idempotency-Key 提交了不同的请求内容；如需新操作请更换新的 key",
        )
    return json.loads(winner.result_json)


def sweep_with_settings(db: Session) -> int:
    """按当前配置执行保留期清理（写接口调用点统一走这里）。"""
    from app.core.config import get_settings

    s = get_settings()
    return sweep_expired(
        db,
        retention_days=s.idempotency_retention_days,
        interval_seconds=s.idempotency_sweep_interval,
    )


def sweep_expired(
    db: Session,
    *,
    retention_days: int = 7,
    interval_seconds: float = 300,
) -> int:
    """清理过期幂等记录（进程内节流；测试传 interval_seconds=0 强制执行）。"""
    global _last_sweep
    now = time.monotonic()
    if interval_seconds > 0 and (now - _last_sweep) < interval_seconds:
        return 0
    _last_sweep = now
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    deleted = (
        db.query(IdempotencyRecord)
        .filter(IdempotencyRecord.created_at < cutoff)
        .delete(synchronize_session=False)
    )
    if deleted:
        db.commit()
    return int(deleted)
