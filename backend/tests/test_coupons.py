"""券生命周期测试：发券 / 作废 / 过期 / 核销 / 重复核销 / 动态码。

Run from backend/:
  .\\.venv\\Scripts\\python.exe -m pytest tests/test_coupons.py -v
  # 或无 pytest：
  .\\.venv\\Scripts\\python.exe tests/test_coupons.py
"""

from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from tests._helpers import TempApp, reset_env_defaults


def _find_admin_template_id(ta: TempApp) -> tuple[str, str, str]:
    """返回 (admin_id, template_id, youth1_id)。"""
    with ta.session() as db:
        from app.models.entities import Account, CouponTemplate

        admin = db.query(Account).filter(Account.username == "admin").one()
        tmpl = db.query(CouponTemplate).filter(CouponTemplate.is_active.is_(True)).first()
        youth = db.query(Account).filter(Account.username == "youth1").one()
        return admin.id, tmpl.id, youth.id


def _first_coupon_of(ta: TempApp, username: str) -> tuple[str, str]:
    """返回 (coupon_id, code)。"""
    with ta.session() as db:
        from app.models.entities import Account, CouponInstance, CouponStatus

        youth = db.query(Account).filter(Account.username == username).one()
        c = (
            db.query(CouponInstance)
            .filter(
                CouponInstance.user_id == youth.id,
                CouponInstance.status == CouponStatus.unused,
            )
            .order_by(CouponInstance.issued_at.desc())
            .first()
        )
        assert c is not None, f"{username} has no unused coupon"
        return c.id, c.code


class TestCouponLifecycle(unittest.TestCase):
    def tearDown(self) -> None:
        reset_env_defaults()

    # ---- 发券 ----
    def test_issue_coupon_to_approved_user(self) -> None:
        with TempApp() as ta:
            admin_token = ta.login("issuer", "issuer123")
            _, tmpl_id, youth_id = _find_admin_template_id(ta)
            with ta.client() as c:
                r = c.post(
                    "/api/coupons/issue",
                    headers=ta.bearer(admin_token),
                    json={"user_id": youth_id, "template_id": tmpl_id, "quantity": 2},
                )
                self.assertEqual(r.status_code, 200, r.text)
                data = r.json()
                self.assertEqual(len(data), 2)
                self.assertEqual(data[0]["status"], "unused")
                self.assertEqual(data[0]["user_id"], youth_id)
                self.assertIn("code", data[0])
                self.assertIn("template_name", data[0])

    def test_issue_coupon_to_unapproved_user_fails(self) -> None:
        """youth2 待审核，发券应失败。"""
        with TempApp() as ta:
            admin_token = ta.login("issuer", "issuer123")
            _, tmpl_id, _ = _find_admin_template_id(ta)
            with ta.session() as db:
                from app.models.entities import Account

                youth2 = db.query(Account).filter(Account.username == "youth2").one()
                youth2_id = youth2.id
            with ta.client() as c:
                r = c.post(
                    "/api/coupons/issue",
                    headers=ta.bearer(admin_token),
                    json={"user_id": youth2_id, "template_id": tmpl_id, "quantity": 1},
                )
                self.assertEqual(r.status_code, 400, r.text)
                self.assertIn("核验", r.json()["detail"])

    def test_issue_coupon_invalid_user_role(self) -> None:
        """给商家账号发券应失败。"""
        with TempApp() as ta:
            admin_token = ta.login("issuer", "issuer123")
            _, tmpl_id, _ = _find_admin_template_id(ta)
            with ta.session() as db:
                from app.models.entities import Account

                m = db.query(Account).filter(Account.username == "merchant1").one()
                mid = m.id
            with ta.client() as c:
                r = c.post(
                    "/api/coupons/issue",
                    headers=ta.bearer(admin_token),
                    json={"user_id": mid, "template_id": tmpl_id, "quantity": 1},
                )
                self.assertEqual(r.status_code, 400, r.text)
                self.assertIn("无效", r.json()["detail"])

    # ---- 作废 ----
    def test_void_unused_coupon(self) -> None:
        with TempApp() as ta:
            admin_token = ta.login("issuer", "issuer123")
            coupon_id, _ = _first_coupon_of(ta, "youth1")
            with ta.client() as c:
                r = c.post(
                    f"/api/coupons/instances/{coupon_id}/void",
                    headers=ta.bearer(admin_token),
                    json={"reason": "测试作废"},
                )
                self.assertEqual(r.status_code, 200, r.text)
                self.assertEqual(r.json()["status"], "void")
                self.assertEqual(r.json()["void_reason"], "测试作废")

    def test_void_used_coupon_fails(self) -> None:
        with TempApp() as ta:
            admin_token = ta.login("issuer", "issuer123")
            m_token = ta.login("merchant1", "merchant123")
            coupon_id, code = _first_coupon_of(ta, "youth1")
            with ta.client() as c:
                # 先核销
                r1 = c.post(
                    "/api/coupons/redeem",
                    headers=ta.bearer(m_token),
                    json={"code": code},
                )
                self.assertEqual(r1.status_code, 200, r1.text)
                # 再作废应失败
                r2 = c.post(
                    f"/api/coupons/instances/{coupon_id}/void",
                    headers=ta.bearer(admin_token),
                    json={"reason": "尝试作废已核销券"},
                )
                self.assertEqual(r2.status_code, 400, r2.text)

    # ---- 核销 ----
    def test_redeem_with_permanent_code_success(self) -> None:
        with TempApp() as ta:
            m_token = ta.login("merchant1", "merchant123")
            _, code = _first_coupon_of(ta, "youth1")
            with ta.client() as c:
                r = c.post("/api/coupons/redeem", headers=ta.bearer(m_token), json={"code": code})
                self.assertEqual(r.status_code, 200, r.text)
                self.assertEqual(r.json()["message"], "核销成功")
                self.assertEqual(r.json()["coupon"]["status"], "used")
                self.assertIsNotNone(r.json()["coupon"]["redeemed_at"])

    def test_redeem_already_redeemed_fails(self) -> None:
        """重复核销应失败（并发安全由条件更新保证）。"""
        with TempApp() as ta:
            m_token = ta.login("merchant1", "merchant123")
            _, code = _first_coupon_of(ta, "youth1")
            with ta.client() as c:
                r1 = c.post("/api/coupons/redeem", headers=ta.bearer(m_token), json={"code": code})
                self.assertEqual(r1.status_code, 200, r1.text)
                r2 = c.post("/api/coupons/redeem", headers=ta.bearer(m_token), json={"code": code})
                self.assertEqual(r2.status_code, 400, r2.text)
                self.assertIn("已核销", r2.json()["detail"])

    def test_redeem_expired_coupon_fails(self) -> None:
        with TempApp() as ta:
            m_token = ta.login("merchant1", "merchant123")
            coupon_id, code = _first_coupon_of(ta, "youth1")
            # 直接改 DB 让券过期
            with ta.session() as db:
                from app.models.entities import CouponInstance

                c = db.get(CouponInstance, coupon_id)
                c.expires_at = datetime.now(timezone.utc) - timedelta(days=1)
                db.commit()
            with ta.client() as c:
                r = c.post("/api/coupons/redeem", headers=ta.bearer(m_token), json={"code": code})
                self.assertEqual(r.status_code, 400, r.text)
                self.assertIn("过期", r.json()["detail"])

    def test_redeem_wrong_merchant_fails(self) -> None:
        """merchant2 不能核销 merchant1 店的券。"""
        with TempApp() as ta:
            m2_token = ta.login("merchant2", "merchant123")
            _, code = _first_coupon_of(ta, "youth1")  # 餐饮店券，属 merchant1
            with ta.client() as c:
                r = c.post("/api/coupons/redeem", headers=ta.bearer(m2_token), json={"code": code})
                self.assertEqual(r.status_code, 400, r.text)
                self.assertIn("非本店", r.json()["detail"])

    def test_redeem_nonexistent_code_returns_404(self) -> None:
        with TempApp() as ta:
            m_token = ta.login("merchant1", "merchant123")
            with ta.client() as c:
                r = c.post(
                    "/api/coupons/redeem",
                    headers=ta.bearer(m_token),
                    json={"code": "NOTEXIST1234"},
                )
                self.assertEqual(r.status_code, 404, r.text)

    # ---- 动态码 ----
    def test_live_code_redeem_success(self) -> None:
        with TempApp() as ta:
            u_token = ta.login("youth1", "youth123")
            m_token = ta.login("merchant1", "merchant123")
            coupon_id, _ = _first_coupon_of(ta, "youth1")
            with ta.client() as c:
                # 用户取动态码
                r1 = c.get(
                    f"/api/coupons/instances/{coupon_id}/live-code",
                    headers=ta.bearer(u_token),
                )
                self.assertEqual(r1.status_code, 200, r1.text)
                live = r1.json()["live_code"]
                self.assertGreater(r1.json()["expires_in"], 0)
                # 商家用动态码核销
                r2 = c.post("/api/coupons/redeem", headers=ta.bearer(m_token), json={"code": live})
                self.assertEqual(r2.status_code, 200, r2.text)
                self.assertEqual(r2.json()["coupon"]["status"], "used")

    def test_live_code_expired_fails(self) -> None:
        """动态码过期后核销应失败。"""
        with TempApp() as ta:
            u_token = ta.login("youth1", "youth123")
            m_token = ta.login("merchant1", "merchant123")
            coupon_id, _ = _first_coupon_of(ta, "youth1")
            with ta.client() as c:
                r1 = c.get(
                    f"/api/coupons/instances/{coupon_id}/live-code",
                    headers=ta.bearer(u_token),
                )
                live = r1.json()["live_code"]
            # 把动态码过期：修改 LIVE_CODE_EXPIRE_SECONDS 让新码立刻过期不可行，
            # 这里直接伪造一个过期 token
            from app.services.live_code import create_live_code

            # 用更短的 expiry 不可改；直接构造一个明显过期的 token
            import jwt

            from app.core.config import get_settings

            s = get_settings()
            exp = datetime.now(timezone.utc) - timedelta(seconds=60)
            payload = {
                "typ": "live_coupon",
                "cid": coupon_id,
                "uid": "",
                "code": "",
                "exp": exp,
            }
            expired_token = jwt.encode(payload, s.secret_key, algorithm=s.algorithm)
            if not isinstance(expired_token, str):
                expired_token = expired_token.decode("utf-8")
            with ta.client() as c:
                r = c.post(
                    "/api/coupons/redeem",
                    headers=ta.bearer(m_token),
                    json={"code": expired_token},
                )
                self.assertEqual(r.status_code, 400, r.text)
                self.assertIn("过期", r.json()["detail"])

    def test_live_code_tampered_fails(self) -> None:
        """篡改动态码 payload 应失败。"""
        with TempApp() as ta:
            m_token = ta.login("merchant1", "merchant123")
            coupon_id, _ = _first_coupon_of(ta, "youth1")
            u_token = ta.login("youth1", "youth123")
            with ta.client() as c:
                r1 = c.get(
                    f"/api/coupons/instances/{coupon_id}/live-code",
                    headers=ta.bearer(u_token),
                )
                live = r1.json()["live_code"]
            # 篡改签名
            parts = live.split(".")
            self.assertEqual(len(parts), 3)
            tampered = parts[0] + "." + parts[1] + ".AAAA"
            with ta.client() as c:
                r = c.post(
                    "/api/coupons/redeem",
                    headers=ta.bearer(m_token),
                    json={"code": tampered},
                )
                self.assertEqual(r.status_code, 400, r.text)

    # ---- 时长兑换 ----
    def test_exchange_coupon_with_points(self) -> None:
        """youth1 用志愿服务时长兑换券。"""
        with TempApp() as ta:
            u_token = ta.login("youth1", "youth123")
            with ta.session() as db:
                from app.models.entities import CouponTemplate

                tmpl = (
                    db.query(CouponTemplate)
                    .filter(CouponTemplate.cost_points > 0, CouponTemplate.is_active.is_(True))
                    .order_by(CouponTemplate.cost_points.asc())
                    .first()
                )
                self.assertIsNotNone(tmpl, "no exchangeable template seeded")
                tmpl_id = tmpl.id
                cost = tmpl.cost_points
            with ta.client() as c:
                # 余额
                r0 = c.get("/api/points/me", headers=ta.bearer(u_token))
                self.assertEqual(r0.status_code, 200, r0.text)
                balance_before = Decimal(r0.json()["balance"])
                self.assertGreaterEqual(balance_before, cost)
                # 兑换
                r1 = c.post(
                    "/api/points/exchange",
                    headers=ta.bearer(u_token),
                    json={"template_id": tmpl_id},
                )
                self.assertEqual(r1.status_code, 200, r1.text)
                self.assertEqual(r1.json()["message"], "兑换成功")
                self.assertEqual(r1.json()["coupon"]["status"], "unused")
                # 余额扣减
                balance_after = Decimal(r1.json()["balance"])
                self.assertEqual(balance_after, balance_before - cost)

    def test_exchange_insufficient_points_fails(self) -> None:
        """把 youth1 余额扣光后兑换应失败。"""
        with TempApp() as ta:
            u_token = ta.login("youth1", "youth123")
            with ta.session() as db:
                from app.models.entities import Account, CouponTemplate, PointAccount

                youth = db.query(Account).filter(Account.username == "youth1").one()
                acc = db.query(PointAccount).filter(PointAccount.user_id == youth.id).one()
                acc.balance = Decimal("1.00")
                tmpl = (
                    db.query(CouponTemplate)
                    .filter(CouponTemplate.cost_points > 0, CouponTemplate.is_active.is_(True))
                    .order_by(CouponTemplate.cost_points.asc())
                    .first()
                )
                tmpl_id = tmpl.id
                db.commit()
            with ta.client() as c:
                r = c.post(
                    "/api/points/exchange",
                    headers=ta.bearer(u_token),
                    json={"template_id": tmpl_id},
                )
                self.assertEqual(r.status_code, 400, r.text)
                self.assertIn("余额不足", r.json()["detail"])


def main() -> int:
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromModule(sys.modules[__name__])
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
