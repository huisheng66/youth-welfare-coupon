"""HttpOnly Cookie 辅助：签发与清除认证 token。

将 JWT 从 localStorage 迁到 HttpOnly Cookie，前端 JS 无法读取，
即便发生 XSS 也无法窃取 token，配合 SameSite=Lax 防护 CSRF。
"""

from __future__ import annotations

from fastapi import Response

from app.core.config import Settings, get_settings


def set_auth_cookie(response: Response, token: str, settings: Settings | None = None) -> None:
    """登录/刷新时下发 HttpOnly Cookie。"""
    s = settings or get_settings()
    response.set_cookie(
        key=s.auth_cookie_name,
        value=token,
        max_age=s.access_token_expire_minutes * 60,
        httponly=True,
        secure=s.effective_auth_cookie_secure,
        samesite=s.auth_cookie_samesite,
        path="/",
        domain=s.auth_cookie_domain or None,
    )


def clear_auth_cookie(response: Response, settings: Settings | None = None) -> None:
    """登出时清除 Cookie。"""
    s = settings or get_settings()
    response.delete_cookie(
        key=s.auth_cookie_name,
        path="/",
        domain=s.auth_cookie_domain or None,
    )
