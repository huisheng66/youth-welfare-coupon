import logging
import secrets
import string
from datetime import date as date_cls
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from app.core.config import get_settings
from app.core.database import get_db
from app.core.deps import get_current_account, require_roles
from app.models.entities import (
    Account,
    CouponInstance,
    CouponStatus,
    CouponTemplate,
    Merchant,
    RedemptionLog,
    Role,
    UserProfile,
    VerifyStatus,
)
from app.schemas.bulk_import import ImportResultOut, ImportRowError
from app.schemas.common import Page
from app.schemas.coupon import (
    BatchIssueCouponIn,
    BatchIssueResult,
    CouponOut,
    IssueCouponIn,
    LiveCodeOut,
    RedeemIn,
    RedeemOut,
    RedemptionLogOut,
    TemplateCreate,
    TemplateOut,
    TemplateUpdate,
    VoidCouponIn,
)
from app.services.audit import write_audit
from app.services.live_code import create_live_code, decode_live_code, looks_like_live_code
from app.services.coupons import expire_stale_coupons
from app.services.import_file import (
    KIND_ISSUE,
    map_columns,
    parse_table_file,
    read_upload_bytes,
    resolve_user,
)

router = APIRouter(prefix="/coupons", tags=["优惠券"])

logger = logging.getLogger(__name__)


def _gen_code(length: int = 10) -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _preload_coupons(db: Session, coupon_ids: list[str]) -> list[CouponInstance]:
    """按 id 批量预加载 user/template/merchant，保持入参顺序。"""
    if not coupon_ids:
        return []
    loaded = (
        db.query(CouponInstance)
        .options(
            joinedload(CouponInstance.user),
            joinedload(CouponInstance.template),
            joinedload(CouponInstance.merchant),
        )
        .filter(CouponInstance.id.in_(coupon_ids))
        .all()
    )
    by_id = {c.id: c for c in loaded}
    return [by_id[i] for i in coupon_ids if i in by_id]


def coupon_to_out(c: CouponInstance) -> CouponOut:
    # 直接用 relationship（调用方需通过 joinedload 预加载以避免 N+1）
    user = c.user
    template = c.template
    merchant = c.merchant
    return CouponOut(
        id=c.id,
        code=c.code,
        user_id=c.user_id,
        username=user.username if user else None,
        template_id=c.template_id,
        template_name=template.name if template else None,
        merchant_id=c.merchant_id,
        merchant_name=merchant.name if merchant else None,
        status=c.status,
        issued_by=c.issued_by,
        issued_at=c.issued_at,
        expires_at=c.expires_at,
        redeemed_by=c.redeemed_by,
        redeemed_at=c.redeemed_at,
        void_reason=c.void_reason,
    )


def template_to_out(t: CouponTemplate) -> TemplateOut:
    return TemplateOut(
        id=t.id,
        name=t.name,
        description=t.description,
        merchant_id=t.merchant_id,
        merchant_name=t.merchant.name if t.merchant else None,
        valid_days=t.valid_days,
        cost_points=getattr(t, "cost_points", 0) or 0,
        is_active=t.is_active,
        created_at=t.created_at,
    )


def _resolve_coupon_by_code(db: Session, raw: str) -> CouponInstance | None:
    raw = raw.strip()
    if not raw:
        return None
    if looks_like_live_code(raw):
        try:
            payload = decode_live_code(raw)
        except ValueError:
            return None
        coupon = db.get(CouponInstance, payload["cid"])
        if not coupon:
            return None
        if coupon.user_id != payload.get("uid"):
            return None
        if coupon.code != payload.get("code"):
            return None
        return coupon
    return db.query(CouponInstance).filter(CouponInstance.code == raw.upper()).first()


def _maybe_expire(coupon: CouponInstance) -> None:
    now = datetime.now(timezone.utc)
    exp = coupon.expires_at
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    if coupon.status == CouponStatus.unused and exp < now:
        coupon.status = CouponStatus.expired


# ----- templates -----


@router.get("/templates", response_model=Page[TemplateOut])
def list_templates(
    merchant_id: str | None = None,
    active_only: bool = False,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    _: Account = Depends(require_roles(Role.super_admin, Role.issue_admin)),
) -> Page[TemplateOut]:
    query = db.query(CouponTemplate).options(joinedload(CouponTemplate.merchant)).order_by(CouponTemplate.created_at.desc())
    if merchant_id:
        query = query.filter(CouponTemplate.merchant_id == merchant_id)
    if active_only:
        query = query.filter(CouponTemplate.is_active.is_(True))
    total = query.count()
    items = query.offset(skip).limit(limit).all()
    return Page(total=total, items=[template_to_out(i) for i in items])


@router.post("/templates", response_model=TemplateOut)
def create_template(
    body: TemplateCreate,
    db: Session = Depends(get_db),
    admin: Account = Depends(require_roles(Role.super_admin, Role.issue_admin)),
) -> TemplateOut:
    merchant = db.get(Merchant, body.merchant_id)
    if not merchant or not merchant.is_active:
        raise HTTPException(status_code=400, detail="商家不存在或已停用")
    template = CouponTemplate(**body.model_dump())
    db.add(template)
    write_audit(
        db,
        actor_id=admin.id,
        action="create_template",
        target_type="template",
        target_id=body.name,
        detail=f"merchant={body.merchant_id}",
    )
    db.commit()
    db.refresh(template)
    template = (
        db.query(CouponTemplate)
        .options(joinedload(CouponTemplate.merchant))
        .filter(CouponTemplate.id == template.id)
        .one()
    )
    return template_to_out(template)


@router.put("/templates/{template_id}", response_model=TemplateOut)
def update_template(
    template_id: str,
    body: TemplateUpdate,
    db: Session = Depends(get_db),
    admin: Account = Depends(require_roles(Role.super_admin, Role.issue_admin)),
) -> TemplateOut:
    template = db.get(CouponTemplate, template_id)
    if not template:
        raise HTTPException(status_code=404, detail="模板不存在")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(template, k, v)
    write_audit(db, actor_id=admin.id, action="update_template", target_type="template", target_id=template_id)
    db.commit()
    template = (
        db.query(CouponTemplate)
        .options(joinedload(CouponTemplate.merchant))
        .filter(CouponTemplate.id == template_id)
        .one()
    )
    return template_to_out(template)


# ----- issue / list / void -----


def _issue_for_user(
    db: Session,
    *,
    user: Account,
    template: CouponTemplate,
    quantity: int,
    admin: Account,
) -> list[CouponInstance]:
    profile = db.query(UserProfile).filter(UserProfile.account_id == user.id).first()
    if not profile or profile.verify_status != VerifyStatus.approved:
        raise ValueError("仅可为已核验通过的用户发券")
    now = datetime.now(timezone.utc)
    expires = now + timedelta(days=template.valid_days)
    created: list[CouponInstance] = []
    for _ in range(quantity):
        code = _gen_code()
        while db.query(CouponInstance).filter(CouponInstance.code == code).first():
            code = _gen_code()
        inst = CouponInstance(
            code=code,
            user_id=user.id,
            template_id=template.id,
            merchant_id=template.merchant_id,
            status=CouponStatus.unused,
            issued_by=admin.id,
            issued_at=now,
            expires_at=expires,
        )
        db.add(inst)
        created.append(inst)
    return created


@router.post("/issue", response_model=list[CouponOut])
def issue_coupons(
    body: IssueCouponIn,
    db: Session = Depends(get_db),
    admin: Account = Depends(require_roles(Role.super_admin, Role.issue_admin)),
) -> list[CouponOut]:
    user = db.get(Account, body.user_id)
    if not user or user.role != Role.user:
        raise HTTPException(status_code=400, detail="目标用户无效")
    template = db.get(CouponTemplate, body.template_id)
    if not template or not template.is_active:
        raise HTTPException(status_code=400, detail="券模板不可用")
    merchant = db.get(Merchant, template.merchant_id)
    if not merchant or not merchant.is_active:
        raise HTTPException(status_code=400, detail="关联商家不可用")
    try:
        created = _issue_for_user(db, user=user, template=template, quantity=body.quantity, admin=admin)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    write_audit(
        db,
        actor_id=admin.id,
        action="issue_coupon",
        target_type="user",
        target_id=user.id,
        detail=f"template={template.id}, qty={body.quantity}, merchant={template.merchant_id}",
    )
    db.commit()
    logger.info(
        "coupon.issue",
        extra={
            "operator_id": admin.id,
            "user_id": user.id,
            "template_id": template.id,
            "merchant_id": template.merchant_id,
            "quantity": body.quantity,
        },
    )
    loaded = _preload_coupons(db, [c.id for c in created])
    return [coupon_to_out(c) for c in loaded]


@router.post("/issue-batch", response_model=BatchIssueResult)
def issue_coupons_batch(
    body: BatchIssueCouponIn,
    db: Session = Depends(get_db),
    admin: Account = Depends(require_roles(Role.super_admin, Role.issue_admin)),
) -> BatchIssueResult:
    template = db.get(CouponTemplate, body.template_id)
    if not template or not template.is_active:
        raise HTTPException(status_code=400, detail="券模板不可用")
    merchant = db.get(Merchant, template.merchant_id)
    if not merchant or not merchant.is_active:
        raise HTTPException(status_code=400, detail="关联商家不可用")

    issued: list[CouponOut] = []
    failed: list[dict] = []
    all_created: list[CouponInstance] = []
    for uid in body.user_ids:
        user = db.get(Account, uid)
        if not user or user.role != Role.user:
            failed.append({"user_id": uid, "reason": "用户无效"})
            continue
        try:
            created = _issue_for_user(db, user=user, template=template, quantity=body.quantity, admin=admin)
            all_created.extend(created)
        except ValueError as exc:
            failed.append({"user_id": uid, "username": user.username, "reason": str(exc)})
    write_audit(
        db,
        actor_id=admin.id,
        action="issue_coupon_batch",
        target_type="template",
        target_id=template.id,
        detail=f"users={len(body.user_ids)}, qty_each={body.quantity}, ok={len(all_created)}, fail={len(failed)}",
    )
    db.commit()
    loaded = _preload_coupons(db, [c.id for c in all_created])
    issued = [coupon_to_out(c) for c in loaded]
    return BatchIssueResult(issued=issued, failed=failed)


@router.post("/issue-import", response_model=ImportResultOut)
def issue_coupons_import(
    file: UploadFile = File(..., description="用户标识名单（.xlsx / .csv / .txt / .docx）"),
    template_id: str = Form(...),
    quantity: int = Form(1, ge=1, le=10),
    db: Session = Depends(get_db),
    admin: Account = Depends(require_roles(Role.super_admin, Role.issue_admin)),
) -> ImportResultOut:
    """按名单文件发券：每行一个用户标识（用户名 / 邮箱 / 手机 / 学号）。

    复用单用户发券的全部校验（核验状态、模板/商家可用性），单行失败记入
    errors 不中断；未核验、查无此人的行会明确报错。
    """
    settings = get_settings()
    template = db.get(CouponTemplate, template_id)
    if not template or not template.is_active:
        raise HTTPException(status_code=400, detail="券模板不可用")
    merchant = db.get(Merchant, template.merchant_id)
    if not merchant or not merchant.is_active:
        raise HTTPException(status_code=400, detail="关联商家不可用")

    try:
        data = read_upload_bytes(file.file)
        rows = parse_table_file(file.filename or "", data, max_rows=settings.import_max_rows)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    header = map_columns(rows[0], KIND_ISSUE)
    data_rows = rows[1:] if header else rows
    ident_idx = (header or {}).get("identifier", 0)

    errors: list[ImportRowError] = []
    ok = 0
    created_all: list[CouponInstance] = []
    for lineno, row in enumerate(data_rows, start=1):
        token = row[ident_idx].strip() if ident_idx < len(row) else ""
        if not token:
            errors.append(ImportRowError(row=lineno, identifier="", reason="用户标识为空"))
            continue
        user = resolve_user(db, token)
        if not user:
            errors.append(
                ImportRowError(
                    row=lineno,
                    identifier=token,
                    reason="用户不存在或无法唯一识别（支持用户名/邮箱/手机/学号）",
                )
            )
            continue
        try:
            created = _issue_for_user(db, user=user, template=template, quantity=quantity, admin=admin)
        except ValueError as exc:
            errors.append(ImportRowError(row=lineno, identifier=token, reason=str(exc)))
            continue
        created_all.extend(created)
        ok += 1

    write_audit(
        db,
        actor_id=admin.id,
        action="issue_coupon_import",
        target_type="template",
        target_id=template.id,
        detail=f"rows={len(data_rows)}, qty_each={quantity}, ok={ok}, fail={len(errors)}",
    )
    db.commit()
    shown = errors[:100]
    message = f"按名单发券完成：共 {len(data_rows)} 行，成功 {ok} 人（{len(created_all)} 张券），失败 {len(errors)} 行"
    if len(errors) > len(shown):
        message += "（错误明细仅显示前 100 条）"
    return ImportResultOut(
        total=len(data_rows),
        succeeded=ok,
        failed=len(errors),
        errors=shown,
        message=message,
    )


@router.get("/preview", response_model=CouponOut)
def preview_coupon(
    code: str = Query(..., min_length=4, max_length=4096),
    db: Session = Depends(get_db),
    account: Account = Depends(require_roles(Role.merchant)),
) -> CouponOut:
    """商家核销前预览，不改变状态。支持永久券码或动态券码。"""
    if not account.merchant_id:
        raise HTTPException(status_code=400, detail="商家账号未绑定门店")
    raw = code.strip()
    if looks_like_live_code(raw):
        try:
            decode_live_code(raw)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    coupon = _resolve_coupon_by_code(db, raw)
    if not coupon:
        raise HTTPException(status_code=404, detail="券码不存在或动态码已过期")
    _maybe_expire(coupon)
    db.commit()
    if coupon.merchant_id != account.merchant_id:
        raise HTTPException(status_code=400, detail="该券仅限指定商家核销，非本店券")
    return coupon_to_out(coupon)


@router.get("/instances/{coupon_id}/live-code", response_model=LiveCodeOut)
def get_live_code(
    coupon_id: str,
    db: Session = Depends(get_db),
    account: Account = Depends(require_roles(Role.user)),
) -> LiveCodeOut:
    coupon = db.get(CouponInstance, coupon_id)
    if not coupon or coupon.user_id != account.id:
        raise HTTPException(status_code=404, detail="券不存在")
    _maybe_expire(coupon)
    db.commit()
    if coupon.status != CouponStatus.unused:
        raise HTTPException(status_code=400, detail=f"当前状态不可出示：{coupon.status.value}")
    live, seconds, exp = create_live_code(
        coupon_id=coupon.id,
        user_id=account.id,
        permanent_code=coupon.code,
    )
    template = db.get(CouponTemplate, coupon.template_id)
    merchant = db.get(Merchant, coupon.merchant_id)
    return LiveCodeOut(
        coupon_id=coupon.id,
        live_code=live,
        expires_in=seconds,
        expires_at=exp,
        permanent_code=coupon.code,
        template_name=template.name if template else None,
        merchant_name=merchant.name if merchant else None,
    )


def _day_bounds(date_from: date_cls | None, date_to: date_cls | None) -> tuple[datetime | None, datetime | None]:
    start = datetime.combine(date_from, datetime.min.time(), tzinfo=timezone.utc) if date_from else None
    end = datetime.combine(date_to, datetime.max.time().replace(microsecond=0), tzinfo=timezone.utc) if date_to else None
    return start, end


def _literal_like_pattern(value: str) -> str:
    """Wrap a literal substring for LIKE without treating user input as wildcards."""
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


@router.get("/instances", response_model=Page[CouponOut])
def list_instances(
    status: CouponStatus | None = None,
    user_id: str | None = None,
    merchant_id: str | None = None,
    q: str | None = None,
    date_from: date_cls | None = None,
    date_to: date_cls | None = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    account: Account = Depends(get_current_account),
) -> Page[CouponOut]:
    # Keep expiry state current without loading every coupon into Python.
    expire_stale_coupons(db)
    query = (
        db.query(CouponInstance)
        .options(
            joinedload(CouponInstance.user),
            joinedload(CouponInstance.template),
            joinedload(CouponInstance.merchant),
        )
        .order_by(CouponInstance.issued_at.desc(), CouponInstance.id.desc())
    )
    if account.role == Role.user:
        query = query.filter(CouponInstance.user_id == account.id)
    elif account.role == Role.merchant:
        query = query.filter(CouponInstance.merchant_id == account.merchant_id)
    elif account.role not in (Role.super_admin, Role.issue_admin):
        raise HTTPException(status_code=403, detail="无权限")
    else:
        if user_id:
            query = query.filter(CouponInstance.user_id == user_id)
        if merchant_id:
            query = query.filter(CouponInstance.merchant_id == merchant_id)
    start, end = _day_bounds(date_from, date_to)
    if start:
        query = query.filter(CouponInstance.issued_at >= start)
    if end:
        query = query.filter(CouponInstance.issued_at <= end)
    if status:
        query = query.filter(CouponInstance.status == status)
    if q and q.strip():
        keyword = _literal_like_pattern(q.strip())
        query = query.join(Account, CouponInstance.user_id == Account.id).filter(
            or_(
                CouponInstance.code.ilike(keyword, escape="\\"),
                Account.username.ilike(keyword, escape="\\"),
                Account.display_name.ilike(keyword, escape="\\"),
            )
        )
    total = query.order_by(None).count()
    rows = query.offset(skip).limit(limit).all()
    return Page(total=total, items=[coupon_to_out(r) for r in rows])


@router.get("/my", response_model=list[CouponOut])
def my_coupons(
    status: CouponStatus | None = None,
    db: Session = Depends(get_db),
    account: Account = Depends(require_roles(Role.user)),
) -> list[CouponOut]:
    expire_stale_coupons(db)
    query = (
        db.query(CouponInstance)
        .options(
            joinedload(CouponInstance.user),
            joinedload(CouponInstance.template),
            joinedload(CouponInstance.merchant),
        )
        .filter(CouponInstance.user_id == account.id)
        .order_by(CouponInstance.issued_at.desc(), CouponInstance.id.desc())
    )
    if status:
        query = query.filter(CouponInstance.status == status)
    rows = (
        query.all()
    )
    return [coupon_to_out(r) for r in rows]


@router.post("/instances/{coupon_id}/void", response_model=CouponOut)
def void_coupon(
    coupon_id: str,
    body: VoidCouponIn,
    db: Session = Depends(get_db),
    admin: Account = Depends(require_roles(Role.super_admin, Role.issue_admin)),
) -> CouponOut:
    coupon = db.get(CouponInstance, coupon_id)
    if not coupon:
        raise HTTPException(status_code=404, detail="券不存在")
    _maybe_expire(coupon)
    if coupon.status != CouponStatus.unused:
        raise HTTPException(status_code=400, detail=f"仅未使用的券可作废，当前状态：{coupon.status.value}")
    coupon.status = CouponStatus.void
    coupon.void_reason = body.reason
    write_audit(
        db,
        actor_id=admin.id,
        action="void_coupon",
        target_type="coupon",
        target_id=coupon_id,
        detail=body.reason,
    )
    db.commit()
    db.refresh(coupon)
    return coupon_to_out(coupon)


@router.post("/redeem", response_model=RedeemOut)
def redeem(
    body: RedeemIn,
    db: Session = Depends(get_db),
    account: Account = Depends(require_roles(Role.merchant)),
) -> RedeemOut:
    if not account.merchant_id:
        raise HTTPException(status_code=400, detail="商家账号未绑定门店")
    raw = body.code.strip()
    display_code = raw.upper() if not looks_like_live_code(raw) else raw[:24] + "..."
    if looks_like_live_code(raw):
        try:
            decode_live_code(raw)
        except ValueError as exc:
            db.add(
                RedemptionLog(
                    coupon_id=None,
                    merchant_id=account.merchant_id,
                    operator_id=account.id,
                    user_id=None,
                    code=display_code,
                    result="failed",
                    message=str(exc),
                )
            )
            db.commit()
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    coupon = _resolve_coupon_by_code(db, raw)
    if not coupon:
        db.add(
            RedemptionLog(
                coupon_id=None,
                merchant_id=account.merchant_id,
                operator_id=account.id,
                user_id=None,
                code=display_code,
                result="failed",
                message="券码不存在或动态码已过期",
            )
        )
        db.commit()
        raise HTTPException(status_code=404, detail="券码不存在或动态码已过期")
    code = coupon.code

    _maybe_expire(coupon)
    if coupon.merchant_id != account.merchant_id:
        db.add(
            RedemptionLog(
                coupon_id=coupon.id,
                merchant_id=account.merchant_id,
                operator_id=account.id,
                user_id=coupon.user_id,
                code=code,
                result="failed",
                message="非本店可用券",
            )
        )
        db.commit()
        raise HTTPException(status_code=400, detail="该券仅限指定商家核销，非本店券")
    if coupon.status == CouponStatus.used:
        raise HTTPException(status_code=400, detail="该券已核销")
    if coupon.status == CouponStatus.void:
        raise HTTPException(status_code=400, detail="该券已作废")
    if coupon.status == CouponStatus.expired:
        raise HTTPException(status_code=400, detail="该券已过期")
    if coupon.status != CouponStatus.unused:
        raise HTTPException(status_code=400, detail="券状态不可核销")

    now = datetime.now(timezone.utc)
    # Conditional update for concurrency safety
    updated = (
        db.query(CouponInstance)
        .filter(CouponInstance.id == coupon.id, CouponInstance.status == CouponStatus.unused)
        .update(
            {
                CouponInstance.status: CouponStatus.used,
                CouponInstance.redeemed_by: account.id,
                CouponInstance.redeemed_at: now,
            },
            synchronize_session=False,
        )
    )
    if not updated:
        db.rollback()
        raise HTTPException(status_code=400, detail="核销失败，券可能已被使用")

    db.add(
        RedemptionLog(
            coupon_id=coupon.id,
            merchant_id=account.merchant_id,
            operator_id=account.id,
            user_id=coupon.user_id,
            code=code,
            result="success",
            message="核销成功",
        )
    )
    write_audit(
        db,
        actor_id=account.id,
        action="redeem_coupon",
        target_type="coupon",
        target_id=coupon.id,
        detail=code,
    )
    db.commit()
    logger.info(
        "coupon.redeem",
        extra={
            "coupon_id": coupon.id,
            "merchant_id": account.merchant_id,
            "operator_id": account.id,
            "user_id": coupon.user_id,
        },
    )
    coupon = db.get(CouponInstance, coupon.id)
    assert coupon is not None
    return RedeemOut(message="核销成功", coupon=coupon_to_out(coupon))


@router.get("/redemptions", response_model=Page[RedemptionLogOut])
def list_redemptions(
    result: str | None = Query(default=None, description="success / failed"),
    merchant_id: str | None = None,
    q: str | None = None,
    date_from: date_cls | None = None,
    date_to: date_cls | None = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    account: Account = Depends(require_roles(Role.super_admin, Role.issue_admin, Role.merchant)),
) -> Page[RedemptionLogOut]:
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
    if q and q.strip():
        like = f"%{q.strip()}%"
        query = query.filter(RedemptionLog.code.ilike(like) | RedemptionLog.message.ilike(like))
    total = query.count()
    rows = query.offset(skip).limit(limit).all()
    # 批量预取关联，避免 N+1
    merchant_ids = {r.merchant_id for r in rows if r.merchant_id}
    account_ids = {r.operator_id for r in rows if r.operator_id} | {r.user_id for r in rows if r.user_id}
    merchants: dict[str, Merchant] = {}
    accounts: dict[str, Account] = {}
    if merchant_ids:
        merchants = {m.id: m for m in db.query(Merchant).filter(Merchant.id.in_(merchant_ids)).all()}
    if account_ids:
        accounts = {a.id: a for a in db.query(Account).filter(Account.id.in_(account_ids)).all()}
    items: list[RedemptionLogOut] = []
    for r in rows:
        merchant = merchants.get(r.merchant_id) if r.merchant_id else None
        operator = accounts.get(r.operator_id) if r.operator_id else None
        user = accounts.get(r.user_id) if r.user_id else None
        items.append(
            RedemptionLogOut(
                id=r.id,
                coupon_id=r.coupon_id,
                merchant_id=r.merchant_id,
                merchant_name=merchant.name if merchant else None,
                operator_id=r.operator_id,
                operator_name=operator.display_name if operator else None,
                user_id=r.user_id,
                username=user.username if user else None,
                code=r.code,
                result=r.result,
                message=r.message,
                created_at=r.created_at,
            )
        )
    return Page(total=total, items=items)
