"""Field-level encryption (Fernet) for sensitive PII such as bank card numbers."""

from __future__ import annotations

import base64
import hashlib
import logging
import re
import warnings
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from app.core.config import get_settings

logger = logging.getLogger(__name__)


def _digits_only(value: str) -> str:
    return re.sub(r"\D", "", value or "")


def normalize_bank_card(card_number: str) -> str:
    """Strip spaces/dashes; keep digits only."""
    return _digits_only(card_number)


def validate_bank_card(card_number: str) -> str:
    """Validate length (CN debit/credit common 16–19) and Luhn; return digits."""
    digits = normalize_bank_card(card_number)
    if not (16 <= len(digits) <= 19):
        raise ValueError("银行卡号应为 16–19 位数字")
    if not _luhn_ok(digits):
        raise ValueError("银行卡号校验失败，请核对后重试")
    return digits


def _luhn_ok(digits: str) -> bool:
    total = 0
    reverse = digits[::-1]
    for i, ch in enumerate(reverse):
        n = ord(ch) - 48
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


def mask_bank_card(digits: str) -> str:
    """Display form: 6222********1234"""
    d = _digits_only(digits)
    if len(d) < 8:
        return "****"
    mid = "*" * max(4, len(d) - 8)
    return f"{d[:4]}{mid}{d[-4:]}"


def _fernet_from_material(material: str) -> Fernet:
    raw = hashlib.sha256(material.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(raw))


@lru_cache
def _multi_fernet() -> MultiFernet:
    """
    Primary key = FIELD_ENCRYPTION_KEY if set, else SECRET_KEY (deprecated fallback).
    Previous key (if set) can still decrypt old ciphertext.
    """
    settings = get_settings()
    materials: list[str] = []
    primary = (settings.field_encryption_key or "").strip()
    if primary:
        materials.append(primary)
    else:
        warnings.warn(
            "FIELD_ENCRYPTION_KEY 未设置，银行卡加密回退使用 SECRET_KEY。"
            "生产环境请配置独立 FIELD_ENCRYPTION_KEY。",
            DeprecationWarning,
            stacklevel=2,
        )
        logger.warning(
            "FIELD_ENCRYPTION_KEY not set; field encryption falls back to SECRET_KEY"
        )
        materials.append(settings.secret_key)
    prev = (settings.field_encryption_key_previous or "").strip()
    if prev and prev not in materials:
        materials.append(prev)
    # Also try SECRET_KEY as last resort when dedicated key is set
    # (migration path from old installs)
    sk = settings.secret_key
    if primary and sk and sk not in materials:
        materials.append(sk)
    fernets = [_fernet_from_material(m) for m in materials]
    return MultiFernet(fernets)


def encrypt_text(plain: str) -> str:
    if not plain:
        raise ValueError("empty plaintext")
    # MultiFernet.encrypt uses the first (primary) key
    return _multi_fernet().encrypt(plain.encode("utf-8")).decode("ascii")


def decrypt_text(token: str) -> str:
    if not token:
        raise ValueError("empty ciphertext")
    try:
        return _multi_fernet().decrypt(token.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise ValueError("密文无效或密钥已变更，无法解密") from exc


def clear_crypto_cache() -> None:
    _multi_fernet.cache_clear()
