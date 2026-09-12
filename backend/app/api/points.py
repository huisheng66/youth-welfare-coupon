import hashlib
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from sqlalchemy import func
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
    PointAccount,
    PointLedger,
    Role,
)
from app.schemas.bulk_import import ImportResultOut, ImportRowError
from app.schemas.common import MessageOut, Page
from app.schemas.coupon import CouponOut
from app.schemas.points import (
    BatchGrantPointsIn,
    ExchangeBackIn,
    ExchangeBackOptionsOut,
    ExchangeBackOut,
    ExchangeIn,
    ExchangeOut,
    GrantPointsIn,
    PointAccountOut,
    PointLedgerOut,
)
from app.services.audit import write_audit
from app.services.eligibility import (
    EligibilityError,
    require_benefit_user,
    require_exchangeable_template,
)
from app.services import idempotency as idem
from app.services.points import ZERO, apply_points, get_or_create_account, quantize_hours
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
    # 统一资格检查（T12）：单人/批量/名单导入同一判定（角色/账号启用/核验状态）
    require_benefit_user(db, user, action="调整时长")
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
    request: Request,
    db: Session = Depends(get_db),
    admin: Account = Depends(require_roles(Role.super_admin, Role.issue_admin)),
):
    idem_key = idem.extract_key(request)
    fp = idem.fingerprint(body.model_dump(mode="json"))
    if idem_key:
        replayed = idem.replay(db, actor_id=admin.id, action="points.grant", key=idem_key, request_hash=fp)
        if replayed is not None:
            return replayed
        idem.sweep_with_settings(db)
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
    result = out.model_dump(mode="json")
    # 幂等记录与余额/账本写入同事务提交（T13）
    if idem_key:
        idem.store(db, actor_id=admin.id, action="points.grant", key=idem_key, request_hash=fp, result=result)
    raced = idem.commit_idempotent(db, actor_id=admin.id, action="points.grant", key=idem_key, request_hash=fp)
    if raced is not None:
        return raced
    return result


@router.post("/grant-batch", response_model=MessageOut)
def grant_points_batch(
    body: BatchGrantPointsIn,
    request: Request,
    db: Session = Depends(get_db),
    admin: Account = Depends(require_roles(Role.super_admin, Role.issue_admin)),
):
    idem_key = idem.extract_key(request)
    fp = idem.fingerprint(body.model_dump(mode="json"))
    if idem_key:
        replayed = idem.replay(db, actor_id=admin.id, action="points.grant_batch", key=idem_key, request_hash=fp)
        if replayed is not None:
            return replayed
        idem.sweep_with_settings(db)
    ok = 0
    failed: list[str] = []
    for uid in body.user_ids:
        try:
            _grant_one(db, user_id=uid, amount=body.amount, reason=body.reason, admin=admin)
            ok += 1
        except ValueError as exc:
            failed.append(f"{uid[:8]}:{exc}")
    msg = f"成功 {ok} 人"
    if failed:
        msg += f"，失败 {len(failed)}：{'; '.join(failed[:5])}"
    result = MessageOut(message=msg).model_dump(mode="json")
    if idem_key:
        idem.store(db, actor_id=admin.id, action="points.grant_batch", key=idem_key, request_hash=fp, result=result)
    raced = idem.commit_idempotent(db, actor_id=admin.id, action="points.grant_batch", key=idem_key, request_hash=fp)
    if raced is not None:
        return raced
    return result


@router.post("/grant-import", response_model=ImportResultOut)
def grant_points_import(
    request: Request,
    file: UploadFile = File(..., description="时长名单（.xlsx / .csv / .txt / .docx）"),
    reason: str = Form("志愿服务时长入账", description="行内未填说明时使用的默认说明"),
    db: Session = Depends(get_db),
    admin: Account = Depends(require_roles(Role.super_admin, Role.issue_admin)),
):
    """按名单文件调整时长：每行「用户标识、时长(小时)、说明(可选)」。

    复用单人发放的全部校验（核验状态、两位小数、余额不为负），单行失败
    记入 errors 不中断；时长支持负数（扣减）。支持 Idempotency-Key：
    同 key + 同文件重放不重复入账。
    """
    settings = get_settings()
    idem_key = idem.extract_key(request)
    try:
        data = read_upload_bytes(file.file)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    fp = idem.fingerprint(
        {"reason": reason, "file_sha256": hashlib.sha256(data).hexdigest()}
    )
    if idem_key:
        replayed = idem.replay(db, actor_id=admin.id, action="points.grant_import", key=idem_key, request_hash=fp)
        if replayed is not None:
            return replayed
        idem.sweep_with_settings(db)
    try:
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
    shown = errors[:100]
    message = f"按名单时长调整完成：共 {len(data_rows)} 行，成功 {ok} 行，失败 {len(errors)} 行"
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
        idem.store(db, actor_id=admin.id, action="points.grant_import", key=idem_key, request_hash=fp, result=result)
    raced = idem.commit_idempotent(db, actor_id=admin.id, action="points.grant_import", key=idem_key, request_hash=fp)
    if raced is not None:
        return raced
    return result


@router.get("/catalog")
def exchange_catalog(
    db: Session = Depends(get_db),
    account: Account = Depends(require_roles(Role.user, Role.super_admin, Role.issue_admin)),
) -> list[dict]:
    # 目录提前过滤停用门店（T12）：不让用户点击后才发现商家不可用
    rows = (
        db.query(CouponTemplate)
        .join(Merchant, CouponTemplate.merchant_id == Merchant.id)
        .options(joinedload(CouponTemplate.merchant))
        .filter(
            CouponTemplate.is_active.is_(True),
            CouponTemplate.cost_points > 0,
            Merchant.is_active.is_(True),
        )
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
    request: Request,
    db: Session = Depends(get_db),
    account: Account = Depends(require_roles(Role.user)),
):
    idem_key = idem.extract_key(request)
    fp = idem.fingerprint(body.model_dump(mode="json"))
    if idem_key:
        replayed = idem.replay(db, actor_id=account.id, action="points.exchange", key=idem_key, request_hash=fp)
        if replayed is not None:
            return replayed
        idem.sweep_with_settings(db)
    template = db.get(CouponTemplate, body.template_id)
    try:
        # 统一资格检查（T12）：与发券/入账同一判定，复核期间暂停兑换
        require_benefit_user(db, account, action="兑换")
        require_exchangeable_template(db, template)
    except EligibilityError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    cost = quantize_hours(template.cost_points)
    if cost <= 0:
        raise HTTPException(status_code=400, detail="该券不可兑换")

    # 先建券实例并 flush 取 id：兑换账本的 ref_id 关联实际券而非模板，
    # 扣减失败时整个事务回滚，不会留下“有券无扣减”或“有扣减无券”
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
        template_name=template.name,
        template_description=template.description,
    )
    db.add(coupon)
    db.flush()

    try:
        acc = apply_points(
            db,
            user_id=account.id,
            change=-cost,
            reason=f"兑换优惠券：{template.name}",
            operator_id=account.id,
            ref_type="exchange",
            ref_id=coupon.id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    write_audit(
        db,
        actor_id=account.id,
        action="exchange_coupon",
        target_type="template",
        target_id=template.id,
        detail=f"cost={cost}, coupon={coupon.id}",
    )
    result = ExchangeOut(
        message="兑换成功",
        balance=acc.balance,
        coupon=_coupon_out(coupon),
    ).model_dump(mode="json")
    # 幂等记录与券实例/账本同一事务提交：重放不重复扣时长、不重复出券（T13）
    if idem_key:
        idem.store(db, actor_id=account.id, action="points.exchange", key=idem_key, request_hash=fp, result=result)
    raced = idem.commit_idempotent(db, actor_id=account.id, action="points.exchange", key=idem_key, request_hash=fp)
    if raced is not None:
        return raced
    return result


VOID_REASON_EXCHANGE_BACK = "换回志愿服务时长"


@router.get("/exchange-back/options", response_model=ExchangeBackOptionsOut)
def exchange_back_options(
    db: Session = Depends(get_db),
    account: Account = Depends(require_roles(Role.user, Role.super_admin, Role.issue_admin)),
):
    """券换时长（T24）：本人可换回时长的未使用券清单。

    仅限非时长兑换所得的未使用券（如管理员发放），按券模板当前标价折算
    退回时长；标价为 0 的券无法折算，不进入清单。兑换所得的券不可换回
    （单向流动），经账本 ref_type=exchange 的 ref_id 识别。
    """
    rows = (
        db.query(CouponInstance)
        .join(CouponTemplate, CouponInstance.template_id == CouponTemplate.id)
        .options(joinedload(CouponInstance.template), joinedload(CouponInstance.merchant))
        .filter(
            CouponInstance.user_id == account.id,
            CouponInstance.status == CouponStatus.unused,
            CouponTemplate.cost_points > 0,
        )
        .order_by(CouponInstance.expires_at.asc())
        .all()
    )
    # 兑换所得的券排除在可换清单外（批量查账本，避免逐行 N+1）
    exchanged_ids: set[str] = set()
    if rows:
        exchanged_ids = {
            rid
            for (rid,) in db.query(PointLedger.ref_id)
            .filter(
                PointLedger.ref_type == "exchange",
                PointLedger.ref_id.in_([c.id for c in rows]),
            )
            .all()
        }
    items = []
    for c in rows:
        if c.id in exchanged_ids:
            continue
        template = c.template
        items.append(
            {
                "coupon_id": c.id,
                "code": c.code,
                # 优先发放时快照；历史行无快照回退模板当前名称
                "template_name": c.template_name or (template.name if template else None),
                "merchant_name": c.merchant.name if c.merchant else None,
                "expires_at": c.expires_at,
                "refund_hours": quantize_hours(template.cost_points),
            }
        )
    return ExchangeBackOptionsOut(items=items)


@router.post("/exchange-back", response_model=ExchangeBackOut)
def exchange_back(
    body: ExchangeBackIn,
    request: Request,
    db: Session = Depends(get_db),
    account: Account = Depends(require_roles(Role.user)),
):
    """券换时长（T24）：把本人一张未使用券作废，按模板当前标价换回时长。

    单向流动（T24b）：仅限非时长兑换所得的券（兑换所得的券不可换回），
    换回即作废（每张券自然只有一次）；作废券与退回时长在同一事务完成。
    并发竞争由券状态条件更新兜底（单胜者，与核销同一模式）。
    """
    idem_key = idem.extract_key(request)
    fp = idem.fingerprint(body.model_dump(mode="json"))
    if idem_key:
        replayed = idem.replay(db, actor_id=account.id, action="points.exchange_back", key=idem_key, request_hash=fp)
        if replayed is not None:
            return replayed
        idem.sweep_with_settings(db)
    try:
        require_benefit_user(db, account, action="换回时长")
    except EligibilityError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    coupon = db.get(CouponInstance, body.coupon_id)
    # 他人券与不存在的券同一响应，避免券枚举
    if not coupon or coupon.user_id != account.id:
        raise HTTPException(status_code=404, detail="券不存在")

    # 过期转换与核销同一数据库级条件更新写法：已过期的未使用券不能换回时长
    now = datetime.now(timezone.utc)
    expired_now = (
        db.query(CouponInstance)
        .filter(
            CouponInstance.id == coupon.id,
            CouponInstance.status == CouponStatus.unused,
            CouponInstance.expires_at <= now,
        )
        .update({CouponInstance.status: CouponStatus.expired}, synchronize_session=False)
    )
    if expired_now:
        raise HTTPException(status_code=400, detail="该券已过期，无法换回时长")
    if coupon.status != CouponStatus.unused:
        raise HTTPException(status_code=400, detail="仅未使用的券可换回时长")
    # 单向流动（T24b）：时长换券所得的券不可再换回时长，杜绝来回兑换环路
    exchange_source = (
        db.query(PointLedger.id)
        .filter(PointLedger.ref_type == "exchange", PointLedger.ref_id == coupon.id)
        .first()
    )
    if exchange_source is not None:
        raise HTTPException(status_code=400, detail="时长兑换所得的券不能换回时长")

    template = coupon.template
    if template is None:
        raise HTTPException(status_code=400, detail="券模板不存在，无法折算时长")
    refund = quantize_hours(template.cost_points)
    if refund <= ZERO:
        raise HTTPException(status_code=400, detail="该券未标价时长，无法换回")

    # 条件更新作废券（单胜者）：并发换回/核销同一张券时只有一方能改状态
    updated = (
        db.query(CouponInstance)
        .filter(CouponInstance.id == coupon.id, CouponInstance.status == CouponStatus.unused)
        .update(
            {
                CouponInstance.status: CouponStatus.void,
                CouponInstance.void_reason: VOID_REASON_EXCHANGE_BACK,
            },
            synchronize_session=False,
        )
    )
    if not updated:
        raise HTTPException(status_code=400, detail="券状态已变化，请刷新后重试")

    try:
        acc = apply_points(
            db,
            user_id=account.id,
            change=refund,
            reason=f"券换回时长：{template.name}",
            operator_id=account.id,
            ref_type="exchange_back",
            ref_id=coupon.id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    write_audit(
        db,
        actor_id=account.id,
        action="exchange_back_hours",
        target_type="coupon_instance",
        target_id=coupon.id,
        detail=f"refund={refund}",
    )
    db.refresh(coupon)
    result = ExchangeBackOut(
        message="换回成功",
        balance=acc.balance,
        refunded_hours=refund,
        coupon=_coupon_out(coupon),
    ).model_dump(mode="json")
    # 幂等记录与券作废/账本同一事务提交：重放不重复退时长、不重复作废（T13）
    if idem_key:
        idem.store(db, actor_id=account.id, action="points.exchange_back", key=idem_key, request_hash=fp, result=result)
    raced = idem.commit_idempotent(db, actor_id=account.id, action="points.exchange_back", key=idem_key, request_hash=fp)
    if raced is not None:
        return raced
    return result


@router.get("/reconcile")
def reconcile_balances(
    db: Session = Depends(get_db),
    _: Account = Depends(require_roles(Role.super_admin, Role.issue_admin)),
) -> dict:
    """只读对账：账户余额应等于该账户全部账本变更之和。

    返回不一致账户清单（最多 100 条），供人工核对期初余额与历史流水，
    不自动改写任何数据。
    """
    balances = dict(db.query(PointAccount.user_id, PointAccount.balance).all())
    sums = dict(
        db.query(PointLedger.user_id, func.sum(PointLedger.change))
        .group_by(PointLedger.user_id)
        .all()
    )
    mismatches: list[dict] = []
    for user_id in set(balances) | set(sums):
        balance = quantize_hours(balances.get(user_id) or ZERO)
        ledger_sum = quantize_hours(sums.get(user_id) or ZERO)
        if balance != ledger_sum:
            mismatches.append(
                {
                    "user_id": user_id,
                    "balance": float(balance),
                    "ledger_sum": float(ledger_sum),
                }
            )
    return {
        "accounts_checked": len(set(balances) | set(sums)),
        "mismatch_count": len(mismatches),
        "mismatches": mismatches[:100],
    }
