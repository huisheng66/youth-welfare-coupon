"""核验申请快照、旧申请失效与条件审核。"""

from __future__ import annotations

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.models.entities import (
    Account,
    UserProfile,
    UserVerification,
    VerifyStatus,
    utcnow,
)
from app.services.audit import write_audit

RESULT_SUCCESS = "success"
RESULT_ALREADY = "already_processed"
RESULT_CONFLICT = "version_conflict"
RESULT_NOT_FOUND = "not_found"

RESULT_MESSAGES = {
    RESULT_SUCCESS: "已处理",
    RESULT_ALREADY: "该申请已处理",
    RESULT_CONFLICT: "资料已更新，请审核最新申请",
    RESULT_NOT_FOUND: "审核记录不存在",
}

SUPERSEDE_NOTE = "资料已更新，本申请已由新申请替代"


def bump_identity_version(profile: UserProfile) -> int:
    profile.profile_version = int(profile.profile_version or 1) + 1
    return profile.profile_version


def supersede_pending(db: Session, profile: UserProfile, note: str = SUPERSEDE_NOTE) -> int:
    """将同一资料下仍待审的申请标为已失效，保留原记录。"""
    result = db.execute(
        update(UserVerification)
        .where(
            UserVerification.profile_id == profile.id,
            UserVerification.status == VerifyStatus.pending,
        )
        .values(
            status=VerifyStatus.superseded,
            review_note=note,
            reviewed_at=utcnow(),
        )
    )
    return int(result.rowcount or 0)


def apply_review(
    db: Session,
    verification_id: str,
    admin: Account,
    approve: bool,
    review_note: str,
    expected_version: int | None = None,
) -> tuple[str, UserVerification | None]:
    """条件更新审核结果。调用方负责 commit。

    两个管理员同时处理同一申请时只有一条 UPDATE 命中 pending。
    申请快照版本与当前资料版本不一致时拒绝批准/驳回，避免旧决定落到新资料上。
    """
    verification = db.get(UserVerification, verification_id)
    if not verification:
        return RESULT_NOT_FOUND, None

    profile = (
        db.query(UserProfile)
        .filter(UserProfile.id == verification.profile_id)
        .with_for_update()
        .first()
    )
    if not profile:
        return RESULT_NOT_FOUND, None

    if verification.status != VerifyStatus.pending:
        return RESULT_ALREADY, verification

    if expected_version is not None and verification.snapshot_version != expected_version:
        return RESULT_CONFLICT, verification

    if verification.snapshot_version and verification.snapshot_version != profile.profile_version:
        return RESULT_CONFLICT, verification

    now = utcnow()
    new_status = VerifyStatus.approved if approve else VerifyStatus.rejected
    result = db.execute(
        update(UserVerification)
        .where(
            UserVerification.id == verification_id,
            UserVerification.status == VerifyStatus.pending,
        )
        .values(
            status=new_status,
            reviewer_id=admin.id,
            review_note=review_note or "",
            reviewed_at=now,
        )
    )
    if result.rowcount != 1:
        db.refresh(verification)
        return RESULT_ALREADY, verification

    profile.verify_status = new_status
    write_audit(
        db,
        actor_id=admin.id,
        action="approve_verification" if approve else "reject_verification",
        target_type="verification",
        target_id=verification.id,
        detail=review_note or "",
    )
    db.refresh(verification)
    return RESULT_SUCCESS, verification
