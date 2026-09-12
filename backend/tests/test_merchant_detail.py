"""商家详情页后端测试（T25）：用户可读门店资料、门头照上传/查看/删除、坐标校验。

Run from backend/:
  .\\.venv\\Scripts\\python.exe -m pytest tests/test_merchant_detail.py -v
"""

from __future__ import annotations

import base64
import os
import unittest

from tests._helpers import TempApp, reset_env_defaults

# 合法 1x1 PNG（魔数校验与字节回读都用它）
PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)


def _m1_id(ta: TempApp) -> str:
    with ta.session() as db:
        from app.models.entities import Account

        return db.query(Account).filter(Account.username == "merchant1").one().merchant_id


class TestMerchantDetailAccess(unittest.TestCase):
    def tearDown(self) -> None:
        reset_env_defaults()

    def test_user_can_view_merchant_detail(self) -> None:
        """用户角色可读门店公开资料（地址/电话/坐标），券面本就展示指定商家。"""
        with TempApp() as ta:
            token = ta.login("youth1", "youth123")
            with ta.client() as c:
                r = c.get(f"/api/merchants/{_m1_id(ta)}", headers=ta.bearer(token))
                self.assertEqual(r.status_code, 200, r.text)
                body = r.json()
                self.assertEqual(body["name"], "示例餐饮店")
                self.assertEqual(body["contact_phone"], "13800000001")
                self.assertIn("青年路", body["address"])
                self.assertEqual(body["longitude"], "116.397428")
                self.assertEqual(body["latitude"], "39.909230")
                self.assertFalse(body["has_photo"])

    def test_user_cannot_list_or_modify_merchants(self) -> None:
        """用户角色只能按 id 看详情：列表与全部写操作保持 403。"""
        with TempApp() as ta:
            token = ta.login("youth1", "youth123")
            m1 = _m1_id(ta)
            with ta.client() as c:
                cases = [
                    ("GET", "/api/merchants", None),
                    ("POST", "/api/merchants", {"name": "x"}),
                    ("PUT", f"/api/merchants/{m1}", {"address": "hack"}),
                    ("POST", f"/api/merchants/{m1}/photo", None),
                    ("DELETE", f"/api/merchants/{m1}/photo", None),
                ]
                for method, url, json in cases:
                    kwargs = {"headers": ta.bearer(token)}
                    if json is not None:
                        kwargs["json"] = json
                    r = c.request(method, url, **kwargs)
                    self.assertEqual(r.status_code, 403, f"{method} {url}: {r.text}")


class TestMerchantPhoto(unittest.TestCase):
    def tearDown(self) -> None:
        reset_env_defaults()

    def test_upload_serve_replace_delete(self) -> None:
        with TempApp() as ta:
            m1 = _m1_id(ta)
            admin = ta.login("admin", "admin123")
            user = ta.login("youth1", "youth123")
            png = base64.b64decode(PNG_B64)
            with ta.client() as c:
                # 管理员上传 → has_photo
                r = c.post(
                    f"/api/merchants/{m1}/photo",
                    headers=ta.bearer(admin),
                    files={"file": ("photo.png", png, "image/png")},
                )
                self.assertEqual(r.status_code, 200, r.text)
                self.assertTrue(r.json()["has_photo"])

                # 用户经 <img> 同源 GET 拿到同字节、正确 Content-Type
                r2 = c.get(f"/api/merchants/{m1}/photo", headers=ta.bearer(user))
                self.assertEqual(r2.status_code, 200, r2.text)
                self.assertEqual(r2.content, png)
                self.assertTrue(r2.headers["content-type"].startswith("image/png"))
                self.assertIn("private", r2.headers.get("cache-control", ""))

                # 覆盖上传（伪装成 .png 的 JPEG 字节，按魔数识别）
                jpeg = b"\xff\xd8\xff\xe0" + b"\x00" * 32
                r3 = c.post(
                    f"/api/merchants/{m1}/photo",
                    headers=ta.bearer(admin),
                    files={"file": ("photo.png", jpeg, "image/png")},
                )
                self.assertEqual(r3.status_code, 200, r3.text)
                r4 = c.get(f"/api/merchants/{m1}/photo", headers=ta.bearer(user))
                self.assertEqual(r4.content, jpeg)
                self.assertTrue(r4.headers["content-type"].startswith("image/jpeg"))

                # 删除 → 404
                r5 = c.delete(f"/api/merchants/{m1}/photo", headers=ta.bearer(admin))
                self.assertEqual(r5.status_code, 200, r5.text)
                self.assertFalse(r5.json()["has_photo"])
                r6 = c.get(f"/api/merchants/{m1}/photo", headers=ta.bearer(user))
                self.assertEqual(r6.status_code, 404)

    def test_upload_requires_admin_role(self) -> None:
        """商家角色与未登录者都不能上传/删除门头照。"""
        with TempApp() as ta:
            m1 = _m1_id(ta)
            png = base64.b64decode(PNG_B64)
            merchant = ta.login("merchant1", "merchant123")
            with ta.client() as c:
                r = c.post(
                    f"/api/merchants/{m1}/photo",
                    headers=ta.bearer(merchant),
                    files={"file": ("photo.png", png, "image/png")},
                )
                self.assertEqual(r.status_code, 403, r.text)
                r2 = c.delete(f"/api/merchants/{m1}/photo", headers=ta.bearer(merchant))
                self.assertEqual(r2.status_code, 403, r2.text)
                r3 = c.get(f"/api/merchants/{m1}/photo")
                self.assertEqual(r3.status_code, 401, r3.text)

    def test_upload_rejects_empty_or_non_image(self) -> None:
        with TempApp() as ta:
            m1 = _m1_id(ta)
            admin = ta.login("admin", "admin123")
            with ta.client() as c:
                r = c.post(
                    f"/api/merchants/{m1}/photo",
                    headers=ta.bearer(admin),
                    files={"file": ("empty.png", b"", "image/png")},
                )
                self.assertEqual(r.status_code, 400, r.text)

                fake = b"GIF89a not an accepted image"
                r2 = c.post(
                    f"/api/merchants/{m1}/photo",
                    headers=ta.bearer(admin),
                    files={"file": ("fake.png", fake, "image/png")},
                )
                self.assertEqual(r2.status_code, 400, r2.text)
                self.assertIn("JPEG", r2.json()["detail"])

    def test_upload_oversize_rejected(self) -> None:
        """超过 MERCHANT_PHOTO_MAX_BYTES 拒绝（413），不落库。"""
        os.environ["MERCHANT_PHOTO_MAX_BYTES"] = "64"
        try:
            with TempApp() as ta:
                m1 = _m1_id(ta)
                admin = ta.login("admin", "admin123")
                with ta.client() as c:
                    big = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
                    r = c.post(
                        f"/api/merchants/{m1}/photo",
                        headers=ta.bearer(admin),
                        files={"file": ("big.png", big, "image/png")},
                    )
                    self.assertEqual(r.status_code, 413, r.text)
                    # 失败上传不得留下半张照片
                    r2 = c.get(f"/api/merchants/{m1}/photo", headers=ta.bearer(admin))
                    self.assertEqual(r2.status_code, 404, r2.text)
        finally:
            os.environ.pop("MERCHANT_PHOTO_MAX_BYTES", None)


class TestMerchantCoordinates(unittest.TestCase):
    def tearDown(self) -> None:
        reset_env_defaults()

    def test_update_coordinates_valid_and_invalid(self) -> None:
        with TempApp() as ta:
            m1 = _m1_id(ta)
            admin = ta.login("admin", "admin123")
            with ta.client() as c:
                r = c.put(
                    f"/api/merchants/{m1}",
                    headers=ta.bearer(admin),
                    json={"longitude": "116.397428", "latitude": "39.909230"},
                )
                self.assertEqual(r.status_code, 200, r.text)
                self.assertEqual(r.json()["longitude"], "116.397428")

                for bad in [{"longitude": "999"}, {"longitude": "abc"}, {"latitude": "39.1.2"}]:
                    r2 = c.put(f"/api/merchants/{m1}", headers=ta.bearer(admin), json=bad)
                    self.assertEqual(r2.status_code, 422, f"{bad}: {r2.text}")

    def test_create_merchant_with_coordinates(self) -> None:
        with TempApp() as ta:
            admin = ta.login("admin", "admin123")
            with ta.client() as c:
                r = c.post(
                    "/api/merchants",
                    headers=ta.bearer(admin),
                    json={
                        "name": "坐标测试店",
                        "address": "测试路 1 号",
                        "longitude": "121.473701",
                        "latitude": "31.230416",
                    },
                )
                self.assertEqual(r.status_code, 200, r.text)
                self.assertEqual(r.json()["latitude"], "31.230416")
                # 清理避免影响其他用例的演示数据假设
                c.put(
                    f"/api/merchants/{r.json()['id']}",
                    headers=ta.bearer(admin),
                    json={"is_active": False},
                )


if __name__ == "__main__":
    unittest.main()
