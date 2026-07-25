import csv
import io
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import require_roles
from app.models.entities import Account, CouponInstance, CouponStatus, CouponTemplate, Merchant, RedemptionLog, Role

router = APIRouter(prefix="/export", tags=["导出"])


def _csv_response(filename: str, rows: list[list]) -> StreamingResponse:
    buf = io.StringIO()
    # Excel-friendly UTF-8 BOM
    buf.write("\ufeff")
    writer = csv.writer(buf)
    for row in rows:
        writer.writerow(row)
    data = buf.getvalue().encode("utf-8")
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return StreamingResponse(iter([data]), media_type="text/csv; charset=utf-8", headers=headers)


def _fmt(dt: datetime | None) -> str:
    if not dt:
        return ""
    if dt.tzinfo is None:
        return dt.isoformat(sep=" ", timespec="seconds")
    return dt.astimezone().strftime("%Y-%m-%d %H:%M:%S")


@router.get("/redemptions")
def export_redemptions(
    db: Session = Depends(get_db),
    account: Account = Depends(require_roles(Role.super_admin, Role.issue_admin, Role.merchant)),
) -> StreamingResponse:
    query = db.query(RedemptionLog).order_by(RedemptionLog.created_at.desc())
    if account.role == Role.merchant:
        query = query.filter(RedemptionLog.merchant_id == account.merchant_id)
    rows = query.limit(5000).all()
    out: list[list] = [["时间", "券码", "结果", "说明", "商家", "用户", "操作员", "券ID"]]
    for r in rows:
        merchant = db.get(Merchant, r.merchant_id) if r.merchant_id else None
        user = db.get(Account, r.user_id) if r.user_id else None
        operator = db.get(Account, r.operator_id) if r.operator_id else None
        out.append(
            [
                _fmt(r.created_at),
                r.code,
                r.result,
                r.message,
                merchant.name if merchant else "",
                user.username if user else "",
                operator.display_name if operator else "",
                r.coupon_id or "",
            ]
        )
    return _csv_response(f"redemptions_{datetime.now():%Y%m%d_%H%M%S}.csv", out)


@router.get("/coupons")
def export_coupons(
    status: CouponStatus | None = Query(default=None),
    db: Session = Depends(get_db),
    _: Account = Depends(require_roles(Role.super_admin, Role.issue_admin)),
) -> StreamingResponse:
    query = db.query(CouponInstance).order_by(CouponInstance.issued_at.desc())
    if status:
        query = query.filter(CouponInstance.status == status)
    rows = query.limit(5000).all()
    out: list[list] = [
        ["券码", "状态", "用户", "模板", "商家", "发放时间", "过期时间", "核销时间", "作废原因"]
    ]
    for c in rows:
        user = db.get(Account, c.user_id)
        template = db.get(CouponTemplate, c.template_id)
        merchant = db.get(Merchant, c.merchant_id)
        out.append(
            [
                c.code,
                c.status.value if c.status else "",
                user.username if user else "",
                template.name if template else "",
                merchant.name if merchant else "",
                _fmt(c.issued_at),
                _fmt(c.expires_at),
                _fmt(c.redeemed_at),
                c.void_reason or "",
            ]
        )
    return _csv_response(f"coupons_{datetime.now():%Y%m%d_%H%M%S}.csv", out)
