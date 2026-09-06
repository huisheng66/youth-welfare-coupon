"""T13 写操作幂等测试：重放 / 冲突 / 范围隔离 / 失败不留痕 / 导入重放 / 保留清理。

契约：同 key 同请求重放原结果；同 key 不同请求 409；键按 操作者+动作 隔离；
业务失败（4xx）不留幂等记录；不带 key 行为不变；记录默认保留 7 天。

Run from backend/:
  .venv/bin/python -m pytest tests/test_idempotency.py -v
"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.models.entities import (
    Account,
    CouponInstance,
    CouponTemplate,
    IdempotencyRecord,
    PointAccount,
)
from tests._helpers import TempApp, reset_env_defaults

KEY = "idem-test-key-001"


def _account_id(ta: TempApp, username: str) -> str:
    with ta.session() as db:
        return db.query(Account).filter(Account.username == username).one().id


def _template_id(ta: TempApp, name: str) -> str:
    with ta.session() as db:
        return db.query(CouponTemplate).filter(CouponTemplate.name == name).one().id


def _coupon_count(ta: TempApp, username: str) -> int:
    with ta.session() as db:
        acc = db.query(Account).filter(Account.username == username).one()
        return db.query(CouponInstance).filter(CouponInstance.user_id == acc.id).count()


def _balance(ta: TempApp, username: str) -> Decimal:
    with ta.session() as db:
        acc = db.query(Account).filter(Account.username == username).one()
        pa = db.query(PointAccount).filter(PointAccount.user_id == acc.id).one()
        return Decimal(pa.balance)


def _idem_records(ta: TempApp, action: str | None = None) -> list[IdempotencyRecord]:
    with ta.session() as db:
        q = db.query(IdempotencyRecord)
        if action:
            q = q.filter(IdempotencyRecord.action == action)
        return q.all()


class TestIdempotency(unittest.TestCase):
    def tearDown(self) -> None:
        reset_env_defaults()

    # ---- 同 key 同请求：重放原结果，不重复执行 ----
    def test_issue_replays_same_result_without_duplicating(self) -> None:
        with TempApp() as ta:
            admin = ta.login("admin", "admin123")
            yid = _account_id(ta, "youth1")
            tmpl = _template_id(ta, "餐饮立减券")
            before = _coupon_count(ta, "youth1")
            payload = {"user_id": yid, "template_id": tmpl, "quantity": 2}
            with ta.client() as c:
                r1 = c.post(
                    "/api/coupons/issue",
                    headers={**ta.bearer(admin), "Idempotency-Key": KEY},
                    json=payload,
                )
                self.assertEqual(r1.status_code, 200, r1.text)
                r2 = c.post(
                    "/api/coupons/issue",
                    headers={**ta.bearer(admin), "Idempotency-Key": KEY},
                    json=payload,
                )
                self.assertEqual(r2.status_code, 200, r2.text)
            ids1 = [c["id"] for c in r1.json()]
            ids2 = [c["id"] for c in r2.json()]
            self.assertEqual(ids1, ids2, "同 key 重放必须返回原结果")
            self.assertEqual(_coupon_count(ta, "youth1") - before, 2, "重放不得重复发券")
            self.assertEqual(len(_idem_records(ta, "coupon.issue")), 1)

    def test_without_key_behavior_unchanged(self) -> None:
        with TempApp() as ta:
            admin = ta.login("admin", "admin123")
            yid = _account_id(ta, "youth1")
            tmpl = _template_id(ta, "餐饮立减券")
            before = _coupon_count(ta, "youth1")
            payload = {"user_id": yid, "template_id": tmpl, "quantity": 1}
            with ta.client() as c:
                for _ in range(2):
                    r = c.post("/api/coupons/issue", headers=ta.bearer(admin), json=payload)
                    self.assertEqual(r.status_code, 200, r.text)
            self.assertEqual(_coupon_count(ta, "youth1") - before, 2, "不带 key 保持原有逐次执行")
            self.assertEqual(_idem_records(ta), [])

    # ---- 同 key 不同请求：409 冲突 ----
    def test_same_key_different_payload_conflicts(self) -> None:
        with TempApp() as ta:
            admin = ta.login("admin", "admin123")
            yid = _account_id(ta, "youth1")
            tmpl = _template_id(ta, "餐饮立减券")
            with ta.client() as c:
                r1 = c.post(
                    "/api/coupons/issue",
                    headers={**ta.bearer(admin), "Idempotency-Key": KEY},
                    json={"user_id": yid, "template_id": tmpl, "quantity": 1},
                )
                self.assertEqual(r1.status_code, 200, r1.text)
                r2 = c.post(
                    "/api/coupons/issue",
                    headers={**ta.bearer(admin), "Idempotency-Key": KEY},
                    json={"user_id": yid, "template_id": tmpl, "quantity": 5},
                )
                self.assertEqual(r2.status_code, 409, r2.text)
                self.assertIn("不同的请求内容", r2.json()["detail"])

    # ---- 兑换：重放不重复扣时长、不重复出券 ----
    def test_exchange_replay_charges_once(self) -> None:
        with TempApp() as ta:
            user = ta.login("youth1", "youth123")
            tmpl = _template_id(ta, "餐饮立减券")
            before = _coupon_count(ta, "youth1")
            with ta.client() as c:
                r1 = c.post(
                    "/api/points/exchange",
                    headers={**ta.bearer(user), "Idempotency-Key": KEY},
                    json={"template_id": tmpl},
                )
                self.assertEqual(r1.status_code, 200, r1.text)
                r2 = c.post(
                    "/api/points/exchange",
                    headers={**ta.bearer(user), "Idempotency-Key": KEY},
                    json={"template_id": tmpl},
                )
                self.assertEqual(r2.status_code, 200, r2.text)
            self.assertEqual(r1.json()["coupon"]["id"], r2.json()["coupon"]["id"])
            self.assertEqual(_coupon_count(ta, "youth1") - before, 1)
            self.assertEqual(_balance(ta, "youth1"), Decimal("8.00"))

    # ---- 时长调整：重放只入账一次 ----
    def test_grant_replay_grants_once(self) -> None:
        with TempApp() as ta:
            admin = ta.login("admin", "admin123")
            yid = _account_id(ta, "youth1")
            payload = {"user_id": yid, "amount": "3", "reason": "幂等入账"}
            with ta.client() as c:
                r1 = c.post(
                    "/api/points/grant",
                    headers={**ta.bearer(admin), "Idempotency-Key": KEY},
                    json=payload,
                )
                self.assertEqual(r1.status_code, 200, r1.text)
                r2 = c.post(
                    "/api/points/grant",
                    headers={**ta.bearer(admin), "Idempotency-Key": KEY},
                    json=payload,
                )
                self.assertEqual(r2.status_code, 200, r2.text)
            self.assertEqual(r1.json(), r2.json())
            self.assertEqual(_balance(ta, "youth1"), Decimal("13.00"))

    # ---- 键范围：不同操作者、不同动作互不冲突 ----
    def test_key_scoped_by_actor_and_action(self) -> None:
        with TempApp() as ta:
            admin = ta.login("admin", "admin123")
            issuer = ta.login("issuer", "issuer123")
            yid = _account_id(ta, "youth1")
            tmpl = _template_id(ta, "餐饮立减券")
            before = _coupon_count(ta, "youth1")
            with ta.client() as c:
                # 不同操作者使用相同 key：各自执行
                for token in (admin, issuer):
                    r = c.post(
                        "/api/coupons/issue",
                        headers={**ta.bearer(token), "Idempotency-Key": KEY},
                        json={"user_id": yid, "template_id": tmpl, "quantity": 1},
                    )
                    self.assertEqual(r.status_code, 200, r.text)
                # 同一操作者、相同 key、不同动作：不冲突
                r = c.post(
                    "/api/points/grant",
                    headers={**ta.bearer(admin), "Idempotency-Key": KEY},
                    json={"user_id": yid, "amount": "1", "reason": "动作隔离"},
                )
                self.assertEqual(r.status_code, 200, r.text)
            self.assertEqual(_coupon_count(ta, "youth1") - before, 2)
            self.assertEqual(_balance(ta, "youth1"), Decimal("11.00"))

    # ---- 业务失败不留幂等记录：修正后可用同 key 重发 ----
    def test_failed_request_leaves_no_record(self) -> None:
        with TempApp() as ta:
            admin = ta.login("admin", "admin123")
            y2 = _account_id(ta, "youth2")  # 待审核
            y1 = _account_id(ta, "youth1")
            tmpl = _template_id(ta, "餐饮立减券")
            before = _coupon_count(ta, "youth1")
            with ta.client() as c:
                bad = c.post(
                    "/api/coupons/issue",
                    headers={**ta.bearer(admin), "Idempotency-Key": KEY},
                    json={"user_id": y2, "template_id": tmpl, "quantity": 1},
                )
                self.assertEqual(bad.status_code, 400, bad.text)
                self.assertEqual(_idem_records(ta), [], "4xx 业务失败不得留下幂等记录")
                good = c.post(
                    "/api/coupons/issue",
                    headers={**ta.bearer(admin), "Idempotency-Key": KEY},
                    json={"user_id": y1, "template_id": tmpl, "quantity": 1},
                )
                self.assertEqual(good.status_code, 200, good.text)
            self.assertEqual(_coupon_count(ta, "youth1") - before, 1)

    # ---- 名单导入：同 key + 同文件重放不重复入账 ----
    def test_grant_import_replay_same_file(self) -> None:
        with TempApp() as ta:
            admin = ta.login("admin", "admin123")
            data = "用户标识,时长(小时),说明\nyouth1,2.5,社区志愿服务\n".encode("utf-8")
            with ta.client() as c:
                r1 = c.post(
                    "/api/points/grant-import",
                    headers={**ta.bearer(admin), "Idempotency-Key": KEY},
                    files={"file": ("points.csv", data, "application/octet-stream")},
                    data={"reason": "批量导入"},
                )
                self.assertEqual(r1.status_code, 200, r1.text)
                r2 = c.post(
                    "/api/points/grant-import",
                    headers={**ta.bearer(admin), "Idempotency-Key": KEY},
                    files={"file": ("points.csv", data, "application/octet-stream")},
                    data={"reason": "批量导入"},
                )
                self.assertEqual(r2.status_code, 200, r2.text)
            self.assertEqual(r1.json(), r2.json())
            self.assertEqual(_balance(ta, "youth1"), Decimal("12.50"), "重放不得重复入账")
            # 同 key 但文件不同 → 409
            with ta.client() as c:
                r3 = c.post(
                    "/api/points/grant-import",
                    headers={**ta.bearer(admin), "Idempotency-Key": KEY},
                    files={"file": ("points.csv", "用户标识,时长(小时)\nyouth1,9\n".encode("utf-8"), "application/octet-stream")},
                    data={"reason": "批量导入"},
                )
                self.assertEqual(r3.status_code, 409, r3.text)

    # ---- key 校验 ----
    def test_overlong_key_rejected(self) -> None:
        with TempApp() as ta:
            admin = ta.login("admin", "admin123")
            yid = _account_id(ta, "youth1")
            tmpl = _template_id(ta, "餐饮立减券")
            with ta.client() as c:
                r = c.post(
                    "/api/coupons/issue",
                    headers={**ta.bearer(admin), "Idempotency-Key": "x" * 129},
                    json={"user_id": yid, "template_id": tmpl, "quantity": 1},
                )
                self.assertEqual(r.status_code, 400, r.text)
                self.assertIn("Idempotency-Key", r.json()["detail"])

    # ---- 保留期清理 ----
    def test_sweep_removes_expired_records(self) -> None:
        from app.services import idempotency as idem

        with TempApp() as ta:
            admin_id = _account_id(ta, "admin")
            with ta.session() as db:
                old = IdempotencyRecord(
                    key="old-key",
                    actor_id=admin_id,
                    action="coupon.issue",
                    request_hash="x" * 64,
                    result_json="[]",
                    created_at=datetime.now(timezone.utc) - timedelta(days=8),
                )
                fresh = IdempotencyRecord(
                    key="fresh-key",
                    actor_id=admin_id,
                    action="coupon.issue",
                    request_hash="y" * 64,
                    result_json="[]",
                )
                db.add_all([old, fresh])
                db.commit()
                deleted = idem.sweep_expired(db, retention_days=7, interval_seconds=0)
                self.assertEqual(deleted, 1)
                remaining = {r.key for r in db.query(IdempotencyRecord).all()}
                self.assertEqual(remaining, {"fresh-key"})

    # ---- 幂等记录不保存原始请求 ----
    def test_record_stores_only_hash_and_result(self) -> None:
        with TempApp() as ta:
            admin = ta.login("admin", "admin123")
            yid = _account_id(ta, "youth1")
            with ta.client() as c:
                r = c.post(
                    "/api/points/grant",
                    headers={**ta.bearer(admin), "Idempotency-Key": KEY},
                    json={"user_id": yid, "amount": "1", "reason": "敏感说明-不应入记录"},
                )
                self.assertEqual(r.status_code, 200, r.text)
            recs = _idem_records(ta, "points.grant")
            self.assertEqual(len(recs), 1)
            rec = recs[0]
            self.assertEqual(len(rec.request_hash), 64)
            self.assertNotIn("敏感说明", rec.request_hash)
            # 请求体里的自由文本不进入记录；结果关联只含响应内容
            self.assertNotIn("敏感说明", rec.result_json)


if __name__ == "__main__":
    unittest.main()
