from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from jwt.exceptions import InvalidTokenError, PyJWTError

from app.core.config import get_settings

LIVE_TYP = "live_coupon"

# 动态码载荷只含核销所需的最小 claim 集合：
# - 不再携带永久券码：泄露 JWT 之外，永久编号不具备任何核销能力；
# - exp 必须存在且由 PyJWT 校验，缺 exp 的载荷一律拒绝。
REQUIRED_CLAIMS = ("exp", "cid", "uid", "typ")


def create_live_code(*, coupon_id: str, user_id: str) -> tuple[str, int, datetime]:
    settings = get_settings()
    seconds = settings.live_code_expire_seconds
    exp = datetime.now(timezone.utc) + timedelta(seconds=seconds)
    payload = {
        "typ": LIVE_TYP,
        "cid": coupon_id,
        "uid": user_id,
        "iat": datetime.now(timezone.utc),
        "exp": exp,
    }
    token = jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)
    if not isinstance(token, str):
        token = token.decode("utf-8")
    return token, seconds, exp


def decode_live_code(token: str) -> dict[str, Any]:
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.secret_key,
            algorithms=[settings.algorithm],
            options={"require": list(REQUIRED_CLAIMS)},
        )
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
