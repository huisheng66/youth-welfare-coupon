"""动态券码测试：生成 / 解码 / 篡改 / 跨用户 / 端到端预览。

Run from backend/:
  .\\.venv\\Scripts\\python.exe -m pytest tests/test_live_code.py -v
"""

from __future__ import annotations

import unittest

from tests._helpers import TempApp, reset_env_defaults


def _first_coupon_of(ta: TempApp, username: str = "youth1") -> tuple[str, str]:
    """返回 (coupon_id, permanent_code)。permanent_code 仅作业务查询编号。"""
    with ta.session() as db:
        from app.models.entities import Account, CouponInstance, CouponStatus

        u = db.query(Account).filter(Account.username == username).one()
        c = (
            db.query(CouponInstance)
            .filter(
                CouponInstance.user_id == u.id,
                CouponInstance.status == CouponStatus.unused,
            )
            .order_by(CouponInstance.issued_at.desc())
            .first()
        )
        assert c is not None, f"{username} has no unused coupon"
        return c.id, c.code


class TestLiveCode(unittest.TestCase):
    def tearDown(self) -> None:
        reset_env_defaults()

    # ---- service 层 ----
    def test_create_and_decode_roundtrip(self) -> None:
        from app.services.live_code import create_live_code, decode_live_code

        with TempApp() as ta:
            cid, code = _first_coupon_of(ta)
            with ta.session() as db:
                from app.models.entities import Account

                uid = db.query(Account).filter(Account.username == "youth1").one().id
            live, seconds, exp = create_live_code(coupon_id=cid, user_id=uid)
            self.assertGreater(seconds, 0)
            payload = decode_live_code(live)
            self.assertEqual(payload["cid"], cid)
            self.assertEqual(payload["uid"], uid)
            self.assertEqual(payload["typ"], "live_coupon")
            # T01：动态码载荷不再携带永久券码
            self.assertNotIn("code", payload)

    def test_decode_tampered_signature_fails(self) -> None:
        from app.services.live_code import create_live_code, decode_live_code

        with TempApp() as ta:
            cid, code = _first_coupon_of(ta)
            with ta.session() as db:
                from app.models.entities import Account

                uid = db.query(Account).filter(Account.username == "youth1").one().id
            live, _, _ = create_live_code(coupon_id=cid, user_id=uid)
            # 篡改签名段（最后一段）
            parts = live.split(".")
            tampered = parts[0] + "." + parts[1] + ".AAAA" + parts[2][4:]
            with self.assertRaises(ValueError):
                decode_live_code(tampered)

    def test_decode_foreign_token_with_wrong_typ_fails(self) -> None:
        """用一个普通 access_token（typ 非 live_coupon / 缺必要 claim）应被拒绝。"""
        from app.core.security import create_access_token
        from app.services.live_code import decode_live_code

        with TempApp() as ta:
            foreign = create_access_token("some-user", {"role": "user"})
            with self.assertRaises(ValueError) as ctx:
                decode_live_code(foreign)
            # 缺 claim 与 typ 不符都可能先触发，两种拒绝文案都成立
            self.assertTrue(
                "不是有效的动态券码" in str(ctx.exception)
                or "动态券码无效或已过期" in str(ctx.exception),
                str(ctx.exception),
            )

    def test_looks_like_live_code(self) -> None:
        from app.services.live_code import looks_like_live_code

        # JWT 形态（三段，长度>40）
        self.assertTrue(looks_like_live_code("aaa.bbb.ccc" + "x" * 40))
        # 永久券码（10 位大写字母+数字）不算动态码
        self.assertFalse(looks_like_live_code("ABCD1234XY"))
        # 过短
        self.assertFalse(looks_like_live_code("a.b.c"))

    # ---- API 端到端 ----
    def test_user_can_get_live_code_then_merchant_preview(self) -> None:
        """youth1 生成动态码 → merchant1 用动态码 preview 成功。"""
        with TempApp() as ta:
            user_token = ta.login("youth1", "youth123")
            m_token = ta.login("merchant1", "merchant123")
            cid, _ = _first_coupon_of(ta)
            with ta.client() as c:
                r = c.get(
                    f"/api/coupons/instances/{cid}/live-code",
                    headers=ta.bearer(user_token),
                )
                self.assertEqual(r.status_code, 200, r.text)
                live_code = r.json()["live_code"]
                self.assertTrue(live_code)
                # 商家预览动态码（不改变状态）
                r2 = c.post(
                    "/api/coupons/preview",
                    headers=ta.bearer(m_token),
                    json={"code": live_code},
                )
                self.assertEqual(r2.status_code, 200, r2.text)
                self.assertEqual(r2.json()["status"], "unused")

    def test_user_cannot_get_live_code_of_others(self) -> None:
        """youth1 不能获取他人券的动态码。"""
        with TempApp() as ta:
            # 给 youth2 发一张券（先审核通过）
            admin_token = ta.login("admin", "admin123")
            with ta.session() as db:
                from app.models.entities import Account, CouponTemplate, UserProfile, VerifyStatus

                y2 = db.query(Account).filter(Account.username == "youth2").one()
                db.query(UserProfile).filter(UserProfile.account_id == y2.id).update(
                    {"verify_status": VerifyStatus.approved}
                )
                db.commit()
                tmpl = db.query(CouponTemplate).filter(CouponTemplate.is_active.is_(True)).first()
                y2_id = y2.id
                tmpl_id = tmpl.id
            with ta.client() as c:
                c.post(
                    "/api/coupons/issue",
                    headers=ta.bearer(admin_token),
                    json={"user_id": y2_id, "template_id": tmpl_id, "quantity": 1},
                )
                # 取 youth2 的券 id
                with ta.session() as db:
                    from app.models.entities import CouponInstance, CouponStatus

                    c2 = (
                        db.query(CouponInstance)
                        .filter(
                            CouponInstance.user_id == y2_id,
                            CouponInstance.status == CouponStatus.unused,
                        )
                        .first()
                    )
                    c2_id = c2.id
            # youth1 尝试获取 youth2 的券动态码
            user_token = ta.login("youth1", "youth123")
            with ta.client() as c:
                r = c.get(
                    f"/api/coupons/instances/{c2_id}/live-code",
                    headers=ta.bearer(user_token),
                )
                self.assertEqual(r.status_code, 404, r.text)

    def test_live_code_for_wrong_merchant_preview_fails(self) -> None:
        """merchant2 不能用 merchant1 店的券的动态码预览（跨店）。"""
        with TempApp() as ta:
            user_token = ta.login("youth1", "youth123")
            m2_token = ta.login("merchant2", "merchant123")
            cid, _ = _first_coupon_of(ta)
            with ta.client() as c:
                r = c.get(
                    f"/api/coupons/instances/{cid}/live-code",
                    headers=ta.bearer(user_token),
                )
                self.assertEqual(r.status_code, 200, r.text)
                live_code = r.json()["live_code"]
                # merchant2 预览 merchant1 店的券
                r2 = c.post(
                    "/api/coupons/preview",
                    headers=ta.bearer(m2_token),
                    json={"code": live_code},
                )
                self.assertEqual(r2.status_code, 400, r2.text)
                self.assertIn("非本店", r2.json()["detail"])


if __name__ == "__main__":
    unittest.main()
