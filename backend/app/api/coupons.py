import hashlib
import logging
import secrets
import string
from datetime import date as date_cls
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
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
)
from app.schemas.bulk_import import ImportResultOut, ImportRowError
from app.schemas.common import Page
from app.schemas.coupon import (
    BatchIssueCouponIn,
    BatchIssueResult,
    CouponOut,
    IssueCouponIn,
    LiveCodeOut,
    PreviewIn,
    RedeemIn,
    RedeemOut,
    RedemptionLogOut,
    TemplateCreate,
    TemplateOut,
    TemplateUpdate,
    VoidCouponIn,
)
from app.services.audit import write_audit
from app.services.biztime import day_bounds_utc_closed
from app.services.eligibility import (
    EligibilityError,
    require_benefit_user,
    require_issuable_template,
)
from app.services import idempotency as idem
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
        # 优先发放时快照；历史行无快照回退模板当前名称
        template_name=c.template_name or (template.name if template else None),
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
    """动态券码 → 券实例。

    永久编号只是业务查询编号，不参与核销鉴权：调用方须先确认输入是
    动态码形态，否则视为无效核销凭证。
    """
    raw = raw.strip()
    if not raw or not looks_like_live_code(raw):
        return None
    try:
        payload = decode_live_code(raw)
    except ValueError:
        return None
    coupon = db.get(CouponInstance, payload["cid"])
    if not coupon:
        return None
    if coupon.user_id != payload.get("uid"):
        return None
    return coupon


def _transition_expired(db: Session, coupon: CouponInstance) -> None:
    """把已过期的未使用券条件更新为 expired。

    过期转换必须是 `WHERE status = unused AND expires_at <= now` 的数据库级
    条件更新：从旧 ORM 对象盲写 expired（仅主键条件）会在并发下覆盖他人
    刚写入的 used 终态，造成券状态与核销流水互相矛盾（审查报告 F01）。
    调用方随后 db.commit() 固化转换。
    """
    now = datetime.now(timezone.utc)
    db.query(CouponInstance).filter(
        CouponInstance.id == coupon.id,
        CouponInstance.status == CouponStatus.unused,
        CouponInstance.expires_at <= now,
    ).update({CouponInstance.status: CouponStatus.expired}, synchronize_session=False)


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
    # 统一资格检查（T12）：角色/账号启用/核验状态，单条、批量与名单导入同一判定
    require_benefit_user(db, user, action="发券")
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
            template_name=template.name,
            template_description=template.description,
        )
        db.add(inst)
        created.append(inst)
    return created


@router.post("/issue", response_model=list[CouponOut])
def issue_coupons(
    body: IssueCouponIn,
    request: Request,
    db: Session = Depends(get_db),
    admin: Account = Depends(require_roles(Role.super_admin, Role.issue_admin)),
):
    idem_key = idem.extract_key(request)
    fp = idem.fingerprint(body.model_dump(mode="json"))
    if idem_key:
        replayed = idem.replay(db, actor_id=admin.id, action="coupon.issue", key=idem_key, request_hash=fp)
        if replayed is not None:
            return replayed
        idem.sweep_with_settings(db)
    user = db.get(Account, body.user_id)
    template = db.get(CouponTemplate, body.template_id)
    try:
        require_issuable_template(db, template)
        created = _issue_for_user(db, user=user, template=template, quantity=body.quantity, admin=admin)
    except EligibilityError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    write_audit(
        db,
        actor_id=admin.id,
        action="issue_coupon",
        target_type="user",
        target_id=user.id,
        detail=f"template={template.id}, qty={body.quantity}, merchant={template.merchant_id}",
    )
    db.flush()  # 分配实例主键（Python 端 default 在 flush 时生效）
    loaded = _preload_coupons(db, [c.id for c in created])
    result = [coupon_to_out(c).model_dump(mode="json") for c in loaded]
    # 幂等记录与券写入同事务提交：不会出现“记为完成但券未落库”（T13）
    if idem_key:
        idem.store(db, actor_id=admin.id, action="coupon.issue", key=idem_key, request_hash=fp, result=result)
    raced = idem.commit_idempotent(db, actor_id=admin.id, action="coupon.issue", key=idem_key, request_hash=fp)
    if raced is not None:
        return raced
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
    return result


@router.post("/issue-batch", response_model=BatchIssueResult)
def issue_coupons_batch(
    body: BatchIssueCouponIn,
    request: Request,
    db: Session = Depends(get_db),
    admin: Account = Depends(require_roles(Role.super_admin, Role.issue_admin)),
):
    idem_key = idem.extract_key(request)
    fp = idem.fingerprint(body.model_dump(mode="json"))
    if idem_key:
        replayed = idem.replay(db, actor_id=admin.id, action="coupon.issue_batch", key=idem_key, request_hash=fp)
        if replayed is not None:
            return replayed
        idem.sweep_with_settings(db)
    template = db.get(CouponTemplate, body.template_id)
    try:
        require_issuable_template(db, template)
    except EligibilityError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

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
        except EligibilityError as exc:
            failed.append({"user_id": uid, "username": user.username, "reason": str(exc)})
    write_audit(
        db,
        actor_id=admin.id,
        action="issue_coupon_batch",
        target_type="template",
        target_id=template.id,
        detail=f"users={len(body.user_ids)}, qty_each={body.quantity}, ok={len(all_created)}, fail={len(failed)}",
    )
    db.flush()  # 分配实例主键（Python 端 default 在 flush 时生效）
    loaded = _preload_coupons(db, [c.id for c in all_created])
    issued = [coupon_to_out(c) for c in loaded]
    result = BatchIssueResult(issued=issued, failed=failed).model_dump(mode="json")
    if idem_key:
        idem.store(db, actor_id=admin.id, action="coupon.issue_batch", key=idem_key, request_hash=fp, result=result)
    raced = idem.commit_idempotent(db, actor_id=admin.id, action="coupon.issue_batch", key=idem_key, request_hash=fp)
    if raced is not None:
        return raced
    return result


@router.post("/issue-import", response_model=ImportResultOut)
def issue_coupons_import(
    request: Request,
    file: UploadFile = File(..., description="用户标识名单（.xlsx / .csv / .txt / .docx）"),
    template_id: str = Form(...),
    quantity: int = Form(1, ge=1, le=10),
    db: Session = Depends(get_db),
    admin: Account = Depends(require_roles(Role.super_admin, Role.issue_admin)),
):
    """按名单文件发券：每行一个用户标识（用户名 / 邮箱 / 手机 / 学号）。

    复用单用户发券的全部校验（核验状态、模板/商家可用性），单行失败记入
    errors 不中断；未核验、查无此人的行会明确报错。支持 Idempotency-Key：
    同 key + 同文件重放不重复发券。
    """
    settings = get_settings()
    idem_key = idem.extract_key(request)
    try:
        data = read_upload_bytes(file.file)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    # 请求摘要以文件内容哈希代替原始文件：名单内容不入幂等记录
    fp = idem.fingerprint(
        {
            "template_id": template_id,
            "quantity": quantity,
            "file_sha256": hashlib.sha256(data).hexdigest(),
        }
    )
    if idem_key:
        replayed = idem.replay(db, actor_id=admin.id, action="coupon.issue_import", key=idem_key, request_hash=fp)
        if replayed is not None:
            return replayed
        idem.sweep_with_settings(db)
    template = db.get(CouponTemplate, template_id)
    try:
        require_issuable_template(db, template)
    except EligibilityError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
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
        except EligibilityError as exc:
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
    shown = errors[:100]
    message = f"按名单发券完成：共 {len(data_rows)} 行，成功 {ok} 人（{len(created_all)} 张券），失败 {len(errors)} 行"
    if len(errors) > len(shown):
        message += "（错误明细仅显示前 100 条）"
    result = ImportResultOut(
        total=len(data_rows),
        succeeded=ok,
        failed=len(errors),
        errors=shown,
        message=message,
    ).model_dump(mode="json")
    if idem_key:
        idem.store(db, actor_id=admin.id, action="coupon.issue_import", key=idem_key, request_hash=fp, result=result)
    raced = idem.commit_idempotent(db, actor_id=admin.id, action="coupon.issue_import", key=idem_key, request_hash=fp)
    if raced is not None:
        return raced
    return result


@router.post("/preview", response_model=CouponOut)
def preview_coupon(
    body: PreviewIn,
    db: Session = Depends(get_db),
    account: Account = Depends(require_roles(Role.merchant)),
) -> CouponOut:
    """商家核销前预览，不改变状态。仅接受用户出示的动态券码。

    动态凭证经 body 传输，避免 JWT 进入访问日志的 query 记录。
    """
    if not account.merchant_id:
        raise HTTPException(status_code=400, detail="商家账号未绑定门店")
    merchant = db.get(Merchant, account.merchant_id)
    if not merchant or not merchant.is_active:
        raise HTTPException(status_code=400, detail="门店已停用，无法核销")
    raw = body.code.strip()
    if not looks_like_live_code(raw):
        raise HTTPException(
            status_code=400,
            detail="请使用用户出示的动态券码；永久编号仅用于查询，不能核销",
        )
    try:
        decode_live_code(raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    coupon = _resolve_coupon_by_code(db, raw)
    if not coupon:
        raise HTTPException(status_code=404, detail="券码无效或动态码已过期")
    _transition_expired(db, coupon)
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
    _transition_expired(db, coupon)
    db.commit()
    if coupon.status != CouponStatus.unused:
        raise HTTPException(status_code=400, detail=f"当前状态不可出示：{coupon.status.value}")
    live, seconds, exp = create_live_code(
        coupon_id=coupon.id,
        user_id=account.id,
    )
    template = db.get(CouponTemplate, coupon.template_id)
    merchant = db.get(Merchant, coupon.merchant_id)
    # 响应不再包含永久编号：它不是备用核销凭证，展示只会误导“抄码核销”
    return LiveCodeOut(
        coupon_id=coupon.id,
        live_code=live,
        expires_in=seconds,
        expires_at=exp,
        template_name=coupon.template_name or (template.name if template else None),
        merchant_name=merchant.name if merchant else None,
    )


def _day_bounds(date_from: date_cls | None, date_to: date_cls | None) -> tuple[datetime | None, datetime | None]:
    # T18：业务日期区间统一按 Asia/Shanghai 划日
    return day_bounds_utc_closed(date_from, date_to)


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
    expire_stale_coupons(db, interval_seconds=get_settings().coupon_expire_scan_interval)
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


@router.get("/my", response_model=Page[CouponOut])
def my_coupons(
    status: CouponStatus | None = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
    account: Account = Depends(require_roles(Role.user)),
) -> Page[CouponOut]:
    # T18：明确分页 + 稳定排序（issued_at desc, id desc）；前后端同批升级为 Page 结构
    expire_stale_coupons(db, interval_seconds=get_settings().coupon_expire_scan_interval)
    base = (
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
        base = base.filter(CouponInstance.status == status)
    total = base.count()
    rows = base.offset(skip).limit(limit).all()
    return Page(total=total, items=[coupon_to_out(r) for r in rows])


@router.get("/instances/{coupon_id}/status")
def my_coupon_status(
    coupon_id: str,
    db: Session = Depends(get_db),
    account: Account = Depends(require_roles(Role.user)),
) -> dict:
    """本人单券轻量状态（T18）：出码弹窗轮询不再读取全部券，成本不随券数增长。"""
    coupon = (
        db.query(CouponInstance)
        .filter(CouponInstance.id == coupon_id, CouponInstance.user_id == account.id)
        .first()
    )
    if not coupon:
        raise HTTPException(status_code=404, detail="券不存在")
    _transition_expired(db, coupon)
    db.commit()
    return {
        "id": coupon.id,
        "status": coupon.status.value,
        "expires_at": coupon.expires_at,
        "redeemed_at": coupon.redeemed_at,
        "void_reason": coupon.void_reason or "",
    }


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
    _transition_expired(db, coupon)
    db.commit()
    db.refresh(coupon)
    if coupon.status != CouponStatus.unused:
        raise HTTPException(status_code=400, detail=f"仅未使用的券可作废，当前状态：{coupon.status.value}")
    # 条件更新限定 unused：与商家核销并发时，作废和核销只有一个能在数据库层成功
    updated = (
        db.query(CouponInstance)
        .filter(CouponInstance.id == coupon_id, CouponInstance.status == CouponStatus.unused)
        .update(
            {CouponInstance.status: CouponStatus.void, CouponInstance.void_reason: body.reason},
            synchronize_session=False,
        )
    )
    if not updated:
        db.rollback()
        db.refresh(coupon)
        raise HTTPException(
            status_code=400,
            detail=f"作废失败，券状态已变化（当前：{coupon.status.value}）",
        )
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


def _log_failed_redeem(
    db: Session,
    *,
    merchant_id: str,
    operator_id: str,
    coupon: CouponInstance | None,
    display_code: str,
    reason: str,
    message: str,
) -> None:
    """失败核销写入独立事务：状态事务回滚后失败证据仍需保留。

    跨店失败（coupon.merchant_id 非本店）不落他店用户标识，
    避免商家从失败流水枚举他店客户。
    """
    same_store = coupon is not None and coupon.merchant_id == merchant_id
    db.add(
        RedemptionLog(
            coupon_id=coupon.id if coupon else None,
            merchant_id=merchant_id,
            operator_id=operator_id,
            user_id=coupon.user_id if same_store else None,
            code=display_code[:32],
            result="failed",
            reason=reason,
            message=message[:255],
        )
    )
    db.commit()
    # T22：失败原因进业务指标（原因码稳定，见下方常量表）
    try:
        from app.core.logging import request_id_var
        from app.services.metrics import note_redeem

        note_redeem("failed", reason, request_id_var.get(""))
    except Exception:  # noqa: BLE001 — 指标采集不得影响业务流
        pass


# 稳定失败原因码：前端/报表据此分类，不解析中文 message
REDEEM_REASON_ALREADY_USED = "already_used"
REDEEM_REASON_VOIDED = "voided"
REDEEM_REASON_EXPIRED = "expired"
REDEEM_REASON_WRONG_MERCHANT = "wrong_merchant"
REDEEM_REASON_INVALID_LIVE_CODE = "invalid_live_code"
REDEEM_REASON_STATE_CONFLICT = "state_conflict"
REDEEM_REASON_MERCHANT_INACTIVE = "merchant_inactive"

_STATUS_REASON = {
    CouponStatus.used: (REDEEM_REASON_ALREADY_USED, "该券已核销"),
    CouponStatus.void: (REDEEM_REASON_VOIDED, "该券已作废"),
    CouponStatus.expired: (REDEEM_REASON_EXPIRED, "该券已过期"),
}


@router.post("/redeem", response_model=RedeemOut)
def redeem(
    body: RedeemIn,
    request: Request,
    db: Session = Depends(get_db),
    account: Account = Depends(require_roles(Role.merchant)),
) -> RedeemOut:
    # T16：核销支持 Idempotency-Key——响应丢失（超时）后同 key 重试重放原结果，
    # 失败（4xx）不留记录，重试重新确定性判定
    idem_key = idem.extract_key(request)
    fp = idem.fingerprint(body.model_dump(mode="json"))
    if idem_key:
        replayed = idem.replay(db, actor_id=account.id, action="coupon.redeem", key=idem_key, request_hash=fp)
        if replayed is not None:
            return RedeemOut(**replayed)
    if not account.merchant_id:
        # 无绑定门店：无法满足 redemption_logs 的合法外键，走结构化日志留痕
        logger.warning(
            "coupon.redeem.rejected",
            extra={"operator_id": account.id, "reason": "merchant_unbound"},
        )
        raise HTTPException(status_code=400, detail="商家账号未绑定门店")
    merchant = db.get(Merchant, account.merchant_id)
    if not merchant:
        # 门店记录已缺失：同样无法写核销流水外键，只留结构化日志
        logger.warning(
            "coupon.redeem.rejected",
            extra={
                "operator_id": account.id,
                "merchant_id": account.merchant_id,
                "reason": "merchant_missing",
            },
        )
        raise HTTPException(status_code=400, detail="门店已停用，无法核销")
    if not merchant.is_active:
        # 门店存在但停用：拒绝前必须留下可查询的失败流水（审查报告 F05）
        raw_head = body.code.strip()
        _log_failed_redeem(
            db,
            merchant_id=account.merchant_id,
            operator_id=account.id,
            coupon=None,
            display_code=raw_head[:24] + "..." if looks_like_live_code(raw_head) else raw_head.upper(),
            reason=REDEEM_REASON_MERCHANT_INACTIVE,
            message="门店已停用，无法核销",
        )
        raise HTTPException(status_code=400, detail="门店已停用，无法核销")
    raw = body.code.strip()
    display_code = raw[:24] + "..." if looks_like_live_code(raw) else raw.upper()
    # 日志只保留展示片段，不保存完整动态 token

    if not looks_like_live_code(raw):
        _log_failed_redeem(
            db,
            merchant_id=account.merchant_id,
            operator_id=account.id,
            coupon=None,
            display_code=display_code,
            reason=REDEEM_REASON_INVALID_LIVE_CODE,
            message="核销需使用动态券码，永久编号已不能核销",
        )
        raise HTTPException(
            status_code=400,
            detail="核销需使用用户出示的动态券码；永久编号仅用于查询，不能核销",
        )
    try:
        decode_live_code(raw)
    except ValueError as exc:
        _log_failed_redeem(
            db,
            merchant_id=account.merchant_id,
            operator_id=account.id,
            coupon=None,
            display_code=display_code,
            reason=REDEEM_REASON_INVALID_LIVE_CODE,
            message=str(exc),
        )
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    coupon = _resolve_coupon_by_code(db, raw)
    if not coupon:
        _log_failed_redeem(
            db,
            merchant_id=account.merchant_id,
            operator_id=account.id,
            coupon=None,
            display_code=display_code,
            reason=REDEEM_REASON_INVALID_LIVE_CODE,
            message="券码无效或动态码已过期",
        )
        raise HTTPException(status_code=404, detail="券码无效或动态码已过期")

    _transition_expired(db, coupon)
    db.commit()
    db.refresh(coupon)

    if coupon.merchant_id != account.merchant_id:
        _log_failed_redeem(
            db,
            merchant_id=account.merchant_id,
            operator_id=account.id,
            coupon=coupon,
            display_code=display_code,
            reason=REDEEM_REASON_WRONG_MERCHANT,
            message="非本店可用券",
        )
        raise HTTPException(status_code=400, detail="该券仅限指定商家核销，非本店券")
    if coupon.status != CouponStatus.unused:
        reason, message = _STATUS_REASON.get(
            coupon.status, (REDEEM_REASON_STATE_CONFLICT, "券状态不可核销")
        )
        _log_failed_redeem(
            db,
            merchant_id=account.merchant_id,
            operator_id=account.id,
            coupon=coupon,
            display_code=display_code,
            reason=reason,
            message=message,
        )
        raise HTTPException(status_code=400, detail=message)

    now = datetime.now(timezone.utc)
    # 条件更新把 unused、有效期一起放进 WHERE：双核销/作废竞争/临界过期
    # 都由数据库判定，只有一方能成功
    updated = (
        db.query(CouponInstance)
        .filter(
            CouponInstance.id == coupon.id,
            CouponInstance.status == CouponStatus.unused,
            CouponInstance.expires_at > now,
        )
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
        winner = db.get(CouponInstance, coupon.id)
        reason, message = _STATUS_REASON.get(
            winner.status, (REDEEM_REASON_STATE_CONFLICT, "核销失败，券状态已变化")
        )
        if winner.status == CouponStatus.unused:
            reason, message = REDEEM_REASON_EXPIRED, "该券已过期，无法核销"
        _log_failed_redeem(
            db,
            merchant_id=account.merchant_id,
            operator_id=account.id,
            coupon=winner,
            display_code=display_code,
            reason=reason,
            message=message,
        )
        raise HTTPException(status_code=400, detail=message)

    db.add(
        RedemptionLog(
            coupon_id=coupon.id,
            merchant_id=account.merchant_id,
            operator_id=account.id,
            user_id=coupon.user_id,
            code=coupon.code[:32],
            result="success",
            reason="redeemed",
            message="核销成功",
        )
    )
    write_audit(
        db,
        actor_id=account.id,
        action="redeem_coupon",
        target_type="coupon",
        target_id=coupon.id,
        detail=coupon.code,
    )
    # 同事务内 refresh 拿到核销后状态，构建可重放结果
    db.refresh(coupon)
    result = RedeemOut(message="核销成功", coupon=coupon_to_out(coupon)).model_dump(mode="json")
    if idem_key:
        idem.store(
            db,
            actor_id=account.id,
            action="coupon.redeem",
            key=idem_key,
            request_hash=fp,
            result=result,
        )
    raced = idem.commit_idempotent(
        db, actor_id=account.id, action="coupon.redeem", key=idem_key, request_hash=fp
    )
    if raced is not None:
        logger.info(
            "coupon.redeem.replayed",
            extra={"coupon_id": coupon.id, "merchant_id": account.merchant_id, "operator_id": account.id},
        )
        return RedeemOut(**raced)
    # T22：成功核销进业务指标
    try:
        from app.core.logging import request_id_var
        from app.services.metrics import note_redeem

        note_redeem("success", "redeemed", request_id_var.get("-"))
    except Exception:  # noqa: BLE001
        pass
    logger.info(
        "coupon.redeem",
        extra={
            "coupon_id": coupon.id,
            "merchant_id": account.merchant_id,
            "operator_id": account.id,
            "user_id": coupon.user_id,
        },
    )
    return RedeemOut(**result)


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
                reason=r.reason or ("legacy_unknown" if r.result == "failed" else ""),
                message=r.message,
                created_at=r.created_at,
            )
        )
    return Page(total=total, items=items)
