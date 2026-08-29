from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session, joinedload

from app.core.config import get_settings
from app.core.database import get_db
from app.core.deps import require_roles
from app.models.entities import (
    Account,
    CouponInstance,
    CouponStatus,
    CouponTemplate,
    Merchant,
    PointLedger,
    Role,
    UserProfile,
    VerifyStatus,
)
from app.schemas.bulk_import import ImportResultOut, ImportRowError
from app.schemas.common import MessageOut, Page
from app.schemas.coupon import CouponOut
from app.schemas.points import (
    BatchGrantPointsIn,
    ExchangeIn,
    ExchangeOut,
    GrantPointsIn,
    PointAccountOut,
    PointLedgerOut,
)
from app.services.audit import write_audit
from app.services.points import apply_points, get_or_create_account, quantize_hours
from app.services.import_file import (
    KIND_POINTS,
    map_columns,
    parse_table_file,
    read_upload_bytes,
    resolve_user,
)
import secrets
import string

router = APIRouter(prefix="/points", tags=["志愿服务时长"])


def _gen_code(length: int = 10) -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _coupon_out(c: CouponInstance) -> CouponOut:
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


@router.get("/me", response_model=PointAccountOut)
def my_points(
    account: Account = Depends(require_roles(Role.user)),
    db: Session = Depends(get_db),
) -> PointAccountOut:
    acc = get_or_create_account(db, account.id)
    db.commit()
    return PointAccountOut(user_id=acc.user_id, balance=acc.balance, updated_at=acc.updated_at)


@router.get("/me/ledger", response_model=Page[PointLedgerOut])
def my_ledger(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    account: Account = Depends(require_roles(Role.user)),
    db: Session = Depends(get_db),
) -> Page[PointLedgerOut]:
    q = db.query(PointLedger).filter(PointLedger.user_id == account.id).order_by(PointLedger.created_at.desc())
    total = q.count()
    rows = q.offset(skip).limit(limit).all()
    return Page(total=total, items=[PointLedgerOut.model_validate(r) for r in rows])


@router.get("/users/{user_id}", response_model=PointAccountOut)
def user_points(
    user_id: str,
    db: Session = Depends(get_db),
    _: Account = Depends(require_roles(Role.super_admin, Role.issue_admin)),
) -> PointAccountOut:
    user = db.get(Account, user_id)
    if not user or user.role != Role.user:
        raise HTTPException(status_code=404, detail="用户不存在")
    acc = get_or_create_account(db, user_id)
    db.commit()
    return PointAccountOut(user_id=acc.user_id, balance=acc.balance, updated_at=acc.updated_at)


@router.get("/ledger", response_model=Page[PointLedgerOut])
def admin_ledger(
    user_id: str | None = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
    _: Account = Depends(require_roles(Role.super_admin, Role.issue_admin)),
) -> Page[PointLedgerOut]:
    q = db.query(PointLedger).order_by(PointLedger.created_at.desc())
    if user_id:
        q = q.filter(PointLedger.user_id == user_id)
    total = q.count()
    rows = q.offset(skip).limit(limit).all()
    return Page(total=total, items=[PointLedgerOut.model_validate(r) for r in rows])


def _grant_one(
    db: Session,
    *,
    user_id: str,
    amount: Decimal,
    reason: str,
    admin: Account,
) -> PointAccountOut:
    user = db.get(Account, user_id)
    if not user or user.role != Role.user:
        raise ValueError("目标用户无效")
    profile = db.query(UserProfile).filter(UserProfile.account_id == user.id).first()
    if not profile or profile.verify_status != VerifyStatus.approved:
        raise ValueError("仅可为已核验用户调整时长")
    amount = quantize_hours(amount)
    ref_type = "grant" if amount > 0 else "adjust"
    try:
        acc = apply_points(
            db,
            user_id=user.id,
            change=amount,
            reason=reason,
            operator_id=admin.id,
            ref_type=ref_type,
        )
    except ValueError as exc:
        raise ValueError(str(exc)) from exc
    sign = f"+{amount}" if amount > 0 else str(amount)
    write_audit(
        db,
        actor_id=admin.id,
        action="grant_points" if amount > 0 else "adjust_points",
        target_type="user",
        target_id=user.id,
        detail=f"{sign} {reason}",
    )
    return PointAccountOut(user_id=acc.user_id, balance=acc.balance, updated_at=acc.updated_at)


@router.post("/grant", response_model=PointAccountOut)
def grant_points(
    body: GrantPointsIn,
    db: Session = Depends(get_db),
    admin: Account = Depends(require_roles(Role.super_admin, Role.issue_admin)),
) -> PointAccountOut:
    try:
        out = _grant_one(
            db,
            user_id=body.user_id,
            amount=body.amount,
            reason=body.reason,
            admin=admin,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    return out


@router.post("/grant-batch", response_model=MessageOut)
def grant_points_batch(
    body: BatchGrantPointsIn,
    db: Session = Depends(get_db),
    admin: Account = Depends(require_roles(Role.super_admin, Role.issue_admin)),
) -> MessageOut:
    ok = 0
    failed: list[str] = []
    for uid in body.user_ids:
        try:
            _grant_one(db, user_id=uid, amount=body.amount, reason=body.reason, admin=admin)
            ok += 1
        except ValueError as exc:
            failed.append(f"{uid[:8]}:{exc}")
    db.commit()
    msg = f"成功 {ok} 人"
    if failed:
        msg += f"，失败 {len(failed)}：{'; '.join(failed[:5])}"
    return MessageOut(message=msg)


@router.post("/grant-import", response_model=ImportResultOut)
def grant_points_import(
    file: UploadFile = File(..., description="时长名单（.xlsx / .csv / .txt / .docx）"),
    reason: str = Form("志愿服务时长入账", description="行内未填说明时使用的默认说明"),
    db: Session = Depends(get_db),
    admin: Account = Depends(require_roles(Role.super_admin, Role.issue_admin)),
) -> ImportResultOut:
    """按名单文件调整时长：每行「用户标识、时长(小时)、说明(可选)」。

    复用单人发放的全部校验（核验状态、两位小数、余额不为负），单行失败
    记入 errors 不中断；时长支持负数（扣减）。
    """
    settings = get_settings()
    try:
        data = read_upload_bytes(file.file)
        rows = parse_table_file(file.filename or "", data, max_rows=settings.import_max_rows)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    header = map_columns(rows[0], KIND_POINTS)
    data_rows = rows[1:] if header else rows

    def cell_of(row: list[str], logical: str, position: int | None) -> str:
        idx = header.get(logical) if header else position
        if idx is None or idx >= len(row):
            return ""
        return row[idx]

    default_reason = (reason or "").strip()[:255] or "志愿服务时长入账"
    errors: list[ImportRowError] = []
    ok = 0
    for lineno, row in enumerate(data_rows, start=1):
        token = cell_of(row, "identifier", 0)
        hours_raw = cell_of(row, "hours", 1)
        row_reason = cell_of(row, "reason", 2)[:255] or default_reason
        if not token:
            errors.append(ImportRowError(row=lineno, identifier=hours_raw, reason="用户标识为空"))
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
            amount = Decimal(hours_raw)
        except (InvalidOperation, ValueError):
            errors.append(ImportRowError(row=lineno, identifier=token, reason=f"时长格式无效：{hours_raw}"))
            continue
        try:
            _grant_one(db, user_id=user.id, amount=amount, reason=row_reason, admin=admin)
        except (ValueError, ArithmeticError) as exc:
            errors.append(ImportRowError(row=lineno, identifier=token, reason=str(exc)))
            continue
        ok += 1

    write_audit(
        db,
        actor_id=admin.id,
        action="grant_points_import",
        target_type="account",
        detail=f"rows={len(data_rows)}, ok={ok}, fail={len(errors)}",
    )
    db.commit()
    shown = errors[:100]
    message = f"按名单时长调整完成：共 {len(data_rows)} 行，成功 {ok} 行，失败 {len(errors)} 行"
    if len(errors) > len(shown):
        message += "（错误明细仅显示前 100 条）"
    return ImportResultOut(
        total=len(data_rows),
        succeeded=ok,
        failed=len(errors),
        errors=shown,
        message=message,
    )


@router.get("/catalog")
def exchange_catalog(
    db: Session = Depends(get_db),
    account: Account = Depends(require_roles(Role.user, Role.super_admin, Role.issue_admin)),
) -> list[dict]:
    rows = (
        db.query(CouponTemplate)
        .options(joinedload(CouponTemplate.merchant))
        .filter(CouponTemplate.is_active.is_(True), CouponTemplate.cost_points > 0)
        .order_by(CouponTemplate.cost_points.asc())
        .all()
    )
    items = []
    for t in rows:
        merchant = t.merchant
        items.append(
            {
                "id": t.id,
                "name": t.name,
                "description": t.description,
                "merchant_id": t.merchant_id,
                "merchant_name": merchant.name if merchant else None,
                "valid_days": t.valid_days,
                "cost_points": quantize_hours(t.cost_points),
                "is_active": t.is_active,
                "created_at": t.created_at,
            }
        )
    return items


@router.post("/exchange", response_model=ExchangeOut)
def exchange(
    body: ExchangeIn,
    db: Session = Depends(get_db),
    account: Account = Depends(require_roles(Role.user)),
) -> ExchangeOut:
    profile = db.query(UserProfile).filter(UserProfile.account_id == account.id).first()
    if not profile or profile.verify_status != VerifyStatus.approved:
        raise HTTPException(status_code=400, detail="请先完成身份核验")
    template = db.get(CouponTemplate, body.template_id)
    cost = quantize_hours(getattr(template, "cost_points", 0) if template else 0)
    if not template or not template.is_active or cost <= 0:
        raise HTTPException(status_code=400, detail="该券不可兑换")
    merchant = db.get(Merchant, template.merchant_id)
    if not merchant or not merchant.is_active:
        raise HTTPException(status_code=400, detail="关联商家不可用")

    try:
        acc = apply_points(
            db,
            user_id=account.id,
            change=-cost,
            reason=f"兑换优惠券：{template.name}",
            operator_id=account.id,
            ref_type="exchange",
            ref_id=template.id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    now = datetime.now(timezone.utc)
    code = _gen_code()
    while db.query(CouponInstance).filter(CouponInstance.code == code).first():
        code = _gen_code()
    coupon = CouponInstance(
        code=code,
        user_id=account.id,
        template_id=template.id,
        merchant_id=template.merchant_id,
        status=CouponStatus.unused,
        issued_by=account.id,
        issued_at=now,
        expires_at=now + timedelta(days=template.valid_days),
    )
    db.add(coupon)
    write_audit(
        db,
        actor_id=account.id,
        action="exchange_coupon",
        target_type="template",
        target_id=template.id,
        detail=f"cost={cost}",
    )
    db.commit()
    db.refresh(coupon)
    db.refresh(acc)
    return ExchangeOut(
        message="兑换成功",
        balance=acc.balance,
        coupon=_coupon_out(coupon),
    )
