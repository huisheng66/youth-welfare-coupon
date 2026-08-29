from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.entities import CouponInstance, CouponStatus


def expire_stale_coupons(db: Session) -> int:
    """Mark all expired unused coupons in one database update."""
    now = datetime.now(timezone.utc)
    updated = (
        db.query(CouponInstance)
        .filter(
            CouponInstance.status == CouponStatus.unused,
            CouponInstance.expires_at <= now,
        )
        .update(
            {CouponInstance.status: CouponStatus.expired},
            synchronize_session=False,
        )
    )
    if updated:
        db.commit()
    return int(updated)
