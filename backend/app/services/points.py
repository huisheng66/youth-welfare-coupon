from sqlalchemy.orm import Session

from app.models.entities import PointAccount, PointLedger, utcnow


def get_or_create_account(db: Session, user_id: str) -> PointAccount:
    acc = db.query(PointAccount).filter(PointAccount.user_id == user_id).first()
    if acc:
        return acc
    acc = PointAccount(user_id=user_id, balance=0)
    db.add(acc)
    db.flush()
    return acc


def apply_points(
    db: Session,
    *,
    user_id: str,
    change: int,
    reason: str,
    operator_id: str | None = None,
    ref_type: str = "",
    ref_id: str = "",
) -> PointAccount:
    acc = get_or_create_account(db, user_id)
    new_balance = acc.balance + change
    if new_balance < 0:
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
