"""邮件 outbox 管理（T15）：状态可查询 + 永久失败人工重发。

只报告三种终态语义：queued（已排队）、sent（SMTP 已受理，不等于用户已收件）、
failed（失败）；响应不含邮件正文（正文可能含一次性激活链接）。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import require_roles
from app.models.entities import Account, EmailOutbox, OutboxStatus, Role, utcnow

router = APIRouter(prefix="/outbox", tags=["邮件 outbox"])

_READ_STATUSES = {OutboxStatus.queued, OutboxStatus.sent, OutboxStatus.failed}


def _out_dict(task: EmailOutbox) -> dict:
    return {
        "id": task.id,
        "kind": task.kind,
        "to_email": task.to_email,
        "subject": task.subject,
        "ref_type": task.ref_type,
        "ref_id": task.ref_id,
        "status": task.status.value if isinstance(task.status, OutboxStatus) else task.status,
        "attempts": task.attempts,
        "max_attempts": task.max_attempts,
        "last_error": task.last_error,
        "created_at": task.created_at,
        "sent_at": task.sent_at,
        "next_retry_at": task.next_retry_at,
    }


def _get_task(db: Session, task_id: str) -> EmailOutbox:
    task = db.get(EmailOutbox, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="邮件任务不存在")
    return task


@router.get("")
def list_outbox(
    status: str | None = Query(default=None, description="queued/sent/failed"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    _: Account = Depends(require_roles(Role.super_admin)),
) -> dict:
    q = db.query(EmailOutbox).order_by(EmailOutbox.created_at.desc(), EmailOutbox.id)
    if status:
        if status not in _READ_STATUSES:  # str-enum：字符串直接比对成员
            raise HTTPException(status_code=400, detail=f"未知状态：{status}")
        q = q.filter(EmailOutbox.status == status)
    total = q.count()
    items = q.offset(skip).limit(limit).all()
    return {"total": total, "items": [_out_dict(t) for t in items]}


@router.post("/{task_id}/resend")
def resend_outbox(
    task_id: str,
    db: Session = Depends(get_db),
    _: Account = Depends(require_roles(Role.super_admin)),
) -> dict:
    """人工重发：仅 failed（达到重试上限）可重置回 queued 立即投递。"""
    task = _get_task(db, task_id)
    if task.status != OutboxStatus.failed:
        raise HTTPException(status_code=409, detail="仅失败（达到重试上限）的任务可重发")
    updated = (
        db.query(EmailOutbox)
        .filter(EmailOutbox.id == task.id, EmailOutbox.status == OutboxStatus.failed)
        .update(
            {EmailOutbox.status: OutboxStatus.queued, EmailOutbox.next_retry_at: utcnow()},
            synchronize_session=False,
        )
    )
    if not updated:  # 并发下已被他人重发
        raise HTTPException(status_code=409, detail="任务已被重发")
    db.commit()
    return {"id": task.id, "status": OutboxStatus.queued.value}
