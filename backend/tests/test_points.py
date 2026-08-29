"""志愿服务时长账户测试：发分 / 兑换 / 余额不足 / 未核验 / 目录。

Run from backend/:
  .\\.venv\\Scripts\\python.exe -m pytest tests/test_points.py -v
  # 或无 pytest：
  .\\.venv\\Scripts\\python.exe tests/test_points.py
"""

from __future__ import annotations

import unittest
from decimal import Decimal

from tests._helpers import TempApp, reset_env_defaults


def _youth1_id(ta: TempApp) -> str:
    with ta.session() as db:
        from app.models.entities import Account

        return db.query(Account).filter(Account.username == "youth1").one().id


def _youth2_id(ta: TempApp) -> str:
    with ta.session() as db:
        from app.models.entities import Account

        return db.query(Account).filter(Account.username == "youth2").one().id


def _exchangeable_template_id(ta: TempApp) -> str:
    """返回一个可兑换模板 id（cost_points>0 且 active）。"""
    with ta.session() as db:
        from app.models.entities import CouponTemplate

        t = (
            db.query(CouponTemplate)
            .filter(CouponTemplate.is_active.is_(True), CouponTemplate.cost_points > 0)
            .order_by(CouponTemplate.cost_points.asc())
            .first()
        )
        assert t is not None, "no exchangeable template seeded"
        return t.id


class TestPoints(unittest.TestCase):
    def tearDown(self) -> None:
        reset_env_defaults()

    # ---- 查看时长 ----
    def test_user_can_view_own_points(self) -> None:
        """youth1 种子余额 10。"""
        with TempApp() as ta:
            token = ta.login("youth1", "youth123")
            with ta.client() as c:
                r = c.get("/api/points/me", headers=ta.bearer(token))
                self.assertEqual(r.status_code, 200, r.text)
                self.assertEqual(Decimal(r.json()["balance"]), Decimal("10.00"))

    def test_user_cannot_view_others_points(self) -> None:
        """普通用户不能访问 /points/users/{id}（仅管理员）。"""
        with TempApp() as ta:
            token = ta.login("youth1", "youth123")
            with ta.client() as c:
                r = c.get(f"/api/points/users/{_youth2_id(ta)}", headers=ta.bearer(token))
                self.assertEqual(r.status_code, 403, r.text)

    # ---- 发分 ----
    def test_admin_can_grant_points(self) -> None:
        with TempApp() as ta:
            admin_token = ta.login("admin", "admin123")
            yid = _youth1_id(ta)
            with ta.client() as c:
                r = c.post(
                    "/api/points/grant",
                    headers=ta.bearer(admin_token),
                    json={"user_id": yid, "amount": "5.5", "reason": "测试发分"},
                )
                self.assertEqual(r.status_code, 200, r.text)
                self.assertEqual(Decimal(r.json()["balance"]), Decimal("15.50"))

    def test_grant_to_unverified_user_fails(self) -> None:
        """youth2 待审核，调整时长应失败。"""
        with TempApp() as ta:
            admin_token = ta.login("admin", "admin123")
            y2 = _youth2_id(ta)
            with ta.client() as c:
                r = c.post(
                    "/api/points/grant",
                    headers=ta.bearer(admin_token),
                    json={"user_id": y2, "amount": "3", "reason": "尝试给待审用户"},
                )
                self.assertEqual(r.status_code, 400, r.text)
                self.assertIn("核验", r.json()["detail"])

    def test_grant_negative_beyond_balance_fails(self) -> None:
        """扣减超过余额应失败（youth1 余额 10，扣 100）。"""
        with TempApp() as ta:
            admin_token = ta.login("admin", "admin123")
            yid = _youth1_id(ta)
            with ta.client() as c:
                r = c.post(
                    "/api/points/grant",
                    headers=ta.bearer(admin_token),
                    json={"user_id": yid, "amount": "-100", "reason": "超额扣减"},
                )
                self.assertEqual(r.status_code, 400, r.text)
                self.assertIn("余额不足", r.json()["detail"])

    def test_grant_zero_is_rejected(self) -> None:
        with TempApp() as ta:
            admin_token = ta.login("admin", "admin123")
            with ta.client() as c:
                response = c.post(
                    "/api/points/grant",
                    headers=ta.bearer(admin_token),
                    json={"user_id": _youth1_id(ta), "amount": "0", "reason": "无效调整"},
                )
                self.assertEqual(response.status_code, 422, response.text)

    # ---- 兑换 ----
    def test_exchange_coupon_success(self) -> None:
        """youth1 用 2 时长兑换餐饮券，余额 10→8。"""
        with TempApp() as ta:
            token = ta.login("youth1", "youth123")
            tmpl_id = _exchangeable_template_id(ta)
            with ta.client() as c:
                r = c.post(
                    "/api/points/exchange",
                    headers=ta.bearer(token),
                    json={"template_id": tmpl_id},
                )
                self.assertEqual(r.status_code, 200, r.text)
                data = r.json()
                self.assertEqual(data["message"], "兑换成功")
                self.assertEqual(Decimal(data["balance"]), Decimal("8.00"))
                self.assertEqual(data["coupon"]["status"], "unused")
                self.assertTrue(data["coupon"]["code"])

    def test_exchange_insufficient_balance_fails(self) -> None:
        """youth2 余额 0，兑换应失败。需先把 youth2 审核通过（兑换前置条件）。"""
        with TempApp() as ta:
            # 先让 youth2 通过核验
            with ta.session() as db:
                from app.models.entities import Account, UserProfile, VerifyStatus

                y2 = db.query(Account).filter(Account.username == "youth2").one()
                db.query(UserProfile).filter(UserProfile.account_id == y2.id).update(
                    {"verify_status": VerifyStatus.approved}
                )
                db.commit()
            token = ta.login("youth2", "youth123")
            tmpl_id = _exchangeable_template_id(ta)
            with ta.client() as c:
                r = c.post(
                    "/api/points/exchange",
                    headers=ta.bearer(token),
                    json={"template_id": tmpl_id},
                )
                self.assertEqual(r.status_code, 400, r.text)
                self.assertIn("余额不足", r.json()["detail"])

    def test_exchange_unverified_user_fails(self) -> None:
        """youth2 待审核，兑换应失败（即使有余额也不会到余额校验步）。"""
        with TempApp() as ta:
            token = ta.login("youth2", "youth123")
            tmpl_id = _exchangeable_template_id(ta)
            with ta.client() as c:
                r = c.post(
                    "/api/points/exchange",
                    headers=ta.bearer(token),
                    json={"template_id": tmpl_id},
                )
                self.assertEqual(r.status_code, 400, r.text)
                self.assertIn("核验", r.json()["detail"])

    # ---- 目录 ----
    def test_catalog_lists_active_exchangeable_templates(self) -> None:
        with TempApp() as ta:
            token = ta.login("youth1", "youth123")
            with ta.client() as c:
                r = c.get("/api/points/catalog", headers=ta.bearer(token))
                self.assertEqual(r.status_code, 200, r.text)
                items = r.json()
                self.assertTrue(items, "catalog should not be empty")
                for it in items:
                    self.assertGreater(float(it["cost_points"]), 0)
                    self.assertTrue(it["is_active"])

    # ---- 流水 ----
    def test_my_ledger_records_grant_and_exchange(self) -> None:
        """发分 + 兑换后，流水应包含对应记录。"""
        with TempApp() as ta:
            admin_token = ta.login("admin", "admin123")
            user_token = ta.login("youth1", "youth123")
            yid = _youth1_id(ta)
            tmpl_id = _exchangeable_template_id(ta)
            with ta.client() as c:
                c.post(
                    "/api/points/grant",
                    headers=ta.bearer(admin_token),
                    json={"user_id": yid, "amount": "5", "reason": "流水测试发分"},
                )
                c.post(
                    "/api/points/exchange",
                    headers=ta.bearer(user_token),
                    json={"template_id": tmpl_id},
                )
                r = c.get("/api/points/me/ledger", headers=ta.bearer(user_token))
                self.assertEqual(r.status_code, 200, r.text)
                reasons = [row["reason"] for row in r.json()["items"]]
                self.assertTrue(any("流水测试发分" in x for x in reasons))
                self.assertTrue(any("兑换优惠券" in x for x in reasons))


if __name__ == "__main__":
    unittest.main()
