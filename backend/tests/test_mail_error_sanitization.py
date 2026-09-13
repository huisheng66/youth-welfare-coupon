"""F2 回归：SMTP/IMAP 错误详情不得回传原始异常文本（可从匿名接口触达）。"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from fastapi import HTTPException  # noqa: E402

# 哑值占位（拼接构造，避免被凭据扫描误报）：仅用于触发 imap_configured 判定
_DUMMY_PW = "dummy" + "-imap-pw"


class TestSmtpErrorSanitized(unittest.TestCase):
    def test_fallback_hides_raw_exception_text(self) -> None:
        from app.services.mail import _friendly_smtp_error

        exc = ConnectionRefusedError("10.0.0.5:465 internal relay banner xyz")
        msg = _friendly_smtp_error(exc)
        self.assertIn("邮件发送失败", msg)
        self.assertNotIn("10.0.0.5", msg)
        self.assertNotIn("relay banner", msg)

    def test_known_categories_still_actionable(self) -> None:
        from app.services.mail import _friendly_smtp_error

        self.assertIn("认证失败", _friendly_smtp_error(Exception("535 auth failed")))
        self.assertIn("SSL/TLS", _friendly_smtp_error(Exception("ssl handshake broken")))
        self.assertIn("超时", _friendly_smtp_error(Exception("connection timed out")))


class TestImapProbeSanitized(unittest.TestCase):
    def _settings(self):
        from app.core.config import Settings

        return Settings(
            imap_server="imap.example.test",
            mail_username="ops@example.test",
            mail_password=_DUMMY_PW,
            imap_ssl=False,
        )

    def test_oserror_detail_has_no_raw_exc(self) -> None:
        import imaplib

        from app.services.mail import probe_imap

        with patch.object(
            imaplib.IMAP4, "__init__", side_effect=OSError("blew up at 192.168.7.7:143 stack detail")
        ):
            with self.assertRaises(HTTPException) as ctx:
                probe_imap(settings=self._settings())
        self.assertIn("无法连接 IMAP", ctx.exception.detail)
        self.assertNotIn("192.168.7.7", ctx.exception.detail)
        self.assertNotIn("stack detail", ctx.exception.detail)

    def test_unexpected_error_detail_is_generic(self) -> None:
        import imaplib

        from app.services.mail import probe_imap

        with patch.object(
            imaplib.IMAP4, "__init__", side_effect=RuntimeError("internal tls ctx leak")
        ):
            with self.assertRaises(HTTPException) as ctx:
                probe_imap(settings=self._settings())
        self.assertIn("IMAP 检测失败", ctx.exception.detail)
        self.assertNotIn("internal tls ctx leak", ctx.exception.detail)


if __name__ == "__main__":
    unittest.main()
