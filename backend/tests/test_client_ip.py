"""Client IP trust model + login rate keys (XFF bypass resistance)."""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


class TestClientIp(unittest.TestCase):
    def _req(self, peer: str, headers: dict | None = None):
        from app.core.client_ip import get_client_ip

        req = MagicMock()
        req.client = MagicMock()
        req.client.host = peer
        hdrs = {k.lower(): v for k, v in (headers or {}).items()}
        req.headers.get = lambda k, default=None: hdrs.get(k.lower(), default)
        return get_client_ip(req)

    def test_direct_ignores_spoofed_xff_and_cf(self) -> None:
        ip = self._req(
            "203.0.113.50",
            {
                "X-Forwarded-For": "1.2.3.4, 5.6.7.8",
                "CF-Connecting-IP": "9.9.9.9",
                "X-Real-IP": "8.8.8.8",
            },
        )
        self.assertEqual(ip, "203.0.113.50")

    def test_loopback_prefers_cf_when_real_is_cf(self) -> None:
        # 162.158.0.0/15 is Cloudflare
        ip = self._req(
            "127.0.0.1",
            {
                "CF-Connecting-IP": "198.51.100.10",
                "X-Real-IP": "162.158.1.1",
                "X-Forwarded-For": "198.51.100.10, 162.158.1.1",
            },
        )
        self.assertEqual(ip, "198.51.100.10")

    def test_loopback_forged_cf_with_non_cf_real_uses_real(self) -> None:
        ip = self._req(
            "127.0.0.1",
            {
                "CF-Connecting-IP": "1.1.1.1",
                "X-Real-IP": "203.0.113.99",
            },
        )
        self.assertEqual(ip, "203.0.113.99")

    def test_loopback_xff_uses_last_not_first(self) -> None:
        ip = self._req(
            "127.0.0.1",
            {"X-Forwarded-For": "1.2.3.4, 10.0.0.1"},
        )
        self.assertEqual(ip, "10.0.0.1")

    def test_cloudflare_peer_trusts_cf_connecting(self) -> None:
        ip = self._req(
            "162.158.10.20",
            {"CF-Connecting-IP": "203.0.113.7"},
        )
        self.assertEqual(ip, "203.0.113.7")

    def test_docker_bridge_peer_trusts_x_real_ip_when_configured(self) -> None:
        """Compose web→api 对端是 172.x；配置 TRUSTED_PROXY_CIDRS 后应读 X-Real-IP。"""
        os.environ["TRUSTED_PROXY_CIDRS"] = "10.0.0.0/8,172.16.0.0/12,192.168.0.0/16"
        from app.core.config import clear_settings_cache

        clear_settings_cache()
        try:
            ip = self._req(
                "172.18.0.5",
                {
                    "X-Real-IP": "203.0.113.88",
                    "X-Forwarded-For": "1.2.3.4, 172.18.0.5",
                },
            )
            self.assertEqual(ip, "203.0.113.88")
        finally:
            os.environ.pop("TRUSTED_PROXY_CIDRS", None)
            clear_settings_cache()

    def test_docker_bridge_peer_without_config_ignores_headers(self) -> None:
        os.environ.pop("TRUSTED_PROXY_CIDRS", None)
        from app.core.config import clear_settings_cache

        clear_settings_cache()
        ip = self._req(
            "172.18.0.5",
            {"X-Real-IP": "203.0.113.88"},
        )
        self.assertEqual(ip, "172.18.0.5")


class TestLoginRateByUser(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["RATE_LIMIT_BACKEND"] = "memory"
        os.environ["LOGIN_MAX_FAILS"] = "3"
        os.environ["LOGIN_WINDOW_SECONDS"] = "300"
        os.environ["GLOBAL_IP_MAX_REQUESTS"] = "0"
        from app.core.config import clear_settings_cache
        from app.services.rate_limit import reset_limiters

        clear_settings_cache()
        reset_limiters()

    def test_xff_cannot_reset_user_bucket(self) -> None:
        from app.api import auth as auth_mod

        user = "victim_user"
        # 3 fails under different "IPs" should still lock by username
        for i in range(3):
            auth_mod._record_login_fail(f"203.0.113.{i}", user)
        with self.assertRaises(Exception) as ctx:
            auth_mod._check_login_rate("198.51.100.1", user)
        # FastAPI HTTPException
        exc = ctx.exception
        self.assertEqual(getattr(exc, "status_code", None), 429)


if __name__ == "__main__":
    unittest.main()
