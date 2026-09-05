"""T20：MySQL 8 双连接并发回归（真实 REPEATABLE READ 隔离级别）。

覆盖计划验收：余额与账本、首次开户、双核销、作废竞争、验证码消费、
会话版本原子性、大小写唯一性、Decimal 精度与临界过期。

运行方式：
  set MYSQL_TEST_URL=mysql+pymysql://root@127.0.0.1:33307   # 不含库名
  python -m pytest tests/test_mysql_concurrency.py -v

未设置 MYSQL_TEST_URL 且无法自动供给 mysqld 时整组跳过。
本文件只使用临时实例/专用数据库，绝不连接业务库。
"""

from __future__ import annotations

import threading
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from tests._mysql_fixture import MySQLCaseEnv, get_base_url
from tests._helpers import reset_env_defaults  # noqa: F401  保证 sys.path 已注入

import pytest


def _base_url() -> str:
    return get_base_url()


@pytest.fixture()
def my():
    try:
        env = MySQLCaseEnv(_base_url())
    except Exception as exc:  # noqa: BLE001 — 供给失败按文档 skip，不作为用例错误
        pytest.skip(f"MySQL 环境不可用：{exc.__class__.__name__}: {exc}")
    yield env
    env.close()


def _seed_store(env: MySQLCaseEnv, *, coupon_expires_delta: timedelta | None = None) -> dict:
    """最小业务数据：门店 + 商家账号 + 用户 + 可核销券。返回关键对象 id 与永久码。"""
    import secrets
    import string

    from app.models.entities import (
        Account,
        CouponInstance,
        CouponStatus,
        CouponTemplate,
        Merchant,
        Role,
        UserProfile,
        VerifyStatus,
        utcnow,
    )

    suffix = secrets.token_hex(4)
    with env.session() as db:
        merchant = Merchant(
            name=f"测试门店-{suffix}", contact_name="测", contact_phone="13800000000"
        )
        db.add(merchant)
        db.flush()
        m_acc = Account(
            username=f"m_{suffix}",
            password_hash="x",
            role=Role.merchant,
            display_name="商家",
            merchant_id=merchant.id,
        )
        admin = Account(
            username=f"admin_{suffix}", password_hash="x", role=Role.super_admin
        )
        user = Account(
            username=f"u_{suffix}", password_hash="x", role=Role.user, display_name="青年"
        )
        db.add_all([m_acc, admin, user])
        db.flush()
        db.add(
            UserProfile(account_id=user.id, real_name="青年", verify_status=VerifyStatus.approved)
        )
        template = CouponTemplate(
            name=f"模板-{suffix}",
            merchant_id=merchant.id,
            valid_days=30,
            cost_points=Decimal("2.00"),
            is_active=True,
        )
        db.add(template)
        db.flush()
        now = datetime.now(timezone.utc)
        alphabet = string.ascii_uppercase + string.digits
        code = "".join(secrets.choice(alphabet) for _ in range(10))
        expires = now + (coupon_expires_delta or timedelta(days=30))
        coupon = CouponInstance(
            code=code,
            user_id=user.id,
            template_id=template.id,
            merchant_id=merchant.id,
            status=CouponStatus.unused,
            issued_by=admin.id,
            issued_at=now,
            expires_at=expires,
        )
        db.add(coupon)
        db.commit()
        return {
            "merchant_id": merchant.id,
            "merchant_account_id": m_acc.id,
            "admin_id": admin.id,
            "user_id": user.id,
            "template_id": template.id,
            "coupon_id": coupon.id,
            "coupon_code": code,
        }


def _load(env: MySQLCaseEnv, model, entity_id: str):
    with env.session() as db:
        return db.get(model, entity_id)


class TestMySQLConcurrency:
    def tearDown(self) -> None:
        reset_env_defaults()

    # ---- F03 / 首次开户 ----
    def test_first_account_race_single_row(self, my) -> None:
        """两独立连接并发首次开户：只落一条账户、两笔变更、余额正确、无 500。"""
        from app.models.entities import PointAccount, PointLedger
        from app.services.points import apply_points

        data = _seed_store(my)
        uid = data["user_id"]
        errors: list[Exception] = []
        barrier = threading.Barrier(2)

        def grant(amount: str) -> None:
            db = my.Session()
            try:
                barrier.wait(timeout=10)
                apply_points(db, user_id=uid, change=amount, reason="并发开户")
                db.commit()
            except Exception as exc:  # noqa: BLE001
                db.rollback()
                errors.append(exc)
            finally:
                db.close()

        threads = [
            threading.Thread(target=grant, args=("2.50",)),
            threading.Thread(target=grant, args=("1.25",)),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=60)

        assert errors == [], f"并发开户出现失败: {errors}"
        with my.session() as db:
            accounts = db.query(PointAccount).filter(PointAccount.user_id == uid).all()
            assert len(accounts) == 1
            rows = db.query(PointLedger).filter(PointLedger.user_id == uid).all()
            assert len(rows) == 2
            assert sum(Decimal(r.change) for r in rows) == Decimal("3.75")
            assert accounts[0].balance == Decimal("3.75")
            # MySQL created_at 为秒精度：同一秒内的两笔账本排序不稳定，
            # 因此断言与顺序无关——{change, balance_after} 必须匹配两种
            # 串行化之一，且最大 balance_after 等于最终余额（F03 不变量）
            pairs = {(Decimal(r.change), Decimal(r.balance_after)) for r in rows}
            valid_orders = {
                frozenset({(Decimal("2.50"), Decimal("2.50")), (Decimal("1.25"), Decimal("3.75"))}),
                frozenset({(Decimal("1.25"), Decimal("1.25")), (Decimal("2.50"), Decimal("3.75"))}),
            }
            assert frozenset(pairs) in valid_orders, pairs
            assert max(Decimal(r.balance_after) for r in rows) == Decimal("3.75")

    # ---- 双核销 / 作废竞争 ----
    def test_double_redeem_race_single_winner(self, my) -> None:
        from fastapi import HTTPException

        from app.api.coupons import redeem
        from app.models.entities import Account, RedemptionLog
        from app.schemas.coupon import RedeemIn
        from app.services.live_code import create_live_code

        data = _seed_store(my)
        user_id = _load(my, Account, data["user_id"]).id
        live, _, _ = create_live_code(coupon_id=data["coupon_id"], user_id=user_id)
        results: list[str] = []
        barrier = threading.Barrier(2)

        def do_redeem() -> None:
            db = my.Session()
            try:
                acc = db.get(Account, data["merchant_account_id"])
                barrier.wait(timeout=10)
                out = redeem(body=RedeemIn(code=live), db=db, account=acc)
                results.append(out.coupon.status.value)
            except HTTPException as exc:
                results.append(f"rejected:{exc.status_code}")
            finally:
                db.close()

        threads = [threading.Thread(target=do_redeem), threading.Thread(target=do_redeem)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=60)

        success = [r for r in results if r == "used"]
        assert len(success) == 1, f"双核销必须只有一个成功: {results}"
        with my.session() as db:
            logs = (
                db.query(RedemptionLog)
                .filter(RedemptionLog.coupon_id == data["coupon_id"], RedemptionLog.result == "success")
                .count()
            )
            assert logs == 1

    def test_void_vs_redeem_race_single_winner(self, my) -> None:
        from fastapi import HTTPException

        from app.api.coupons import redeem, void_coupon
        from app.models.entities import Account, CouponInstance, CouponStatus
        from app.schemas.coupon import RedeemIn, VoidCouponIn
        from app.services.live_code import create_live_code

        data = _seed_store(my)
        user = _load(my, Account, data["user_id"])
        live, _, _ = create_live_code(coupon_id=data["coupon_id"], user_id=user.id)
        results: list[str] = []
        barrier = threading.Barrier(2)

        def do_redeem() -> None:
            db = my.Session()
            try:
                acc = db.get(Account, data["merchant_account_id"])
                barrier.wait(timeout=10)
                redeem(body=RedeemIn(code=live), db=db, account=acc)
                results.append("redeem:200")
            except HTTPException:
                db.rollback()
                results.append("redeem:400")
            finally:
                db.close()

        def do_void() -> None:
            db = my.Session()
            try:
                admin = db.get(Account, data["admin_id"])
                barrier.wait(timeout=10)
                void_coupon(
                    coupon_id=data["coupon_id"],
                    body=VoidCouponIn(reason="竞争作废"),
                    db=db,
                    admin=admin,
                )
                results.append("void:200")
            except HTTPException:
                db.rollback()
                results.append("void:400")
            finally:
                db.close()

        threads = [threading.Thread(target=do_redeem), threading.Thread(target=do_void)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=60)

        final = _load(my, CouponInstance, data["coupon_id"])
        if "redeem:200" in results:
            assert "void:400" in results, results
            assert final.status == CouponStatus.used
        elif "void:200" in results:
            assert "redeem:400" in results, results
            assert final.status == CouponStatus.void
        else:
            pytest.fail(f"两方都失败: {results}")

    def test_redeem_after_stale_read_keeps_used(self, my) -> None:
        """F01 复现路径：旧会话读过 unused，他方成功核销，旧会话随后作废/过期。

        终态必须保持 used，成功流水唯一，旧会话的作废请求被拒绝且不覆盖状态。
        """
        from datetime import timedelta

        from fastapi import HTTPException

        from app.api.coupons import void_coupon
        from app.models.entities import Account, CouponInstance, CouponStatus, RedemptionLog
        from app.schemas.coupon import VoidCouponIn

        data = _seed_store(my, coupon_expires_delta=timedelta(seconds=30))
        stale = my.Session()  # 会话 A：读取券并保持事务打开
        try:
            stale_coupon = stale.get(CouponInstance, data["coupon_id"])
            assert stale_coupon.status == CouponStatus.unused

            # 会话 B：真实核销（模拟业务时钟仍在有效期内）
            from app.schemas.coupon import RedeemIn
            from app.api.coupons import redeem
            from app.services.live_code import create_live_code

            user = _load(my, Account, data["user_id"])
            live, _, _ = create_live_code(coupon_id=data["coupon_id"], user_id=user.id)
            with my.session() as db:
                acc = db.get(Account, data["merchant_account_id"])
                out = redeem(body=RedeemIn(code=live), db=db, account=acc)
                assert out.coupon.status == "used"

            # A 的业务时钟推进：把 A 视角中的有效期改为已过（不影响数据库真实值），
            # 使 A 的过期转换判断成立；随后 A 调用真实作废接口
            from datetime import timedelta as _td

            stale_coupon.expires_at = datetime.now(timezone.utc) - _td(seconds=1)
            admin = stale.get(Account, data["admin_id"])
            with pytest.raises(HTTPException):
                void_coupon(
                    coupon_id=data["coupon_id"],
                    body=VoidCouponIn(reason="旧会话过期后作废"),
                    db=stale,
                    admin=admin,
                )
            stale.rollback()

            fresh = _load(my, CouponInstance, data["coupon_id"])
            assert fresh.status == CouponStatus.used, f"终态被覆盖: {fresh.status}"
            with my.session() as db:
                success_logs = (
                    db.query(RedemptionLog)
                    .filter(
                        RedemptionLog.coupon_id == data["coupon_id"],
                        RedemptionLog.result == "success",
                    )
                    .count()
                )
                assert success_logs == 1
        finally:
            stale.close()

    # ---- 验证码 ----
    def test_concurrent_consume_single_winner_mysql(self, my) -> None:
        """真实并发：两个连接同时消费同一验证码，只有一个成功。"""
        from fastapi import HTTPException

        from app.models.entities import EmailCode, EmailCodePurpose, utcnow
        from app.services.mail import consume_email_code

        with my.session() as db:
            db.add(
                EmailCode(
                    email="race@example.com",
                    code="123456",
                    purpose=EmailCodePurpose.register,
                    expires_at=utcnow() + timedelta(minutes=10),
                )
            )
            db.commit()
        winners: list[str] = []
        barrier = threading.Barrier(2)

        def consume() -> None:
            db = my.Session()
            try:
                barrier.wait(timeout=10)
                consume_email_code(
                    db, email="race@example.com", code="123456", purpose=EmailCodePurpose.register
                )
                db.commit()
                winners.append("ok")
            except HTTPException:
                db.rollback()
            finally:
                db.close()

        threads = [threading.Thread(target=consume), threading.Thread(target=consume)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=60)
        assert winners == ["ok"], f"并发消费应只有一个成功: {winners}"

    def test_locked_code_cannot_be_consumed(self, my) -> None:
        """F02 复现路径：读取时 attempts=4，锁定前他人把计数推到 5，正确码必须被拒。"""
        from fastapi import HTTPException

        from app.models.entities import EmailCode, EmailCodePurpose, utcnow
        from app.services.mail import consume_email_code

        with my.session() as db:
            row = EmailCode(
                email="lock@example.com",
                code="654321",
                purpose=EmailCodePurpose.register,
                expires_at=utcnow() + timedelta(minutes=10),
                attempts=4,
            )
            db.add(row)
            db.commit()
            row_id = row.id

        sA = my.Session()
        try:
            seen = sA.query(EmailCode).filter(EmailCode.id == row_id).one()
            assert seen.attempts == 4
            # 会话 B：把错误次数推到上限并提交
            with my.session() as db:
                db.query(EmailCode).filter(EmailCode.id == row_id).update(
                    {EmailCode.attempts: 5}, synchronize_session=False
                )
                db.commit()
            # 会话 A：在自身快照里 attempts 仍是 4，提交正确码
            with pytest.raises(HTTPException) as ctx:
                consume_email_code(
                    sA, email="lock@example.com", code="654321", purpose=EmailCodePurpose.register
                )
            sA.rollback()
            assert "次数过多" in ctx.value.detail, ctx.value.detail
            with my.session() as db:
                fresh = db.get(EmailCode, row_id)
                assert fresh.attempts == 5
                assert fresh.used_at is None
        finally:
            sA.close()

    # ---- 会话版本 ----
    def test_concurrent_password_reset_versions_add_up(self, my) -> None:
        """两管理员并发重置同一账号：session_version 必须净增 2。"""
        import secrets

        from app.api.auth import reset_password
        from app.models.entities import Account, Role
        from app.schemas.auth import ResetPasswordIn

        data = _seed_store(my)
        errors: list[Exception] = []
        barrier = threading.Barrier(2)

        def do_reset() -> None:
            db = my.Session()
            try:
                admin = db.get(Account, data["admin_id"])
                barrier.wait(timeout=10)
                reset_password(
                    account_id=data["user_id"],
                    body=ResetPasswordIn(new_password=f"NewPass{secrets.token_hex(4)}"),
                    db=db,
                    admin=admin,
                )
            except Exception as exc:  # noqa: BLE001
                db.rollback()
                errors.append(exc)
            finally:
                db.close()

        threads = [threading.Thread(target=do_reset), threading.Thread(target=do_reset)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=60)
        assert errors == []
        with my.session() as db:
            user = db.get(Account, data["user_id"])
            assert user.session_version == 2, f"并发重置丢版本: {user.session_version}"

    # ---- MySQL 平台特性 ----
    def test_username_unique_case_insensitive(self, my) -> None:
        """MySQL 大小写不敏感排序规则下用户名唯一约束生效。"""
        import pytest as _pytest
        from sqlalchemy.exc import IntegrityError

        from app.models.entities import Account, Role

        suffix = "caseu"
        with my.session() as db:
            db.add(Account(username=f"Alex_{suffix}", password_hash="x", role=Role.user))
            db.commit()
        with my.session() as db:
            db.add(Account(username=f"alex_{suffix}", password_hash="x", role=Role.user))
            with _pytest.raises(IntegrityError):
                db.flush()

    def test_decimal_precision_two_places(self, my) -> None:
        from app.models.entities import PointAccount
        from app.services.points import apply_points

        data = _seed_store(my)
        uid = data["user_id"]
        with my.session() as db:
            acc = apply_points(db, user_id=uid, change="0.005", reason="四舍五入")
            db.commit()
            db.refresh(acc)
            assert acc.balance == Decimal("0.01")
            apply_points(db, user_id=uid, change="10.555", reason="再入账")
            db.commit()
            db.refresh(acc)
            assert acc.balance == Decimal("10.57")

    def test_boundary_expiry_redeem_rejected_mysql(self, my) -> None:
        """临界过期（expires_at 已过）核销拒绝，原因 expired，券状态转为 expired。"""
        from datetime import timedelta

        from fastapi import HTTPException

        from app.api.coupons import redeem
        from app.models.entities import Account, CouponInstance, CouponStatus, RedemptionLog
        from app.schemas.coupon import RedeemIn
        from app.services.live_code import create_live_code

        data = _seed_store(my, coupon_expires_delta=timedelta(seconds=-1))
        user = _load(my, Account, data["user_id"])
        live, _, _ = create_live_code(coupon_id=data["coupon_id"], user_id=user.id)
        with my.session() as db:
            acc = db.get(Account, data["merchant_account_id"])
            with pytest.raises(HTTPException) as ctx:
                redeem(body=RedeemIn(code=live), db=db, account=acc)
            assert "过期" in ctx.value.detail
        with my.session() as db:
            final = db.get(CouponInstance, data["coupon_id"])
            assert final.status == CouponStatus.expired
            log = (
                db.query(RedemptionLog)
                .filter(RedemptionLog.coupon_id == data["coupon_id"], RedemptionLog.result == "failed")
                .order_by(RedemptionLog.created_at.desc())
                .first()
            )
            assert log is not None and log.reason == "expired"
