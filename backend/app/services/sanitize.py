"""Sanitize user-controlled free-text fields to reduce stored XSS surface."""

from __future__ import annotations

import re

# C0 controls except tab/newline; also DEL
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
# HTML / script angle brackets
_ANGLE_RE = re.compile(r"[<>]")
# Crude tag strip before angle strip
_TAG_RE = re.compile(r"<[^>]*>", re.IGNORECASE)
# Password: at least one letter and one digit (recommended policy helper)
_HAS_LETTER = re.compile(r"[A-Za-z\u4e00-\u9fff]")
_HAS_DIGIT = re.compile(r"\d")


def strip_control_chars(value: str) -> str:
    return _CONTROL_RE.sub("", value or "")


def sanitize_plain_text(
    value: str | None,
    *,
    max_length: int = 256,
    strip_angles: bool = True,
) -> str:
    """
    Normalize free text for names / org / display: strip controls and optional ``<>``.
    Never returns raw ``<script>...</script>``.
    """
    s = strip_control_chars(value or "").strip()
    if strip_angles:
        s = _TAG_RE.sub("", s)
        s = _ANGLE_RE.sub("", s)
    if max_length > 0:
        s = s[:max_length]
    return s


def sanitize_note(value: str | None, *, max_length: int = 2000) -> str:
    """Remarks / material notes: allow prose but strip markup."""
    return sanitize_plain_text(value, max_length=max_length, strip_angles=True)


def contains_raw_markup(value: str | None) -> bool:
    if not value:
        return False
    return "<" in value or ">" in value


def validate_password_strength(password: str, *, min_length: int = 8) -> str:
    """
    Enforce minimum length (default 8). Letters+digits recommended;
    reject empty / too short. Returns cleaned password (strip only ends).
    """
    pwd = password if password is not None else ""
    if len(pwd) < min_length:
        raise ValueError(f"密码至少 {min_length} 位")
    if len(pwd) > 64:
        raise ValueError("密码过长")
    return pwd


def password_has_letter_and_digit(password: str) -> bool:
    return bool(_HAS_LETTER.search(password or "") and _HAS_DIGIT.search(password or ""))
