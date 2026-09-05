from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy.exc import IntegrityError
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
    # 首次开户用 savepoint 包裹：并发请求同时开户时，唯一约束竞争中失败方
    # 回滚到 savepoint 后用锁定读重查。MySQL REPEATABLE READ 下普通 SELECT
    # 走旧快照、看不到已提交的胜者，必须用当前读（FOR UPDATE）；SQLite 忽略
    # with_for_update，行为不变。
    try:
        with db.begin_nested():
            acc = PointAccount(user_id=user_id, balance=ZERO)
            db.add(acc)
            db.flush()
    except IntegrityError:
        acc = (
            db.query(PointAccount)
            .filter(PointAccount.user_id == user_id)
            .with_for_update()
            .first()
        )
        if acc is None:
            raise
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
      多 worker 同时入账/扣减不会互相覆盖（避免读改写丢更新）；
    - UPDATE 持有行锁直到事务提交，随后在同一事务内重读该行，
      读到的必然是本次变更后的串行余额，账本 balance_after 与之严格一致
      （MySQL REPEATABLE READ 下本事务自己的写入对自己可见；SQLite 写锁串行）。
    """
    change = quantize_hours(change)
    if change == ZERO:
        raise ValueError("变动时长不能为 0")
    acc = get_or_create_account(db, user_id)

    stmt = db.query(PointAccount).filter(PointAccount.user_id == user_id)
    if change < ZERO:
        stmt = stmt.filter(PointAccount.balance >= -change)
    updated = stmt.update(
        {PointAccount.balance: PointAccount.balance + change, PointAccount.updated_at: utcnow()},
        synchronize_session=False,
    )
    if not updated:
        raise ValueError("时长余额不足")
    db.refresh(acc)
    db.add(
        PointLedger(
            user_id=user_id,
            change=change,
            balance_after=quantize_hours(acc.balance),
            reason=reason,
            operator_id=operator_id,
            ref_type=ref_type,
            ref_id=ref_id,
        )
    )
    return acc
