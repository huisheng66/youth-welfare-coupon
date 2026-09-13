"""CSRF 中间件来源校验回归（X-Requested-With + Origin/Referer 白名单）。

只构造带 CsrfProtectMiddleware 的最小应用，不依赖数据库；Settings 显式
传入并屏蔽 .env，避免读本机开发配置。
"""

from __future__ import annotations

import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

import tests._helpers  # noqa: F401  (进程级 dotenv 隔离，须在导入 app 前生效)
from app.core.config import Settings
from app.main import CsrfProtectMiddleware


def make_settings(lan: bool) -> Settings:
    return Settings(
        _env_file=None,
        cors_origins="https://app.example.com,https://alt.example.com",
        cors_allow_lan=lan,
    )


def make_app(settings: Settings) -> FastAPI:
    app = FastAPI()

    @app.post("/ping")
    def ping_post():
        return {"ok": True}

    @app.get("/ping")
    def ping_get():
        return {"ok": True}

    app.add_middleware(CsrfProtectMiddleware, settings=settings)
    return app


XHR = {"X-Requested-With": "XMLHttpRequest"}


class CsrfOriginTests(unittest.TestCase):
    def test_missing_header_still_rejected(self):
        c = TestClient(make_app(make_settings(False)))
        r = c.post("/ping")
        self.assertEqual(r.status_code, 403)
        self.assertIn("缺少 CSRF", r.json()["detail"])

    def test_no_origin_non_browser_client_passes(self):
        c = TestClient(make_app(make_settings(False)))
        r = c.post("/ping", headers=XHR)
        self.assertEqual(r.status_code, 200, r.text)

    def test_same_origin_host_passes(self):
        c = TestClient(make_app(make_settings(False)))
        r = c.post("/ping", headers={**XHR, "Origin": "http://testserver"})
        self.assertEqual(r.status_code, 200, r.text)

    def test_cors_allowlisted_origin_passes(self):
        c = TestClient(make_app(make_settings(False)))
        r = c.post("/ping", headers={**XHR, "Origin": "https://app.example.com"})
        self.assertEqual(r.status_code, 200, r.text)
        r = c.post("/ping", headers={**XHR, "Origin": "https://alt.example.com"})
        self.assertEqual(r.status_code, 200, r.text)

    def test_foreign_origin_rejected(self):
        c = TestClient(make_app(make_settings(False)))
        r = c.post("/ping", headers={**XHR, "Origin": "https://evil.com"})
        self.assertEqual(r.status_code, 403)
        self.assertIn("来源不在允许列表", r.json()["detail"])

    def test_cors_list_entry_with_different_scheme_rejected(self):
        # 白名单是精确匹配：https 条目不能给 http 同域放行
        c = TestClient(make_app(make_settings(False)))
        r = c.post("/ping", headers={**XHR, "Origin": "http://app.example.com"})
        self.assertEqual(r.status_code, 403)

    def test_referer_foreign_origin_rejected(self):
        c = TestClient(make_app(make_settings(False)))
        r = c.post("/ping", headers={**XHR, "Referer": "https://evil.com/form"})
        self.assertEqual(r.status_code, 403)

    def test_referer_same_origin_passes(self):
        c = TestClient(make_app(make_settings(False)))
        r = c.post("/ping", headers={**XHR, "Referer": "http://testserver/page"})
        self.assertEqual(r.status_code, 200, r.text)

    def test_get_requests_skip_all_checks(self):
        c = TestClient(make_app(make_settings(False)))
        r = c.get("/ping", headers={"Origin": "https://evil.com"})
        self.assertEqual(r.status_code, 200, r.text)

    def test_lan_regex_allowed_when_enabled(self):
        c = TestClient(make_app(make_settings(True)))
        r = c.post("/ping", headers={**XHR, "Origin": "http://192.168.1.50:5173"})
        self.assertEqual(r.status_code, 200, r.text)

    def test_lan_regex_prefix_spoof_rejected(self):
        # http://10.0.0.1.evil.com 不能因前缀匹配 LAN 正则而放行
        c = TestClient(make_app(make_settings(True)))
        r = c.post("/ping", headers={**XHR, "Origin": "http://10.0.0.1.evil.com"})
        self.assertEqual(r.status_code, 403)

    def test_lan_origin_rejected_when_lan_disabled(self):
        c = TestClient(make_app(make_settings(False)))
        r = c.post("/ping", headers={**XHR, "Origin": "http://192.168.1.50:5173"})
        self.assertEqual(r.status_code, 403)


if __name__ == "__main__":
    unittest.main()
