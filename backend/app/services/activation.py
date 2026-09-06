"""一次性账号激活（T15）。

导入的有邮箱账号不再使用共用初始密码，而是收到一次性激活链接自行设置密码；
token 只存 HMAC-SHA256 摘要（复用验证码同一 keyed-hash 方案），条件更新
保证单次消费——重复点击激活链接不能重复设置密码。
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import hash_password
from app.models.entities import Account, ActivationToken, utcnow
from app.services.audit import write_audit
from app.services.mail import hash_email_code
from app.services.sanitize import password_has_letter_and_digit, validate_password_strength


def create_activation_token(db: Session, account: Account) -> str:
    """为账号签发一次性激活 token，返回明文（只进入激活链接，不落库）。"""
    settings = get_settings()
    raw = secrets.token_urlsafe(32)
    db.add(
        ActivationToken(
            account_id=account.id,
            token_hash=hash_email_code(raw, settings),
            expires_at=utcnow() + timedelta(hours=settings.activation_token_expire_hours),
        )
    )
    return raw


def activation_link(raw_token: str) -> str:
    base = (get_settings().public_base_url or "").rstrip("/")
    return f"{base}/activate?token={raw_token}"


def consume_activation(db: Session, *, token: str, new_password: str) -> Account:
    """消费激活 token 并设置新密码。单次消费：条件更新 used_at 只有一个胜者。"""
    settings = get_settings()
    raw = (token or "").strip()
    if not raw:
        raise HTTPException(status_code=400, detail="激活链接无效")
    try:
        validate_password_strength(new_password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not password_has_letter_and_digit(new_password):
        raise HTTPException(status_code=400, detail="密码需同时包含字母和数字")

    token_hash = hash_email_code(raw, settings)
    row = db.query(ActivationToken).filter(ActivationToken.token_hash == token_hash).first()
    if not row:
        raise HTTPException(status_code=400, detail="激活链接无效或已被使用")
    now = datetime.now(timezone.utc)
    # 单次消费：未使用且未过期才允许置 used_at，并发/重复点击只有一方成功
    consumed = (
        db.query(ActivationToken)
        .filter(
            ActivationToken.id == row.id,
            ActivationToken.used_at.is_(None),
            ActivationToken.expires_at > now,
        )
        .update({ActivationToken.used_at: utcnow()}, synchronize_session=False)
    )
    if not consumed:
        detail = "激活链接已过期" if row.used_at is None else "激活链接已被使用"
        raise HTTPException(status_code=400, detail=detail)

    account = db.get(Account, row.account_id)
    if not account or not account.is_active:
        raise HTTPException(status_code=400, detail="账号不可用")
    # 条件更新原子写入：新密码 + 会话版本递增（激活前签发的会话全部失效，T05 同一语义）
    updated = (
        db.query(Account)
        .filter(Account.id == account.id)
        .update(
            {
                Account.password_hash: hash_password(new_password),
                Account.must_change_password: False,
                Account.session_version: Account.session_version + 1,
            },
            synchronize_session=False,
        )
    )
    if not updated:  # 账号已被并发删除
        raise HTTPException(status_code=400, detail="账号不可用")
    write_audit(
        db,
        actor_id=account.id,
        action="activate_account",
        target_type="account",
        target_id=account.id,
        detail="一次性激活链接设置密码",
    )
    db.commit()
    return account
