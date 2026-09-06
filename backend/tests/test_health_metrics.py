"""T22 健康与指标测试。

覆盖：liveness 轻量、readiness 数据库失效时报未就绪（验收项）、
schema 落后报未就绪、指标仅超管、核销埋点、备份状态文件解析。

Run from backend/:
  .venv/bin/python -m pytest tests/test_health_metrics.py -v
"""

from __future__ import annotations

import json
import unittest

from tests._helpers import TempApp, reset_env_defaults


class TestReadinessAndMetrics(unittest.TestCase):
    def tearDown(self) -> None:
        reset_env_defaults()

    def test_liveness_and_readiness_ok(self) -> None:
        with TempApp() as ta:
            with ta.client() as c:
                r = c.get("/api/health")
                self.assertEqual(r.status_code, 200)
                self.assertEqual(r.json()["status"], "ok")
                r = c.get("/api/ready")
                self.assertEqual(r.status_code, 200, r.text)
                body = r.json()
                self.assertEqual(body["status"], "ready")
                self.assertTrue(body["checks"]["database_connected"])
                self.assertTrue(body["checks"]["schema_up_to_date"])

    def test_readiness_fails_when_database_down(self) -> None:
        """验收：进程存活但数据库失效 → readiness 503，liveness 仍 200。"""
        with TempApp() as ta:
            # 模拟数据库失效：dispose 连接池并指向不可达库
            ta.engine.dispose()
            ta._dbmod.engine = None  # type: ignore[attr-defined]
            from sqlalchemy import create_engine

            dead = create_engine("sqlite:///./nonexistent-readonly/dead.db")
            ta._dbmod.engine = dead

            with ta.client() as c:
                r = c.get("/api/health")
                self.assertEqual(r.status_code, 200, "liveness 不依赖数据库")
                r = c.get("/api/ready")
                self.assertEqual(r.status_code, 503, r.text)
                body = r.json()
                self.assertEqual(body["status"], "not_ready")
                self.assertFalse(body["checks"]["database_connected"])
            dead.dispose()

    def test_readiness_fails_when_schema_behind(self) -> None:
        """库内 alembic 版本落后于代码 head → readiness 503。"""
        with TempApp() as ta:
            from sqlalchemy import text

            # TempApp 是 create_all 直建库（无 alembic_version）；模拟已接入迁移的库落后
            with ta.engine.begin() as conn:
                conn.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
                conn.execute(text("INSERT INTO alembic_version VALUES ('000000000000')"))
            with ta.client() as c:
                r = c.get("/api/ready")
                self.assertEqual(r.status_code, 503, r.text)
                body = r.json()
                self.assertFalse(body["checks"]["schema_up_to_date"])

    def test_metrics_super_admin_only(self) -> None:
        with TempApp() as ta:
            with ta.client() as c:
                r = c.get("/api/metrics")
                self.assertEqual(r.status_code, 401)
            issuer = ta.login("issuer", "issuer123")
            with ta.client() as c:
                r = c.get("/api/metrics", headers=ta.bearer(issuer))
                self.assertEqual(r.status_code, 403, "发券管理员不可读指标")
            admin = ta.login("admin", "admin123")
            with ta.client() as c:
                r = c.get("/api/metrics", headers=ta.bearer(admin))
                self.assertEqual(r.status_code, 200, r.text)
                body = r.json()
                for key in (
                    "requests_total",
                    "errors_5xx_total",
                    "latency_buckets",
                    "redeem_results",
                    "outbox_backlog",
                    "last_backup",
                ):
                    self.assertIn(key, body)
                # 快照不含任何敏感内容（凭据/完整码/卡号）
                text = json.dumps(body, ensure_ascii=False)
                self.assertNotIn("youth123", text)
                self.assertNotIn("admin123", text)

    def test_redeem_results_tracked_in_metrics(self) -> None:
        """核销成功与失败进入指标分布（T22 条款 2）。"""
        with TempApp() as ta:
            merchant = ta.login("merchant1", "merchant123")
            admin = ta.login("admin", "admin123")
            with ta.session() as db:
                from app.models.entities import Account, CouponInstance, CouponStatus

                y = db.query(Account).filter(Account.username == "youth1").one()
                c1 = (
                    db.query(CouponInstance)
                    .filter(CouponInstance.user_id == y.id, CouponInstance.status == CouponStatus.unused)
                    .first()
                )
                coupon_id = c1.id
            with ta.client() as c:
                code = _live_code(ta, coupon_id)
                # 核销成功
                r = c.post(
                    "/api/coupons/redeem",
                    headers=ta.bearer(merchant),
                    json={"code": code},
                )
                self.assertEqual(r.status_code, 200, r.text)
                # 短窗内重放同一动态码 → already_used 失败
                r = c.post(
                    "/api/coupons/redeem",
                    headers=ta.bearer(merchant),
                    json={"code": code},
                )
                self.assertEqual(r.status_code, 400, r.text)
                # 无效动态码失败
                r = c.post(
                    "/api/coupons/redeem",
                    headers=ta.bearer(merchant),
                    json={"code": "LIVE-NOPE-1234567890"},
                )
                self.assertEqual(r.status_code in (400, 404), True)
            with ta.client() as c:
                r = c.get("/api/metrics", headers=ta.bearer(admin))
                dist = r.json()["redeem_results"]
            self.assertGreaterEqual(dist.get("success:redeemed", 0), 1)
            self.assertGreaterEqual(dist.get("failed:already_used", 0), 1)
            self.assertGreaterEqual(dist.get("failed:invalid_live_code", 0), 1)


def _live_code(ta: TempApp, coupon_id: str) -> str:
    youth = ta.login("youth1", "youth123")
    with ta.client() as c:
        r = c.get(f"/api/coupons/instances/{coupon_id}/live-code", headers=ta.bearer(youth))
        assert r.status_code == 200, r.text
        return r.json()["live_code"]


class TestBackupStatus(unittest.TestCase):
    def test_last_backup_status_parsing(self) -> None:
        import tempfile
        from pathlib import Path

        from app.services.metrics import last_backup_status

        with tempfile.TemporaryDirectory() as td:
            # 从未备份
            r = last_backup_status(td)
            self.assertIsNone(r["ok"])
            # 成功
            p = Path(td) / "last-backup-status.json"
            p.write_text(json.dumps({"ok": True, "at": "2026-09-06T03:00:00+08:00", "tables": 21}))
            r = last_backup_status(td)
            self.assertTrue(r["ok"])
            self.assertEqual(r["tables"], 21) if "tables" in r else None
            # 失败
            p.write_text(json.dumps({"ok": False, "at": "2026-09-07T03:00:00+08:00", "error": "mysqldump 失败"}))
            r = last_backup_status(td)
            self.assertFalse(r["ok"])
            self.assertEqual(r["error"], "mysqldump 失败")
            # 损坏文件
            p.write_text("not json")
            r = last_backup_status(td)
            self.assertIsNone(r["ok"])
            self.assertEqual(r["note"], "unreadable backup status file")


if __name__ == "__main__":
    unittest.main()
