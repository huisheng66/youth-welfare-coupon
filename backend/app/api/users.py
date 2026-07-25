from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload

from app.core.database import get_db
from app.core.deps import require_roles
from app.models.entities import Account, Role, UserProfile, UserVerification, VerifyStatus
from app.schemas.common import MessageOut, Page
from app.schemas.user import (
    BatchReviewIn,
    ProfileUpdateIn,
    ReviewVerificationIn,
    SubmitVerificationIn,
    UserListItem,
    VerificationOut,
)
from app.services.audit import write_audit

router = APIRouter(prefix="/users", tags=["用户核验"])


def _latest_material(db: Session, profile_id: str) -> str | None:
    row = (
        db.query(UserVerification)
        .filter(UserVerification.profile_id == profile_id)
        .order_by(UserVerification.created_at.desc())
        .first()
    )
    return row.material_note if row else None


def _user_item(acc: Account, profile: UserProfile, db: Session) -> UserListItem:
    return UserListItem(
        id=acc.id,
        username=acc.username,
        display_name=acc.display_name,
        phone=acc.phone,
        real_name=profile.real_name,
        organization=profile.organization,
        verify_status=profile.verify_status,
        created_at=acc.created_at,
        id_number_masked=profile.id_number_masked,
        remark=profile.remark,
        latest_material_note=_latest_material(db, profile.id),
    )


def _enrich_verification(db: Session, verification: UserVerification) -> VerificationOut:
    data = VerificationOut.model_validate(verification)
    profile = db.get(UserProfile, verification.profile_id)
    if profile:
        acc = db.get(Account, profile.account_id)
        data.user_id = profile.account_id
        data.real_name = profile.real_name
        data.organization = profile.organization
        if acc:
            data.username = acc.username
            data.phone = acc.phone
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
    profile.id_number_masked = body.id_number_masked
    profile.organization = body.organization
    profile.remark = body.remark
    db.commit()
    return my_profile(account, db)


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
        .options(joinedload(Account.profile))
        .filter(Account.role == Role.user)
        .order_by(Account.created_at.desc())
    )
    if q:
        like = f"%{q}%"
        query = query.filter(
            (Account.username.ilike(like))
            | (Account.display_name.ilike(like))
            | (Account.phone.ilike(like))
        )
    accounts = query.all()
    items: list[UserListItem] = []
    for acc in accounts:
        profile = acc.profile
        if not profile:
            continue
        if verify_status and profile.verify_status != verify_status:
            continue
        items.append(_user_item(acc, profile, db))
    total = len(items)
    return Page(total=total, items=items[skip : skip + limit])


@router.get("/pending-verifications", response_model=list[VerificationOut])
def pending_verifications(
    db: Session = Depends(get_db),
    _: Account = Depends(require_roles(Role.super_admin, Role.issue_admin)),
) -> list[VerificationOut]:
    rows = (
        db.query(UserVerification)
        .filter(UserVerification.status == VerifyStatus.pending)
        .order_by(UserVerification.created_at.asc())
        .all()
    )
    return [_enrich_verification(db, r) for r in rows]


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
        .filter(UserVerification.profile_id == profile.id)
        .order_by(UserVerification.created_at.desc())
        .all()
    )
    return [_enrich_verification(db, r) for r in rows]
