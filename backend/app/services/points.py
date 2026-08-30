from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy.orm import Session

from app.models.entities import PointAccount, PointLedger, utcnow

TWOPLACES = Decimal("0.01")
ZERO = Decimal("0.00")


def quantize_hours(value) -> Decimal:
    """Normalize hours to 2 decimal places (half-up)."""
    if value is None:
        return ZERO
    if isinstance(value, Decimal):
        d = value
    else:
        d = Decimal(str(value))
    return d.quantize(TWOPLACES, rounding=ROUND_HALF_UP)


def get_or_create_account(db: Session, user_id: str) -> PointAccount:
    acc = db.query(PointAccount).filter(PointAccount.user_id == user_id).first()
    if acc:
        return acc
    acc = PointAccount(user_id=user_id, balance=ZERO)
    db.add(acc)
    db.flush()
    return acc


def apply_points(
    db: Session,
    *,
    user_id: str,
    change,
    reason: str,
    operator_id: str | None = None,
    ref_type: str = "",
    ref_id: str = "",
) -> PointAccount:
    """余额变动唯一入口。用单条条件 UPDATE 原子变更余额：

    - 扣减时 WHERE balance >= -change 由数据库判定，并发下不会透支；
    - SET balance = balance + change 让数据库基于最新值计算，
      多 worker 同时入账/扣减不会互相覆盖（避免读改写丢更新）。
    SQLite/MySQL/Postgres 均支持同一语句内的列表达式。
    """
    change = quantize_hours(change)
    if change == ZERO:
        raise ValueError("变动时长不能为 0")
    acc = get_or_create_account(db, user_id)
    current = quantize_hours(acc.balance)

    stmt = db.query(PointAccount).filter(PointAccount.user_id == user_id)
    if change < ZERO:
        stmt = stmt.filter(PointAccount.balance >= -change)
    updated = stmt.update(
        {PointAccount.balance: PointAccount.balance + change, PointAccount.updated_at: utcnow()},
        synchronize_session=False,
    )
    if not updated:
        raise ValueError("时长余额不足")
    # identity map 里的余额已过期；账本记本次变更后的计算值
    db.expire(acc)
    db.add(
        PointLedger(
            user_id=user_id,
            change=change,
            balance_after=quantize_hours(current + change),
            reason=reason,
            operator_id=operator_id,
            ref_type=ref_type,
            ref_id=ref_id,
        )
    )
    return acc
