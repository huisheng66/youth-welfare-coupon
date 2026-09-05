"""邮箱验证码测试：发码冷却 / 过期 / 复用 / 错误次数 / 消费。

Run from backend/:
  .\\.venv\\Scripts\\python.exe -m pytest tests/test_email_code.py -v
"""

from __future__ import annotations

import asyncio
import unittest
from datetime import timedelta
from unittest import mock

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

    def test_production_never_returns_debug_code(self) -> None:
        """生产未配 SMTP 必须 fail-closed：发码接口不可用，而不是“成功只写日志”。"""
        from fastapi import HTTPException

        from app.core.config import get_settings
        from app.models.entities import EmailCodePurpose
        from app.services.mail import issue_email_code

        with TempApp() as ta:
            settings = get_settings()
            settings.app_env = "production"
            settings.mail_console = True
            with ta.session() as db:
                with mock.patch.object(
                    type(settings), "smtp_configured", new_callable=mock.PropertyMock, return_value=False
                ):
                    with self.assertRaises(HTTPException) as ctx:
                        asyncio.run(
                            issue_email_code(
                                db,
                                email="production@demo.local",
                                purpose=EmailCodePurpose.reset_password,
                                settings=settings,
                            )
                        )
                self.assertEqual(ctx.exception.status_code, 503)
                # 未产生任何验证码行（fail-closed 而非控制台回落）
                from app.models.entities import EmailCode

                self.assertEqual(
                    db.query(EmailCode).filter(EmailCode.email == "production@demo.local").count(), 0
                )

    def test_stored_code_is_keyed_hash_not_plaintext(self) -> None:
        """新验证码入库即 HMAC 摘要：拖库后无法离线枚举六位码。"""
        from app.core.config import get_settings
        from app.models.entities import EmailCode
        from app.services.mail import hash_email_code

        with TempApp() as ta:
            _, debug = _issue_code(ta, "hashstore@demo.local", "register")
            self.assertIsNotNone(debug)
            with ta.session() as db:
                row = db.query(EmailCode).filter(EmailCode.email == "hashstore@demo.local").one()
            self.assertEqual(len(row.code), 64)
            self.assertNotEqual(row.code, debug)
            self.assertEqual(row.code, hash_email_code(debug, get_settings()))

    def test_smtp_send_uses_tls_and_validates_certificates(self) -> None:
        from unittest import mock

        from app.core.config import Settings
        from app.services.mail import send_email_html

        settings = Settings(
            mail_server="smtp.example.invalid",
            mail_port=465,
            mail_username="sender@example.invalid",
            mail_password="app-password",
            mail_from="sender@example.invalid",
            mail_from_name="Youth",
            mail_ssl_tls=True,
            mail_starttls=True,
        )
        with mock.patch("aiosmtplib.send", new_callable=mock.AsyncMock) as smtp_send:
            asyncio.run(
                send_email_html(
                    to="recipient@example.invalid",
                    subject="Verification",
                    html="<p>123456</p>",
                    settings=settings,
                )
            )

        message = smtp_send.await_args.args[0]
        kwargs = smtp_send.await_args.kwargs
        self.assertEqual(message["From"], "Youth <sender@example.invalid>")
        self.assertEqual(message["To"], "recipient@example.invalid")
        self.assertTrue(message.is_multipart())
        self.assertTrue(kwargs["use_tls"])
        self.assertFalse(kwargs["start_tls"])
        self.assertTrue(kwargs["validate_certs"])
        self.assertEqual(kwargs["timeout"], 30)

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

    def test_wrong_attempts_survive_request_rollback(self) -> None:
        """T04 核心回归：连续 HTTP 试错达到上限后锁定，attempts 不随请求回滚清零。"""
        with TempApp() as ta:
            _, debug = _issue_code(ta, "lockout@example.com", "register")
            with ta.client() as c:
                last = None
                for _ in range(5):
                    last = c.post(
                        "/api/auth/register",
                        json={
                            "email": "lockout@example.com",
                            "code": "000000",
                            "password": "goodpass123",
                        },
                    )
                    self.assertEqual(last.status_code, 400, last.text)
                # 第 6 次：正确码也应被拒绝（错误次数已锁定）
                correct = c.post(
                    "/api/auth/register",
                    json={
                        "email": "lockout@example.com",
                        "code": debug,
                        "password": "goodpass123",
                    },
                )
                self.assertEqual(correct.status_code, 400, correct.text)
                self.assertIn("次数过多", correct.json()["detail"])
                from app.models.entities import EmailCode

                with ta.session() as db:
                    row = (
                        db.query(EmailCode)
                        .filter(EmailCode.email == "lockout@example.com")
                        .order_by(EmailCode.created_at.desc())
                        .first()
                    )
                self.assertEqual(row.attempts, 5, "错误计数必须在独立事务持久化")

    def test_concurrent_consume_single_winner(self) -> None:
        """并发消费同一验证码：条件更新保证只有一个成功。"""
        from sqlalchemy.orm import sessionmaker

        from fastapi import HTTPException
        from app.models.entities import utcnow

        with TempApp() as ta:
            _insert_code_row(
                ta,
                email="race@demo.local",
                code="654321",
                purpose="register",
                expires_at=utcnow() + timedelta(minutes=10),
            )
            # 两个独立会话模拟并发请求
            Session2 = sessionmaker(bind=ta.engine, autoflush=False)
            results: list[str] = []

            def attempt(session_factory, tag: str) -> None:
                db = session_factory()
                try:
                    from app.models.entities import EmailCodePurpose
                    from app.services.mail import consume_email_code

                    consume_email_code(db, email="race@demo.local", code="654321", purpose=EmailCodePurpose.register)
                    db.commit()
                    results.append(tag)
                except HTTPException:
                    db.rollback()
                finally:
                    db.close()

            attempt(ta.Session, "s1")
            attempt(Session2, "s2")
            self.assertEqual(len(results), 1, f"并发消费只允许一个成功，实际: {results}")


if __name__ == "__main__":
    unittest.main()
