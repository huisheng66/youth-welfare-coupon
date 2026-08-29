"""Regression guards for query counts on high-traffic list and export paths."""

from __future__ import annotations

import unittest

from sqlalchemy import event

from tests._helpers import TempApp, reset_env_defaults


class TestQueryCounts(unittest.TestCase):
    def tearDown(self) -> None:
        reset_env_defaults()

    @staticmethod
    def _select_counter(engine):
        statements: list[str] = []

        def track(_conn, _cursor, statement, _parameters, _context, _executemany):
            if statement.lstrip().upper().startswith("SELECT"):
                statements.append(statement)

        event.listen(engine, "before_cursor_execute", track)
        return statements, track

    def test_coupon_search_page_uses_bounded_queries(self) -> None:
        with TempApp() as ta:
            token = ta.login("issuer", "issuer123")
            statements, listener = self._select_counter(ta.engine)
            try:
                with ta.client() as client:
                    response = client.get(
                        "/api/coupons/instances",
                        headers=ta.bearer(token),
                        params={"q": "youth1", "limit": 20},
                    )
            finally:
                event.remove(ta.engine, "before_cursor_execute", listener)

            self.assertEqual(response.status_code, 200, response.text)
            self.assertGreaterEqual(response.json()["total"], 1)
            self.assertLessEqual(len(statements), 3, "coupon page regressed to extra/N+1 SELECTs")

    def test_coupon_export_uses_bounded_queries(self) -> None:
        with TempApp() as ta:
            token = ta.login("issuer", "issuer123")
            statements, listener = self._select_counter(ta.engine)
            try:
                with ta.client() as client:
                    response = client.get("/api/export/coupons", headers=ta.bearer(token))
            finally:
                event.remove(ta.engine, "before_cursor_execute", listener)

            self.assertEqual(response.status_code, 200, response.text)
            self.assertIn("text/csv", response.headers.get("content-type", ""))
            self.assertLessEqual(len(statements), 6, "coupon export regressed to N+1 SELECTs")


if __name__ == "__main__":
    unittest.main()
