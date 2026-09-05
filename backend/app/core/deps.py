from collections.abc import Callable

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.core.security import decode_access_token
from app.models.entities import Account, Role

bearer_scheme = HTTPBearer(auto_error=False)

# 首次改密期间只允许完成改密所需的认证接口，不能依赖前端路由守卫。
PASSWORD_CHANGE_ALLOWED_PATHS = frozenset(
    {
        "/api/auth/me",
        "/api/auth/change-password",
        "/api/auth/logout",
    }
)


def _extract_token(request: Request, creds: HTTPAuthorizationCredentials | None) -> str | None:
    """优先读 HttpOnly Cookie；过渡期回落 Authorization: Bearer。"""
    s = get_settings()
    cookie_token = request.cookies.get(s.auth_cookie_name)
    if cookie_token:
        return cookie_token
    if s.auth_allow_bearer and creds is not None and creds.credentials:
        return creds.credentials
    return None


def get_current_account(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> Account:
    token = _extract_token(request, creds)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未登录")
    try:
        payload = decode_access_token(token)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    account_id = payload.get("sub")
    if not account_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="无效令牌")
    account = db.get(Account, account_id)
    if not account or not account.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="账号不可用")
    # Token 在改密前签发时的版本必须与数据库一致，防止旧 Cookie / Bearer 会话继续可用。
    if payload.get("sv") != account.session_version:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="登录状态已失效，请重新登录")
    if account.must_change_password and request.url.path not in PASSWORD_CHANGE_ALLOWED_PATHS:
        raise HTTPException(status_code=403, detail="请先修改初始密码")
    return account


def get_current_account_optional(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> Account | None:
    token = _extract_token(request, creds)
    if not token:
        return None
    try:
        payload = decode_access_token(token)
    except ValueError:
        return None
    account_id = payload.get("sub")
    if not account_id:
        return None
    account = db.get(Account, account_id)
    if not account or not account.is_active:
        return None
    if payload.get("sv") != account.session_version:
        return None
    return account


def require_roles(*roles: Role) -> Callable:
    def checker(account: Account = Depends(get_current_account)) -> Account:
        if account.role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权限")
        return account

    return checker
