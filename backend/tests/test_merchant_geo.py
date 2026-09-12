"""商家坐标在线解析测试（T25 补充）：geo-search 端点的权限、解析与错误映射。

Run from backend/:
  .\\.venv\\Scripts\\python.exe -m pytest tests/test_merchant_geo.py -v
"""

from __future__ import annotations

import os
import unittest

from tests._helpers import TempApp, reset_env_defaults

FAKE_POIS = {
    "status": "1",
    "pois": [
        {
            "name": "蜜雪冰城(青年路店)",
            "address": "青年路88号1层",
            "location": "116.397428,39.909230",
            "pname": "北京市",
            "cityname": "北京市",
            "adname": "朝阳区",
        },
        {"name": "无坐标POI", "location": ""},
    ],
}


class TestMerchantGeoSearch(unittest.TestCase):
    def tearDown(self) -> None:
        reset_env_defaults()

    def test_requires_configured_key(self) -> None:
        """未配置 AMAP_WEB_KEY：返回带配置指引的 400，而非静默失败。"""
        with TempApp() as ta:
            token = ta.login("admin", "admin123")
            with ta.client() as c:
                r = c.get(
                    "/api/merchants/geo-search",
                    headers=ta.bearer(token),
                    params={"keywords": "蜜雪冰城"},
                )
                self.assertEqual(r.status_code, 400, r.text)
                self.assertIn("AMAP_WEB_KEY", r.json()["detail"])

    def test_user_role_forbidden(self) -> None:
        """在线解析仅管理员可用（user/merchant 角色 403）。"""
        os.environ["AMAP_WEB_KEY"] = "test-key"
        try:
            with TempApp() as ta:
                user = ta.login("youth1", "youth123")
                merchant = ta.login("merchant1", "merchant123")
                with ta.client() as c:
                    for token in (user, merchant):
                        r = c.get(
                            "/api/merchants/geo-search",
                            headers=ta.bearer(token),
                            params={"keywords": "蜜雪冰城"},
                        )
                        self.assertEqual(r.status_code, 403, r.text)
        finally:
            os.environ.pop("AMAP_WEB_KEY", None)

    def test_parses_amap_pois(self) -> None:
        """解析 POI：跳过无坐标项，经纬度按高德 lng,lat 顺序；URL 携带 key 与 city。"""
        os.environ["AMAP_WEB_KEY"] = "test-key"
        try:
            with TempApp() as ta:
                from app.api import merchants as m

                captured: dict[str, str] = {}

                def fake_get_json(url: str, timeout: float = 5.0) -> dict:
                    captured["url"] = url
                    return FAKE_POIS

                orig = m._http_get_json
                m._http_get_json = fake_get_json
                try:
                    token = ta.login("admin", "admin123")
                    with ta.client() as c:
                        r = c.get(
                            "/api/merchants/geo-search",
                            headers=ta.bearer(token),
                            params={"keywords": "蜜雪冰城", "city": "北京"},
                        )
                finally:
                    m._http_get_json = orig
                self.assertEqual(r.status_code, 200, r.text)
                items = r.json()
                self.assertEqual(len(items), 1)
                self.assertEqual(items[0]["name"], "蜜雪冰城(青年路店)")
                self.assertEqual(items[0]["longitude"], "116.397428")
                self.assertEqual(items[0]["latitude"], "39.909230")
                self.assertIn("key=test-key", captured["url"])
                self.assertIn("keywords=%E8%9C%9C%E9%9B%AA%E5%86%B0%E5%9F%8E", captured["url"])
                self.assertIn("city=%E5%8C%97%E4%BA%AC", captured["url"])
        finally:
            os.environ.pop("AMAP_WEB_KEY", None)

    def test_amap_error_maps_to_502_with_hint(self) -> None:
        """高德返回错误态（如 key 无效）：映射 502 并给出配置指引。"""
        os.environ["AMAP_WEB_KEY"] = "bad-key"
        try:
            with TempApp() as ta:
                from app.api import merchants as m

                orig = m._http_get_json
                m._http_get_json = lambda url, timeout=5.0: {
                    "status": "0",
                    "info": "INVALID_USER_KEY",
                    "infocode": "10001",
                }
                try:
                    token = ta.login("admin", "admin123")
                    with ta.client() as c:
                        r = c.get(
                            "/api/merchants/geo-search",
                            headers=ta.bearer(token),
                            params={"keywords": "蜜雪冰城"},
                        )
                finally:
                    m._http_get_json = orig
                self.assertEqual(r.status_code, 502, r.text)
                detail = r.json()["detail"]
                self.assertIn("INVALID_USER_KEY", detail)
                self.assertIn("Web服务", detail)
        finally:
            os.environ.pop("AMAP_WEB_KEY", None)


if __name__ == "__main__":
    unittest.main()
