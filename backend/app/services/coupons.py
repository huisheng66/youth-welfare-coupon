import time
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.entities import CouponInstance, CouponStatus

# 读取路径扫描节流（monotonic 时间戳）；启动扫描不走节流
_last_scan = 0.0


def expire_stale_coupons(db: Session, *, interval_seconds: float = 0) -> int:
    """Mark all expired unused coupons in one database update.

    interval_seconds > 0 时做进程内节流：距上次扫描不足该间隔则直接跳过，
    避免列表类读接口每次都触发一条 UPDATE。测试与启动扫描传 0 强制执行。
    """
    global _last_scan
    now = time.monotonic()
    if interval_seconds > 0 and (now - _last_scan) < interval_seconds:
        return 0
    _last_scan = now
    updated = (
        db.query(CouponInstance)
        .filter(
            CouponInstance.status == CouponStatus.unused,
            CouponInstance.expires_at <= datetime.now(timezone.utc),
        )
        .update(
            {CouponInstance.status: CouponStatus.expired},
            synchronize_session=False,
        )
    )
    if updated:
        db.commit()
    return int(updated)
