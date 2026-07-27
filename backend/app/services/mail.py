"""Email sending via fastapi-mail, with console fallback for local dev."""

from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.models.entities import EmailCode, EmailCodePurpose, utcnow

logger = logging.getLogger("app.mail")

_PURPOSE_SUBJECT = {
    EmailCodePurpose.register: "注册验证码",
    EmailCodePurpose.reset_password: "重置密码验证码",
    EmailCodePurpose.bind_email: "绑定邮箱验证码",
}


def _gen_code(length: int = 6) -> str:
    return f"{secrets.randbelow(10**length):0{length}d}"


def _aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


async def send_email_html(*, to: str, subject: str, html: str, settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    if not settings.smtp_configured:
        logger.info("[mail:console] to=%s subject=%s\n%s", to, subject, html)
        return

    from fastapi_mail import ConnectionConfig, FastMail, MessageSchema, MessageType
    from pydantic import SecretStr

    conf = ConnectionConfig(
        MAIL_USERNAME=settings.mail_username or settings.mail_from,
        MAIL_PASSWORD=SecretStr(settings.mail_password or ""),
        MAIL_FROM=settings.mail_from,
        MAIL_FROM_NAME=settings.mail_from_name,
        MAIL_PORT=settings.mail_port,
        MAIL_SERVER=settings.mail_server,
        MAIL_STARTTLS=settings.mail_starttls,
        MAIL_SSL_TLS=settings.mail_ssl_tls,
        USE_CREDENTIALS=bool(settings.mail_username or settings.mail_password),
        VALIDATE_CERTS=True,
    )
    message = MessageSchema(
        subject=subject,
        recipients=[to],
        body=html,
        subtype=MessageType.html,
    )
    fm = FastMail(conf)
    await fm.send_message(message)


def _check_send_limits(db: Session, email: str, purpose: EmailCodePurpose, settings: Settings) -> None:
    now = utcnow()
    last = (
        db.query(EmailCode)
        .filter(EmailCode.email == email, EmailCode.purpose == purpose)
        .order_by(EmailCode.created_at.desc())
        .first()
    )
    if last:
        age = (now - _aware(last.created_at)).total_seconds()
        if age < settings.email_code_cooldown_seconds:
            wait = max(1, int(settings.email_code_cooldown_seconds - age))
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"发送过于频繁，请 {wait} 秒后再试",
            )

    hour_ago = now - timedelta(hours=1)
    count = (
        db.query(EmailCode)
        .filter(
            EmailCode.email == email,
            EmailCode.purpose == purpose,
            EmailCode.created_at >= hour_ago,
        )
        .count()
    )
    if count >= settings.email_code_max_per_hour:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="该邮箱验证码发送次数过多，请 1 小时后再试",
        )


def _html_code_body(app_name: str, purpose: EmailCodePurpose, code: str, minutes: int) -> str:
    label = _PURPOSE_SUBJECT.get(purpose, "验证码")
    return f"""
    <div style="font-family:sans-serif;line-height:1.6;color:#222">
      <p>您好，</p>
      <p>您正在使用 <strong>{app_name}</strong> 的「{label}」功能。</p>
      <p style="font-size:28px;letter-spacing:6px;font-weight:700;margin:16px 0">{code}</p>
      <p>验证码 {minutes} 分钟内有效，请勿泄露给他人。</p>
      <p style="color:#888;font-size:12px">如非本人操作，请忽略本邮件。</p>
    </div>
    """


async def issue_email_code(
    db: Session,
    *,
    email: str,
    purpose: EmailCodePurpose,
    settings: Settings | None = None,
) -> tuple[EmailCode, str | None]:
    """Create code, send (or console-log). Returns (row, debug_code or None)."""
    settings = settings or get_settings()
    email = email.strip().lower()
    _check_send_limits(db, email, purpose, settings)

    code = _gen_code(6)
    row = EmailCode(
        email=email,
        code=code,
        purpose=purpose,
        expires_at=utcnow() + timedelta(minutes=settings.email_code_expire_minutes),
    )
    db.add(row)
    db.flush()

    subject = f"【{settings.app_name}】{_PURPOSE_SUBJECT.get(purpose, '验证码')}"
    html = _html_code_body(settings.app_name, purpose, code, settings.email_code_expire_minutes)

    try:
        await send_email_html(to=email, subject=subject, html=html, settings=settings)
    except Exception as exc:  # noqa: BLE001
        logger.exception("send mail failed: %s", exc)
        raise HTTPException(status_code=502, detail="邮件发送失败，请稍后重试或检查 SMTP 配置") from exc

    if not settings.smtp_configured:
        logger.warning("[mail:console] purpose=%s email=%s code=%s", purpose.value, email, code)

    debug: str | None = None
    if settings.mail_console and not settings.smtp_configured:
        debug = code
    return row, debug


def consume_email_code(
    db: Session,
    *,
    email: str,
    code: str,
    purpose: EmailCodePurpose,
    max_attempts: int = 5,
) -> None:
    """Validate and mark code used. Raises HTTPException on failure."""
    email = email.strip().lower()
    code = (code or "").strip()
    if not code:
        raise HTTPException(status_code=400, detail="请填写验证码")

    row = (
        db.query(EmailCode)
        .filter(
            EmailCode.email == email,
            EmailCode.purpose == purpose,
            EmailCode.used_at.is_(None),
        )
        .order_by(EmailCode.created_at.desc())
        .first()
    )
    if not row:
        raise HTTPException(status_code=400, detail="验证码无效或已过期，请重新获取")

    if _aware(row.expires_at) < utcnow():
        raise HTTPException(status_code=400, detail="验证码已过期，请重新获取")

    if row.attempts >= max_attempts:
        raise HTTPException(status_code=400, detail="验证码错误次数过多，请重新获取")

    if row.code != code:
        row.attempts += 1
        db.flush()
        left = max_attempts - row.attempts
        raise HTTPException(status_code=400, detail=f"验证码错误，还可尝试 {left} 次")

    row.used_at = utcnow()
    db.flush()
