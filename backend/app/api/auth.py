import logging
import re

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy.orm import Session

from app.core.client_ip import get_client_ip
from app.core.config import get_settings
from app.core.cookie import clear_auth_cookie, set_auth_cookie
from app.core.database import get_db
from app.core.deps import get_current_account, get_current_account_optional, require_roles
from app.core.security import create_access_token, hash_password, verify_password
from app.models.entities import Account, EmailCodePurpose, Role, UserProfile, VerifyStatus
from app.schemas.auth import (
    AccountOut,
    ActivateIn,
    ChangePasswordIn,
    CreateIssueAdminIn,
    CreateMerchantAccountIn,
    ForgotPasswordIn,
    LoginIn,
    RegisterIn,
    ResetPasswordByEmailIn,
    ResetPasswordIn,
    SendEmailCodeIn,
    SendEmailCodeOut,
    SetActiveIn,
    SmtpStatusOut,
    TestSmtpIn,
    UpdateEmailIn,
)
from app.schemas.common import MessageOut, Page, TokenOut
from app.services.audit import write_audit
from app.services.mail import consume_email_code, issue_email_code, send_test_email
from app.services.rate_limit import get_login_limiter
from app.services.sanitize import mask_email, sanitize_plain_text

router = APIRouter(prefix="/auth", tags=["认证"])

logger = logging.getLogger(__name__)


def _login_user_key(username: str) -> str:
    """按账号限流：换 IP / 伪造 XFF 无法重置计数。"""
    return f"u:{(username or '').strip().lower()}"


def _login_ip_key(ip: str) -> str:
    """按 IP 限流：抑制对大量用户名的喷洒。"""
    return f"ip:{(ip or 'unknown').strip()}"


def _check_login_rate(ip: str, username: str) -> None:
    limiter = get_login_limiter()
    for key in (_login_user_key(username), _login_ip_key(ip)):
        allowed, retry_after = limiter.check(key)
        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="登录尝试过于频繁，请 5 分钟后再试",
                headers={"Retry-After": str(retry_after)},
            )


def _record_login_fail(ip: str, username: str) -> None:
    limiter = get_login_limiter()
    limiter.hit(_login_user_key(username))
    limiter.hit(_login_ip_key(ip))


def _clear_login_fail(ip: str, username: str) -> None:
    # 成功登录只清账号桶，保留 IP 桶以免喷洒后立刻换号
    get_login_limiter().clear(_login_user_key(username))


def account_to_out(account: Account) -> AccountOut:
    verify_status = None
    if account.profile:
        verify_status = account.profile.verify_status
    return AccountOut(
        id=account.id,
        username=account.username,
        email=account.email,
        role=account.role,
        display_name=account.display_name,
        phone=account.phone,
        is_active=account.is_active,
        must_change_password=account.must_change_password,
        merchant_id=account.merchant_id,
        verify_status=verify_status,
    )


def _find_by_login(db: Session, login: str) -> Account | None:
    key = (login or "").strip()
    if not key:
        return None
    # 邮箱优先（含 @）
    if "@" in key:
        return db.query(Account).filter(Account.email == key.lower()).first()
    account = db.query(Account).filter(Account.username == key).first()
    if account:
        return account
    # 也允许无 @ 时按邮箱再试（少见）
    return db.query(Account).filter(Account.email == key.lower()).first()


def _unique_username_from_email(db: Session, email: str, preferred: str | None = None) -> str:
    if preferred and preferred.strip():
        base = re.sub(r"[^a-zA-Z0-9_\u4e00-\u9fff]", "", preferred.strip())[:32] or "user"
    else:
        local = email.split("@", 1)[0]
        base = re.sub(r"[^a-zA-Z0-9_]", "", local)[:24] or "user"
    if not base:
        base = "user"
    candidate = base
    n = 0
    while db.query(Account).filter(Account.username == candidate).first():
        n += 1
        candidate = f"{base}{n}"
        if n > 9999:
            raise HTTPException(status_code=400, detail="无法生成唯一用户名，请指定用户名")
    return candidate


@router.get("/email/smtp-status", response_model=SmtpStatusOut)
def smtp_status(
    _: Account = Depends(require_roles(Role.super_admin)),
) -> SmtpStatusOut:
    """超级管理员查看 SMTP/IMAP 是否已配置（不返回密码）。"""
    s = get_settings()
    user = s.mail_username or ""
    # 脱敏：只显示前 2 与域名
    masked = user
    if "@" in user:
        local, domain = user.split("@", 1)
        masked = (local[:2] + "***@" + domain) if local else "***@" + domain
    return SmtpStatusOut(
        smtp_configured=s.smtp_configured,
        mail_server=s.mail_server or "",
        mail_port=s.mail_port,
        mail_username=masked,
        mail_from=s.mail_sender,
        mail_ssl_tls=s.mail_ssl_tls,
        mail_starttls=s.mail_starttls and not s.mail_ssl_tls,
        mail_console=s.mail_console and not s.smtp_configured,
        imap_configured=s.imap_configured,
        imap_server=s.imap_server or "",
        imap_port=s.imap_port,
        imap_ssl=s.imap_ssl,
    )


@router.post("/email/test", response_model=MessageOut)
async def test_smtp(
    body: TestSmtpIn,
    db: Session = Depends(get_db),
    admin: Account = Depends(require_roles(Role.super_admin)),
) -> MessageOut:
    """超级管理员：向指定邮箱发送一封测试邮件，验证腾讯企业邮等 SMTP。"""
    await send_test_email(to=body.to)
    write_audit(
        db,
        actor_id=admin.id,
        action="test_smtp",
        target_type="email",
        target_id=body.to,
    )
    db.commit()
    return MessageOut(message=f"测试邮件已发送至 {body.to}，请查收（含垃圾箱）")


@router.post("/email/test-imap", response_model=MessageOut)
def test_imap(
    db: Session = Depends(get_db),
    admin: Account = Depends(require_roles(Role.super_admin)),
) -> MessageOut:
    """超级管理员：登录 IMAP 收件服务器，验证 SSL/账号（不拉取正文）。"""
    from app.services.mail import probe_imap

    info = probe_imap()
    write_audit(
        db,
        actor_id=admin.id,
        action="test_imap",
        target_type="email",
        target_id=info.get("imap_server", ""),
        detail=f"inbox={info.get('inbox_messages')}",
    )
    db.commit()
    return MessageOut(
        message=(
            f"IMAP 连通正常：{info.get('imap_server')}:{info.get('imap_port')} "
            f"（INBOX 约 {info.get('inbox_messages')} 封）"
        )
    )


@router.post("/email/send-code", response_model=SendEmailCodeOut)
async def send_email_code(
    body: SendEmailCodeIn,
    db: Session = Depends(get_db),
    account: Account | None = Depends(get_current_account_optional),
) -> SendEmailCodeOut:
    """发送邮箱验证码。purpose: register | reset_password | bind_email"""
    settings = get_settings()
    email = body.email
    purpose = body.purpose

    if purpose == EmailCodePurpose.register:
        if db.query(Account).filter(Account.email == email).first():
            raise HTTPException(status_code=400, detail="该邮箱已注册")
    elif purpose == EmailCodePurpose.reset_password:
        # 不泄露是否注册：无账号也假装成功（不发真码）
        target = db.query(Account).filter(Account.email == email).first()
        if not target or not target.is_active:
            return SendEmailCodeOut(
                message="若该邮箱已注册，将收到验证码邮件",
                expire_minutes=settings.email_code_expire_minutes,
                debug_code=None,
            )
    elif purpose == EmailCodePurpose.bind_email:
        if account is None:
            raise HTTPException(status_code=401, detail="请先登录")
        exists = db.query(Account).filter(Account.email == email, Account.id != account.id).first()
        if exists:
            raise HTTPException(status_code=400, detail="该邮箱已被占用")
    else:
        raise HTTPException(status_code=400, detail="不支持的验证码用途")

    _, debug = await issue_email_code(db, email=email, purpose=purpose, settings=settings)
    write_audit(
        db,
        actor_id=account.id if account else None,
        action="send_email_code",
        target_type="email",
        target_id=email,
        detail=purpose.value,
    )
    db.commit()

    if settings.smtp_configured:
        msg = "验证码已发送，请查收邮件"
    else:
        msg = "验证码已生成（未配置 SMTP，请使用界面/日志中的开发验证码）"
    return SendEmailCodeOut(
        message=msg,
        expire_minutes=settings.email_code_expire_minutes,
        debug_code=debug,
    )


@router.post("/forgot-password", response_model=SendEmailCodeOut)
async def forgot_password(body: ForgotPasswordIn, db: Session = Depends(get_db)) -> SendEmailCodeOut:
    """忘记密码：向已注册邮箱发送重置验证码（未注册不暴露）。"""
    settings = get_settings()
    email = body.email
    target = db.query(Account).filter(Account.email == email).first()
    debug: str | None = None
    if target and target.is_active:
        _, debug = await issue_email_code(
            db, email=email, purpose=EmailCodePurpose.reset_password, settings=settings
        )
        write_audit(
            db,
            actor_id=target.id,
            action="forgot_password_code",
            target_type="account",
            target_id=target.id,
        )
        db.commit()
    if settings.smtp_configured:
        msg = "若该邮箱已注册，将收到验证码邮件"
    else:
        msg = "若该邮箱已注册，验证码已生成（开发模式可返回 debug_code）"
    return SendEmailCodeOut(
        message=msg,
        expire_minutes=settings.email_code_expire_minutes,
        debug_code=debug,
    )


@router.post("/reset-password-by-email", response_model=MessageOut)
def reset_password_by_email(body: ResetPasswordByEmailIn, db: Session = Depends(get_db)) -> MessageOut:
    """用邮箱验证码重置密码（无需登录）。"""
    account = db.query(Account).filter(Account.email == body.email).first()
    if not account or not account.is_active:
        raise HTTPException(status_code=400, detail="验证码无效或账号不存在")
    consume_email_code(
        db,
        email=body.email,
        code=body.code,
        purpose=EmailCodePurpose.reset_password,
    )
    # 会话版本用数据库原子表达式递增：两个并发重置请求不会互相覆盖版本号
    db.query(Account).filter(Account.id == account.id).update(
        {
            Account.password_hash: hash_password(body.new_password),
            Account.session_version: Account.session_version + 1,
        },
        synchronize_session=False,
    )
    write_audit(
        db,
        actor_id=account.id,
        action="reset_password_by_email",
        target_type="account",
        target_id=account.id,
    )
    db.commit()
    return MessageOut(message="密码已重置，请使用新密码登录")


@router.post("/login", response_model=TokenOut)
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)) -> TokenOut:
    ip = get_client_ip(request)
    login_id = body.username.strip()
    _check_login_rate(ip, login_id)
    account = _find_by_login(db, login_id)
    if not account or not verify_password(body.password, account.password_hash):
        _record_login_fail(ip, login_id)
        logger.warning(
            "login.failed",
            extra={"login_id": mask_email(login_id) if "@" in login_id else login_id, "ip": ip, "reason": "bad_credentials"},
        )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="邮箱/用户名或密码错误")
    if not account.is_active:
        _record_login_fail(ip, login_id)
        logger.warning(
            "login.failed",
            extra={"user_id": account.id, "ip": ip, "reason": "inactive"},
        )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="账号已停用")
    _clear_login_fail(ip, login_id)
    token = create_access_token(
        account.id,
        {"role": account.role.value, "sv": account.session_version},
    )
    # 主路径：HttpOnly Cookie 下发 token，前端 JS 不可读，防 XSS 窃取
    set_auth_cookie(response, token)
    logger.info(
        "login.success",
        extra={"user_id": account.id, "role": account.role.value, "ip": ip},
    )
    # Cookie 专用模式（关闭 Bearer 兼容）时响应体不再返回真实 token，
    # 避免 JS 可读凭据重新出现；过渡期默认保留以兼容未改造的客户端。
    body_token = token if get_settings().auth_allow_bearer else ""
    return TokenOut(access_token=body_token)


@router.post("/activate", response_model=MessageOut)
def activate_account(
    body: ActivateIn,
    db: Session = Depends(get_db),
) -> MessageOut:
    """一次性激活链接设置密码（T15）：token 单次消费，重复点击/过期拒绝。"""
    from app.services.activation import consume_activation

    consume_activation(db, token=body.token, new_password=body.new_password)
    return MessageOut(message="账号已激活，请使用新密码登录")


@router.post("/logout", response_model=MessageOut)
def logout(response: Response) -> MessageOut:
    """登出：清除认证 Cookie。前端调用后丢弃本地账号缓存。"""
    clear_auth_cookie(response)
    return MessageOut(message="已登出")


@router.post("/register", response_model=AccountOut)
def register(body: RegisterIn, db: Session = Depends(get_db)) -> AccountOut:
    email = body.email
    if db.query(Account).filter(Account.email == email).first():
        raise HTTPException(status_code=400, detail="该邮箱已注册")
    consume_email_code(db, email=email, code=body.code, purpose=EmailCodePurpose.register)
    if body.phone and db.query(Account).filter(Account.phone == body.phone).first():
        raise HTTPException(status_code=400, detail="手机号已注册")
    if body.username and body.username.strip():
        if db.query(Account).filter(Account.username == body.username.strip()).first():
            raise HTTPException(status_code=400, detail="用户名已存在")
        username = body.username.strip()
    else:
        username = _unique_username_from_email(db, email)
    display = sanitize_plain_text(body.display_name or username, max_length=64) or username
    account = Account(
        username=username,
        email=email,
        password_hash=hash_password(body.password),
        role=Role.user,
        display_name=display,
        phone=body.phone,
    )
    db.add(account)
    db.flush()
    db.add(UserProfile(account_id=account.id, verify_status=VerifyStatus.draft))
    from app.services.points import get_or_create_account

    get_or_create_account(db, account.id)
    write_audit(db, actor_id=account.id, action="user_register", target_type="account", target_id=account.id)
    db.commit()
    db.refresh(account)
    return account_to_out(account)


@router.get("/me", response_model=AccountOut)
def me(account: Account = Depends(get_current_account)) -> AccountOut:
    return account_to_out(account)


@router.post("/merchant-accounts", response_model=AccountOut)
def create_merchant_account(
    body: CreateMerchantAccountIn,
    db: Session = Depends(get_db),
    admin: Account = Depends(require_roles(Role.super_admin)),
) -> AccountOut:
    from app.models.entities import Merchant

    if db.query(Account).filter(Account.username == body.username).first():
        raise HTTPException(status_code=400, detail="用户名已存在")
    merchant = db.get(Merchant, body.merchant_id)
    if not merchant:
        raise HTTPException(status_code=404, detail="商家不存在")
    email = str(body.email).strip().lower() if body.email else None
    if email and db.query(Account).filter(Account.email == email).first():
        raise HTTPException(status_code=400, detail="该邮箱已被占用")
    account = Account(
        username=body.username,
        email=email,
        password_hash=hash_password(body.password),
        role=Role.merchant,
        display_name=body.display_name or body.username,
        merchant_id=body.merchant_id,
        must_change_password=True,
    )
    db.add(account)
    write_audit(
        db,
        actor_id=admin.id,
        action="create_merchant_account",
        target_type="account",
        target_id=body.username,
        detail=f"merchant={body.merchant_id}",
    )
    db.commit()
    db.refresh(account)
    return account_to_out(account)


@router.post("/issue-admins", response_model=AccountOut)
def create_issue_admin(
    body: CreateIssueAdminIn,
    db: Session = Depends(get_db),
    admin: Account = Depends(require_roles(Role.super_admin)),
) -> AccountOut:
    if db.query(Account).filter(Account.username == body.username).first():
        raise HTTPException(status_code=400, detail="用户名已存在")
    email = str(body.email).strip().lower() if body.email else None
    if email and db.query(Account).filter(Account.email == email).first():
        raise HTTPException(status_code=400, detail="该邮箱已被占用")
    account = Account(
        username=body.username,
        email=email,
        password_hash=hash_password(body.password),
        role=Role.issue_admin,
        display_name=body.display_name or body.username,
        must_change_password=True,
    )
    db.add(account)
    write_audit(db, actor_id=admin.id, action="create_issue_admin", target_type="account", target_id=body.username)
    db.commit()
    db.refresh(account)
    return account_to_out(account)


@router.post("/change-password", response_model=MessageOut)
def change_password(
    body: ChangePasswordIn,
    db: Session = Depends(get_db),
    account: Account = Depends(get_current_account),
) -> MessageOut:
    if not verify_password(body.old_password, account.password_hash):
        raise HTTPException(status_code=400, detail="原密码不正确")
    if body.old_password == body.new_password:
        raise HTTPException(status_code=400, detail="新密码不能与原密码相同")
    # 长度/策略由 ChangePasswordIn 校验（最少 8 位）
    # 原子更新密码与版本号：并发改密时版本号基于数据库当前值递增，不丢递增
    db.query(Account).filter(Account.id == account.id).update(
        {
            Account.password_hash: hash_password(body.new_password),
            Account.must_change_password: False,
            Account.session_version: Account.session_version + 1,
        },
        synchronize_session=False,
    )
    write_audit(
        db,
        actor_id=account.id,
        action="change_password",
        target_type="account",
        target_id=account.id,
    )
    db.commit()
    return MessageOut(message="密码已修改，请使用新密码登录")


@router.put("/me/email", response_model=AccountOut)
def update_my_email(
    body: UpdateEmailIn,
    db: Session = Depends(get_db),
    account: Account = Depends(get_current_account),
) -> AccountOut:
    email = body.email
    exists = db.query(Account).filter(Account.email == email, Account.id != account.id).first()
    if exists:
        raise HTTPException(status_code=400, detail="该邮箱已被占用")
    consume_email_code(db, email=email, code=body.code, purpose=EmailCodePurpose.bind_email)
    account.email = email
    write_audit(
        db,
        actor_id=account.id,
        action="update_email",
        target_type="account",
        target_id=account.id,
        detail=email,
    )
    db.commit()
    db.refresh(account)
    return account_to_out(account)


@router.get("/accounts", response_model=Page[AccountOut])
def list_accounts(
    role: Role | None = None,
    q: str | None = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    _: Account = Depends(require_roles(Role.super_admin)),
) -> Page[AccountOut]:
    query = db.query(Account).order_by(Account.created_at.desc())
    if role:
        query = query.filter(Account.role == role)
    if q:
        like = f"%{q.strip()}%"
        query = query.filter(
            (Account.username.ilike(like))
            | (Account.display_name.ilike(like))
            | (Account.phone.ilike(like))
            | (Account.email.ilike(like))
        )
    total = query.count()
    rows = query.offset(skip).limit(limit).all()
    return Page(total=total, items=[account_to_out(r) for r in rows])


@router.post("/accounts/{account_id}/reset-password", response_model=MessageOut)
def reset_password(
    account_id: str,
    body: ResetPasswordIn,
    db: Session = Depends(get_db),
    admin: Account = Depends(require_roles(Role.super_admin)),
) -> MessageOut:
    target = db.get(Account, account_id)
    if not target:
        raise HTTPException(status_code=404, detail="账号不存在")
    if target.role == Role.super_admin and target.id != admin.id:
        raise HTTPException(status_code=400, detail="不能重置其他超级管理员密码")
    # 管理员重置同样废止被重置账号已有的全部令牌（原子递增防并发覆盖）。
    db.query(Account).filter(Account.id == target.id).update(
        {
            Account.password_hash: hash_password(body.new_password),
            Account.must_change_password: True,
            Account.session_version: Account.session_version + 1,
        },
        synchronize_session=False,
    )
    write_audit(
        db,
        actor_id=admin.id,
        action="reset_password",
        target_type="account",
        target_id=target.id,
        detail=f"username={target.username}",
    )
    db.commit()
    return MessageOut(message="密码已重置")


@router.post("/accounts/{account_id}/set-active", response_model=AccountOut)
def set_account_active(
    account_id: str,
    body: SetActiveIn,
    db: Session = Depends(get_db),
    admin: Account = Depends(require_roles(Role.super_admin)),
) -> AccountOut:
    target = db.get(Account, account_id)
    if not target:
        raise HTTPException(status_code=404, detail="账号不存在")
    if target.id == admin.id and not body.is_active:
        raise HTTPException(status_code=400, detail="不能停用当前登录账号")
    if target.role == Role.super_admin and target.id != admin.id and not body.is_active:
        raise HTTPException(status_code=400, detail="不能停用其他超级管理员")
    target.is_active = body.is_active
    if not body.is_active:
        # 停用即废止该账号全部现有会话：即使之后被重新启用，旧 Cookie/Bearer
        # 也已失效，必须重新登录，避免“停用又启用”期间保留可用旧会话。
        db.query(Account).filter(Account.id == target.id).update(
            {Account.session_version: Account.session_version + 1},
            synchronize_session=False,
        )
    write_audit(
        db,
        actor_id=admin.id,
        action="set_account_active",
        target_type="account",
        target_id=target.id,
        detail=f"is_active={body.is_active}",
    )
    db.commit()
    db.refresh(target)
    return account_to_out(target)
