"""邮箱验证码测试：发码冷却 / 过期 / 复用 / 错误次数 / 消费。

Run from backend/:
  .\\.venv\\Scripts\\python.exe -m pytest tests/test_email_code.py -v
"""

from __future__ import annotations

import asyncio
import unittest
from datetime import timedelta

from tests._helpers import TempApp, reset_env_defaults


def _issue_code(ta: TempApp, email: str, purpose: str = "register") -> tuple[str, str | None]:
    """直接调 service 层发码，返回 (code_id, debug_code)。

    强制禁用 SMTP（console 模式），避免环境变量残留的 MAIL 配置触发真实发送。
    """
    from unittest import mock

    from app.core.config import Settings, get_settings
    from app.models.entities import EmailCodePurpose
    from app.services.mail import issue_email_code

    s = get_settings()
    purpose_enum = EmailCodePurpose(purpose)
    with ta.session() as db:
        with mock.patch.object(Settings, "smtp_configured", new_callable=mock.PropertyMock, return_value=False), \
             mock.patch.object(s, "mail_console", True):
            row, debug = asyncio.run(
                issue_email_code(db, email=email, purpose=purpose_enum, settings=s)
            )
            db.commit()
            return row.id, debug


def _consume(ta: TempApp, email: str, code: str, purpose: str = "register") -> None:
    from app.models.entities import EmailCodePurpose
    from app.services.mail import consume_email_code

    with ta.session() as db:
        consume_email_code(
            db, email=email, code=code, purpose=EmailCodePurpose(purpose)
        )
        db.commit()


def _insert_code_row(
    ta: TempApp,
    *,
    email: str,
    code: str,
    purpose: str,
    expires_at,
    used_at=None,
    attempts: int = 0,
) -> None:
    """直接插入 EmailCode 行（绕过冷却），用于测试 consume 边界。"""
    from app.models.entities import EmailCode, EmailCodePurpose

    with ta.session() as db:
        db.add(
            EmailCode(
                email=email,
                code=code,
                purpose=EmailCodePurpose(purpose),
                expires_at=expires_at,
                used_at=used_at,
                attempts=attempts,
            )
        )
        db.commit()


class TestEmailCode(unittest.TestCase):
    def tearDown(self) -> None:
        reset_env_defaults()

    def test_issue_returns_debug_in_console_mode(self) -> None:
        """未配置 SMTP 时，issue_email_code 返回 debug_code（控制台模式）。"""
        with TempApp() as ta:
            _, debug = _issue_code(ta, "newuser1@demo.local", "register")
            self.assertIsNotNone(debug)
            self.assertEqual(len(debug), 6)

    def test_send_cooldown_blocks_rapid_resend(self) -> None:
        """同一邮箱同用途连续发码，第二次应 429。"""
        from fastapi import HTTPException

        with TempApp() as ta:
            _issue_code(ta, "cooldown@demo.local", "register")
            with self.assertRaises(HTTPException) as ctx:
                _issue_code(ta, "cooldown@demo.local", "register")
            self.assertEqual(ctx.exception.status_code, 429)
            self.assertIn("频繁", ctx.exception.detail)

    def test_consume_correct_code_success(self) -> None:
        with TempApp() as ta:
            _, debug = _issue_code(ta, "ok@demo.local", "register")
            _consume(ta, "ok@demo.local", debug, "register")  # 不抛异常即成功

    def test_consume_wrong_code_increments_attempts(self) -> None:
        from fastapi import HTTPException

        with TempApp() as ta:
            _, debug = _issue_code(ta, "wrong@demo.local", "register")
            with self.assertRaises(HTTPException) as ctx:
                _consume(ta, "wrong@demo.local", "000000", "register")
            self.assertEqual(ctx.exception.status_code, 400)
            self.assertIn("还可尝试", ctx.exception.detail)
            # 正确码仍可消费（attempts 未超限）
            _consume(ta, "wrong@demo.local", debug, "register")

    def test_consume_expired_code_fails(self) -> None:
        from fastapi import HTTPException
        from app.models.entities import utcnow

        with TempApp() as ta:
            _insert_code_row(
                ta,
                email="expired@demo.local",
                code="123456",
                purpose="register",
                expires_at=utcnow() - timedelta(minutes=1),
            )
            with self.assertRaises(HTTPException) as ctx:
                _consume(ta, "expired@demo.local", "123456", "register")
            self.assertEqual(ctx.exception.status_code, 400)
            self.assertIn("过期", ctx.exception.detail)

    def test_consume_reused_code_fails(self) -> None:
        """已使用的验证码（used_at 非空）不能再消费。"""
        from fastapi import HTTPException
        from app.models.entities import utcnow

        with TempApp() as ta:
            _insert_code_row(
                ta,
                email="reused@demo.local",
                code="654321",
                purpose="register",
                expires_at=utcnow() + timedelta(minutes=10),
                used_at=utcnow(),
            )
            with self.assertRaises(HTTPException) as ctx:
                _consume(ta, "reused@demo.local", "654321", "register")
            self.assertEqual(ctx.exception.status_code, 400)
            self.assertIn("无效或已过期", ctx.exception.detail)

    def test_consume_wrong_code_exceeds_max_attempts(self) -> None:
        """错误次数达上限后，正确码也不再可用。"""
        from fastapi import HTTPException
        from app.models.entities import utcnow

        with TempApp() as ta:
            _insert_code_row(
                ta,
                email="maxatt@demo.local",
                code="999999",
                purpose="register",
                expires_at=utcnow() + timedelta(minutes=10),
                attempts=5,  # 已达上限
            )
            with self.assertRaises(HTTPException) as ctx:
                _consume(ta, "maxatt@demo.local", "999999", "register")
            self.assertEqual(ctx.exception.status_code, 400)
            self.assertIn("次数过多", ctx.exception.detail)


if __name__ == "__main__":
    unittest.main()
