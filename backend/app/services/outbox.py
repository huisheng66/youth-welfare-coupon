"""最小邮件 outbox（T15）：持久化待发送任务 + worker 退避重试。

- `enqueue` 与业务写入同事务记录任务（进程重启不丢待发送）；
- worker 条件 UPDATE 领取（多 worker 不重复发送），失败按 1/5/15/60 分钟
  退避，达到上限转 failed（永久失败可见，可人工重发）；
- 状态语义只有三种：queued（已排队）、sent（SMTP 已受理，不等于用户已收件）、
  failed（失败）；sending 为领取中间态，崩溃后超时回收；
- 状态、错误与日志不保存初始密码或激活 token 明文（邮件正文只在 html 字段，
  错误信息截断并去除可能的敏感片段由 SMTP 层保证不含正文）。
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.entities import EmailOutbox, OutboxStatus, utcnow

logger = logging.getLogger(__name__)

# 退避序列（秒）：第 1..4 次重试分别等待 1/5/15/60 分钟
BACKOFF_SECONDS = (60, 300, 900, 3600)
# sending 中间态回收窗口：worker 崩溃后超过该时长允许重新领取
_STALE_SENDING_MINUTES = 5


def enqueue(
    db: Session,
    *,
    kind: str,
    to_email: str,
    subject: str,
    html: str,
    ref_type: str = "",
    ref_id: str = "",
) -> EmailOutbox:
    """登记待发送任务（调用方负责与业务写入同一事务 commit）。"""
    settings = get_settings()
    task = EmailOutbox(
        kind=kind,
        to_email=to_email,
        subject=subject,
        html=html,
        ref_type=ref_type,
        ref_id=ref_id,
        status=OutboxStatus.queued,
        max_attempts=settings.outbox_max_attempts,
        next_retry_at=utcnow(),
    )
    db.add(task)
    return task


def _claim_due(db: Session, *, limit: int) -> EmailOutbox | None:
    """条件领取一个到期任务（queued 到期 / 超时 sending），多 worker 单胜者。"""
    now = datetime.now(timezone.utc)
    stale_before = now - timedelta(minutes=_STALE_SENDING_MINUTES)
    candidates = (
        db.query(EmailOutbox.id, EmailOutbox.status)
        .filter(
            (EmailOutbox.status == OutboxStatus.queued) & (EmailOutbox.next_retry_at <= now)
            | (EmailOutbox.status == OutboxStatus.sending) & (EmailOutbox.next_retry_at <= stale_before)
        )
        .order_by(EmailOutbox.next_retry_at)
        .limit(limit)
        .all()
    )
    for task_id, status in candidates:
        won = (
            db.query(EmailOutbox)
            .filter(EmailOutbox.id == task_id, EmailOutbox.status == status)
            .update({EmailOutbox.status: OutboxStatus.sending}, synchronize_session=False)
        )
        db.commit()
        if won:
            return db.get(EmailOutbox, task_id)
    return None


async def send_due(db: Session, *, limit: int = 10) -> dict[str, int]:
    """发送一批到期任务；返回 {sent, failed, retried} 计数。"""
    from app.services.mail import send_email_html

    counts = {"sent": 0, "failed": 0, "retried": 0}
    for _ in range(limit):
        task = _claim_due(db, limit=limit)
        if task is None:
            break
        task_id = task.id
        try:
            await send_email_html(to=task.to_email, subject=task.subject, html=task.html)
        except Exception as exc:  # noqa: BLE001 — 单个失败不影响其它任务
            # 错误信息只保留异常类型与截断文本，不回显邮件正文/凭证
            message = f"{exc.__class__.__name__}: {exc}"[:240]
            attempts = task.attempts + 1
            if attempts >= task.max_attempts:
                db.query(EmailOutbox).filter(EmailOutbox.id == task_id).update(
                    {
                        EmailOutbox.status: OutboxStatus.failed,
                        EmailOutbox.attempts: attempts,
                        EmailOutbox.last_error: message,
                    },
                    synchronize_session=False,
                )
                counts["failed"] += 1
                logger.error(
                    "outbox.permanent_failure",
                    extra={"task_id": task_id, "kind": task.kind, "attempts": attempts},
                )
            else:
                delay = BACKOFF_SECONDS[min(attempts - 1, len(BACKOFF_SECONDS) - 1)]
                db.query(EmailOutbox).filter(EmailOutbox.id == task_id).update(
                    {
                        EmailOutbox.status: OutboxStatus.queued,
                        EmailOutbox.attempts: attempts,
                        EmailOutbox.last_error: message,
                        EmailOutbox.next_retry_at: utcnow() + timedelta(seconds=delay),
                    },
                    synchronize_session=False,
                )
                counts["retried"] += 1
            db.commit()
            continue
        db.query(EmailOutbox).filter(EmailOutbox.id == task_id).update(
            {
                EmailOutbox.status: OutboxStatus.sent,
                EmailOutbox.attempts: task.attempts + 1,
                EmailOutbox.last_error: "",
                EmailOutbox.sent_at: utcnow(),
                # 已受理即清空正文：激活链接含一次性 token，不长期留库
                EmailOutbox.html: "",
            },
            synchronize_session=False,
        )
        db.commit()
        counts["sent"] += 1
    return counts


async def worker_loop(stop: asyncio.Event, *, poll_seconds: int | None = None) -> None:
    """后台 outbox worker：周期领取到期任务直到 stop 置位。

    由应用 lifespan 启停（不引入独立队列平台）；进程重启后 queued 任务
    仍在库中，下一进程继续投递。
    """
    import app.core.database as dbmod

    settings = get_settings()
    interval = poll_seconds if poll_seconds is not None else settings.outbox_poll_seconds
    batch = settings.outbox_batch_size
    while not stop.is_set():
        try:
            session = dbmod.SessionLocal()
            try:
                counts = await send_due(session, limit=batch)
                if any(counts.values()):
                    logger.info("outbox.flush", extra=counts)
            finally:
                session.close()
        except Exception:  # noqa: BLE001 — worker 不得因单轮异常退出
            logger.exception("outbox.worker_iteration_failed")
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
        except asyncio.TimeoutError:
            pass
