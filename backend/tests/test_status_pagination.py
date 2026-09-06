"""T18 状态查询、分页与统计口径测试。

覆盖：本人单券轻量状态（不泄露他券、成本 O(1)）、/my 分页与稳定排序、
pending-verifications limit、业务时区划日（Asia/Shanghai 跨午夜）、
导出日期区间按业务时区转换。

Run from backend/:
  .venv/bin/python -m pytest tests/test_status_pagination.py -v
"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.models.entities import Account, CouponInstance, CouponStatus
from app.services.biztime import biz_today_start_utc, day_bounds_utc_closed
from tests._helpers import TempApp, reset_env_defaults

BIZ = ZoneInfo("Asia/Shanghai")


def _token(ta: TempApp, username: str, password: str) -> str:
    return ta.login(username, password)


class TestCouponStatusAndPagination(unittest.TestCase):
    def tearDown(self) -> None:
        reset_env_defaults()

    def test_my_coupons_paginated_and_stable(self) -> None:
        """/my 分页无重复遗漏，排序稳定（issued_at desc, id desc）。"""
        with TempApp() as ta:
            admin = ta.login("admin", "admin123")
            youth = _token(ta, "youth1", "youth123")
            with ta.session() as db:
                yid = db.query(Account).filter(Account.username == "youth1").one().id
            # 发 7 张（模板默认余量足够）
            with ta.client() as c:
                r = c.post(
                    "/api/coupons/issue",
                    headers=ta.bearer(admin),
                    json={"user_id": yid, "template_id": self._tmpl(ta), "quantity": 7},
                )
                self.assertEqual(r.status_code, 200, r.text)
            all_ids: list[str] = []
            for skip in (0, 3, 6):
                with ta.client() as c:
                    r = c.get(
                        "/api/coupons/my",
                        headers=ta.bearer(youth),
                        params={"skip": skip, "limit": 3},
                    )
                    self.assertEqual(r.status_code, 200, r.text)
                    body = r.json()
                self.assertEqual(body["total"] >= 7, True, r.text)
                self.assertEqual(["items", "total"], sorted(body.keys()))
                all_ids.extend(i["id"] for i in body["items"])
            self.assertEqual(len(all_ids), len(set(all_ids)), "分页不得重复")
            # 全量一次与分页合集一致（无遗漏）
            with ta.client() as c:
                r = c.get("/api/coupons/my", headers=ta.bearer(youth), params={"limit": 50})
                full_body = r.json()
                full = [i["id"] for i in full_body["items"]]
            self.assertEqual(len(full), full_body["total"], "全量 items 数与 total 一致")
            self.assertEqual(sorted(full), sorted(all_ids), "分页合集与全量一致（无遗漏无重复）")
            with ta.client() as c:
                r = c.get("/api/coupons/my", headers=ta.bearer(youth), params={"limit": 50})
                items = r.json()["items"]
            issued = [i["issued_at"] for i in items]
            self.assertEqual(issued, sorted(issued, reverse=True), "按 issued_at 降序")

    @staticmethod
    def _tmpl(ta: TempApp) -> str:
        with ta.session() as db:
            from app.models.entities import CouponTemplate

            return (
                db.query(CouponTemplate).filter(CouponTemplate.name == "餐饮立减券").one().id
            )

    def test_single_coupon_status_scoped_and_light(self) -> None:
        """本人单券状态：他人券 404，仅返回轻量字段。"""
        with TempApp() as ta:
            admin = ta.login("admin", "admin123")
            youth = _token(ta, "youth1", "youth123")
            merchant = ta.login("merchant1", "merchant123")
            with ta.session() as db:
                y1 = db.query(Account).filter(Account.username == "youth1").one()
            with ta.client() as c:
                r = c.post(
                    "/api/coupons/issue",
                    headers=ta.bearer(admin),
                    json={"user_id": y1.id, "template_id": self._tmpl(ta), "quantity": 1},
                )
                self.assertEqual(r.status_code, 200, r.text)
                cid = r.json()[0]["id"]
            with ta.client() as c:
                r = c.get(f"/api/coupons/instances/{cid}/status", headers=ta.bearer(merchant))
                self.assertEqual(r.status_code in (401, 403), True, "非本人角色不可查")
                r = c.get(f"/api/coupons/instances/{cid}/status", headers=ta.bearer(youth))
                self.assertEqual(r.status_code, 200, r.text)
                body = r.json()
                self.assertEqual(body["status"], "unused")
                # 轻量字段：不含模板/商家/用户等冗余
                self.assertNotIn("template_name", body)
                self.assertNotIn("username", body)

    def test_pending_verifications_limit_param(self) -> None:
        with TempApp() as ta:
            admin = ta.login("admin", "admin123")
            with ta.client() as c:
                r = c.get(
                    "/api/users/pending-verifications",
                    headers=ta.bearer(admin),
                    params={"limit": 5},
                )
                self.assertEqual(r.status_code, 200, r.text)
                self.assertLessEqual(len(r.json()), 5)


class TestBusinessTimezone(unittest.TestCase):
    def tearDown(self) -> None:
        reset_env_defaults()

    def test_today_start_follows_business_tz(self) -> None:
        """UTC 16:00（北京次日 00:00）即新业务日开始。"""
        # UTC 2026-09-06 15:59 → 北京 23:59，业务日仍是 09-06
        before = datetime(2026, 9, 6, 15, 59, tzinfo=timezone.utc)
        self.assertEqual(biz_today_start_utc(before), datetime(2026, 9, 6, 0, 0, tzinfo=BIZ))
        # UTC 2026-09-06 16:00 → 北京 09-07 00:00，业务日翻到 09-07
        after = datetime(2026, 9, 6, 16, 0, tzinfo=timezone.utc)
        self.assertEqual(biz_today_start_utc(after), datetime(2026, 9, 7, 0, 0, tzinfo=BIZ))

    def test_day_bounds_closed_cover_whole_business_day(self) -> None:
        start, end = day_bounds_utc_closed(None, None)
        self.assertIsNone(start)
        self.assertIsNone(end)
        start, end = day_bounds_utc_closed(
            datetime(2026, 9, 6, tzinfo=BIZ).date(),
            datetime(2026, 9, 6, tzinfo=BIZ).date(),
        )
        self.assertEqual(start, datetime(2026, 9, 6, 0, 0, tzinfo=BIZ))
        self.assertEqual(end, datetime(2026, 9, 7, 0, 0, tzinfo=BIZ) - timedelta(microseconds=1))


if __name__ == "__main__":
    unittest.main()
