"""志愿服务时长账户测试：发分 / 兑换 / 余额不足 / 未核验 / 目录。

Run from backend/:
  .\\.venv\\Scripts\\python.exe -m pytest tests/test_points.py -v
  # 或无 pytest：
  .\\.venv\\Scripts\\python.exe tests/test_points.py
"""

from __future__ import annotations

import secrets
import string
import threading
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi import Request

from app.models.entities import Account, CouponStatus, PointAccount, Role
from tests._helpers import TempApp, reset_env_defaults


def _fake_request() -> Request:
    """直调端点函数用：仅含空 headers 的最小 Request（无幂等键）。"""
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/points/exchange-back",
            "headers": [],
        }
    )


def _seed_coupon(
    ta: TempApp,
    user_id: str,
    *,
    cost: str = "2.00",
    status: CouponStatus = CouponStatus.unused,
) -> str:
    """给指定用户造一张券（独立门店/模板，标价可控），返回券 id。"""
    from app.models.entities import CouponInstance, CouponTemplate, Merchant

    with ta.session() as db:
        merchant = Merchant(name=f"券换时长门店-{secrets.token_hex(4)}")
        db.add(merchant)
        db.flush()
        template = CouponTemplate(
            name=f"券换时长模板-{secrets.token_hex(4)}",
            merchant_id=merchant.id,
            valid_days=30,
            cost_points=Decimal(cost),
            is_active=True,
        )
        db.add(template)
        db.flush()
        alphabet = string.ascii_uppercase + string.digits
        code = "".join(secrets.choice(alphabet) for _ in range(10))
        now = datetime.now(timezone.utc)
        coupon = CouponInstance(
            code=code,
            user_id=user_id,
            template_id=template.id,
            merchant_id=merchant.id,
            status=status,
            issued_by=user_id,
            issued_at=now,
            expires_at=now + timedelta(days=30),
        )
        db.add(coupon)
        db.commit()
        return coupon.id


def _youth1_id(ta: TempApp) -> str:
    with ta.session() as db:
        from app.models.entities import Account

        return db.query(Account).filter(Account.username == "youth1").one().id


def _youth2_id(ta: TempApp) -> str:
    with ta.session() as db:
        from app.models.entities import Account

        return db.query(Account).filter(Account.username == "youth2").one().id


def _exchangeable_template_id(ta: TempApp) -> str:
    """返回一个可兑换模板 id（cost_points>0 且 active）。"""
    with ta.session() as db:
        from app.models.entities import CouponTemplate

        t = (
            db.query(CouponTemplate)
            .filter(CouponTemplate.is_active.is_(True), CouponTemplate.cost_points > 0)
            .order_by(CouponTemplate.cost_points.asc())
            .first()
        )
        assert t is not None, "no exchangeable template seeded"
        return t.id


class TestPoints(unittest.TestCase):
    def tearDown(self) -> None:
        reset_env_defaults()

    # ---- 查看时长 ----
    def test_user_can_view_own_points(self) -> None:
        """youth1 种子余额 10。"""
        with TempApp() as ta:
            token = ta.login("youth1", "youth123")
            with ta.client() as c:
                r = c.get("/api/points/me", headers=ta.bearer(token))
                self.assertEqual(r.status_code, 200, r.text)
                self.assertEqual(Decimal(r.json()["balance"]), Decimal("10.00"))

    def test_user_cannot_view_others_points(self) -> None:
        """普通用户不能访问 /points/users/{id}（仅管理员）。"""
        with TempApp() as ta:
            token = ta.login("youth1", "youth123")
            with ta.client() as c:
                r = c.get(f"/api/points/users/{_youth2_id(ta)}", headers=ta.bearer(token))
                self.assertEqual(r.status_code, 403, r.text)

    # ---- 发分 ----
    def test_admin_can_grant_points(self) -> None:
        with TempApp() as ta:
            admin_token = ta.login("admin", "admin123")
            yid = _youth1_id(ta)
            with ta.client() as c:
                r = c.post(
                    "/api/points/grant",
                    headers=ta.bearer(admin_token),
                    json={"user_id": yid, "amount": "5.5", "reason": "测试发分"},
                )
                self.assertEqual(r.status_code, 200, r.text)
                self.assertEqual(Decimal(r.json()["balance"]), Decimal("15.50"))

    def test_grant_to_unverified_user_fails(self) -> None:
        """youth2 待审核，调整时长应失败。"""
        with TempApp() as ta:
            admin_token = ta.login("admin", "admin123")
            y2 = _youth2_id(ta)
            with ta.client() as c:
                r = c.post(
                    "/api/points/grant",
                    headers=ta.bearer(admin_token),
                    json={"user_id": y2, "amount": "3", "reason": "尝试给待审用户"},
                )
                self.assertEqual(r.status_code, 400, r.text)
                self.assertIn("核验", r.json()["detail"])

    def test_grant_negative_beyond_balance_fails(self) -> None:
        """扣减超过余额应失败（youth1 余额 10，扣 100）。"""
        with TempApp() as ta:
            admin_token = ta.login("admin", "admin123")
            yid = _youth1_id(ta)
            with ta.client() as c:
                r = c.post(
                    "/api/points/grant",
                    headers=ta.bearer(admin_token),
                    json={"user_id": yid, "amount": "-100", "reason": "超额扣减"},
                )
                self.assertEqual(r.status_code, 400, r.text)
                self.assertIn("余额不足", r.json()["detail"])

    def test_grant_zero_is_rejected(self) -> None:
        with TempApp() as ta:
            admin_token = ta.login("admin", "admin123")
            with ta.client() as c:
                response = c.post(
                    "/api/points/grant",
                    headers=ta.bearer(admin_token),
                    json={"user_id": _youth1_id(ta), "amount": "0", "reason": "无效调整"},
                )
                self.assertEqual(response.status_code, 422, response.text)

    # ---- 兑换 ----
    def test_exchange_coupon_success(self) -> None:
        """youth1 用 2 时长兑换餐饮券，余额 10→8。"""
        with TempApp() as ta:
            token = ta.login("youth1", "youth123")
            tmpl_id = _exchangeable_template_id(ta)
            with ta.client() as c:
                r = c.post(
                    "/api/points/exchange",
                    headers=ta.bearer(token),
                    json={"template_id": tmpl_id},
                )
                self.assertEqual(r.status_code, 200, r.text)
                data = r.json()
                self.assertEqual(data["message"], "兑换成功")
                self.assertEqual(Decimal(data["balance"]), Decimal("8.00"))
                self.assertEqual(data["coupon"]["status"], "unused")
                self.assertTrue(data["coupon"]["code"])

    def test_exchange_insufficient_balance_fails(self) -> None:
        """youth2 余额 0，兑换应失败。需先把 youth2 审核通过（兑换前置条件）。"""
        with TempApp() as ta:
            # 先让 youth2 通过核验
            with ta.session() as db:
                from app.models.entities import Account, UserProfile, VerifyStatus

                y2 = db.query(Account).filter(Account.username == "youth2").one()
                db.query(UserProfile).filter(UserProfile.account_id == y2.id).update(
                    {"verify_status": VerifyStatus.approved}
                )
                db.commit()
            token = ta.login("youth2", "youth123")
            tmpl_id = _exchangeable_template_id(ta)
            with ta.client() as c:
                r = c.post(
                    "/api/points/exchange",
                    headers=ta.bearer(token),
                    json={"template_id": tmpl_id},
                )
                self.assertEqual(r.status_code, 400, r.text)
                self.assertIn("余额不足", r.json()["detail"])

    def test_exchange_unverified_user_fails(self) -> None:
        """youth2 待审核，兑换应失败（即使有余额也不会到余额校验步）。"""
        with TempApp() as ta:
            token = ta.login("youth2", "youth123")
            tmpl_id = _exchangeable_template_id(ta)
            with ta.client() as c:
                r = c.post(
                    "/api/points/exchange",
                    headers=ta.bearer(token),
                    json={"template_id": tmpl_id},
                )
                self.assertEqual(r.status_code, 400, r.text)
                self.assertIn("核验", r.json()["detail"])

    # ---- 目录 ----
    def test_catalog_lists_active_exchangeable_templates(self) -> None:
        with TempApp() as ta:
            token = ta.login("youth1", "youth123")
            with ta.client() as c:
                r = c.get("/api/points/catalog", headers=ta.bearer(token))
                self.assertEqual(r.status_code, 200, r.text)
                items = r.json()
                self.assertTrue(items, "catalog should not be empty")
                for it in items:
                    self.assertGreater(float(it["cost_points"]), 0)
                    self.assertTrue(it["is_active"])

    # ---- 流水 ----
    def test_my_ledger_records_grant_and_exchange(self) -> None:
        """发分 + 兑换后，流水应包含对应记录。"""
        with TempApp() as ta:
            admin_token = ta.login("admin", "admin123")
            user_token = ta.login("youth1", "youth123")
            yid = _youth1_id(ta)
            tmpl_id = _exchangeable_template_id(ta)
            with ta.client() as c:
                c.post(
                    "/api/points/grant",
                    headers=ta.bearer(admin_token),
                    json={"user_id": yid, "amount": "5", "reason": "流水测试发分"},
                )
                c.post(
                    "/api/points/exchange",
                    headers=ta.bearer(user_token),
                    json={"template_id": tmpl_id},
                )
                r = c.get("/api/points/me/ledger", headers=ta.bearer(user_token))
                self.assertEqual(r.status_code, 200, r.text)
                reasons = [row["reason"] for row in r.json()["items"]]
                self.assertTrue(any("流水测试发分" in x for x in reasons))
                self.assertTrue(any("兑换优惠券" in x for x in reasons))

    # ---- 并发（原子余额变更）----
    def test_interleaved_sessions_do_not_lose_update(self) -> None:
        """双会话交错：旧读数上的扣减必须基于库内最新余额。

        复现多 worker 竞态：会话 A 读到余额 10 → 会话 B 入账 5（库内变 15）
        → A 基于旧读数扣 2。读改写实现会写回 8（丢更新）；原子条件 UPDATE
        应得到 13。
        """
        with TempApp() as ta:
            from app.services.points import apply_points

            yid = _youth1_id(ta)
            s1 = ta.Session()
            s2 = ta.Session()
            try:
                # 会话 A：读取当前余额（10.00），保持事务未提交
                stale_read = s1.query(PointAccount).filter(PointAccount.user_id == yid).one()
                self.assertEqual(Decimal(stale_read.balance), Decimal("10.00"))

                # 会话 B：并发入账 +5 并提交
                apply_points(s2, user_id=yid, change="5", reason="并发入账", ref_type="grant")
                s2.commit()

                # 会话 A：基于过期读数扣减 -2
                apply_points(s1, user_id=yid, change="-2", reason="并发扣减", ref_type="adjust")
                s1.commit()

                s1.expire_all()
                final = s1.query(PointAccount).filter(PointAccount.user_id == yid).one()
                self.assertEqual(Decimal(final.balance), Decimal("13.00"))
            finally:
                s1.close()
                s2.close()

    def test_interleaved_overdraft_is_rejected(self) -> None:
        """双会话交错：旧读数认为余额充足，库内已被他人扣减 → 条件 UPDATE 拒绝透支。"""
        with TempApp() as ta:
            from app.services.points import apply_points

            yid = _youth1_id(ta)
            s1 = ta.Session()
            s2 = ta.Session()
            try:
                # 会话 A 读到 10.00（未提交事务的快照读）
                stale = s1.query(PointAccount).filter(PointAccount.user_id == yid).one()
                self.assertEqual(Decimal(stale.balance), Decimal("10.00"))

                # 会话 B 把余额扣到 1.00 并提交
                apply_points(s2, user_id=yid, change="-9", reason="并发先扣", ref_type="adjust")
                s2.commit()

                # 会话 A 基于旧读数扣 5：条件 UPDATE 的 WHERE balance >= 5 不满足
                with self.assertRaises(ValueError) as ctx:
                    apply_points(s1, user_id=yid, change="-5", reason="并发透支", ref_type="adjust")
                self.assertIn("余额不足", str(ctx.exception))
                s1.rollback()

                s2.expire_all()
                final = s2.query(PointAccount).filter(PointAccount.user_id == yid).one()
                self.assertEqual(Decimal(final.balance), Decimal("1.00"))
            finally:
                s1.close()
                s2.close()

    # ---- 账本一致性（T03）----
    def test_ledger_balance_after_matches_serialized_balance(self) -> None:
        """10 → 入账 5 → 扣 2：末条账本 balance_after 必须等于最终串行余额 13。"""
        with TempApp() as ta:
            from app.models.entities import PointLedger
            from app.services.points import apply_points

            yid = _youth1_id(ta)
            s1 = ta.Session()
            s2 = ta.Session()
            try:
                s1.query(PointAccount).filter(PointAccount.user_id == yid).one()  # A 读旧值
                apply_points(s2, user_id=yid, change="5", reason="并发入账")
                s2.commit()
                apply_points(s1, user_id=yid, change="-2", reason="并发扣减")
                s1.commit()

                with ta.session() as db:
                    ledgers = (
                        db.query(PointLedger)
                        .filter(PointLedger.user_id == yid)
                        .order_by(PointLedger.created_at.asc(), PointLedger.id.asc())
                        .all()
                    )
                # 每条 balance_after 都等于到该条为止的变更累计
                running = Decimal("0")
                for row in ledgers:
                    running += Decimal(row.change)
                    self.assertEqual(Decimal(row.balance_after), running, f"ledger {row.id}")
                # 最后一条 = 最终余额
                with ta.session() as db:
                    final = db.query(PointAccount).filter(PointAccount.user_id == yid).one()
                self.assertEqual(Decimal(ledgers[-1].balance_after), Decimal(final.balance))
                self.assertEqual(Decimal(final.balance), Decimal("13.00"))
            finally:
                s1.close()
                s2.close()

    def test_exchange_ledger_refs_coupon_instance(self) -> None:
        """兑换账本 ref_id 必须指向实际券实例，而不是模板。"""
        with TempApp() as ta:
            from app.models.entities import PointLedger

            token = ta.login("youth1", "youth123")
            tmpl_id = _exchangeable_template_id(ta)
            with ta.client() as c:
                r = c.post("/api/points/exchange", headers=ta.bearer(token), json={"template_id": tmpl_id})
                self.assertEqual(r.status_code, 200, r.text)
                coupon_id = r.json()["coupon"]["id"]
            with ta.session() as db:
                row = (
                    db.query(PointLedger)
                    .filter(PointLedger.user_id == _youth1_id(ta), PointLedger.ref_type == "exchange")
                    .order_by(PointLedger.created_at.desc())
                    .first()
                )
                self.assertIsNotNone(row)
                self.assertEqual(row.ref_id, coupon_id)

    def test_reconcile_reports_mismatch_without_rewriting(self) -> None:
        """对账输出发现余额与账本之和的不一致账户，且不修改任何数据。"""
        with TempApp() as ta:
            admin_token = ta.login("admin", "admin123")
            yid = _youth1_id(ta)
            # 正常入账后应无差异
            with ta.client() as c:
                r = c.post(
                    "/api/points/grant",
                    headers=ta.bearer(admin_token),
                    json={"user_id": yid, "amount": "3.25", "reason": "对账基线"},
                )
                self.assertEqual(r.status_code, 200, r.text)
                ok = c.get("/api/points/reconcile", headers=ta.bearer(admin_token))
                self.assertEqual(ok.status_code, 200, ok.text)
                self.assertEqual(ok.json()["mismatch_count"], 0)
            # 直接改余额制造差异（模拟历史事故），对账能发现且不回写
            with ta.session() as db:
                acc = db.query(PointAccount).filter(PointAccount.user_id == yid).one()
                acc.balance = Decimal("99.99")
                db.commit()
            with ta.client() as c:
                bad = c.get("/api/points/reconcile", headers=ta.bearer(admin_token))
                body = bad.json()
                self.assertEqual(body["mismatch_count"], 1)
                hit = body["mismatches"][0]
                self.assertEqual(hit["user_id"], yid)
                self.assertEqual(Decimal(str(hit["balance"])), Decimal("99.99"))
                self.assertEqual(Decimal(str(hit["ledger_sum"])), Decimal("13.25"))
                # 对账不改写余额
                with ta.session() as db:
                    acc = db.query(PointAccount).filter(PointAccount.user_id == yid).one()
                self.assertEqual(Decimal(acc.balance), Decimal("99.99"))

    def test_concurrent_first_account_creation_single_row(self) -> None:
        """并发首次开户：唯一约束竞争后只落一条账户且两笔变更都有账本。"""
        with TempApp() as ta:
            from app.core.security import hash_password

            with ta.session() as db:
                newbie = Account(
                    username="points_newbie",
                    password_hash=hash_password("newbie12345"),
                    role=Role.user,
                    display_name="并发开户",
                )
                db.add(newbie)
                db.commit()
                uid = newbie.id

            from app.services.points import apply_points

            s1 = ta.Session()
            s2 = ta.Session()
            errors: list[Exception] = []
            barrier = threading.Barrier(2)

            def grant(session, amount: str) -> None:
                try:
                    barrier.wait(timeout=10)
                    apply_points(session, user_id=uid, change=amount, reason="并发开户入账")
                    session.commit()
                except Exception as exc:  # noqa: BLE001
                    session.rollback()
                    errors.append(exc)

            threads = [
                threading.Thread(target=grant, args=(s1, "2.50")),
                threading.Thread(target=grant, args=(s2, "1.25")),
            ]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=30)
            s1.close()
            s2.close()
            self.assertEqual(errors, [])
            with ta.session() as db:
                from app.models.entities import PointLedger

                self.assertEqual(db.query(PointAccount).filter(PointAccount.user_id == uid).count(), 1)
                rows = db.query(PointLedger).filter(PointLedger.user_id == uid).all()
                self.assertEqual(len(rows), 2)
                total = sum(Decimal(r.change) for r in rows)
                self.assertEqual(total, Decimal("3.75"))
                acc = db.query(PointAccount).filter(PointAccount.user_id == uid).one()
                self.assertEqual(Decimal(acc.balance), Decimal("3.75"))


class TestExchangeBack(unittest.TestCase):
    """券换时长（T24/T24b）：单向流动——仅非时长兑换所得的未使用券可换回
    时长（换回即作废，每张券一次）；兑换所得的券不可换回，杜绝来回环路。"""

    def tearDown(self) -> None:
        reset_env_defaults()

    def _exchange(self, c, token: str, tmpl_id: str):
        return c.post(
            "/api/points/exchange",
            headers=TempApp.bearer(token),
            json={"template_id": tmpl_id},
        )

    def test_exchange_obtained_coupon_cannot_go_back(self) -> None:
        """时长兑换所得的券不能换回时长，且不出现在可换清单；时长换券不受影响。"""
        with TempApp() as ta:
            token = ta.login("youth1", "youth123")
            tmpl_id = _exchangeable_template_id(ta)
            with ta.client() as c:
                r = self._exchange(c, token, tmpl_id)
                self.assertEqual(r.status_code, 200, r.text)
                coupon_id = r.json()["coupon"]["id"]

                # 兑换所得的券不在可换清单中
                ro = c.get("/api/points/exchange-back/options", headers=ta.bearer(token))
                self.assertEqual(ro.status_code, 200, ro.text)
                self.assertNotIn(
                    coupon_id, [it["coupon_id"] for it in ro.json()["items"]]
                )

                # 不能换回时长
                rb = c.post(
                    "/api/points/exchange-back",
                    headers=ta.bearer(token),
                    json={"coupon_id": coupon_id},
                )
                self.assertEqual(rb.status_code, 400, rb.text)
                self.assertIn("时长兑换所得", rb.json()["detail"])

                # 时长换券不受影响：可继续兑换（8 → 8−2）
                r2 = self._exchange(c, token, tmpl_id)
                self.assertEqual(r2.status_code, 200, r2.text)
                self.assertEqual(Decimal(str(r2.json()["balance"])), Decimal("6.00"))

            with ta.session() as db:
                from app.models.entities import CouponInstance

                coupon = db.get(CouponInstance, coupon_id)
                self.assertEqual(coupon.status, CouponStatus.unused)

    def test_exchange_back_non_exchange_coupon_success(self) -> None:
        """非兑换所得（如管理员发放）的未使用券可换回时长：10 → 12，券作废。"""
        with TempApp() as ta:
            token = ta.login("youth1", "youth123")
            yid = _youth1_id(ta)
            cid = _seed_coupon(ta, yid)
            with ta.client() as c:
                # 可换清单包含该券
                ro = c.get("/api/points/exchange-back/options", headers=ta.bearer(token))
                self.assertIn(cid, [it["coupon_id"] for it in ro.json()["items"]])
                rb = c.post(
                    "/api/points/exchange-back",
                    headers=ta.bearer(token),
                    json={"coupon_id": cid},
                )
                self.assertEqual(rb.status_code, 200, rb.text)
                data = rb.json()
                self.assertEqual(data["message"], "换回成功")
                self.assertEqual(Decimal(str(data["balance"])), Decimal("12.00"))
                self.assertEqual(Decimal(str(data["refunded_hours"])), Decimal("2.00"))
                self.assertEqual(data["coupon"]["status"], "void")

            with ta.session() as db:
                from app.models.entities import CouponInstance, PointLedger

                coupon = db.get(CouponInstance, cid)
                self.assertEqual(coupon.status, CouponStatus.void)
                self.assertEqual(coupon.void_reason, "换回志愿服务时长")
                back = (
                    db.query(PointLedger)
                    .filter(PointLedger.user_id == yid, PointLedger.ref_type == "exchange_back")
                    .one()
                )
                self.assertEqual(back.ref_id, cid)

    def test_can_exchange_back_each_of_multiple_coupons(self) -> None:
        """多张非兑换券逐张换回：每张各得一次，互不影响（3 张全换回）。"""
        with TempApp() as ta:
            from app.models.entities import CouponInstance

            token = ta.login("youth1", "youth123")
            yid = _youth1_id(ta)
            cids = [_seed_coupon(ta, yid, cost="1.00") for _ in range(3)]
            with ta.client() as c:
                for cid in cids:
                    rb = c.post(
                        "/api/points/exchange-back",
                        headers=ta.bearer(token),
                        json={"coupon_id": cid},
                    )
                    self.assertEqual(rb.status_code, 200, rb.text)
                # 余额 10 + 3 × 1.00
                r = c.get("/api/points/me", headers=ta.bearer(token))
                self.assertEqual(Decimal(str(r.json()["balance"])), Decimal("13.00"))
            with ta.session() as db:
                statuses = {db.get(CouponInstance, cid).status for cid in cids}
                self.assertEqual(statuses, {CouponStatus.void})

    def test_exchange_back_non_exchange_source_coupon(self) -> None:
        """非兑换来源的未使用券可换回，种子演示券（管理员发放）也在可换清单。"""
        with TempApp() as ta:
            from app.models.entities import CouponInstance, PointLedger

            token = ta.login("youth1", "youth123")
            yid = _youth1_id(ta)
            with ta.session() as db:
                coupon = (
                    db.query(CouponInstance)
                    .filter(
                        CouponInstance.user_id == yid,
                        CouponInstance.status == CouponStatus.unused,
                        ~CouponInstance.id.in_(
                            db.query(PointLedger.ref_id).filter(
                                PointLedger.ref_type == "exchange"
                            )
                        ),
                    )
                    .first()
                )
                assert coupon is not None, "seed demo coupon missing"
                cid = coupon.id
            with ta.client() as c:
                rb = c.post(
                    "/api/points/exchange-back", headers=ta.bearer(token), json={"coupon_id": cid}
                )
                self.assertEqual(rb.status_code, 200, rb.text)
                self.assertEqual(Decimal(str(rb.json()["balance"])), Decimal("12.00"))

    def test_exchange_back_zero_price_rejected(self) -> None:
        """未标价时长（cost_points=0）的券无法折算，拒绝换回。"""
        with TempApp() as ta:
            token = ta.login("youth1", "youth123")
            yid = _youth1_id(ta)
            cid = _seed_coupon(ta, yid, cost="0.00")
            with ta.client() as c:
                rb = c.post(
                    "/api/points/exchange-back", headers=ta.bearer(token), json={"coupon_id": cid}
                )
                self.assertEqual(rb.status_code, 400, rb.text)
                self.assertIn("标价", rb.json()["detail"])

    def test_exchange_back_non_unused_coupon_rejected(self) -> None:
        """已作废/已使用的券不能换回时长。"""
        with TempApp() as ta:
            token = ta.login("youth1", "youth123")
            yid = _youth1_id(ta)
            cid = _seed_coupon(ta, yid, status=CouponStatus.void)
            with ta.client() as c:
                rb = c.post(
                    "/api/points/exchange-back", headers=ta.bearer(token), json={"coupon_id": cid}
                )
                self.assertEqual(rb.status_code, 400, rb.text)
                self.assertIn("未使用", rb.json()["detail"])

    def test_exchange_back_other_users_coupon_rejected(self) -> None:
        """他人的券不可见不可换（404，避免券枚举）。"""
        with TempApp() as ta:
            token = ta.login("youth1", "youth123")
            cid = _seed_coupon(ta, _youth2_id(ta))
            with ta.client() as c:
                rb = c.post(
                    "/api/points/exchange-back", headers=ta.bearer(token), json={"coupon_id": cid}
                )
                self.assertEqual(rb.status_code, 404, rb.text)

    def test_exchange_back_unverified_fails(self) -> None:
        """未核验用户不能券换时长。"""
        with TempApp() as ta:
            token = ta.login("youth2", "youth123")
            cid = _seed_coupon(ta, _youth2_id(ta))
            with ta.client() as c:
                rb = c.post(
                    "/api/points/exchange-back", headers=ta.bearer(token), json={"coupon_id": cid}
                )
                self.assertEqual(rb.status_code, 400, rb.text)
                self.assertIn("核验", rb.json()["detail"])

    def test_exchange_back_refunds_current_template_price(self) -> None:
        """按模板当前标价折算：非兑换券模板标价 2 改 3，换回退 3（10 → 13）。"""
        with TempApp() as ta:
            from app.models.entities import CouponInstance, CouponTemplate

            token = ta.login("youth1", "youth123")
            yid = _youth1_id(ta)
            cid = _seed_coupon(ta, yid, cost="2.00")
            with ta.session() as db:
                coupon = db.get(CouponInstance, cid)
                tmpl_id = coupon.template_id
            with ta.session() as db:
                t = db.get(CouponTemplate, tmpl_id)
                t.cost_points = Decimal("3.00")
                db.commit()
            with ta.client() as c:
                rb = c.post(
                    "/api/points/exchange-back",
                    headers=ta.bearer(token),
                    json={"coupon_id": cid},
                )
                self.assertEqual(rb.status_code, 200, rb.text)
                self.assertEqual(Decimal(str(rb.json()["refunded_hours"])), Decimal("3.00"))
                self.assertEqual(Decimal(str(rb.json()["balance"])), Decimal("13.00"))

    def test_exchange_back_idempotent_replay(self) -> None:
        """同幂等键重试重放原结果：不重复退时长、不重复记账。"""
        with TempApp() as ta:
            from app.models.entities import PointLedger

            token = ta.login("youth1", "youth123")
            yid = _youth1_id(ta)
            cid = _seed_coupon(ta, yid)
            key = "test-exchange-back-once"
            headers = {**ta.bearer(token), "Idempotency-Key": key}
            with ta.client() as c:
                r1 = c.post("/api/points/exchange-back", headers=headers, json={"coupon_id": cid})
                self.assertEqual(r1.status_code, 200, r1.text)
                r2 = c.post("/api/points/exchange-back", headers=headers, json={"coupon_id": cid})
                self.assertEqual(r2.status_code, 200, r2.text)
                self.assertEqual(r1.json(), r2.json())
            with ta.session() as db:
                rows = (
                    db.query(PointLedger)
                    .filter(PointLedger.user_id == yid, PointLedger.ref_type == "exchange_back")
                    .all()
                )
                self.assertEqual(len(rows), 1)
                acc = db.query(PointAccount).filter(PointAccount.user_id == yid).one()
                self.assertEqual(Decimal(acc.balance), Decimal("12.00"))

    def test_options_list_eligible_coupons(self) -> None:
        """可换清单只含本人未使用且模板标价>0 的券，标价 0 的券不出现。"""
        with TempApp() as ta:
            token = ta.login("youth1", "youth123")
            yid = _youth1_id(ta)
            cid_ok = _seed_coupon(ta, yid, cost="2.50")
            _seed_coupon(ta, yid, cost="0.00")
            with ta.client() as c:
                r = c.get("/api/points/exchange-back/options", headers=ta.bearer(token))
                self.assertEqual(r.status_code, 200, r.text)
                data = r.json()
                ids = [it["coupon_id"] for it in data["items"]]
                self.assertIn(cid_ok, ids)
                item = next(it for it in data["items"] if it["coupon_id"] == cid_ok)
                self.assertEqual(Decimal(str(item["refund_hours"])), Decimal("2.50"))

    def test_concurrent_exchange_back_same_coupon_single_winner(self) -> None:
        """并发换回同一张券：条件更新单胜者，时长只退一次。"""
        from fastapi import HTTPException

        from app.api.points import exchange_back
        from app.schemas.points import ExchangeBackIn

        with TempApp() as ta:
            token = ta.login("youth1", "youth123")
            yid = _youth1_id(ta)
            cid = _seed_coupon(ta, yid)
            s1 = ta.Session()
            s2 = ta.Session()
            results: list[str] = []
            barrier = threading.Barrier(2)

            def do_back(session) -> None:
                try:
                    acc = session.get(Account, yid)
                    barrier.wait(timeout=10)
                    exchange_back(
                        body=ExchangeBackIn(coupon_id=cid),
                        request=_fake_request(),
                        db=session,
                        account=acc,
                    )
                    results.append("ok")
                except HTTPException as exc:
                    session.rollback()
                    results.append(f"rejected:{exc.status_code}")
                finally:
                    session.close()

            threads = [
                threading.Thread(target=do_back, args=(s1,)),
                threading.Thread(target=do_back, args=(s2,)),
            ]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=30)
            self.assertEqual(results.count("ok"), 1, results)
            self.assertEqual(results.count("rejected:400"), 1, results)
            with ta.session() as db:
                from app.models.entities import CouponInstance

                self.assertEqual(db.get(CouponInstance, cid).status, CouponStatus.void)
                acc = db.query(PointAccount).filter(PointAccount.user_id == yid).one()
                self.assertEqual(Decimal(acc.balance), Decimal("12.00"))


if __name__ == "__main__":
    unittest.main()
