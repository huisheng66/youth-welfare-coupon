"""测试盲区补齐：导出（redemptions / points-ledger）、批量时长、登出、
忘记密码、仪表盘等此前零覆盖端点的回归测试。

资损敏感面（导出、批量入账）优先；覆盖鉴权、CSV 行结构与幂等语义。

Run from backend/:
  .venv/bin/python -m pytest tests/test_export_points_auth.py -v
"""

from __future__ import annotations

import unittest
from decimal import Decimal

from tests._helpers import TempApp, reset_env_defaults


def _uid(ta: TempApp, username: str) -> str:
    with ta.session() as db:
        from app.models.entities import Account

        return db.query(Account).filter(Account.username == username).one().id


def _balance(ta: TempApp, user_id: str) -> Decimal:
    with ta.session() as db:
        from app.models.entities import PointAccount

        acc = db.query(PointAccount).filter(PointAccount.user_id == user_id).first()
        return acc.balance if acc else Decimal("0")


class TestRedemptionsExport(unittest.TestCase):
    def tearDown(self) -> None:
        reset_env_defaults()

    def _seed_logs(self, ta: TempApp) -> None:
        with ta.session() as db:
            from app.models.entities import Account, Merchant, RedemptionLog

            admin = db.query(Account).filter(Account.username == "admin").one()
            user = db.query(Account).filter(Account.username == "youth1").one()
            merchant = db.query(Merchant).first()
            db.add_all(
                [
                    RedemptionLog(
                        coupon_id=None,
                        merchant_id=merchant.id,
                        operator_id=admin.id,
                        user_id=user.id,
                        code="LIVEOK0000000001",
                        result="success",
                        reason="redeemed",
                        message="核销成功",
                    ),
                    RedemptionLog(
                        coupon_id=None,
                        merchant_id=merchant.id,
                        operator_id=admin.id,
                        user_id=None,
                        code="LIVEFAIL00000001",
                        result="failed",
                        reason="already_used",
                        message="券已使用",
                    ),
                ]
            )
            db.commit()

    def test_admin_export_contains_rows_and_result_filter(self) -> None:
        with TempApp() as ta:
            self._seed_logs(ta)
            token = ta.login("admin", "admin123")
            with ta.client() as c:
                r = c.get("/api/export/redemptions", headers=ta.bearer(token))
                self.assertEqual(r.status_code, 200, r.text)
                self.assertTrue(r.headers["content-type"].startswith("text/csv"))
                body = r.text
                self.assertIn("券码", body)
                self.assertIn("LIVEOK0000000001", body)
                self.assertIn("券已使用", body)
                self.assertIn("youth1", body)

                only_failed = c.get(
                    "/api/export/redemptions", headers=ta.bearer(token), params={"result": "failed"}
                )
                self.assertEqual(only_failed.status_code, 200)
                self.assertIn("LIVEFAIL00000001", only_failed.text)
                self.assertNotIn("LIVEOK0000000001", only_failed.text)

    def test_user_role_forbidden(self) -> None:
        with TempApp() as ta:
            token = ta.login("youth1", "youth123")
            with ta.client() as c:
                r = c.get("/api/export/redemptions", headers=ta.bearer(token))
                self.assertEqual(r.status_code, 403, r.text)


class TestPointsLedgerExport(unittest.TestCase):
    def tearDown(self) -> None:
        reset_env_defaults()

    def test_export_after_grant_and_user_filter(self) -> None:
        with TempApp() as ta:
            uid1 = _uid(ta, "youth1")
            uid2 = _uid(ta, "youth2")
            admin_id = _uid(ta, "admin")
            # 种子里仅 youth1 已核验：走真实 API 入账；youth2 直插账本行（导出只读账本）
            with ta.session() as db:
                from app.models.entities import PointLedger

                db.add(
                    PointLedger(
                        user_id=uid2,
                        change=Decimal("1.00"),
                        balance_after=Decimal("1.00"),
                        reason="志愿服务",
                        operator_id=admin_id,
                        ref_type="manual",
                    )
                )
                db.commit()
            admin = ta.login("admin", "admin123")
            with ta.client() as c:
                g = c.post(
                    "/api/points/grant",
                    headers=ta.bearer(admin),
                    json={"user_id": uid1, "amount": "2.5", "reason": "志愿服务"},
                )
                self.assertEqual(g.status_code, 200, g.text)

                r = c.get("/api/export/points-ledger", headers=ta.bearer(admin))
                self.assertEqual(r.status_code, 200, r.text)
                self.assertTrue(r.headers["content-type"].startswith("text/csv"))
                self.assertIn("youth1", r.text)
                self.assertIn("2.50", r.text)
                self.assertIn("志愿服务", r.text)

                only_u1 = c.get(
                    "/api/export/points-ledger", headers=ta.bearer(admin), params={"user_id": uid1}
                )
                self.assertIn("youth1", only_u1.text)
                self.assertNotIn("youth2", only_u1.text)

    def test_user_role_forbidden(self) -> None:
        with TempApp() as ta:
            token = ta.login("youth1", "youth123")
            with ta.client() as c:
                r = c.get("/api/export/points-ledger", headers=ta.bearer(token))
                self.assertEqual(r.status_code, 403, r.text)


class TestGrantPointsBatch(unittest.TestCase):
    def tearDown(self) -> None:
        reset_env_defaults()

    def test_batch_success_partial_failure_and_idempotency(self) -> None:
        with TempApp() as ta:
            uid1 = _uid(ta, "youth1")
            uid2 = _uid(ta, "youth2")
            base1, base2 = _balance(ta, uid1), _balance(ta, uid2)
            admin = ta.login("admin", "admin123")
            # 种子里仅 youth1 已核验：youth2 未核验应失败，uid3 不存在
            body = {"user_ids": [uid1, uid2, "nonexistent-user-id"], "amount": "2", "reason": "批量入账"}
            with ta.client() as c:
                # 首次请求即携带 Idempotency-Key
                idem_headers = {**ta.bearer(admin), "Idempotency-Key": "batch-test-key-1"}
                r = c.post("/api/points/grant-batch", headers=idem_headers, json=body)
                self.assertEqual(r.status_code, 200, r.text)
                self.assertIn("成功 1 人", r.json()["message"])
                self.assertIn("失败 2", r.json()["message"])
                self.assertIn("已核验", r.json()["message"])
                self.assertEqual(_balance(ta, uid1), base1 + Decimal("2.00"))
                self.assertEqual(_balance(ta, uid2), base2)  # 未核验不入账

                # 同 key 同请求体重放：余额不再增加
                r2 = c.post("/api/points/grant-batch", headers=idem_headers, json=body)
                self.assertEqual(r2.status_code, 200, r2.text)
                self.assertEqual(_balance(ta, uid1), base1 + Decimal("2.00"))

                # 换 key 再次执行：正常入账
                r3 = c.post(
                    "/api/points/grant-batch",
                    headers={**ta.bearer(admin), "Idempotency-Key": "batch-test-key-2"},
                    json=body,
                )
                self.assertEqual(r3.status_code, 200, r3.text)
                self.assertEqual(_balance(ta, uid1), base1 + Decimal("4.00"))

    def test_user_role_forbidden(self) -> None:
        with TempApp() as ta:
            uid1 = _uid(ta, "youth1")
            base1 = _balance(ta, uid1)
            token = ta.login("youth1", "youth123")
            with ta.client() as c:
                r = c.post(
                    "/api/points/grant-batch",
                    headers=ta.bearer(token),
                    json={"user_ids": [uid1], "amount": "1"},
                )
                self.assertEqual(r.status_code, 403, r.text)
                self.assertEqual(_balance(ta, uid1), base1)


class TestAuthLogoutAndForgot(unittest.TestCase):
    def tearDown(self) -> None:
        reset_env_defaults()

    def test_logout_clears_auth_cookie(self) -> None:
        with TempApp() as ta:
            with ta.client() as c:
                login = c.post("/api/auth/login", json={"username": "youth1", "password": "youth123"})
                self.assertEqual(login.status_code, 200, login.text)
                me = c.get("/api/auth/me")  # Cookie 已由登录下发
                self.assertEqual(me.status_code, 200, me.text)

                out = c.post("/api/auth/logout", headers={"X-Requested-With": "XMLHttpRequest"})
                self.assertEqual(out.status_code, 200, out.text)
                self.assertEqual(out.json()["message"], "已登出")

                me2 = c.get("/api/auth/me")
                self.assertEqual(me2.status_code, 401, me2.text)

    def test_forgot_password_does_not_leak_registration(self) -> None:
        with TempApp() as ta:
            # 种子邮箱是 demo.local（email-validator 拒绝的保留域），改写为普通域
            with ta.session() as db:
                from app.models.entities import Account

                acc = db.query(Account).filter(Account.username == "youth1").one()
                acc.email = "youth1@mailtest-xyz.com"
                db.commit()

            with ta.client() as c:
                unknown = c.post(
                    "/api/auth/forgot-password",
                    headers={"X-Requested-With": "XMLHttpRequest"},
                    json={"email": "nobody@mailtest-xyz.com"},
                )
                self.assertEqual(unknown.status_code, 200, unknown.text)

                known = c.post(
                    "/api/auth/forgot-password",
                    headers={"X-Requested-With": "XMLHttpRequest"},
                    json={"email": "youth1@mailtest-xyz.com"},
                )
                self.assertEqual(known.status_code, 200, known.text)

            with ta.session() as db:
                from sqlalchemy import text as _text

                rows = db.execute(
                    _text("SELECT email FROM email_codes WHERE purpose = 'reset_password'")
                ).fetchall()
                emails = {r[0] for r in rows}
                self.assertIn("youth1@mailtest-xyz.com", emails)
                self.assertNotIn("nobody@mailtest-xyz.com", emails)


class TestStatsDashboard(unittest.TestCase):
    def tearDown(self) -> None:
        reset_env_defaults()

    def test_admin_dashboard_shape(self) -> None:
        with TempApp() as ta:
            token = ta.login("admin", "admin123")
            with ta.client() as c:
                r = c.get("/api/dashboard", headers=ta.bearer(token))
                self.assertEqual(r.status_code, 200, r.text)
                body = r.json()
                for key in (
                    "users",
                    "pending_verifications",
                    "merchants",
                    "coupons_issued",
                    "coupons_used",
                    "templates",
                    "today_redemptions",
                ):
                    self.assertIn(key, body)
                self.assertGreaterEqual(body["users"], 1)
                self.assertGreaterEqual(body["merchants"], 1)

    def test_user_role_forbidden(self) -> None:
        with TempApp() as ta:
            token = ta.login("youth1", "youth123")
            with ta.client() as c:
                r = c.get("/api/dashboard", headers=ta.bearer(token))
                self.assertEqual(r.status_code, 403, r.text)


if __name__ == "__main__":
    unittest.main()


class TestClientErrorReport(unittest.TestCase):
    """前端未捕获错误上报：免登录、204、只进审计日志、字段严格截断。"""

    def tearDown(self) -> None:
        reset_env_defaults()

    def test_unauthenticated_report_writes_audit(self) -> None:
        with TempApp() as ta:
            with ta.client() as c:
                r = c.post(
                    "/api/client-errors",
                    headers={"X-Requested-With": "XMLHttpRequest"},
                    json={"kind": "unhandledrejection", "message": "boom at home", "stack": "Error: boom\n  at x", "route": "/home"},
                )
                self.assertEqual(r.status_code, 204, r.text)

            with ta.session() as db:
                from sqlalchemy import text as _text

                row = db.execute(
                    _text("SELECT actor_id, detail FROM audit_logs WHERE action = 'client_error' ORDER BY created_at DESC LIMIT 1")
                ).fetchone()
                self.assertIsNotNone(row)
                self.assertIsNone(row[0])
                self.assertIn("boom at home", row[1])
                self.assertIn("/home", row[1])

    def test_oversized_payload_rejected(self) -> None:
        with TempApp() as ta:
            with ta.client() as c:
                r = c.post(
                    "/api/client-errors",
                    headers={"X-Requested-With": "XMLHttpRequest"},
                    json={"message": "x" * 501},
                )
                self.assertEqual(r.status_code, 422, r.text)
