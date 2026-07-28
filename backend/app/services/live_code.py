from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from jwt.exceptions import InvalidTokenError, PyJWTError

from app.core.config import get_settings

LIVE_TYP = "live_coupon"


def create_live_code(*, coupon_id: str, user_id: str, permanent_code: str) -> tuple[str, int, datetime]:
    settings = get_settings()
    seconds = settings.live_code_expire_seconds
    exp = datetime.now(timezone.utc) + timedelta(seconds=seconds)
    payload = {
        "typ": LIVE_TYP,
        "cid": coupon_id,
        "uid": user_id,
        "code": permanent_code,
        "exp": exp,
    }
    token = jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)
    if not isinstance(token, str):
        token = token.decode("utf-8")
    return token, seconds, exp


def decode_live_code(token: str) -> dict[str, Any]:
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
    except (InvalidTokenError, PyJWTError) as exc:
        raise ValueError("动态券码无效或已过期") from exc
    if payload.get("typ") != LIVE_TYP:
        raise ValueError("不是有效的动态券码")
    if not payload.get("cid") or not payload.get("uid"):
        raise ValueError("动态券码内容不完整")
    return payload


def looks_like_live_code(value: str) -> bool:
    # JWT: header.payload.sig
    parts = value.split(".")
    return len(parts) == 3 and len(value) > 40
