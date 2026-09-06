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
                ids = [item["id"] for item in r.json()["items"]]
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

    def test_must_change_password_is_enforced_by_backend(self) -> None:
        """初始密码账号不能绕过前端直接调用业务接口。"""
        with TempApp() as ta:
            admin_token = ta.login("admin", "admin123")
            with ta.session() as db:
                from app.models.entities import Merchant

                merchant_id = db.query(Merchant).filter(Merchant.name == "示例餐饮店").one().id
            with ta.client() as c:
                created = c.post(
                    "/api/auth/merchant-accounts",
                    headers=ta.bearer(admin_token),
                    json={
                        "username": "mustchange1",
                        "password": "Start1234",
                        "display_name": "测试商家",
                        "merchant_id": merchant_id,
                    },
                )
                self.assertEqual(created.status_code, 200, created.text)
                self.assertTrue(created.json()["must_change_password"])

            token = ta.login("mustchange1", "Start1234")
            with ta.client() as c:
                blocked = c.get("/api/merchant-dashboard", headers=ta.bearer(token))
                self.assertEqual(blocked.status_code, 403, blocked.text)
                changed = c.post(
                    "/api/auth/change-password",
                    headers=ta.bearer(token),
                    json={"old_password": "Start1234", "new_password": "Changed1234"},
                )
                self.assertEqual(changed.status_code, 200, changed.text)
                allowed = c.get("/api/merchant-dashboard", headers=ta.bearer(token))
                self.assertEqual(allowed.status_code, 401, allowed.text)
                relogin_token = ta.login("mustchange1", "Changed1234")
                allowed = c.get("/api/merchant-dashboard", headers=ta.bearer(relogin_token))
                self.assertEqual(allowed.status_code, 200, allowed.text)

    def test_password_change_invalidates_existing_sessions(self) -> None:
        """改密后旧 Bearer token 和登录 Cookie 都不能继续访问业务接口。"""
        with TempApp() as ta:
            old_token = ta.login("youth1", "youth123")
            with ta.client() as c:
                changed = c.post(
                    "/api/auth/change-password",
                    headers=ta.bearer(old_token),
                    json={"old_password": "youth123", "new_password": "Changed1234"},
                )
                self.assertEqual(changed.status_code, 200, changed.text)
                old_session = c.get("/api/coupons/my", headers=ta.bearer(old_token))
                self.assertEqual(old_session.status_code, 401, old_session.text)
                new_token = ta.login("youth1", "Changed1234")
                new_session = c.get("/api/coupons/my", headers=ta.bearer(new_token))
                self.assertEqual(new_session.status_code, 200, new_session.text)

    def test_admin_password_reset_invalidates_target_session(self) -> None:
        """管理员重置密码后，目标账号的旧令牌也必须无法继续使用。"""
        with TempApp() as ta:
            admin_token = ta.login("admin", "admin123")
            user_token = ta.login("youth1", "youth123")
            user_id = _youth1_id(ta)
            with ta.client() as c:
                reset = c.post(
                    f"/api/auth/accounts/{user_id}/reset-password",
                    headers=ta.bearer(admin_token),
                    json={"new_password": "Reset1234"},
                )
                self.assertEqual(reset.status_code, 200, reset.text)
                stale = c.get("/api/coupons/my", headers=ta.bearer(user_token))
                self.assertEqual(stale.status_code, 401, stale.text)

    def test_email_password_reset_invalidates_target_session(self) -> None:
        """邮箱找回密码是改密入口，完成后也必须废止之前签发的令牌。"""
        from app.models.entities import Account, EmailCode, EmailCodePurpose, utcnow

        with TempApp() as ta:
            user_token = ta.login("youth1", "youth123")
            with ta.session() as db:
                user = db.query(Account).filter(Account.username == "youth1").one()
                # 演示账号使用 .local；接口按 EmailStr 校验，因此测试改用可投递域名。
                user.email = "password-reset@example.com"
                db.add(
                    EmailCode(
                        email=user.email,
                        code="654321",
                        purpose=EmailCodePurpose.reset_password,
                        expires_at=utcnow() + timedelta(minutes=10),
                    )
                )
                db.commit()
                email = user.email
            with ta.client() as c:
                reset = c.post(
                    "/api/auth/reset-password-by-email",
                    json={"email": email, "code": "654321", "new_password": "EmailReset1234"},
                )
                self.assertEqual(reset.status_code, 200, reset.text)
                stale = c.get("/api/coupons/my", headers=ta.bearer(user_token))
                self.assertEqual(stale.status_code, 401, stale.text)

    def test_deactivate_then_reactivate_requires_relogin(self) -> None:
        """T05：停用废止旧会话；重新启用后旧 Cookie/Bearer 仍不可用，必须重新登录。"""
        with TempApp() as ta:
            admin_token = ta.login("admin", "admin123")
            user_token = ta.login("youth1", "youth123")
            user_id = _youth1_id(ta)
            with ta.client() as c:
                stop = c.post(
                    f"/api/auth/accounts/{user_id}/set-active",
                    headers=ta.bearer(admin_token),
                    json={"is_active": False},
                )
                self.assertEqual(stop.status_code, 200, stop.text)
                stopped = c.get("/api/coupons/my", headers=ta.bearer(user_token))
                self.assertEqual(stopped.status_code, 401, stopped.text)

                resume = c.post(
                    f"/api/auth/accounts/{user_id}/set-active",
                    headers=ta.bearer(admin_token),
                    json={"is_active": True},
                )
                self.assertEqual(resume.status_code, 200, resume.text)
                # 停用动作已递增 session_version：重新启用不能“复活”旧会话
                stale = c.get("/api/coupons/my", headers=ta.bearer(user_token))
                self.assertEqual(stale.status_code, 401, stale.text)
                fresh = ta.login("youth1", "youth123")
                ok = c.get("/api/coupons/my", headers=ta.bearer(fresh))
                self.assertEqual(ok.status_code, 200, ok.text)

    def test_cookie_only_mode_login_hides_body_token(self) -> None:
        """关闭 Bearer 兼容后，登录响应体不返回真实 access_token，Cookie 会话仍可用。"""
        with TempApp() as ta:
            from tests._helpers import fresh_settings

            fresh_settings(AUTH_ALLOW_BEARER="false")
            try:
                with ta.client() as c:
                    r = c.post("/api/auth/login", json={"username": "youth1", "password": "youth123"})
                    self.assertEqual(r.status_code, 200, r.text)
                    self.assertEqual(
                        r.json().get("access_token") or "",
                        "",
                        "Cookie 专用模式下响应体不得携带真实 token",
                    )
                    # Cookie 会话照常工作
                    me = c.get("/api/auth/me")
                    self.assertEqual(me.status_code, 200, me.text)
                    self.assertEqual(me.json()["username"], "youth1")
            finally:
                fresh_settings(AUTH_ALLOW_BEARER="true")

    def test_approved_profile_change_requires_re_review(self) -> None:
        """已核验身份字段变更后必须重新审核，不能继续保持 approved。"""
        with TempApp() as ta:
            token = ta.login("youth1", "youth123")
            with ta.client() as c:
                response = c.put(
                    "/api/users/me/profile",
                    headers=ta.bearer(token),
                    json={"real_name": "核验后修改的姓名"},
                )
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json()["verify_status"], "pending")

            with ta.session() as db:
                from app.models.entities import Account, UserProfile, UserVerification, VerifyStatus

                user = db.query(Account).filter(Account.username == "youth1").one()
                profile = db.query(UserProfile).filter(UserProfile.account_id == user.id).one()
                self.assertEqual(profile.verify_status, VerifyStatus.pending)
                self.assertTrue(
                    db.query(UserVerification)
                    .filter(
                        UserVerification.profile_id == profile.id,
                        UserVerification.status == VerifyStatus.pending,
                    )
                    .first()
                )

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

    # ---- T17：超管专用页面权限与导出筛选一致性 ----
    def test_issue_admin_cannot_access_super_only_apis(self) -> None:
        """菜单隐藏不够：/auth/accounts 与 /audit-logs 后端仅超管（对应前端路由 roles）。"""
        with TempApp() as ta:
            issuer = ta.login("issuer", "issuer123")
            with ta.client() as c:
                for path in ("/api/auth/accounts", "/api/audit-logs"):
                    r = c.get(path, headers=ta.bearer(issuer))
                    self.assertEqual(r.status_code, 403, f"{path}: {r.text}")

    def test_export_users_respects_search_filter(self) -> None:
        """导出与列表筛选条件一致：q 搜索在导出生效（T17 条款 3）。"""
        with TempApp() as ta:
            admin = ta.login("admin", "admin123")
            with ta.client() as c:
                r_all = c.get("/api/export/users", headers=ta.bearer(admin))
                self.assertEqual(r_all.status_code, 200, r_all.text)
                # youth1 在种子数据中存在；按其用户名过滤后仍包含，按不存在用户过滤则为空
                r_hit = c.get(
                    "/api/export/users",
                    headers=ta.bearer(admin),
                    params={"q": "youth1"},
                )
                self.assertEqual(r_hit.status_code, 200, r_hit.text)
                self.assertIn("youth1", r_hit.text)
                r_miss = c.get(
                    "/api/export/users",
                    headers=ta.bearer(admin),
                    params={"q": "no-such-user-xyz"},
                )
                self.assertEqual(r_miss.status_code, 200)
                self.assertNotIn("youth1", r_miss.text)
