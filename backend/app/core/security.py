from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
import jwt
from jwt.exceptions import InvalidTokenError, PyJWTError

from app.core.config import get_settings


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        return False


def create_access_token(subject: str, extra: dict[str, Any] | None = None) -> str:
    settings = get_settings()
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_expire_minutes)
    payload: dict[str, Any] = {"sub": subject, "exp": expire}
    if extra:
        payload.update(extra)
    token = jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)
    # PyJWT may return str (v2+) 
    return token if isinstance(token, str) else token.decode("utf-8")


def decode_access_token(token: str) -> dict[str, Any]:
    settings = get_settings()
    try:
        return jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
    except (InvalidTokenError, PyJWTError) as exc:
        raise ValueError("无效或过期的令牌") from exc
