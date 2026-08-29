from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session, joinedload

from app.core.config import get_settings
from app.core.database import get_db
from app.core.deps import require_roles
from app.core.security import hash_password
from app.models.entities import Account, Role, UserProfile, UserVerification, VerifyStatus, utcnow
from app.schemas.bulk_import import ImportResultOut, ImportRowError
from app.schemas.common import MessageOut, Page
from app.schemas.user import (
    BankCardIn,
    BankCardPlainOut,
    BatchReviewIn,
    ProfileUpdateIn,
    ReviewVerificationIn,
    SubmitVerificationIn,
    UserListItem,
    VerificationOut,
)
from app.services.audit import write_audit
from app.services.crypto import decrypt_text, encrypt_text, mask_bank_card, validate_bank_card
from app.services.import_file import KIND_USERS, map_columns, parse_table_file, read_upload_bytes
from app.services.points import get_or_create_account
from app.services.sanitize import (
    password_has_letter_and_digit,
    sanitize_note,
    sanitize_plain_text,
    strip_control_chars,
    validate_password_strength,
)

router = APIRouter(prefix="/users", tags=["用户核验"])


def _latest_material(db: Session, profile_id: str) -> str | None:
    row = (
        db.query(UserVerification)
        .filter(UserVerification.profile_id == profile_id)
        .order_by(UserVerification.created_at.desc())
        .first()
    )
    return row.material_note if row else None


def _bulk_latest_materials(db: Session, profile_ids: list[str]) -> dict[str, str | None]:
    """批量取每个 profile 的最新一条 material_note，避免 N+1。"""
    if not profile_ids:
        return {}
    rows = (
        db.query(UserVerification)
        .filter(UserVerification.profile_id.in_(profile_ids))
        .order_by(UserVerification.profile_id, UserVerification.created_at.desc())
        .all()
    )
    result: dict[str, str | None] = {pid: None for pid in profile_ids}
    seen: set[str] = set()
    for v in rows:
        if v.profile_id not in seen:
            result[v.profile_id] = v.material_note
            seen.add(v.profile_id)
    return result


def _user_item(
    acc: Account,
    profile: UserProfile,
    db: Session,
    latest_material: str | None = None,
) -> UserListItem:
    bound = bool(profile.bank_card_encrypted)
    # 列表/资料接口不解密，仅展示脱敏
    masked = f"**** **** **** {profile.bank_card_last4}" if bound and profile.bank_card_last4 else ("****" if bound else None)
    if latest_material is None:
        latest_material = _latest_material(db, profile.id)
    return UserListItem(
        id=acc.id,
        username=acc.username,
        display_name=acc.display_name,
        phone=acc.phone,
        real_name=profile.real_name,
        organization=profile.organization,
        verify_status=profile.verify_status,
        created_at=acc.created_at,
        student_no=profile.student_no,
        remark=profile.remark,
        latest_material_note=latest_material,
        bank_card_bound=bound,
        bank_card_masked=masked,
        bank_card_bank_name=profile.bank_card_bank_name or None,
        bank_card_bound_at=profile.bank_card_bound_at,
    )


def _enrich_verification(db: Session, verification: UserVerification) -> VerificationOut:
    data = VerificationOut.model_validate(verification)
    # List endpoints eager-load this graph; retain a lazy fallback for single-row writes.
    profile = verification.profile
    if profile:
        acc = profile.account
        data.user_id = profile.account_id
        data.real_name = profile.real_name
        data.organization = profile.organization
        data.student_no = profile.student_no
        data.remark = profile.remark
        data.verify_status = profile.verify_status
        data.bank_card_bound = bool(profile.bank_card_encrypted)
        data.bank_card_masked = (
            f"**** **** **** {profile.bank_card_last4}"
            if profile.bank_card_encrypted and profile.bank_card_last4
            else ("****" if profile.bank_card_encrypted else None)
        )
        data.bank_card_bank_name = profile.bank_card_bank_name or None
        data.bank_card_bound_at = profile.bank_card_bound_at
        if acc:
            data.username = acc.username
            data.display_name = acc.display_name
            data.phone = acc.phone
            data.account_created_at = acc.created_at
    if verification.reviewer:
        data.reviewer_name = verification.reviewer.display_name or verification.reviewer.username
    return data


@router.get("/me/profile", response_model=UserListItem)
def my_profile(account: Account = Depends(require_roles(Role.user)), db: Session = Depends(get_db)) -> UserListItem:
    profile = db.query(UserProfile).filter(UserProfile.account_id == account.id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="资料不存在")
    return _user_item(account, profile, db)


@router.put("/me/profile", response_model=UserListItem)
def update_my_profile(
    body: ProfileUpdateIn,
    account: Account = Depends(require_roles(Role.user)),
    db: Session = Depends(get_db),
) -> UserListItem:
    profile = db.query(UserProfile).filter(UserProfile.account_id == account.id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="资料不存在")
    if body.display_name is not None:
        account.display_name = body.display_name
    if body.phone is not None:
        exists = db.query(Account).filter(Account.phone == body.phone, Account.id != account.id).first()
        if exists:
            raise HTTPException(status_code=400, detail="手机号已被占用")
        account.phone = body.phone
    profile.real_name = body.real_name
    profile.student_no = (body.student_no or "").strip()
    profile.organization = body.organization
    profile.remark = body.remark
    db.commit()
    return my_profile(account, db)


@router.put("/me/bank-card", response_model=UserListItem)
def bind_my_bank_card(
    body: BankCardIn,
    account: Account = Depends(require_roles(Role.user)),
    db: Session = Depends(get_db),
) -> UserListItem:
    """核验通过后自愿绑定/更新银行卡（库内加密存储）。"""
    profile = db.query(UserProfile).filter(UserProfile.account_id == account.id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="资料不存在")
    if profile.verify_status != VerifyStatus.approved:
        raise HTTPException(status_code=400, detail="仅核验通过后可自愿添加银行卡")
    try:
        digits = validate_bank_card(body.card_number)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    profile.bank_card_encrypted = encrypt_text(digits)
    profile.bank_card_last4 = digits[-4:]
    profile.bank_card_bank_name = body.bank_name
    profile.bank_card_bound_at = utcnow()
    write_audit(
        db,
        actor_id=account.id,
        action="bind_bank_card",
        target_type="profile",
        target_id=profile.id,
        detail=f"masked={mask_bank_card(digits)} bank={body.bank_name}",
    )
    db.commit()
    return _user_item(account, profile, db)


@router.delete("/me/bank-card", response_model=MessageOut)
def unbind_my_bank_card(
    account: Account = Depends(require_roles(Role.user)),
    db: Session = Depends(get_db),
) -> MessageOut:
    profile = db.query(UserProfile).filter(UserProfile.account_id == account.id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="资料不存在")
    if not profile.bank_card_encrypted:
        return MessageOut(message="当前未绑定银行卡")
    profile.bank_card_encrypted = None
    profile.bank_card_last4 = ""
    profile.bank_card_bank_name = ""
    profile.bank_card_bound_at = None
    write_audit(
        db,
        actor_id=account.id,
        action="unbind_bank_card",
        target_type="profile",
        target_id=profile.id,
    )
    db.commit()
    return MessageOut(message="已解除银行卡绑定")


@router.get("/{user_id}/bank-card", response_model=BankCardPlainOut)
def reveal_user_bank_card(
    user_id: str,
    db: Session = Depends(get_db),
    admin: Account = Depends(require_roles(Role.super_admin)),
) -> BankCardPlainOut:
    """超级管理员查看完整卡号（解密 + 审计）。发券管理员仅能看脱敏。"""
    profile = db.query(UserProfile).filter(UserProfile.account_id == user_id).first()
    if not profile or not profile.bank_card_encrypted:
        raise HTTPException(status_code=404, detail="该用户未绑定银行卡")
    try:
        plain = decrypt_text(profile.bank_card_encrypted)
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    write_audit(
        db,
        actor_id=admin.id,
        action="reveal_bank_card",
        target_type="account",
        target_id=user_id,
        detail=f"masked={mask_bank_card(plain)}",
    )
    db.commit()
    return BankCardPlainOut(
        user_id=user_id,
        card_number=plain,
        bank_card_masked=mask_bank_card(plain),
        bank_name=profile.bank_card_bank_name or "",
    )


@router.get("/me/verifications", response_model=list[VerificationOut])
def my_verifications(
    account: Account = Depends(require_roles(Role.user)),
    db: Session = Depends(get_db),
) -> list[VerificationOut]:
    profile = db.query(UserProfile).filter(UserProfile.account_id == account.id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="资料不存在")
    rows = (
        db.query(UserVerification)
        .options(
            joinedload(UserVerification.profile).joinedload(UserProfile.account),
            joinedload(UserVerification.reviewer),
        )
        .filter(UserVerification.profile_id == profile.id)
        .order_by(UserVerification.created_at.desc())
        .all()
    )
    return [_enrich_verification(db, r) for r in rows]


@router.post("/me/verifications", response_model=VerificationOut)
def submit_verification(
    body: SubmitVerificationIn,
    account: Account = Depends(require_roles(Role.user)),
    db: Session = Depends(get_db),
) -> VerificationOut:
    profile = db.query(UserProfile).filter(UserProfile.account_id == account.id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="资料不存在")
    if profile.verify_status == VerifyStatus.approved:
        raise HTTPException(status_code=400, detail="已通过核验，无需重复提交")
    if profile.verify_status == VerifyStatus.pending:
        raise HTTPException(status_code=400, detail="已有待审核申请")
    if not profile.real_name:
        raise HTTPException(status_code=400, detail="请先完善真实姓名等基本资料")
    verification = UserVerification(
        profile_id=profile.id,
        material_note=body.material_note,
        status=VerifyStatus.pending,
    )
    profile.verify_status = VerifyStatus.pending
    db.add(verification)
    write_audit(db, actor_id=account.id, action="submit_verification", target_type="profile", target_id=profile.id)
    db.commit()
    db.refresh(verification)
    return _enrich_verification(db, verification)


@router.get("", response_model=Page[UserListItem])
def list_users(
    verify_status: VerifyStatus | None = None,
    q: str | None = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    _: Account = Depends(require_roles(Role.super_admin, Role.issue_admin)),
) -> Page[UserListItem]:
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
    total = query.count()
    accounts = query.offset(skip).limit(limit).all()
    profile_ids = [acc.profile.id for acc in accounts if acc.profile]
    materials = _bulk_latest_materials(db, profile_ids)
    items = [
        _user_item(acc, acc.profile, db, materials.get(acc.profile.id))
        for acc in accounts
        if acc.profile
    ]
    return Page(total=total, items=items)


@router.get("/pending-verifications", response_model=list[VerificationOut])
def pending_verifications(
    db: Session = Depends(get_db),
    _: Account = Depends(require_roles(Role.super_admin, Role.issue_admin)),
) -> list[VerificationOut]:
    rows = (
        db.query(UserVerification)
        .options(
            joinedload(UserVerification.profile).joinedload(UserProfile.account),
            joinedload(UserVerification.reviewer),
        )
        .filter(UserVerification.status == VerifyStatus.pending)
        .order_by(UserVerification.created_at.asc())
        .all()
    )
    return [_enrich_verification(db, r) for r in rows]


@router.post("/import", response_model=ImportResultOut)
def import_users(
    file: UploadFile = File(..., description="用户名单（.xlsx / .csv / .txt / .docx）"),
    dry_run: bool = Form(False, description="仅校验不写入"),
    db: Session = Depends(get_db),
    admin: Account = Depends(require_roles(Role.super_admin, Role.issue_admin)),
) -> ImportResultOut:
    """按文件批量导入用户名单：导入即视为核验通过，使用统一初始密码。

    列（首行可为表头，无表头按此顺序）：姓名、学号、用户名、手机、组织、备注。
    用户名缺省时依次回退学号、手机；逐行校验并收集错误，不因单行失败中断。
    """
    settings = get_settings()
    password = settings.import_initial_password
    try:
        validate_password_strength(password)
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=f"IMPORT_INITIAL_PASSWORD 配置无效：{exc}") from exc
    if not password_has_letter_and_digit(password):
        raise HTTPException(status_code=500, detail="IMPORT_INITIAL_PASSWORD 配置无效：需同时包含字母和数字")

    try:
        data = read_upload_bytes(file.file)
        rows = parse_table_file(file.filename or "", data, max_rows=settings.import_max_rows)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    header = map_columns(rows[0], KIND_USERS)
    data_rows = rows[1:] if header else rows

    def cell_of(row: list[str], logical: str, position: int | None) -> str:
        idx = header.get(logical) if header else position
        if idx is None or idx >= len(row):
            return ""
        return row[idx]

    errors: list[ImportRowError] = []
    ok = 0
    seen_usernames: set[str] = set()
    seen_phones: set[str] = set()
    seen_emails: set[str] = set()

    for lineno, row in enumerate(data_rows, start=1):
        real_name = sanitize_plain_text(cell_of(row, "real_name", 0), max_length=64)
        student_no = strip_control_chars(cell_of(row, "student_no", 1)).strip()[:64]
        username_raw = strip_control_chars(cell_of(row, "username", 2)).strip()
        phone = strip_control_chars(cell_of(row, "phone", 3)).strip()
        organization = sanitize_plain_text(cell_of(row, "organization", 4), max_length=128)
        remark = sanitize_note(cell_of(row, "remark", 5))
        email = strip_control_chars(cell_of(row, "email", None)).strip().lower()
        identifier = real_name or username_raw or phone or f"第{lineno}行"

        def fail(reason: str) -> None:
            errors.append(ImportRowError(row=lineno, identifier=identifier, reason=reason))

        if not real_name:
            fail("姓名为空")
            continue

        username = username_raw or (student_no if len(student_no) >= 3 else "") or (phone if len(phone) >= 5 else "")
        username = sanitize_plain_text(username, max_length=64)
        if len(username) < 3:
            fail("无法确定用户名（用户名/学号/手机均缺失或过短，需 ≥3 位）")
            continue

        if phone and (not phone.isdigit() or not 5 <= len(phone) <= 20):
            fail("手机号格式无效")
            continue
        if email and ("@" not in email or len(email) > 128):
            fail("邮箱格式无效")
            continue

        # 文件内重复 / 库内重复（dry_run=False 时 autoflush 会看到本批已建账号）
        if username in seen_usernames:
            fail("用户名在文件内重复")
            continue
        if phone and phone in seen_phones:
            fail("手机号在文件内重复")
            continue
        if email and email in seen_emails:
            fail("邮箱在文件内重复")
            continue
        if db.query(Account).filter(Account.username == username).first():
            fail("用户名已存在")
            continue
        if phone and db.query(Account).filter(Account.phone == phone).first():
            fail("手机号已被占用")
            continue
        if email and db.query(Account).filter(Account.email == email).first():
            fail("邮箱已被占用")
            continue

        seen_usernames.add(username)
        if phone:
            seen_phones.add(phone)
        if email:
            seen_emails.add(email)

        if not dry_run:
            account = Account(
                username=username,
                email=email or None,
                password_hash=hash_password(password),
                role=Role.user,
                display_name=real_name,
                phone=phone or None,
            )
            db.add(account)
            db.flush()
            db.add(
                UserProfile(
                    account_id=account.id,
                    real_name=real_name,
                    student_no=student_no,
                    organization=organization,
                    remark=remark,
                    verify_status=VerifyStatus.approved,
                )
            )
            get_or_create_account(db, account.id)
            write_audit(
                db,
                actor_id=admin.id,
                action="user_import",
                target_type="account",
                target_id=account.id,
                detail=f"username={username}, real_name={real_name}",
            )
        ok += 1

    if dry_run:
        db.rollback()
    else:
        write_audit(
            db,
            actor_id=admin.id,
            action="user_import_batch",
            target_type="account",
            detail=f"rows={len(data_rows)}, ok={ok}, fail={len(errors)}, dry_run={dry_run}",
        )
        db.commit()

    shown = errors[:100]
    message = f"{'校验' if dry_run else '导入'}完成：共 {len(data_rows)} 行，成功 {ok} 行，失败 {len(errors)} 行"
    if len(errors) > len(shown):
        message += "（错误明细仅显示前 100 条）"
    return ImportResultOut(
        total=len(data_rows),
        succeeded=ok,
        failed=len(errors),
        errors=shown,
        message=message,
        default_password=password if ok else None,
    )


def _apply_review(
    db: Session,
    verification: UserVerification,
    admin: Account,
    approve: bool,
    review_note: str,
) -> UserVerification:
    if verification.status != VerifyStatus.pending:
        raise HTTPException(status_code=400, detail="该申请已处理")
    profile = db.get(UserProfile, verification.profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="用户资料不存在")
    now = datetime.now(timezone.utc)
    if approve:
        verification.status = VerifyStatus.approved
        profile.verify_status = VerifyStatus.approved
        action = "approve_verification"
    else:
        verification.status = VerifyStatus.rejected
        profile.verify_status = VerifyStatus.rejected
        action = "reject_verification"
    verification.reviewer_id = admin.id
    verification.review_note = review_note
    verification.reviewed_at = now
    write_audit(
        db,
        actor_id=admin.id,
        action=action,
        target_type="verification",
        target_id=verification.id,
        detail=review_note,
    )
    return verification


@router.post("/verifications/{verification_id}/review", response_model=VerificationOut)
def review_verification(
    verification_id: str,
    body: ReviewVerificationIn,
    db: Session = Depends(get_db),
    admin: Account = Depends(require_roles(Role.super_admin, Role.issue_admin)),
) -> VerificationOut:
    verification = db.get(UserVerification, verification_id)
    if not verification:
        raise HTTPException(status_code=404, detail="审核记录不存在")
    _apply_review(db, verification, admin, body.approve, body.review_note)
    db.commit()
    db.refresh(verification)
    return _enrich_verification(db, verification)


@router.post("/verifications/batch-review", response_model=MessageOut)
def batch_review(
    body: BatchReviewIn,
    db: Session = Depends(get_db),
    admin: Account = Depends(require_roles(Role.super_admin, Role.issue_admin)),
) -> MessageOut:
    count = 0
    for vid in body.verification_ids:
        verification = db.get(UserVerification, vid)
        if not verification or verification.status != VerifyStatus.pending:
            continue
        _apply_review(db, verification, admin, body.approve, body.review_note)
        count += 1
    db.commit()
    action = "通过" if body.approve else "驳回"
    return MessageOut(message=f"已批量{action} {count} 条")


@router.get("/{user_id}", response_model=UserListItem)
def get_user(
    user_id: str,
    db: Session = Depends(get_db),
    _: Account = Depends(require_roles(Role.super_admin, Role.issue_admin)),
) -> UserListItem:
    acc = db.get(Account, user_id)
    if not acc or acc.role != Role.user:
        raise HTTPException(status_code=404, detail="用户不存在")
    profile = db.query(UserProfile).filter(UserProfile.account_id == acc.id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="资料不存在")
    return _user_item(acc, profile, db)


@router.get("/{user_id}/verifications", response_model=list[VerificationOut])
def user_verifications(
    user_id: str,
    db: Session = Depends(get_db),
    _: Account = Depends(require_roles(Role.super_admin, Role.issue_admin)),
) -> list[VerificationOut]:
    profile = db.query(UserProfile).filter(UserProfile.account_id == user_id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="用户不存在")
    rows = (
        db.query(UserVerification)
        .options(
            joinedload(UserVerification.profile).joinedload(UserProfile.account),
            joinedload(UserVerification.reviewer),
        )
        .filter(UserVerification.profile_id == profile.id)
        .order_by(UserVerification.created_at.desc())
        .all()
    )
    return [_enrich_verification(db, r) for r in rows]
