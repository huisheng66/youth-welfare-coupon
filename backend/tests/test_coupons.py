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


def _live_code_of(ta: TempApp, coupon_id: str, username: str = "youth1") -> str:
    """用户登录后为目标券签发动态码（T01：核销一律走动态码）。"""
    with ta.client() as c:
        r = c.post("/api/auth/login", json={"username": username, "password": "youth123"})
        assert r.status_code == 200, r.text
        token = r.json()["access_token"]
        r2 = c.get(
            f"/api/coupons/instances/{coupon_id}/live-code",
            headers=ta.bearer(token),
        )
        assert r2.status_code == 200, r2.text
        return r2.json()["live_code"]


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
            coupon_id, _ = _first_coupon_of(ta, "youth1")
            with ta.client() as c:
                # 先核销（动态码）
                r1 = c.post(
                    "/api/coupons/redeem",
                    headers=ta.bearer(m_token),
                    json={"code": _live_code_of(ta, coupon_id)},
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
    def test_redeem_with_permanent_code_rejected(self) -> None:
        """T01：永久编号只是查询编号，泄露它不能核销；失败也留痕。"""
        with TempApp() as ta:
            m_token = ta.login("merchant1", "merchant123")
            coupon_id, code = _first_coupon_of(ta, "youth1")
            with ta.client() as c:
                r = c.post("/api/coupons/redeem", headers=ta.bearer(m_token), json={"code": code})
                self.assertEqual(r.status_code, 400, r.text)
                self.assertIn("动态券码", r.json()["detail"])
            # 失败核销已写入流水（永久码拒绝发生在定位券之前，按展示码检索）
            with ta.session() as db:
                from app.models.entities import RedemptionLog

                log = (
                    db.query(RedemptionLog)
                    .filter(RedemptionLog.code == code, RedemptionLog.result == "failed")
                    .order_by(RedemptionLog.created_at.desc())
                    .first()
                )
                self.assertIsNotNone(log)
                self.assertEqual(log.reason, "invalid_live_code")
                self.assertIsNone(log.coupon_id)

    def test_redeem_with_permanent_code_via_preview_rejected(self) -> None:
        """预览同样只接受动态码，且永久码不因预览泄露可核销性。"""
        with TempApp() as ta:
            m_token = ta.login("merchant1", "merchant123")
            _, code = _first_coupon_of(ta, "youth1")
            with ta.client() as c:
                r = c.post("/api/coupons/preview", headers=ta.bearer(m_token), json={"code": code})
                self.assertEqual(r.status_code, 400, r.text)

    def test_redeem_already_redeemed_fails(self) -> None:
        """重复核销应失败（并发安全由条件更新保证）。"""
        with TempApp() as ta:
            m_token = ta.login("merchant1", "merchant123")
            coupon_id, _ = _first_coupon_of(ta, "youth1")
            with ta.client() as c:
                live = _live_code_of(ta, coupon_id)
                r1 = c.post("/api/coupons/redeem", headers=ta.bearer(m_token), json={"code": live})
                self.assertEqual(r1.status_code, 200, r1.text)
                # 已核销后重放同一动态码也应失败
                r2 = c.post("/api/coupons/redeem", headers=ta.bearer(m_token), json={"code": live})
                self.assertEqual(r2.status_code, 400, r2.text)
                self.assertIn("已核销", r2.json()["detail"])

    def test_redeem_expired_coupon_fails(self) -> None:
        """先出码再过期：临界过期在核销确认时拒绝。"""
        with TempApp() as ta:
            m_token = ta.login("merchant1", "merchant123")
            coupon_id, _ = _first_coupon_of(ta, "youth1")
            live = _live_code_of(ta, coupon_id)
            # 出码后把券置为过期
            with ta.session() as db:
                from app.models.entities import CouponInstance

                c = db.get(CouponInstance, coupon_id)
                c.expires_at = datetime.now(timezone.utc) - timedelta(days=1)
                db.commit()
            with ta.client() as c:
                r = c.post("/api/coupons/redeem", headers=ta.bearer(m_token), json={"code": live})
                self.assertEqual(r.status_code, 400, r.text)
                self.assertIn("过期", r.json()["detail"])
            with ta.session() as db:
                from app.models.entities import RedemptionLog

                log = (
                    db.query(RedemptionLog)
                    .filter(RedemptionLog.coupon_id == coupon_id, RedemptionLog.result == "failed")
                    .order_by(RedemptionLog.created_at.desc())
                    .first()
                )
                self.assertIsNotNone(log)
                self.assertEqual(log.reason, "expired")

    def test_redeem_wrong_merchant_fails_and_masks_user(self) -> None:
        """merchant2 不能核销 merchant1 店的券；失败记录不泄露他店用户身份。"""
        with TempApp() as ta:
            m2_token = ta.login("merchant2", "merchant123")
            coupon_id, _ = _first_coupon_of(ta, "youth1")  # 餐饮店券，属 merchant1
            user_id = None
            with ta.session() as db:
                from app.models.entities import CouponInstance

                user_id = db.get(CouponInstance, coupon_id).user_id
            live = _live_code_of(ta, coupon_id)
            with ta.client() as c:
                r = c.post("/api/coupons/redeem", headers=ta.bearer(m2_token), json={"code": live})
                self.assertEqual(r.status_code, 400, r.text)
                self.assertIn("非本店", r.json()["detail"])
            with ta.session() as db:
                from app.models.entities import RedemptionLog

                log = (
                    db.query(RedemptionLog)
                    .filter(RedemptionLog.coupon_id == coupon_id, RedemptionLog.result == "failed")
                    .order_by(RedemptionLog.created_at.desc())
                    .first()
                )
                self.assertIsNotNone(log)
                self.assertEqual(log.reason, "wrong_merchant")
                self.assertNotEqual(log.user_id, user_id, "跨店失败不得记录他店用户标识")
                self.assertIsNone(log.user_id)

    def test_redeem_non_live_code_rejected(self) -> None:
        """非动态码输入（含未知永久码）一律拒绝且不留券关联。"""
        with TempApp() as ta:
            m_token = ta.login("merchant1", "merchant123")
            with ta.client() as c:
                r = c.post(
                    "/api/coupons/redeem",
                    headers=ta.bearer(m_token),
                    json={"code": "NOTEXIST1234"},
                )
                self.assertEqual(r.status_code, 400, r.text)
                self.assertIn("动态券码", r.json()["detail"])

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
                self.assertEqual(r1.status_code, 200, r1.text)
            # 构造签名有效但明显过期的动态码（载荷只含必要 claim，无永久码字段）
            import jwt

            from app.core.config import get_settings

            with ta.session() as db:
                from app.models.entities import Account

                uid = db.query(Account).filter(Account.username == "youth1").one().id

            s = get_settings()
            exp = datetime.now(timezone.utc) - timedelta(seconds=60)
            payload = {"typ": "live_coupon", "cid": coupon_id, "uid": uid, "exp": exp}
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

    def test_coupon_list_searches_and_paginates_in_database(self) -> None:
        with TempApp() as ta:
            admin_token = ta.login("issuer", "issuer123")
            coupon_id, _ = _first_coupon_of(ta, "youth1")
            with ta.session() as db:
                from app.models.entities import CouponInstance

                coupon = db.get(CouponInstance, coupon_id)
                assert coupon is not None
                coupon.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
                db.commit()

            with ta.client() as c:
                response = c.get(
                    "/api/coupons/instances",
                    headers=ta.bearer(admin_token),
                    params={"status": "expired", "q": "youth1", "limit": 1},
                )
                self.assertEqual(response.status_code, 200, response.text)
                data = response.json()
                self.assertGreaterEqual(data["total"], 1)
                self.assertEqual(len(data["items"]), 1)
                self.assertEqual(data["items"][0]["username"], "youth1")
                self.assertEqual(data["items"][0]["status"], "expired")

                for wildcard in ("%", "_"):
                    literal = c.get(
                        "/api/coupons/instances",
                        headers=ta.bearer(admin_token),
                        params={"q": wildcard},
                    )
                    self.assertEqual(literal.status_code, 200, literal.text)
                    self.assertEqual(literal.json()["total"], 0)

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
