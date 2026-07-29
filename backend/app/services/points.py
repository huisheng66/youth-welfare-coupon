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
    change = quantize_hours(change)
    if change == ZERO:
        raise ValueError("变动时长不能为 0")
    acc = get_or_create_account(db, user_id)
    current = quantize_hours(acc.balance)
    new_balance = quantize_hours(current + change)
    if new_balance < ZERO:
        raise ValueError("时长余额不足")
    acc.balance = new_balance
    acc.updated_at = utcnow()
    db.add(
        PointLedger(
            user_id=user_id,
            change=change,
            balance_after=new_balance,
            reason=reason,
            operator_id=operator_id,
            ref_type=ref_type,
            ref_id=ref_id,
        )
    )
    return acc
