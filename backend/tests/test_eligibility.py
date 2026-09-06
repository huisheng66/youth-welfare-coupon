"""T12 业务资格规则统一测试：账号/核验/门店/模板四类资格的行为矩阵。

验证发券（单条/批量/名单）、时长调整、兑换复用同一资格判定；
兑换目录提前过滤停用门店；券实例保留发放时模板快照。

Run from backend/:
  .venv/bin/python -m pytest tests/test_eligibility.py -v
"""

from __future__ import annotations

import unittest

from app.models.entities import (
    Account,
    CouponInstance,
    CouponStatus,
    CouponTemplate,
    Merchant,
    UserProfile,
    VerifyStatus,
)
from tests._helpers import TempApp, reset_env_defaults


def _account_id(ta: TempApp, username: str) -> str:
    with ta.session() as db:
        return db.query(Account).filter(Account.username == username).one().id


def _template_by_name(ta: TempApp, name: str) -> CouponTemplate:
    with ta.session() as db:
        t = db.query(CouponTemplate).filter(CouponTemplate.name == name).one()
        db.expunge(t)
        return t


def _set_merchant_active(ta: TempApp, merchant_name: str, active: bool) -> None:
    with ta.session() as db:
        m = db.query(Merchant).filter(Merchant.name == merchant_name).one()
        m.is_active = active
        db.commit()


def _first_unused_coupon_id(ta: TempApp, username: str) -> str:
    with ta.session() as db:
        user = db.query(Account).filter(Account.username == username).one()
        c = (
            db.query(CouponInstance)
            .filter(
                CouponInstance.user_id == user.id,
                CouponInstance.status == CouponStatus.unused,
            )
            .first()
        )
        assert c is not None, f"{username} 应有种子里未使用的券"
        return c.id


class TestEligibility(unittest.TestCase):
    def tearDown(self) -> None:
        reset_env_defaults()

    # ---- 账号停用：发券与入账统一拒绝 ----
    def test_deactivated_user_rejected_by_issue_and_grant(self) -> None:
        with TempApp() as ta:
            yid = _account_id(ta, "youth1")
            tmpl = _template_by_name(ta, "餐饮立减券")
            with ta.session() as db:
                db.query(Account).filter(Account.id == yid).update({"is_active": False})
                db.commit()
            admin = ta.login("admin", "admin123")
            with ta.client() as c:
                r = c.post(
                    "/api/coupons/issue",
                    headers=ta.bearer(admin),
                    json={"user_id": yid, "template_id": tmpl.id, "quantity": 1},
                )
                self.assertEqual(r.status_code, 400, r.text)
                self.assertIn("停用", r.json()["detail"])

                r = c.post(
                    "/api/points/grant",
                    headers=ta.bearer(admin),
                    json={"user_id": yid, "amount": "1", "reason": "停用账号入账"},
                )
                self.assertEqual(r.status_code, 400, r.text)
                self.assertIn("停用", r.json()["detail"])

                # 批量入口同一判定：行级失败原因一致
                r = c.post(
                    "/api/coupons/issue-batch",
                    headers=ta.bearer(admin),
                    json={"user_ids": [yid], "template_id": tmpl.id, "quantity": 1},
                )
                self.assertEqual(r.status_code, 200, r.text)
                body = r.json()
                self.assertEqual(body["issued"], [])
                self.assertIn("停用", body["failed"][0]["reason"])

    # ---- 复核中：暂停新增权益，已有券保留 ----
    def test_pending_review_blocks_new_benefits_but_keeps_existing_coupons(self) -> None:
        with TempApp() as ta:
            yid = _account_id(ta, "youth1")
            coupon_id = _first_unused_coupon_id(ta, "youth1")
            tmpl = _template_by_name(ta, "餐饮立减券")
            # 模拟身份资料变更后进入复核（approved → pending）
            with ta.session() as db:
                db.query(UserProfile).filter(UserProfile.account_id == yid).update(
                    {"verify_status": VerifyStatus.pending}
                )
                db.commit()
            admin = ta.login("admin", "admin123")
            user = ta.login("youth1", "youth123")
            with ta.client() as c:
                r = c.post(
                    "/api/coupons/issue",
                    headers=ta.bearer(admin),
                    json={"user_id": yid, "template_id": tmpl.id, "quantity": 1},
                )
                self.assertEqual(r.status_code, 400, r.text)
                self.assertIn("核验", r.json()["detail"])

                r = c.post(
                    "/api/points/grant",
                    headers=ta.bearer(admin),
                    json={"user_id": yid, "amount": "1", "reason": "复核期入账"},
                )
                self.assertEqual(r.status_code, 400, r.text)
                self.assertIn("核验", r.json()["detail"])

                r = c.post(
                    "/api/points/exchange",
                    headers=ta.bearer(user),
                    json={"template_id": tmpl.id},
                )
                self.assertEqual(r.status_code, 400, r.text)
                self.assertIn("核验", r.json()["detail"])

                # 已有券不随复核冻结：仍可出示动态码
                r = c.get(
                    f"/api/coupons/instances/{coupon_id}/live-code",
                    headers=ta.bearer(user),
                )
                self.assertEqual(r.status_code, 200, r.text)

    # ---- 兑换目录：提前过滤停用门店 ----
    def test_catalog_excludes_templates_of_inactive_merchants(self) -> None:
        with TempApp() as ta:
            user = ta.login("youth1", "youth123")
            with ta.client() as c:
                r = c.get("/api/points/catalog", headers=ta.bearer(user))
                self.assertEqual(r.status_code, 200, r.text)
                names = [i["name"] for i in r.json()]
                self.assertIn("图书优惠券", names)

            _set_merchant_active(ta, "示例书店", False)
            with ta.client() as c:
                r = c.get("/api/points/catalog", headers=ta.bearer(user))
                self.assertEqual(r.status_code, 200, r.text)
                names = [i["name"] for i in r.json()]
                self.assertNotIn("图书优惠券", names)
                self.assertIn("餐饮立减券", names)

    # ---- 停用门店：兑换与发券统一拒绝，余额不变 ----
    def test_exchange_and_issue_rejected_for_inactive_merchant(self) -> None:
        with TempApp() as ta:
            yid = _account_id(ta, "youth1")
            tmpl = _template_by_name(ta, "图书优惠券")
            _set_merchant_active(ta, "示例书店", False)
            admin = ta.login("admin", "admin123")
            user = ta.login("youth1", "youth123")
            with ta.client() as c:
                r = c.post(
                    "/api/points/exchange",
                    headers=ta.bearer(user),
                    json={"template_id": tmpl.id},
                )
                self.assertEqual(r.status_code, 400, r.text)
                self.assertIn("商家不可用", r.json()["detail"])
                r = c.get("/api/points/me", headers=ta.bearer(user))
                self.assertEqual(float(r.json()["balance"]), 10.0)

                r = c.post(
                    "/api/coupons/issue",
                    headers=ta.bearer(admin),
                    json={"user_id": yid, "template_id": tmpl.id, "quantity": 1},
                )
                self.assertEqual(r.status_code, 400, r.text)
                self.assertIn("商家不可用", r.json()["detail"])

    # ---- 模板停用：只停止新增，已发券照常核销 ----
    def test_inactive_template_stops_new_issue_but_existing_coupon_redeems(self) -> None:
        with TempApp() as ta:
            coupon_id = _first_unused_coupon_id(ta, "youth1")
            tmpl = _template_by_name(ta, "餐饮立减券")
            yid = _account_id(ta, "youth1")
            with ta.session() as db:
                db.query(CouponTemplate).filter(CouponTemplate.id == tmpl.id).update(
                    {"is_active": False}
                )
                db.commit()
            admin = ta.login("admin", "admin123")
            user = ta.login("youth1", "youth123")
            merchant = ta.login("merchant1", "merchant123")
            with ta.client() as c:
                r = c.post(
                    "/api/coupons/issue",
                    headers=ta.bearer(admin),
                    json={"user_id": yid, "template_id": tmpl.id, "quantity": 1},
                )
                self.assertEqual(r.status_code, 400, r.text)
                self.assertIn("券模板不可用", r.json()["detail"])

                # 已发券生命周期不受模板停用影响：出码 → 预览 → 核销
                r = c.get(
                    f"/api/coupons/instances/{coupon_id}/live-code",
                    headers=ta.bearer(user),
                )
                self.assertEqual(r.status_code, 200, r.text)
                live = r.json()["live_code"]
                r = c.post(
                    "/api/coupons/preview",
                    headers=ta.bearer(merchant),
                    json={"code": live},
                )
                self.assertEqual(r.status_code, 200, r.text)
                r = c.post(
                    "/api/coupons/redeem",
                    headers=ta.bearer(merchant),
                    json={"code": live},
                )
                self.assertEqual(r.status_code, 200, r.text)

    # ---- 发放快照：模板改名不影响已发券券面 ----
    def test_issued_coupon_keeps_template_snapshot_after_rename(self) -> None:
        with TempApp() as ta:
            yid = _account_id(ta, "youth1")
            tmpl = _template_by_name(ta, "餐饮立减券")
            admin = ta.login("admin", "admin123")
            user = ta.login("youth1", "youth123")
            with ta.client() as c:
                r = c.post(
                    "/api/coupons/issue",
                    headers=ta.bearer(admin),
                    json={"user_id": yid, "template_id": tmpl.id, "quantity": 1},
                )
                self.assertEqual(r.status_code, 200, r.text)
                new_coupon_id = r.json()[0]["id"]

                r = c.put(
                    f"/api/coupons/templates/{tmpl.id}",
                    headers=ta.bearer(admin),
                    json={"name": "餐饮立减券·新版"},
                )
                self.assertEqual(r.status_code, 200, r.text)

                r = c.get("/api/coupons/my", headers=ta.bearer(user))
                self.assertEqual(r.status_code, 200, r.text)
                by_id = {i["id"]: i for i in r.json()["items"]}
                # 新发的券保留发放时名称
                self.assertEqual(by_id[new_coupon_id]["template_name"], "餐饮立减券")
                # 历史无快照的券回退到模板当前名称
                with ta.session() as db:
                    db.query(CouponInstance).filter(
                        CouponInstance.user_id == yid,
                        CouponInstance.id != new_coupon_id,
                    ).update({"template_name": None, "template_description": None})
                    db.commit()
                r = c.get("/api/coupons/my", headers=ta.bearer(user))
                others = [i for i in r.json()["items"] if i["id"] != new_coupon_id]
                self.assertTrue(others)
                for item in others:
                    self.assertEqual(item["template_name"], "餐饮立减券·新版")

    # ---- 兑换的券同样写入快照 ----
    def test_exchanged_coupon_has_template_snapshot(self) -> None:
        with TempApp() as ta:
            user = ta.login("youth1", "youth123")
            tmpl = _template_by_name(ta, "图书优惠券")
            with ta.client() as c:
                r = c.post(
                    "/api/points/exchange",
                    headers=ta.bearer(user),
                    json={"template_id": tmpl.id},
                )
                self.assertEqual(r.status_code, 200, r.text)
                self.assertEqual(r.json()["coupon"]["template_name"], "图书优惠券")
            with ta.session() as db:
                c2 = db.query(CouponInstance).filter(
                    CouponInstance.template_id == tmpl.id
                ).one()
                self.assertEqual(c2.template_name, "图书优惠券")
                self.assertEqual(c2.template_description, tmpl.description)

    # ---- 未核验用户：各入口判定一致 ----
    def test_unverified_user_rejected_consistently_across_entries(self) -> None:
        with TempApp() as ta:
            y2 = _account_id(ta, "youth2")
            tmpl = _template_by_name(ta, "餐饮立减券")
            admin = ta.login("admin", "admin123")
            user2 = ta.login("youth2", "youth123")
            with ta.client() as c:
                checks = []
                r = c.post(
                    "/api/coupons/issue",
                    headers=ta.bearer(admin),
                    json={"user_id": y2, "template_id": tmpl.id, "quantity": 1},
                )
                checks.append(r.json()["detail"])
                r = c.post(
                    "/api/points/grant",
                    headers=ta.bearer(admin),
                    json={"user_id": y2, "amount": "1", "reason": "一致性检查"},
                )
                checks.append(r.json()["detail"])
                r = c.post(
                    "/api/points/exchange",
                    headers=ta.bearer(user2),
                    json={"template_id": tmpl.id},
                )
                checks.append(r.json()["detail"])
                # 三个入口都因核验资格拒绝（措辞按入口契约稳定，但判定来源一致）
                for detail in checks:
                    self.assertIn("核验", detail)

                r = c.post(
                    "/api/coupons/issue-batch",
                    headers=ta.bearer(admin),
                    json={"user_ids": [y2], "template_id": tmpl.id, "quantity": 1},
                )
                self.assertEqual(r.status_code, 200, r.text)
                self.assertIn("核验", r.json()["failed"][0]["reason"])

    # ---- 服务层：资格异常是 ValueError 子类，供批量入口行级捕获 ----
    def test_eligibility_error_is_value_error(self) -> None:
        from app.services.eligibility import EligibilityError

        self.assertTrue(issubclass(EligibilityError, ValueError))


if __name__ == "__main__":
    unittest.main()
