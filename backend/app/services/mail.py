"""Email sending via aiosmtplib, with console fallback for local dev."""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import formataddr
from typing import Any

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


def hash_email_code(code: str, settings: Settings | None = None) -> str:
    """验证码只存 HMAC-SHA256 摘要。

    六位码熵太低，无密钥散列挡不住离线枚举；必须让服务端 SECRET_KEY
    参与校验，库被拖走后攻击者无法把摘要还原成验证码。
    """
    settings = settings or get_settings()
    return hmac.new(
        settings.secret_key.encode("utf-8"),
        code.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _code_matches(stored: str, provided: str, settings: Settings) -> bool:
    stored = (stored or "").strip()
    # 迁移前的历史验证码以明文入库（6 位数字）：保留直接比对，让迁移窗口内
    # 未过期的码仍可用；新码一律为 64 位 HMAC 摘要。
    if len(stored) == 64 and all(c in "0123456789abcdef" for c in stored.lower()):
        digest = hash_email_code(provided, settings)
        return hmac.compare_digest(digest, stored.lower())
    return hmac.compare_digest(stored, provided)


def _aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def build_mail_config(settings: Settings | None = None) -> dict[str, Any]:
    """Build validated aiosmtplib connection options."""
    settings = settings or get_settings()
    if not settings.smtp_configured:
        raise RuntimeError("SMTP 未配置完整（需要 MAIL_SERVER / 账号 / 密码）")

    sender = settings.mail_sender
    if not sender or "@" not in sender:
        raise RuntimeError("MAIL_FROM 或 MAIL_USERNAME 必须是有效邮箱地址")

    # 465 + SSL 与 587 + STARTTLS 互斥，避免两边同时 true
    ssl_tls = bool(settings.mail_ssl_tls)
    starttls = bool(settings.mail_starttls) and not ssl_tls

    return {
        "hostname": settings.mail_server.strip(),
        "port": settings.mail_port,
        "username": settings.mail_username or sender,
        "password": settings.mail_password or "",
        "start_tls": starttls,
        "use_tls": ssl_tls,
        "validate_certs": True,
        "timeout": 30,
    }


async def send_email_html(*, to: str, subject: str, html: str, settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    if not settings.smtp_configured:
        logger.info("[mail:console] to=%s subject=%s\n%s", to, subject, html)
        return

    from aiosmtplib import send

    conf = build_mail_config(settings)
    sender = settings.mail_sender
    message = EmailMessage()
    message["From"] = formataddr(
        (settings.mail_from_name or settings.app_name, sender)
    )
    message["To"] = to
    message["Subject"] = subject
    message.set_content("请使用支持 HTML 的邮件客户端查看此邮件。")
    message.add_alternative(html, subtype="html")
    await send(message, sender=sender, recipients=[to], **conf)


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


def _friendly_smtp_error(exc: BaseException) -> str:
    text = str(exc) or exc.__class__.__name__
    low = text.lower()
    if "authentication" in low or "535" in text or "auth" in low:
        return "SMTP 认证失败：请检查企业邮账号与密码/客户端专用密码是否正确，以及是否已开启 SMTP"
    if "certificate" in low or "ssl" in low or "tls" in low:
        return "SMTP SSL/TLS 握手失败：腾讯企业邮请用 465+SSL 或 587+STARTTLS"
    if "timed out" in low or "timeout" in low:
        return "连接 SMTP 超时：请检查网络/防火墙是否放行 smtp.exmail.qq.com:465"
    if "getaddrinfo" in low or "name or service" in low or "nodename" in low:
        return "无法解析 SMTP 主机名，请检查 MAIL_SERVER"
    return f"邮件发送失败：{text[:180]}"


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
    if not settings.smtp_configured and settings.is_production:
        # 生产未配 SMTP 必须 fail-closed：不允许“成功但只写日志”的假发码
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="邮件服务未配置，暂时无法发送验证码，请联系管理员",
        )
    _check_send_limits(db, email, purpose, settings)

    code = _gen_code(6)
    row = EmailCode(
        email=email,
        code=hash_email_code(code, settings),
        purpose=purpose,
        expires_at=utcnow() + timedelta(minutes=settings.email_code_expire_minutes),
    )
    db.add(row)
    db.flush()

    subject = f"【{settings.app_name}】{_PURPOSE_SUBJECT.get(purpose, '验证码')}"
    html = _html_code_body(settings.app_name, purpose, code, settings.email_code_expire_minutes)

    try:
        await send_email_html(to=email, subject=subject, html=html, settings=settings)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception("send mail failed: %s", exc)
        raise HTTPException(status_code=502, detail=_friendly_smtp_error(exc)) from exc

    debug: str | None = None
    # 生产环境绝不把验证码放进 HTTP 响应；控制台验证码仅限本地开发联调。
    # 日志同样不落验证码明文（开发排错看响应体 debug_code 即可）。
    if settings.mail_console and not settings.smtp_configured and not settings.is_production:
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
    """Validate and mark code used. Raises HTTPException on failure.

    消费与错误计数共用同一原子资格边界（未消费 + 次数未达上限，消费另加
    未过期），全部放进条件 UPDATE 由数据库判定（审查报告 F02）：读后在
    Python 中比较存在窗口，并发请求可在锁定生效前越过旧计数。
    """
    settings = get_settings()
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

    now = utcnow()
    expired = _aware(row.expires_at) < now
    matched = _code_matches(row.code, code, settings)

    if matched:
        # 正确码：资格（未消费/未超限/未过期）与消费在同一条件更新内判定
        updated = (
            db.query(EmailCode)
            .filter(
                EmailCode.id == row.id,
                EmailCode.used_at.is_(None),
                EmailCode.attempts < max_attempts,
                EmailCode.expires_at > now,
            )
            .update({EmailCode.used_at: now}, synchronize_session=False)
        )
        if not updated:
            db.rollback()
            raise HTTPException(status_code=400, detail=_locked_code_detail(db, row.id))
        db.expire(row)
        return

    # 错误码：计数自增同样受资格条件约束，不能无限增长
    attempts_before = row.attempts
    updated = (
        db.query(EmailCode)
        .filter(
            EmailCode.id == row.id,
            EmailCode.used_at.is_(None),
            EmailCode.attempts < max_attempts,
        )
        .update({EmailCode.attempts: EmailCode.attempts + 1}, synchronize_session=False)
    )
    if not updated:
        db.rollback()
        raise HTTPException(status_code=400, detail=_locked_code_detail(db, row.id))
    # 错误计数必须先落库再返回错误：请求以 4xx 结束时 get_db 只 close 不
    # commit，不提交则 attempts 随事务回滚清零，等于可以无限次试码。
    db.commit()
    left = max_attempts - (attempts_before + 1)
    raise HTTPException(status_code=400, detail=f"验证码错误，还可尝试 {left} 次")


def _locked_code_detail(db: Session, code_id: str) -> str:
    """条件更新未命中后，用锁定读（当前读）分类被拒原因。

    MySQL REPEATABLE READ 下普通 SELECT 走旧快照，看不到其他请求刚提交
    的消费/计数；锁定读能看到最新提交状态且避免分类竞态。
    """
    fresh = db.query(EmailCode).filter(EmailCode.id == code_id).with_for_update().first()
    if fresh is None:
        return "验证码无效或已过期，请重新获取"
    if fresh.used_at is not None:
        return "验证码已被使用，请重新获取"
    if _aware(fresh.expires_at) < utcnow():
        return "验证码已过期，请重新获取"
    return "验证码错误次数过多，请重新获取"


async def send_test_email(*, to: str, settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    if not settings.smtp_configured:
        raise HTTPException(status_code=400, detail="尚未配置 SMTP（MAIL_SERVER / 账号 / 密码）")
    subject = f"【{settings.app_name}】SMTP 连通测试"
    html = f"""
    <div style="font-family:sans-serif;line-height:1.6">
      <p>这是一封测试邮件。</p>
      <p>若你收到本信，说明 <strong>{settings.app_name}</strong> 的腾讯企业邮 / SMTP 配置正常。</p>
      <p style="color:#888;font-size:12px">发件服务器：{settings.mail_server}:{settings.mail_port}</p>
    </div>
    """
    try:
        await send_email_html(to=to, subject=subject, html=html, settings=settings)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception("test mail failed: %s", exc)
        raise HTTPException(status_code=502, detail=_friendly_smtp_error(exc)) from exc


def probe_imap(*, settings: Settings | None = None) -> dict:
    """
    用标准库 imaplib 登录 IMAP，验证账号/密码与 SSL 端口。
    不拉取正文；成功返回邮箱文件夹概况。
    """
    import imaplib
    import ssl

    settings = settings or get_settings()
    if not settings.imap_configured:
        raise HTTPException(
            status_code=400,
            detail="尚未配置 IMAP（IMAP_SERVER + MAIL_USERNAME + MAIL_PASSWORD）",
        )

    host = (settings.imap_server or "").strip()
    port = int(settings.imap_port or 993)
    user = (settings.mail_username or "").strip()
    password = settings.mail_password or ""
    use_ssl = bool(settings.imap_ssl)

    try:
        if use_ssl:
            ctx = ssl.create_default_context()
            client: imaplib.IMAP4 = imaplib.IMAP4_SSL(host, port, ssl_context=ctx, timeout=20)
        else:
            client = imaplib.IMAP4(host, port, timeout=20)
            client.starttls(ssl_context=ssl.create_default_context())

        typ, _ = client.login(user, password)
        if typ != "OK":
            raise HTTPException(status_code=502, detail="IMAP 登录失败，请检查账号密码")

        typ, data = client.select("INBOX", readonly=True)
        messages = 0
        if typ == "OK" and data and data[0] is not None:
            try:
                messages = int(data[0])
            except (TypeError, ValueError):
                messages = 0

        try:
            client.logout()
        except Exception:  # noqa: BLE001
            pass

        return {
            "ok": True,
            "imap_server": host,
            "imap_port": port,
            "imap_ssl": use_ssl,
            "inbox_messages": messages,
        }
    except HTTPException:
        raise
    except imaplib.IMAP4.error as exc:
        logger.warning("IMAP auth error: %s", exc)
        raise HTTPException(
            status_code=502,
            detail="IMAP 认证失败：请确认企业邮账号与客户端专用密码正确",
        ) from exc
    except TimeoutError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"连接 IMAP 超时：请检查网络是否放行 {host}:{port}",
        ) from exc
    except OSError as exc:
        logger.warning("IMAP network error: %s", exc)
        raise HTTPException(
            status_code=502,
            detail=f"无法连接 IMAP {host}:{port}（{exc}）",
        ) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("IMAP probe failed: %s", exc)
        raise HTTPException(status_code=502, detail=f"IMAP 检测失败：{exc}") from exc
