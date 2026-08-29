"""权限越权测试：角色边界、未授权访问、跨店/跨用户访问。

Run from backend/:
  .\\.venv\\Scripts\\python.exe -m pytest tests/test_authz.py -v
"""

from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone

from tests._helpers import TempApp, reset_env_defaults


def _youth1_id(ta: TempApp) -> str:
    with ta.session() as db:
        from app.models.entities import Account

        return db.query(Account).filter(Account.username == "youth1").one().id


def _bind_bank_card(ta: TempApp, user_token: str, card_number: str = "4111111111111111") -> None:
    """通过 API 给当前用户绑卡（需已核验）。"""
    with ta.client() as c:
        r = c.put(
            "/api/users/me/bank-card",
            headers=ta.bearer(user_token),
            json={"card_number": card_number, "bank_name": "测试银行"},
        )
        assert r.status_code == 200, f"bind card failed: {r.status_code} {r.text}"


class TestAuthz(unittest.TestCase):
    def tearDown(self) -> None:
        reset_env_defaults()

    # ---- 未授权 ----
    def test_unauthenticated_cannot_access_protected(self) -> None:
        with TempApp() as ta:
            with ta.client() as c:
                # 用户接口
                r1 = c.get("/api/coupons/my")
                self.assertEqual(r1.status_code, 401, r1.text)
                # 管理接口
                r2 = c.get("/api/coupons/templates")
                self.assertEqual(r2.status_code, 401, r2.text)
                # 商家接口
                r3 = c.get("/api/coupons/instances")
                self.assertEqual(r3.status_code, 401, r3.text)
                # 银行卡明文
                r4 = c.get(f"/api/users/{_youth1_id(ta)}/bank-card")
                self.assertEqual(r4.status_code, 401, r4.text)

    def test_pending_review_includes_complete_masked_profile(self) -> None:
        with TempApp() as ta:
            admin_token = ta.login("admin", "admin123")
            with ta.client() as c:
                response = c.get(
                    "/api/users/pending-verifications",
                    headers=ta.bearer(admin_token),
                )

            self.assertEqual(response.status_code, 200, response.text)
            pending = next(item for item in response.json() if item["username"] == "youth2")
            for field in (
                "display_name",
                "real_name",
                "phone",
                "student_no",
                "organization",
                "remark",
                "verify_status",
                "account_created_at",
                "bank_card_bound",
                "bank_card_masked",
                "bank_card_bank_name",
                "bank_card_bound_at",
                "reviewer_name",
            ):
                self.assertIn(field, pending)
            self.assertEqual(pending["verify_status"], "pending")
            self.assertNotIn("bank_card_encrypted", pending)
            self.assertNotIn("card_number", pending)

    # ---- 用户只能看自己的券 ----
    def test_user_only_sees_own_coupons(self) -> None:
        """youth1 不应看到 youth2 的券（这里 youth2 无券，但接口过滤必须生效）。"""
        with TempApp() as ta:
            # 先给 youth2 发一张券（需要先把 youth2 审核通过）
            admin_token = ta.login("admin", "admin123")
            with ta.session() as db:
                from app.models.entities import Account, UserProfile, VerifyStatus

                youth2 = db.query(Account).filter(Account.username == "youth2").one()
                profile = db.query(UserProfile).filter(UserProfile.account_id == youth2.id).one()
                profile.verify_status = VerifyStatus.approved
                db.commit()
            with ta.session() as db:
                from app.models.entities import Account, CouponTemplate

                tmpl = db.query(CouponTemplate).filter(CouponTemplate.is_active.is_(True)).first()
                youth2 = db.query(Account).filter(Account.username == "youth2").one()
                tmpl_id = tmpl.id
                youth2_id = youth2.id
            with ta.client() as c:
                r = c.post(
                    "/api/coupons/issue",
                    headers=ta.bearer(admin_token),
                    json={"user_id": youth2_id, "template_id": tmpl_id, "quantity": 1},
                )
                self.assertEqual(r.status_code, 200, r.text)
                youth2_coupon_id = r.json()[0]["id"]
                youth2_code = r.json()[0]["code"]

            # youth1 看自己的券列表
            u1_token = ta.login("youth1", "youth123")
            with ta.client() as c:
                r = c.get("/api/coupons/my", headers=ta.bearer(u1_token))
                self.assertEqual(r.status_code, 200, r.text)
                ids = [item["id"] for item in r.json()]
                self.assertNotIn(youth2_coupon_id, ids, "youth1 看到了 youth2 的券")

            # youth1 不能取 youth2 券的动态码
            with ta.client() as c:
                r = c.get(
                    f"/api/coupons/instances/{youth2_coupon_id}/live-code",
                    headers=ta.bearer(u1_token),
                )
                self.assertEqual(r.status_code, 404, r.text)

            # youth1 不能用 instances 列表查到 youth2 的券（按 user_id 过滤）
            with ta.client() as c:
                r = c.get("/api/coupons/instances", headers=ta.bearer(u1_token))
                self.assertEqual(r.status_code, 200, r.text)
                for item in r.json()["items"]:
                    self.assertEqual(item["user_id"], _youth1_id(ta))

    # ---- 商家跨店核销 ----
    def test_merchant_cannot_access_admin_apis(self) -> None:
        """商家不能调发券、模板管理、用户列表等管理接口。"""
        with TempApp() as ta:
            m_token = ta.login("merchant1", "merchant123")
            _, _, youth_id = _find_ids(ta)
            with ta.session() as db:
                from app.models.entities import CouponTemplate

                tmpl = db.query(CouponTemplate).filter(CouponTemplate.is_active.is_(True)).first()
                tmpl_id = tmpl.id
            with ta.client() as c:
                # 发券
                r1 = c.post(
                    "/api/coupons/issue",
                    headers=ta.bearer(m_token),
                    json={"user_id": youth_id, "template_id": tmpl_id, "quantity": 1},
                )
                self.assertEqual(r1.status_code, 403, r1.text)
                # 模板列表
                r2 = c.get("/api/coupons/templates", headers=ta.bearer(m_token))
                self.assertEqual(r2.status_code, 403, r2.text)
                # 用户列表
                r3 = c.get("/api/users", headers=ta.bearer(m_token))
                self.assertEqual(r3.status_code, 403, r3.text)
                # 时长入账
                r4 = c.post(
                    "/api/points/grant",
                    headers=ta.bearer(m_token),
                    json={"user_id": youth_id, "amount": "1.00", "reason": "x"},
                )
                self.assertEqual(r4.status_code, 403, r4.text)

    def test_user_cannot_access_admin_apis(self) -> None:
        """普通用户不能调管理接口。"""
        with TempApp() as ta:
            u_token = ta.login("youth1", "youth123")
            with ta.client() as c:
                r1 = c.get("/api/coupons/templates", headers=ta.bearer(u_token))
                self.assertEqual(r1.status_code, 403, r1.text)
                r2 = c.get("/api/users", headers=ta.bearer(u_token))
                self.assertEqual(r2.status_code, 403, r2.text)
                r3 = c.get("/api/coupons/redemptions", headers=ta.bearer(u_token))
                self.assertEqual(r3.status_code, 403, r3.text)
                # 核销（商家接口）
                r4 = c.post("/api/coupons/redeem", headers=ta.bearer(u_token), json={"code": "ANYCODE1234"})
                self.assertEqual(r4.status_code, 403, r4.text)

    # ---- 商家只能看本店核销流水 ----
    def test_merchant_only_sees_own_redemptions(self) -> None:
        with TempApp() as ta:
            m1_token = ta.login("merchant1", "merchant123")
            m2_token = ta.login("merchant2", "merchant123")
            admin_token = ta.login("admin", "admin123")
            # 给 youth1 发一张餐饮店券并让 merchant1 核销
            _, tmpl_id, youth_id = _find_ids(ta)
            with ta.client() as c:
                r = c.post(
                    "/api/coupons/issue",
                    headers=ta.bearer(admin_token),
                    json={"user_id": youth_id, "template_id": tmpl_id, "quantity": 1},
                )
                code1 = r.json()[0]["code"]
                m1_merchant_id = r.json()[0]["merchant_id"]
            # 找到书店模板，给 youth1 发一张书店券
            with ta.session() as db:
                from app.models.entities import CouponTemplate, Merchant

                bookstore = db.query(Merchant).filter(Merchant.name == "示例书店").one()
                tmpl2 = (
                    db.query(CouponTemplate)
                    .filter(CouponTemplate.merchant_id == bookstore.id)
                    .first()
                )
                tmpl2_id = tmpl2.id
                m2_merchant_id = bookstore.id
            with ta.client() as c:
                r = c.post(
                    "/api/coupons/issue",
                    headers=ta.bearer(admin_token),
                    json={"user_id": youth_id, "template_id": tmpl2_id, "quantity": 1},
                )
                code2 = r.json()[0]["code"]
            # 分别核销
            with ta.client() as c:
                c.post("/api/coupons/redeem", headers=ta.bearer(m1_token), json={"code": code1})
                c.post("/api/coupons/redeem", headers=ta.bearer(m2_token), json={"code": code2})
            # merchant1 看流水，应只有自己店的
            with ta.client() as c:
                r = c.get("/api/coupons/redemptions", headers=ta.bearer(m1_token))
                self.assertEqual(r.status_code, 200, r.text)
                for item in r.json()["items"]:
                    self.assertEqual(item["merchant_id"], m1_merchant_id, "merchant1 看到了它店流水")
            # merchant2 看流水
            with ta.client() as c:
                r = c.get("/api/coupons/redemptions", headers=ta.bearer(m2_token))
                self.assertEqual(r.status_code, 200, r.text)
                for item in r.json()["items"]:
                    self.assertEqual(item["merchant_id"], m2_merchant_id, "merchant2 看到了它店流水")

    # ---- 银行卡明文仅超管可解密 ----
    def test_user_cannot_reveal_bank_card(self) -> None:
        with TempApp() as ta:
            u_token = ta.login("youth1", "youth123")
            _bind_bank_card(ta, u_token)
            youth_id = _youth1_id(ta)
            with ta.client() as c:
                # 用户自己访问明文接口
                r = c.get(f"/api/users/{youth_id}/bank-card", headers=ta.bearer(u_token))
                self.assertEqual(r.status_code, 403, r.text)

    def test_merchant_cannot_reveal_bank_card(self) -> None:
        with TempApp() as ta:
            u_token = ta.login("youth1", "youth123")
            _bind_bank_card(ta, u_token)
            m_token = ta.login("merchant1", "merchant123")
            youth_id = _youth1_id(ta)
            with ta.client() as c:
                r = c.get(f"/api/users/{youth_id}/bank-card", headers=ta.bearer(m_token))
                self.assertEqual(r.status_code, 403, r.text)

    def test_super_admin_can_reveal_bank_card(self) -> None:
        with TempApp() as ta:
            u_token = ta.login("youth1", "youth123")
            _bind_bank_card(ta, u_token, "4111111111111111")
            admin_token = ta.login("admin", "admin123")
            youth_id = _youth1_id(ta)
            with ta.client() as c:
                r = c.get(f"/api/users/{youth_id}/bank-card", headers=ta.bearer(admin_token))
                self.assertEqual(r.status_code, 200, r.text)
                self.assertEqual(r.json()["card_number"], "4111111111111111")
                # 接口默认列表/资料不返回明文
                r2 = c.get(f"/api/users/{youth_id}", headers=ta.bearer(admin_token))
                self.assertEqual(r2.status_code, 200, r2.text)
                self.assertNotIn("4111111111111111", r2.text)

    def test_issue_admin_cannot_reveal_bank_card(self) -> None:
        """发券管理员只能看脱敏，不能解密明文。"""
        with TempApp() as ta:
            u_token = ta.login("youth1", "youth123")
            _bind_bank_card(ta, u_token, "4111111111111111")
            issuer_token = ta.login("issuer", "issuer123")
            youth_id = _youth1_id(ta)
            with ta.client() as c:
                r = c.get(f"/api/users/{youth_id}/bank-card", headers=ta.bearer(issuer_token))
                self.assertEqual(r.status_code, 403, r.text)

    # ---- 停用账号无法登录 ----
    def test_inactive_account_cannot_login(self) -> None:
        with TempApp() as ta:
            admin_token = ta.login("admin", "admin123")
            youth_id = _youth1_id(ta)
            with ta.client() as c:
                r = c.post(
                    f"/api/auth/accounts/{youth_id}/set-active",
                    headers=ta.bearer(admin_token),
                    json={"is_active": False},
                )
                self.assertEqual(r.status_code, 200, r.text)
            # 再登录应失败
            with ta.client() as c:
                r = c.post("/api/auth/login", json={"username": "youth1", "password": "youth123"})
                self.assertEqual(r.status_code, 400, r.text)
                self.assertIn("停用", r.json()["detail"])

    # ---- 伪造/过期 token ----
    def test_invalid_token_rejected(self) -> None:
        with TempApp() as ta:
            with ta.client() as c:
                r = c.get("/api/coupons/my", headers={"Authorization": "Bearer not.a.real.token"})
                self.assertEqual(r.status_code, 401, r.text)
                r2 = c.get("/api/coupons/my", headers={"Authorization": "Bearer "})
                self.assertEqual(r2.status_code, 401, r2.text)

    def test_token_signed_with_wrong_secret_rejected(self) -> None:
        with TempApp() as ta:
            import jwt

            from app.core.config import get_settings

            s = get_settings()
            payload = {
                "sub": _youth1_id(ta),
                "role": "user",
                "exp": datetime.now(timezone.utc) + timedelta(hours=1),
            }
            bad_token = jwt.encode(payload, "completely-wrong-secret-key", algorithm=s.algorithm)
            if not isinstance(bad_token, str):
                bad_token = bad_token.decode("utf-8")
            with ta.client() as c:
                r = c.get("/api/coupons/my", headers={"Authorization": f"Bearer {bad_token}"})
                self.assertEqual(r.status_code, 401, r.text)


def _find_ids(ta: TempApp) -> tuple[str, str, str]:
    with ta.session() as db:
        from app.models.entities import Account, CouponTemplate

        admin = db.query(Account).filter(Account.username == "admin").one()
        tmpl = db.query(CouponTemplate).filter(CouponTemplate.is_active.is_(True)).first()
        youth = db.query(Account).filter(Account.username == "youth1").one()
        return admin.id, tmpl.id, youth.id


def main() -> int:
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromModule(sys.modules[__name__])
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
