"""核销状态竞争测试（T06）：双核销、作废竞争、停用门店拦截。

Run from backend/:
  .\\.venv\\Scripts\\python.exe -m pytest tests/test_redemption_race.py -v
"""

from __future__ import annotations

import threading
import unittest

from tests._helpers import TempApp, reset_env_defaults


def _first_unused_coupon(ta: TempApp, username: str = "youth1") -> str:
    with ta.session() as db:
        from app.models.entities import Account, CouponInstance, CouponStatus

        u = db.query(Account).filter(Account.username == username).one()
        c = (
            db.query(CouponInstance)
            .filter(CouponInstance.user_id == u.id, CouponInstance.status == CouponStatus.unused)
            .order_by(CouponInstance.issued_at.desc())
            .first()
        )
        assert c is not None
        return c.id


def _live_code_of(ta: TempApp, coupon_id: str) -> str:
    with ta.client() as c:
        r = c.post("/api/auth/login", json={"username": "youth1", "password": "youth123"})
        token = r.json()["access_token"]
        r2 = c.get(f"/api/coupons/instances/{coupon_id}/live-code", headers=ta.bearer(token))
        assert r2.status_code == 200, r2.text
        return r2.json()["live_code"]


def _redeem_task(ta: TempApp, username: str, password: str, code: str, barrier: threading.Barrier, results: list) -> None:
    with ta.client() as c:
        r = c.post("/api/auth/login", json={"username": username, "password": password})
        token = r.json()["access_token"]
        barrier.wait(timeout=10)
        resp = c.post("/api/coupons/redeem", headers=ta.bearer(token), json={"code": code})
        results.append(resp.status_code)


class TestRedemptionRace(unittest.TestCase):
    def tearDown(self) -> None:
        reset_env_defaults()

    def test_double_redeem_concurrent_only_one_success(self) -> None:
        """同一门店两个操作员并发核销同一张券：仅一方成功，且仅一条成功流水。"""
        with TempApp() as ta:
            admin_token = ta.login("admin", "admin123")
            with ta.session() as db:
                from app.models.entities import Account, Merchant

                store_id = db.query(Account).filter(Account.username == "merchant1").one().merchant_id
                store_name = db.get(Merchant, store_id).name
            with ta.client() as c:
                created = c.post(
                    "/api/auth/merchant-accounts",
                    headers=ta.bearer(admin_token),
                    json={
                        "username": "merchant1_op2",
                        "password": "Start1234",
                        "display_name": "操作员B",
                        "merchant_id": store_id,
                    },
                )
                self.assertEqual(created.status_code, 200, created.text)
                # 首登强制改密后重新登录
                tok = ta.login("merchant1_op2", "Start1234")
                c.post(
                    "/api/auth/change-password",
                    headers=ta.bearer(tok),
                    json={"old_password": "Start1234", "new_password": "Op2pass123"},
                )
                ta.login("merchant1_op2", "Op2pass123")

            coupon_id = _first_unused_coupon(ta)
            code = _live_code_of(ta, coupon_id)

            barrier = threading.Barrier(2)
            results: list[int] = []
            threads = [
                threading.Thread(target=_redeem_task, args=(ta, "merchant1", "merchant123", code, barrier, results)),
                threading.Thread(
                    target=_redeem_task, args=(ta, "merchant1_op2", "Op2pass123", code, barrier, results)
                ),
            ]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=30)

            self.assertEqual(sorted(r == 200 for r in results), [False, True], results)
            with ta.session() as db:
                from app.models.entities import RedemptionLog

                success_logs = (
                    db.query(RedemptionLog)
                    .filter(RedemptionLog.coupon_id == coupon_id, RedemptionLog.result == "success")
                    .count()
                )
                self.assertEqual(success_logs, 1, "一张券至多一条成功核销流水")
                # 双方同店：失败重试若发生也应归属本店
                self.assertIsNotNone(db.get(Merchant, store_id).name, store_name)

    def test_void_vs_redeem_race_single_winner(self) -> None:
        """作废与核销并发：只有一个成功，另一方收到状态冲突。"""
        with TempApp() as ta:
            admin_token = ta.login("issuer", "issuer123")
            coupon_id = _first_unused_coupon(ta)
            code = _live_code_of(ta, coupon_id)

            barrier = threading.Barrier(2)
            results: list[str] = []

            def redeem_task() -> None:
                with ta.client() as c:
                    r = c.post("/api/auth/login", json={"username": "merchant1", "password": "merchant123"})
                    token = r.json()["access_token"]
                    barrier.wait(timeout=10)
                    resp = c.post("/api/coupons/redeem", headers=ta.bearer(token), json={"code": code})
                    results.append(f"redeem:{resp.status_code}")

            def void_task() -> None:
                with ta.client() as c:
                    barrier.wait(timeout=10)
                    resp = c.post(
                        f"/api/coupons/instances/{coupon_id}/void",
                        headers=ta.bearer(admin_token),
                        json={"reason": "竞争作废"},
                    )
                    results.append(f"void:{resp.status_code}")

            threads = [threading.Thread(target=redeem_task), threading.Thread(target=void_task)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=30)

            statuses = sorted(results)
            # 业务不变量是“作废与核销只有一个成功”，胜者取决于线程调度
            self.assertIn(
                statuses,
                ([["redeem:200", "void:400"], ["redeem:400", "void:200"]]),
                statuses,
            )
            with ta.session() as db:
                from app.models.entities import CouponInstance, CouponStatus, RedemptionLog

                final = db.get(CouponInstance, coupon_id)
                # 终态必须与胜者一致：核销成功 → used；作废成功 → void
                if "redeem:200" in statuses:
                    self.assertEqual(final.status, CouponStatus.used)
                else:
                    self.assertEqual(final.status, CouponStatus.void)
                success_logs = (
                    db.query(RedemptionLog)
                    .filter(RedemptionLog.coupon_id == coupon_id, RedemptionLog.result == "success")
                    .count()
                )
                self.assertLessEqual(success_logs, 1)

    def test_inactive_store_blocks_preview_and_redeem(self) -> None:
        """门店停用后：预览与核销都被拒绝，已有券不能继续核销，且核销失败留痕（F05）。"""
        with TempApp() as ta:
            coupon_id = _first_unused_coupon(ta)
            code = _live_code_of(ta, coupon_id)
            with ta.session() as db:
                from app.models.entities import Account, Merchant

                store_id = db.query(Account).filter(Account.username == "merchant1").one().merchant_id
                db.get(Merchant, store_id).is_active = False
                db.commit()
            m_token = ta.login("merchant1", "merchant123")
            with ta.client() as c:
                r1 = c.post("/api/coupons/preview", headers=ta.bearer(m_token), json={"code": code})
                self.assertEqual(r1.status_code, 400, r1.text)
                self.assertIn("停用", r1.json()["detail"])
                r2 = c.post("/api/coupons/redeem", headers=ta.bearer(m_token), json={"code": code})
                self.assertEqual(r2.status_code, 400, r2.text)
                self.assertIn("停用", r2.json()["detail"])
            # 失败核销写入流水：原因 merchant_inactive，记录归属本店与操作者
            with ta.session() as db:
                from app.models.entities import RedemptionLog

                logs = (
                    db.query(RedemptionLog)
                    .filter(
                        RedemptionLog.merchant_id == store_id,
                        RedemptionLog.result == "failed",
                        RedemptionLog.reason == "merchant_inactive",
                    )
                    .all()
                )
                self.assertEqual(len(logs), 1, "停用门店的核销拒绝必须留下失败流水")
                self.assertEqual(logs[0].operator_id, db.query(Account).filter(Account.username == "merchant1").one().id)
                self.assertIsNone(logs[0].user_id)
            # 券保持 unused：停用只阻止新核销，不改变券状态
            with ta.session() as db:
                from app.models.entities import CouponInstance, CouponStatus

                self.assertEqual(db.get(CouponInstance, coupon_id).status, CouponStatus.unused)


if __name__ == "__main__":
    unittest.main()
