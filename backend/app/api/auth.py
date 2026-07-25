from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_account, require_roles
from app.core.security import create_access_token, hash_password, verify_password
from app.models.entities import Account, Role, UserProfile, VerifyStatus
from app.schemas.auth import (
    AccountOut,
    CreateIssueAdminIn,
    CreateMerchantAccountIn,
    LoginIn,
    RegisterIn,
)
from app.schemas.common import TokenOut
from app.services.audit import write_audit

router = APIRouter(prefix="/auth", tags=["认证"])


def account_to_out(account: Account) -> AccountOut:
    verify_status = None
    if account.profile:
        verify_status = account.profile.verify_status
    return AccountOut(
        id=account.id,
        username=account.username,
        role=account.role,
        display_name=account.display_name,
        phone=account.phone,
        is_active=account.is_active,
        merchant_id=account.merchant_id,
        verify_status=verify_status,
    )


@router.post("/login", response_model=TokenOut)
def login(body: LoginIn, db: Session = Depends(get_db)) -> TokenOut:
    account = db.query(Account).filter(Account.username == body.username).first()
    if not account or not verify_password(body.password, account.password_hash):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="用户名或密码错误")
    if not account.is_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="账号已停用")
    token = create_access_token(account.id, {"role": account.role.value})
    return TokenOut(access_token=token)


@router.post("/register", response_model=AccountOut)
def register(body: RegisterIn, db: Session = Depends(get_db)) -> AccountOut:
    if db.query(Account).filter(Account.username == body.username).first():
        raise HTTPException(status_code=400, detail="用户名已存在")
    if body.phone and db.query(Account).filter(Account.phone == body.phone).first():
        raise HTTPException(status_code=400, detail="手机号已注册")
    account = Account(
        username=body.username,
        password_hash=hash_password(body.password),
        role=Role.user,
        display_name=body.display_name or body.username,
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
    account = Account(
        username=body.username,
        password_hash=hash_password(body.password),
        role=Role.merchant,
        display_name=body.display_name or body.username,
        merchant_id=body.merchant_id,
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
    account = Account(
        username=body.username,
        password_hash=hash_password(body.password),
        role=Role.issue_admin,
        display_name=body.display_name or body.username,
    )
    db.add(account)
    write_audit(db, actor_id=admin.id, action="create_issue_admin", target_type="account", target_id=body.username)
    db.commit()
    db.refresh(account)
    return account_to_out(account)
