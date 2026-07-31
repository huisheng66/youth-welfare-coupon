from datetime import date as date_cls
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import require_roles
from app.models.entities import (
    Account,
    AuditLog,
    CouponInstance,
    CouponStatus,
    CouponTemplate,
    Merchant,
    RedemptionLog,
    Role,
    UserProfile,
    UserVerification,
    VerifyStatus,
)
from app.schemas.common import DashboardActivityItem, DashboardOut, MerchantDashboardOut, Page
from app.schemas.coupon import AuditLogOut
from app.services.coupons import expire_stale_coupons

router = APIRouter(tags=["统计审计"])


def _recent_activity(db: Session, limit: int = 8) -> list[DashboardActivityItem]:
    items: list[DashboardActivityItem] = []

    redemptions = (
        db.query(RedemptionLog)
        .filter(RedemptionLog.result == "success")
        .order_by(RedemptionLog.created_at.desc())
        .limit(limit)
        .all()
    )
    r_merchant_ids = {r.merchant_id for r in redemptions if r.merchant_id}
    r_user_ids = {r.user_id for r in redemptions if r.user_id}
    merchants_map: dict[str, Merchant] = {}
    if r_merchant_ids:
        for m in db.query(Merchant).filter(Merchant.id.in_(r_merchant_ids)).all():
            merchants_map[m.id] = m
    users_map: dict[str, Account] = {}
    if r_user_ids:
        for u in db.query(Account).filter(Account.id.in_(r_user_ids)).all():
            users_map[u.id] = u
    for r in redemptions:
        merchant = merchants_map.get(r.merchant_id) if r.merchant_id else None
        user = users_map.get(r.user_id) if r.user_id else None
        items.append(
            DashboardActivityItem(
                time=r.created_at,
                kind="redeem",
                title="核销成功",
                detail=f"{merchant.name if merchant else '商家'} · {user.username if user else r.code}",
            )
        )

    pending = (
        db.query(UserVerification)
        .filter(UserVerification.status == VerifyStatus.pending)
        .order_by(UserVerification.created_at.desc())
        .limit(limit)
        .all()
    )
    profile_ids = [v.profile_id for v in pending]
    profiles_map: dict[str, UserProfile] = {}
    if profile_ids:
        for p in db.query(UserProfile).filter(UserProfile.id.in_(profile_ids)).all():
            profiles_map[p.id] = p
    v_account_ids = {p.account_id for p in profiles_map.values()}
    v_accounts_map: dict[str, Account] = {}
    if v_account_ids:
        for a in db.query(Account).filter(Account.id.in_(v_account_ids)).all():
            v_accounts_map[a.id] = a
    for v in pending:
        profile = profiles_map.get(v.profile_id)
        acc = v_accounts_map.get(profile.account_id) if profile else None
        items.append(
            DashboardActivityItem(
                time=v.created_at,
                kind="verify",
                title="待审核申请",
                detail=f"{acc.username if acc else '用户'} · {(v.material_note or '')[:40]}",
            )
        )

    def _ts(item: DashboardActivityItem) -> datetime:
        t = item.time
        if t is None:
            return datetime.min.replace(tzinfo=timezone.utc)
        if t.tzinfo is None:
            return t.replace(tzinfo=timezone.utc)
        return t

    items.sort(key=_ts, reverse=True)
    return items[:limit]


@router.get("/dashboard", response_model=DashboardOut)
def dashboard(
    db: Session = Depends(get_db),
    _: Account = Depends(require_roles(Role.super_admin, Role.issue_admin)),
) -> DashboardOut:
    expire_stale_coupons(db)
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    today_redemptions = (
        db.query(func.count(RedemptionLog.id))
        .filter(RedemptionLog.result == "success", RedemptionLog.created_at >= today_start)
        .scalar()
        or 0
    )
    today_issued = (
        db.query(func.count(CouponInstance.id))
        .filter(CouponInstance.issued_at >= today_start)
        .scalar()
        or 0
    )
    return DashboardOut(
        users=db.query(Account).filter(Account.role == Role.user).count(),
        pending_verifications=db.query(UserProfile).filter(UserProfile.verify_status == VerifyStatus.pending).count(),
        merchants=db.query(Merchant).count(),
        coupons_issued=db.query(CouponInstance).count(),
        coupons_used=db.query(CouponInstance).filter(CouponInstance.status == CouponStatus.used).count(),
        templates=db.query(CouponTemplate).count(),
        unused_coupons=db.query(CouponInstance).filter(CouponInstance.status == CouponStatus.unused).count(),
        approved_users=db.query(UserProfile).filter(UserProfile.verify_status == VerifyStatus.approved).count(),
        today_redemptions=int(today_redemptions),
        today_issued=int(today_issued),
        expired_coupons=db.query(CouponInstance).filter(CouponInstance.status == CouponStatus.expired).count(),
        recent_activity=_recent_activity(db),
    )


@router.get("/merchant-dashboard", response_model=MerchantDashboardOut)
def merchant_dashboard(
    db: Session = Depends(get_db),
    account: Account = Depends(require_roles(Role.merchant)),
) -> MerchantDashboardOut:
    if not account.merchant_id:
        raise HTTPException(status_code=400, detail="商家账号未绑定门店")
    merchant = db.get(Merchant, account.merchant_id)
    if not merchant:
        raise HTTPException(status_code=404, detail="商家不存在")
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    today_success = (
        db.query(func.count(RedemptionLog.id))
        .filter(
            RedemptionLog.merchant_id == account.merchant_id,
            RedemptionLog.result == "success",
            RedemptionLog.created_at >= today_start,
        )
        .scalar()
        or 0
    )
    total_success = (
        db.query(func.count(RedemptionLog.id))
        .filter(RedemptionLog.merchant_id == account.merchant_id, RedemptionLog.result == "success")
        .scalar()
        or 0
    )
    unused_for_store = (
        db.query(func.count(CouponInstance.id))
        .filter(CouponInstance.merchant_id == account.merchant_id, CouponInstance.status == CouponStatus.unused)
        .scalar()
        or 0
    )
    used_for_store = (
        db.query(func.count(CouponInstance.id))
        .filter(CouponInstance.merchant_id == account.merchant_id, CouponInstance.status == CouponStatus.used)
        .scalar()
        or 0
    )
    return MerchantDashboardOut(
        merchant_id=merchant.id,
        merchant_name=merchant.name,
        today_success=int(today_success),
        total_success=int(total_success),
        unused_for_store=int(unused_for_store),
        used_for_store=int(used_for_store),
    )


@router.get("/audit-logs", response_model=Page[AuditLogOut])
def audit_logs(
    action: str | None = None,
    q: str | None = None,
    date_from: date_cls | None = None,
    date_to: date_cls | None = None,
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db),
    _: Account = Depends(require_roles(Role.super_admin)),
) -> Page[AuditLogOut]:
    query = db.query(AuditLog).order_by(AuditLog.created_at.desc())
    if action and action.strip():
        query = query.filter(AuditLog.action == action.strip())
    if q and q.strip():
        like = f"%{q.strip()}%"
        query = query.filter(
            AuditLog.action.ilike(like)
            | AuditLog.target_type.ilike(like)
            | AuditLog.target_id.ilike(like)
            | AuditLog.detail.ilike(like)
        )
    if date_from:
        start = datetime.combine(date_from, datetime.min.time(), tzinfo=timezone.utc)
        query = query.filter(AuditLog.created_at >= start)
    if date_to:
        end = datetime.combine(date_to, datetime.max.time().replace(microsecond=0), tzinfo=timezone.utc)
        query = query.filter(AuditLog.created_at <= end)
    total = query.count()
    rows = query.offset(skip).limit(limit).all()
    actor_ids = {r.actor_id for r in rows if r.actor_id}
    actor_map: dict[str, Account] = {}
    if actor_ids:
        for acc in db.query(Account).filter(Account.id.in_(actor_ids)).all():
            actor_map[acc.id] = acc
    items: list[AuditLogOut] = []
    for r in rows:
        actor = actor_map.get(r.actor_id) if r.actor_id else None
        items.append(
            AuditLogOut(
                id=r.id,
                actor_id=r.actor_id,
                actor_name=actor.display_name if actor else None,
                action=r.action,
                target_type=r.target_type,
                target_id=r.target_id,
                detail=r.detail,
                created_at=r.created_at,
            )
        )
    return Page(total=total, items=items)
