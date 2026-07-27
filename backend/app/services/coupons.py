from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.entities import CouponInstance, CouponStatus


def expire_stale_coupons(db: Session, *, limit: int = 5000) -> int:
    """Mark unused coupons past expires_at as expired. Returns count updated."""
    now = datetime.now(timezone.utc)
    rows = (
        db.query(CouponInstance)
        .filter(CouponInstance.status == CouponStatus.unused)
        .limit(limit)
        .all()
    )
    n = 0
    for c in rows:
        exp = c.expires_at
        if exp is None:
            continue
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if exp < now:
            c.status = CouponStatus.expired
            n += 1
    if n:
        db.commit()
    return n
