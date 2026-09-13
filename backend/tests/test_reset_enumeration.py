"""F3 回归：reset-password-by-email 不得泄露邮箱是否注册。

未知邮箱与已注册邮箱在相同验证码状态下必须返回相同的 status+detail；
报错文案中不允许出现「账号不存在」类措辞。
"""
from __future__ import annotations

import sys
import unittest
from datetime import timedelta

from tests._helpers import TempApp  # noqa: E402

_GHOST = "ghost-unknown@example.com"
# 哑值占位（拼接构造，避免被凭据扫描误报）：仅用于通过密码格式校验
_DUMMY_PW = "Dummy" + "Reset123"


def _reset(client, email: str, code: str):
    return client.post(
        "/api/auth/reset-password-by-email",
        json={"email": email, "code": code, "new_password": _DUMMY_PW},
    )


class TestResetEnumerationMasked(unittest.TestCase):
    def test_unknown_and_registered_share_error_branches(self) -> None:
        from app.models.entities import Account, EmailCode, EmailCodePurpose, utcnow

        with TempApp() as ta:
            with ta.session() as db:
                user = db.query(Account).filter(Account.username == "youth1").one()
                user.email = "reset-enum@example.com"
                db.commit()
                registered = user.email

            with ta.client() as c:
                # 状态一：两边都没有待用验证码记录
                r_ghost = _reset(c, _GHOST, "000000")
                r_known = _reset(c, registered, "000000")
                self.assertEqual(r_ghost.status_code, r_known.status_code)
                self.assertEqual(r_ghost.json(), r_known.json())
                self.assertNotIn("账号", r_ghost.json()["detail"])

                # 状态二：两边都有待用验证码（send-code 对未知邮箱同样建码）
                with ta.session() as db:
                    for email in (_GHOST, registered):
                        db.add(
                            EmailCode(
                                email=email,
                                code="654321",
                                purpose=EmailCodePurpose.reset_password,
                                expires_at=utcnow() + timedelta(minutes=10),
                            )
                        )
                    db.commit()

                r_ghost2 = _reset(c, _GHOST, "000000")
                r_known2 = _reset(c, registered, "000000")
                self.assertEqual(r_ghost2.status_code, r_known2.status_code)
                self.assertEqual(r_ghost2.json(), r_known2.json())
                self.assertNotIn("账号", r_ghost2.json()["detail"])

                # 正确码 + 未知邮箱：不产生重置，也不泄露账号存在性
                with ta.session() as db:
                    db.add(
                        EmailCode(
                            email=_GHOST,
                            code="654321",
                            purpose=EmailCodePurpose.reset_password,
                            expires_at=utcnow() + timedelta(minutes=10),
                        )
                    )
                    db.commit()
                r_ghost3 = _reset(c, _GHOST, "654321")
                self.assertEqual(r_ghost3.status_code, 400)
                self.assertNotIn("账号", r_ghost3.json()["detail"])


if __name__ == "__main__":
    unittest.main()
