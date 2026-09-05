"""门店范围隔离测试（T02）：商家角色只能读取本店资料与数据。

Run from backend/:
  .\\.venv\\Scripts\\python.exe -m pytest tests/test_merchant_scope.py -v
"""

from __future__ import annotations

import unittest

from tests._helpers import TempApp, reset_env_defaults


def _merchant_ids(ta: TempApp) -> tuple[str, str]:
    """返回 (merchant1 的门店 id, merchant2 的门店 id)。"""
    with ta.session() as db:
        from app.models.entities import Account, Merchant

        m1 = db.query(Account).filter(Account.username == "merchant1").one()
        m2 = db.query(Account).filter(Account.username == "merchant2").one()
        return m1.merchant_id, m2.merchant_id


class TestMerchantScope(unittest.TestCase):
    def tearDown(self) -> None:
        reset_env_defaults()

    def test_merchant_list_locked_to_own_store(self) -> None:
        """商家列表强制限定本店，query 参数不能扩大范围。"""
        with TempApp() as ta:
            m1_id, m2_id = _merchant_ids(ta)
            token = ta.login("merchant1", "merchant123")
            with ta.client() as c:
                r = c.get("/api/merchants", headers=ta.bearer(token))
                self.assertEqual(r.status_code, 200, r.text)
                items = r.json()["items"]
                self.assertEqual([i["id"] for i in items], [m1_id])

                # 管理员仍可看到全部门店
                admin_token = ta.login("admin", "admin123")
                r2 = c.get("/api/merchants", headers=ta.bearer(admin_token))
                self.assertGreaterEqual(r2.json()["total"], 2)

    def test_merchant_detail_of_other_store_returns_404(self) -> None:
        """他店详情与不存在统一 404，不暴露他店联系资料。"""
        with TempApp() as ta:
            _, m2_id = _merchant_ids(ta)
            token = ta.login("merchant1", "merchant123")
            with ta.client() as c:
                r = c.get(f"/api/merchants/{m2_id}", headers=ta.bearer(token))
                self.assertEqual(r.status_code, 404, r.text)
                self.assertNotIn("contact", r.text)

                own = c.get(
                    f"/api/merchants/{_merchant_ids(ta)[0]}",
                    headers=ta.bearer(token),
                )
                self.assertEqual(own.status_code, 200, own.text)

    def test_merchant_without_binding_sees_nothing(self) -> None:
        """未绑定门店的商家账号：列表为空、他店详情 404。"""
        with TempApp() as ta:
            m1_id, _ = _merchant_ids(ta)
            from app.core.security import hash_password
            from app.models.entities import Account, Role

            with ta.session() as db:
                loose = Account(
                    username="loose_merchant",
                    password_hash=hash_password("loose12345"),
                    role=Role.merchant,
                    display_name="未绑定",
                )
                db.add(loose)
                db.commit()
            token = ta.login("loose_merchant", "loose12345")
            with ta.client() as c:
                r = c.get("/api/merchants", headers=ta.bearer(token))
                self.assertEqual((r.status_code, r.json()["total"]), (200, 0))
                r2 = c.get(f"/api/merchants/{m1_id}", headers=ta.bearer(token))
                self.assertEqual(r2.status_code, 404)

    def test_merchant_coupon_filter_cannot_cross_stores(self) -> None:
        """商家查券列表忽略 merchant_id 参数，固定本店范围。"""
        with TempApp() as ta:
            m1_id, m2_id = _merchant_ids(ta)
            token = ta.login("merchant1", "merchant123")
            with ta.client() as c:
                # 用 merchant_id 参数请求他店范围：应仍只见本店数据
                r = c.get(
                    "/api/coupons/instances",
                    headers=ta.bearer(token),
                    params={"merchant_id": m2_id, "limit": 100},
                )
                self.assertEqual(r.status_code, 200, r.text)
                for item in r.json()["items"]:
                    self.assertEqual(item["merchant_id"], m1_id)

    def test_merchant_redemptions_ignore_cross_store_filter(self) -> None:
        """核销流水对商家角色固定本店，merchant_id 参数不生效。"""
        with TempApp() as ta:
            m1_id, m2_id = _merchant_ids(ta)
            token = ta.login("merchant1", "merchant123")
            with ta.client() as c:
                r = c.get(
                    "/api/coupons/redemptions",
                    headers=ta.bearer(token),
                    params={"merchant_id": m2_id, "limit": 100},
                )
                self.assertEqual(r.status_code, 200, r.text)
                for item in r.json()["items"]:
                    self.assertEqual(item["merchant_id"], m1_id)


if __name__ == "__main__":
    unittest.main()
