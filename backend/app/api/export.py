import csv
import io
from datetime import date as date_cls
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session, joinedload

from app.core.database import get_db
from app.core.deps import require_roles
from app.models.entities import (
    Account,
    CouponInstance,
    CouponStatus,
    CouponTemplate,
    Merchant,
    PointLedger,
    RedemptionLog,
    Role,
    UserProfile,
    VerifyStatus,
)

router = APIRouter(prefix="/export", tags=["导出"])

EXPORT_LIMIT = 5000


def _safe_csv_cell(value: object) -> object:
    """Prevent spreadsheet formula execution for user-controlled text."""
    if isinstance(value, str):
        trimmed = value.lstrip(" \t\r\n\v\f")
        if value[:1] in {"\t", "\r", "\n"} or trimmed[:1] in {"=", "+", "-", "@"}:
            return "'" + value
    return value


def _day_bounds(date_from: date_cls | None, date_to: date_cls | None) -> tuple[datetime | None, datetime | None]:
    start = datetime.combine(date_from, datetime.min.time(), tzinfo=timezone.utc) if date_from else None
    end = datetime.combine(date_to, datetime.max.time().replace(microsecond=0), tzinfo=timezone.utc) if date_to else None
    return start, end


def _csv_response(filename: str, rows: list[list], *, truncated: bool = False) -> StreamingResponse:
    buf = io.StringIO()
    buf.write("\ufeff")
    writer = csv.writer(buf)
    for row in rows:
        writer.writerow(_safe_csv_cell(cell) for cell in row)
    data = buf.getvalue().encode("utf-8")
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    if truncated:
        headers["X-Export-Truncated"] = "1"
        headers["Access-Control-Expose-Headers"] = "X-Export-Truncated, Content-Disposition"
    return StreamingResponse(iter([data]), media_type="text/csv; charset=utf-8", headers=headers)


def _fmt(dt: datetime | None) -> str:
    if not dt:
        return ""
    if dt.tzinfo is None:
        return dt.isoformat(sep=" ", timespec="seconds")
    return dt.astimezone().strftime("%Y-%m-%d %H:%M:%S")


@router.get("/redemptions")
def export_redemptions(
    result: str | None = Query(default=None),
    merchant_id: str | None = Query(default=None),
    date_from: date_cls | None = Query(default=None),
    date_to: date_cls | None = Query(default=None),
    db: Session = Depends(get_db),
    account: Account = Depends(require_roles(Role.super_admin, Role.issue_admin, Role.merchant)),
) -> StreamingResponse:
    query = db.query(RedemptionLog).order_by(RedemptionLog.created_at.desc())
    if account.role == Role.merchant:
        query = query.filter(RedemptionLog.merchant_id == account.merchant_id)
    elif merchant_id:
        query = query.filter(RedemptionLog.merchant_id == merchant_id)
    if result in ("success", "failed"):
        query = query.filter(RedemptionLog.result == result)
    start, end = _day_bounds(date_from, date_to)
    if start:
        query = query.filter(RedemptionLog.created_at >= start)
    if end:
        query = query.filter(RedemptionLog.created_at <= end)
    total = query.count()
    rows = query.limit(EXPORT_LIMIT).all()
    merchant_ids = {r.merchant_id for r in rows if r.merchant_id}
    account_ids = {r.user_id for r in rows if r.user_id} | {r.operator_id for r in rows if r.operator_id}
    merchants = {
        m.id: m for m in db.query(Merchant).filter(Merchant.id.in_(merchant_ids)).all()
    } if merchant_ids else {}
    accounts = {
        a.id: a for a in db.query(Account).filter(Account.id.in_(account_ids)).all()
    } if account_ids else {}
    out: list[list] = [["时间", "券码", "结果", "说明", "商家", "用户", "操作员", "券ID"]]
    for r in rows:
        merchant = merchants.get(r.merchant_id) if r.merchant_id else None
        user = accounts.get(r.user_id) if r.user_id else None
        operator = accounts.get(r.operator_id) if r.operator_id else None
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
    return _csv_response(
        f"redemptions_{datetime.now():%Y%m%d_%H%M%S}.csv",
        out,
        truncated=total > EXPORT_LIMIT,
    )


@router.get("/coupons")
def export_coupons(
    status: CouponStatus | None = Query(default=None),
    merchant_id: str | None = Query(default=None),
    date_from: date_cls | None = Query(default=None),
    date_to: date_cls | None = Query(default=None),
    db: Session = Depends(get_db),
    _: Account = Depends(require_roles(Role.super_admin, Role.issue_admin)),
) -> StreamingResponse:
    query = db.query(CouponInstance).order_by(CouponInstance.issued_at.desc())
    if status:
        query = query.filter(CouponInstance.status == status)
    if merchant_id:
        query = query.filter(CouponInstance.merchant_id == merchant_id)
    start, end = _day_bounds(date_from, date_to)
    if start:
        query = query.filter(CouponInstance.issued_at >= start)
    if end:
        query = query.filter(CouponInstance.issued_at <= end)
    total = query.count()
    rows = query.limit(EXPORT_LIMIT).all()
    user_ids = {c.user_id for c in rows if c.user_id}
    template_ids = {c.template_id for c in rows if c.template_id}
    merchant_ids = {c.merchant_id for c in rows if c.merchant_id}
    users = {a.id: a for a in db.query(Account).filter(Account.id.in_(user_ids)).all()} if user_ids else {}
    templates = {
        t.id: t for t in db.query(CouponTemplate).filter(CouponTemplate.id.in_(template_ids)).all()
    } if template_ids else {}
    merchants = {
        m.id: m for m in db.query(Merchant).filter(Merchant.id.in_(merchant_ids)).all()
    } if merchant_ids else {}
    out: list[list] = [
        ["券码", "状态", "用户", "模板", "商家", "发放时间", "过期时间", "核销时间", "作废原因"]
    ]
    for c in rows:
        user = users.get(c.user_id)
        template = templates.get(c.template_id)
        merchant = merchants.get(c.merchant_id)
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
    return _csv_response(
        f"coupons_{datetime.now():%Y%m%d_%H%M%S}.csv",
        out,
        truncated=total > EXPORT_LIMIT,
    )


@router.get("/users")
def export_users(
    verify_status: VerifyStatus | None = Query(default=None),
    q: str | None = Query(default=None, description="与 /users 列表相同的搜索条件"),
    db: Session = Depends(get_db),
    _: Account = Depends(require_roles(Role.super_admin, Role.issue_admin)),
) -> StreamingResponse:
    query = (
        db.query(Account)
        .join(UserProfile, UserProfile.account_id == Account.id)
        .options(joinedload(Account.profile))
        .filter(Account.role == Role.user)
        .order_by(Account.created_at.desc())
    )
    if verify_status:
        query = query.filter(UserProfile.verify_status == verify_status)
    if q and q.strip():
        like = f"%{q.strip()}%"
        query = query.filter(
            (Account.username.ilike(like))
            | (Account.display_name.ilike(like))
            | (Account.phone.ilike(like))
            | (UserProfile.real_name.ilike(like))
            | (UserProfile.student_no.ilike(like))
        )
    accounts = query.limit(EXPORT_LIMIT).all()
    out: list[list] = [
        ["用户名", "昵称", "手机", "姓名", "学号", "组织", "核验状态", "银行卡脱敏", "开户行", "注册时间", "备注"]
    ]
    for acc in accounts:
        profile = acc.profile
        if not profile:
            continue
        card_mask = (
            f"**** **** **** {profile.bank_card_last4}"
            if profile.bank_card_encrypted and profile.bank_card_last4
            else ""
        )
        out.append(
            [
                acc.username,
                acc.display_name or "",
                acc.phone or "",
                profile.real_name or "",
                profile.student_no or "",
                profile.organization or "",
                profile.verify_status.value if profile.verify_status else "",
                card_mask,
                profile.bank_card_bank_name or "",
                _fmt(acc.created_at),
                profile.remark or "",
            ]
        )
    return _csv_response(f"users_{datetime.now():%Y%m%d_%H%M%S}.csv", out)


@router.get("/points-ledger")
def export_points_ledger(
    user_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
    _: Account = Depends(require_roles(Role.super_admin, Role.issue_admin)),
) -> StreamingResponse:
    query = db.query(PointLedger).order_by(PointLedger.created_at.desc())
    if user_id:
        query = query.filter(PointLedger.user_id == user_id)
    total = query.count()
    rows = query.limit(EXPORT_LIMIT).all()
    user_ids = {r.user_id for r in rows if r.user_id}
    operator_ids = {r.operator_id for r in rows if r.operator_id}
    account_ids = user_ids | operator_ids
    accounts = {
        a.id: a for a in db.query(Account).filter(Account.id.in_(account_ids)).all()
    } if account_ids else {}
    out: list[list] = [["时间", "用户", "变动", "余额", "说明", "类型", "操作员"]]
    for r in rows:
        user = accounts.get(r.user_id)
        op = accounts.get(r.operator_id) if r.operator_id else None
        out.append(
            [
                _fmt(r.created_at),
                user.username if user else r.user_id,
                r.change,
                r.balance_after,
                r.reason,
                r.ref_type,
                op.display_name if op else "",
            ]
        )
    return _csv_response(
        f"points_ledger_{datetime.now():%Y%m%d_%H%M%S}.csv",
        out,
        truncated=total > EXPORT_LIMIT,
    )
