"""统一导入预检、批次与逐行执行（T14）。

流程：preview（解析 + 预检，不写业务数据）→ execute（条件领取批次，
逐行独立事务，断点续执只处理未完成行）→ detail/rows/CSV（状态、计数、
全部错误明细）。

要点：
- 预检结果不代替执行时资格检查：每行执行时重新校验资格与唯一冲突；
- 逐行独立事务：行领取（条件 UPDATE）→ 业务写入与行状态同一 commit；
  跨行异常只影响该行，会话可继续；
- 文件内重复策略：拒绝重复行、保留首次出现（预检即标记），不静默重复
  发券或入账；
- 标识解析：用户名 → 邮箱 → 手机 → 学号；跨字段命中不同用户或学号多命中
  报告歧义；姓名不作为唯一标识；
- users 批次共用一次初始密码哈希（bcrypt 单次约 0.2–0.3s，1000 行从分钟级
  降到一次；同一批次本来就用同一初始密码）。
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import hash_password
from app.models.entities import (
    Account,
    ImportBatch,
    ImportBatchStatus,
    ImportRow,
    ImportRowStatus,
    Role,
    UserProfile,
    UserVerification,
    VerificationSource,
    VerifyStatus,
    utcnow,
)
from app.services.audit import write_audit
from app.services.eligibility import EligibilityError, require_benefit_user, require_issuable_template
from app.services.import_file import (
    KIND_ISSUE,
    KIND_POINTS,
    KIND_USERS,
    map_columns,
    parse_table_file,
    resolve_user_detailed,
)
from app.services.points import get_or_create_account, quantize_hours
from app.services.sanitize import (
    password_has_letter_and_digit,
    sanitize_note,
    sanitize_plain_text,
    strip_control_chars,
    validate_password_strength,
)

VALID_KINDS = (KIND_USERS, KIND_ISSUE, KIND_POINTS)

# 行领取为 running 后进程崩溃的回收窗口：超过该时长的 running 行允许重新领取
_STALE_RUNNING_MINUTES = 10


class _RowReject(Exception):
    """单行预检拒绝（写入行 reason，不中断批次）。"""


# ---------------------------------------------------------------------------
# 预检
# ---------------------------------------------------------------------------


def _cell(row: list[str], header: dict[str, int] | None, logical: str, position: int | None) -> str:
    idx = header.get(logical) if header else position
    if idx is None or idx >= len(row):
        return ""
    return row[idx]


def _users_payload(row: list[str], header, lineno: int) -> tuple[dict, str]:
    real_name = sanitize_plain_text(_cell(row, header, "real_name", 0), max_length=64)
    student_no = strip_control_chars(_cell(row, header, "student_no", 1)).strip()[:64]
    username_raw = strip_control_chars(_cell(row, header, "username", 2)).strip()
    phone = strip_control_chars(_cell(row, header, "phone", 3)).strip()
    organization = sanitize_plain_text(_cell(row, header, "organization", 4), max_length=128)
    remark = sanitize_note(_cell(row, header, "remark", 5))
    email = strip_control_chars(_cell(row, header, "email", None)).strip().lower()
    identifier = real_name or username_raw or phone or f"第{lineno}行"

    if not real_name:
        raise _RowReject("姓名为空")
    username = username_raw or (student_no if len(student_no) >= 3 else "") or (
        phone if len(phone) >= 5 else ""
    )
    username = sanitize_plain_text(username, max_length=64)
    if len(username) < 3:
        raise _RowReject("无法确定用户名（用户名/学号/手机均缺失或过短，需 ≥3 位）")
    if phone and (not phone.isdigit() or not 5 <= len(phone) <= 20):
        raise _RowReject("手机号格式无效")
    if email and ("@" not in email or len(email) > 128):
        raise _RowReject("邮箱格式无效")
    payload = {
        "real_name": real_name,
        "student_no": student_no,
        "username": username,
        "phone": phone,
        "email": email,
        "organization": organization,
        "remark": remark,
    }
    return payload, identifier


def _precheck_users_row(db: Session, payload: dict, seen: dict[str, set]) -> None:
    username, phone, email = payload["username"], payload["phone"], payload["email"]
    if username in seen["usernames"]:
        raise _RowReject("用户名在文件内重复（保留首次出现的行）")
    if phone and phone in seen["phones"]:
        raise _RowReject("手机号在文件内重复（保留首次出现的行）")
    if email and email in seen["emails"]:
        raise _RowReject("邮箱在文件内重复（保留首次出现的行）")
    if db.query(Account).filter(Account.username == username).first():
        raise _RowReject("用户名已存在")
    if phone and db.query(Account).filter(Account.phone == phone).first():
        raise _RowReject("手机号已被占用")
    if email and db.query(Account).filter(Account.email == email).first():
        raise _RowReject("邮箱已被占用")
    seen["usernames"].add(username)
    if phone:
        seen["phones"].add(phone)
    if email:
        seen["emails"].add(email)


def _resolve_benefit_user(db: Session, token: str, *, action: str) -> Account:
    account, reason = resolve_user_detailed(db, token)
    if not account:
        raise _RowReject(reason or "用户不存在")
    try:
        require_benefit_user(db, account, action=action)
    except EligibilityError as exc:
        raise _RowReject(str(exc)) from exc
    return account


def create_preview_batch(
    db: Session,
    *,
    kind: str,
    filename: str,
    data: bytes,
    params: dict[str, Any],
    admin: Account,
) -> ImportBatch:
    """解析 + 预检并持久化批次（不写任何业务数据）。解析错误抛 ValueError。"""
    if kind not in VALID_KINDS:
        raise ValueError(f"不支持的导入类型：{kind}")
    settings = get_settings()
    rows_raw = parse_table_file(filename, data, max_rows=settings.import_max_rows)
    header = map_columns(rows_raw[0], kind)
    data_rows = rows_raw[1:] if header else rows_raw

    if kind == KIND_ISSUE:
        # 模板/门店资格在批次层面预检；执行时仍会逐行重新校验
        from app.models.entities import CouponTemplate

        template = db.get(CouponTemplate, params.get("template_id") or "")
        try:
            require_issuable_template(db, template)
        except EligibilityError as exc:
            raise ValueError(str(exc)) from exc

    batch = ImportBatch(
        kind=kind,
        actor_id=admin.id,
        filename=filename,
        file_sha256=hashlib.sha256(data).hexdigest(),
        params_json=json.dumps(params, ensure_ascii=False, default=str),
        status=ImportBatchStatus.previewed,
        total=len(data_rows),
    )
    db.add(batch)
    db.flush()

    seen = {"usernames": set(), "phones": set(), "emails": set()}
    seen_user_ids: set[str] = set()
    precheck_failed = 0
    for lineno, row in enumerate(data_rows, start=1):
        identifier = f"第{lineno}行"
        try:
            if kind == KIND_USERS:
                payload, identifier = _users_payload(row, header, lineno)
                _precheck_users_row(db, payload, seen)
            elif kind == KIND_ISSUE:
                token = _cell(row, header, "identifier", 0).strip()
                identifier = token or identifier
                if not token:
                    raise _RowReject("用户标识为空")
                account = _resolve_benefit_user(db, token, action="发券")
                if account.id in seen_user_ids:
                    raise _RowReject("同一用户在文件内重复（保留首次出现的行）")
                seen_user_ids.add(account.id)
                payload = {"identifier": token, "user_id": account.id}
            else:  # KIND_POINTS
                token = _cell(row, header, "identifier", 0).strip()
                identifier = token or identifier
                if not token:
                    raise _RowReject("用户标识为空")
                hours_raw = _cell(row, header, "hours", 1).strip()
                reason = (_cell(row, header, "reason", 2).strip()[:255]) or (
                    str(params.get("reason") or "").strip()[:255] or "志愿服务时长入账"
                )
                account = _resolve_benefit_user(db, token, action="调整时长")
                hours = _parse_hours(hours_raw)
                if account.id in seen_user_ids:
                    raise _RowReject("同一用户在文件内重复（保留首次出现的行）")
                seen_user_ids.add(account.id)
                payload = {
                    "identifier": token,
                    "user_id": account.id,
                    "hours": hours,
                    "reason": reason,
                }
        except _RowReject as exc:
            precheck_failed += 1
            db.add(
                ImportRow(
                    batch_id=batch.id,
                    row_no=lineno,
                    identifier=identifier[:128],
                    payload_json="{}",
                    status=ImportRowStatus.precheck_failed,
                    reason=str(exc)[:255],
                )
            )
            continue
        db.add(
            ImportRow(
                batch_id=batch.id,
                row_no=lineno,
                identifier=identifier[:128],
                payload_json=json.dumps(payload, ensure_ascii=False, default=str),
                status=ImportRowStatus.pending,
            )
        )

    batch.failed = precheck_failed
    batch.message = (
        f"预检完成：共 {batch.total} 行，可执行 {batch.total - precheck_failed} 行，"
        f"预检失败 {precheck_failed} 行"
    )
    write_audit(
        db,
        actor_id=admin.id,
        action="import_preview",
        target_type="import_batch",
        target_id=batch.id,
        detail=f"kind={kind}, rows={batch.total}, precheck_failed={precheck_failed}, file={batch.file_sha256[:12]}",
    )
    db.commit()
    db.refresh(batch)
    return batch


def _parse_hours(raw: str) -> str:
    """时长字段预检：格式、有限性、非零与边界；返回规范化字符串。"""
    try:
        amount = Decimal(raw)
    except (InvalidOperation, ValueError):
        raise _RowReject(f"时长格式无效：{raw}") from None
    if not amount.is_finite():
        raise _RowReject(f"时长必须是有限数值（不支持 NaN/Infinity）：{raw}")
    amount = quantize_hours(amount)
    if amount == 0:
        raise _RowReject("时长不能为 0")
    if abs(amount) > Decimal("100000"):
        raise _RowReject("时长超出允许范围（±100000 小时）")
    return str(amount)


# ---------------------------------------------------------------------------
# 执行
# ---------------------------------------------------------------------------


def _claim_next_row(db: Session, batch_id: str, *, exclude_ids: set[str]) -> ImportRow | None:
    """条件领取下一待处理行：pending / failed / 超时 running。

    条件 UPDATE + commit 使领取对其他 worker 立即可见；竞争失败者 won=0
    继续尝试下一行，保证同一行只被一个执行者处理。exclude_ids 排除本轮
    执行已处理过的行（本轮失败的行只能等下一轮重试，否则会无限循环）。
    """
    stale_before = datetime.now(timezone.utc) - timedelta(minutes=_STALE_RUNNING_MINUTES)
    retryable = (ImportRowStatus.pending, ImportRowStatus.failed)
    candidates = (
        db.query(ImportRow.id, ImportRow.status)
        .filter(
            ImportRow.batch_id == batch_id,
            ImportRow.status.in_(retryable),
            ImportRow.id.notin_(exclude_ids) if exclude_ids else True,
        )
        .order_by(ImportRow.row_no)
        .limit(5)
        .all()
    )
    stale = (
        db.query(ImportRow.id, ImportRow.status)
        .filter(
            ImportRow.batch_id == batch_id,
            ImportRow.status == ImportRowStatus.running,
            ImportRow.updated_at < stale_before,
            ImportRow.id.notin_(exclude_ids) if exclude_ids else True,
        )
        .order_by(ImportRow.row_no)
        .limit(5)
        .all()
    )
    for row_id, status in [*candidates, *stale]:
        won = (
            db.query(ImportRow)
            .filter(ImportRow.id == row_id, ImportRow.status == status)
            .update(
                {ImportRow.status: ImportRowStatus.running, ImportRow.updated_at: utcnow()},
                synchronize_session=False,
            )
        )
        db.commit()
        if won:
            return db.get(ImportRow, row_id)
    return None


def _exec_users_row(
    db: Session, batch: ImportBatch, row: ImportRow, admin: Account, password_hash: str
) -> tuple[str, tuple[str, str, str] | None]:
    payload = json.loads(row.payload_json)
    username, phone, email = payload["username"], payload["phone"], payload["email"]
    # 执行时重新校验唯一冲突（预检后可能已有他人创建）
    if db.query(Account).filter(Account.username == username).first():
        raise _RowReject("用户名已存在")
    if phone and db.query(Account).filter(Account.phone == phone).first():
        raise _RowReject("手机号已被占用")
    if email and db.query(Account).filter(Account.email == email).first():
        raise _RowReject("邮箱已被占用")

    account = Account(
        username=username,
        email=email or None,
        password_hash=password_hash,
        role=Role.user,
        display_name=payload["real_name"],
        phone=phone or None,
        must_change_password=True,
    )
    db.add(account)
    db.flush()
    profile = UserProfile(
        account_id=account.id,
        real_name=payload["real_name"],
        student_no=payload["student_no"],
        organization=payload["organization"],
        remark=payload["remark"],
        verify_status=VerifyStatus.approved,
        profile_version=1,
    )
    db.add(profile)
    db.flush()
    db.add(
        UserVerification.from_profile(
            profile,
            material_note=(
                f"名单导入直接核验（批次：{batch.id}，文件：{batch.filename}，"
                f"操作者：{admin.username}）"
            ),
            status=VerifyStatus.approved,
            source=VerificationSource.bulk_import,
            reviewer_id=admin.id,
            review_note="名单导入直接核验",
            reviewed_at=utcnow(),
        )
    )
    get_or_create_account(db, account.id)
    write_audit(
        db,
        actor_id=admin.id,
        action="user_import",
        target_type="account",
        target_id=account.id,
        detail=f"username={username}, real_name={payload['real_name']}, batch={batch.id}",
    )
    notify = (email, username, payload["real_name"]) if email else None
    return account.id, notify


def _exec_issue_row(
    db: Session, batch: ImportBatch, row: ImportRow, admin: Account
) -> tuple[str, None]:
    from app.api.coupons import _issue_for_user
    from app.models.entities import CouponTemplate

    params = json.loads(batch.params_json)
    payload = json.loads(row.payload_json)
    template = db.get(CouponTemplate, params["template_id"])
    require_issuable_template(db, template)
    user = db.get(Account, payload["user_id"])
    quantity = int(params.get("quantity") or 1)
    created = _issue_for_user(db, user=user, template=template, quantity=quantity, admin=admin)
    db.flush()
    return (created[0].id if created else ""), None


def _exec_points_row(
    db: Session, batch: ImportBatch, row: ImportRow, admin: Account
) -> tuple[str, None]:
    from app.api.points import _grant_one

    payload = json.loads(row.payload_json)
    _grant_one(
        db,
        user_id=payload["user_id"],
        amount=Decimal(payload["hours"]),
        reason=payload["reason"],
        admin=admin,
    )
    return payload["user_id"], None


def execute_batch(db: Session, batch: ImportBatch, admin: Account) -> dict[str, Any]:
    """执行批次：逐行独立事务，断点续执只处理未完成行（可安全重复调用）。

    返回 {total, succeeded, failed, to_notify}；已完成批次直接返回计数（幂等）。
    """
    if batch.status == ImportBatchStatus.completed:
        retryable = (
            db.query(ImportRow)
            .filter(ImportRow.batch_id == batch.id, ImportRow.status == ImportRowStatus.failed)
            .count()
        )
        if retryable == 0:
            # 全部行已有终态：幂等返回，不重复执行
            return {"total": batch.total, "succeeded": batch.succeeded, "failed": batch.failed, "to_notify": []}
        # 仍有执行期失败行：允许重试（预检失败行是终态，不重试）

    claimed = (
        db.query(ImportBatch)
        .filter(
            ImportBatch.id == batch.id,
            ImportBatch.status.in_(
                [
                    ImportBatchStatus.previewed,
                    ImportBatchStatus.executing,
                    ImportBatchStatus.completed,
                ]
            ),
        )
        .update(
            {ImportBatch.status: ImportBatchStatus.executing, ImportBatch.executed_at: utcnow()},
            synchronize_session=False,
        )
    )
    db.commit()
    if not claimed:  # 并发下已被他人执行完毕
        db.refresh(batch)
        return {"total": batch.total, "succeeded": batch.succeeded, "failed": batch.failed, "to_notify": []}

    shared_password_hash = ""
    if batch.kind == KIND_USERS:
        password = get_settings().import_initial_password
        try:
            validate_password_strength(password)
        except ValueError as exc:
            raise RuntimeError(f"IMPORT_INITIAL_PASSWORD 配置无效：{exc}") from exc
        if not password_has_letter_and_digit(password):
            raise RuntimeError("IMPORT_INITIAL_PASSWORD 配置无效：需同时包含字母和数字")
        # 全批次共用一次 bcrypt：1000 行从分钟级哈希降到单次
        shared_password_hash = hash_password(password)

    to_notify: list[tuple[str, str, str]] = []
    attempted: set[str] = set()
    while True:
        row = _claim_next_row(db, batch.id, exclude_ids=attempted)
        if row is None:
            break
        attempted.add(row.id)
        try:
            if batch.kind == KIND_USERS:
                ref_id, notify = _exec_users_row(db, batch, row, admin, shared_password_hash)
            elif batch.kind == KIND_ISSUE:
                ref_id, notify = _exec_issue_row(db, batch, row, admin)
            else:
                ref_id, notify = _exec_points_row(db, batch, row, admin)
            db.query(ImportRow).filter(ImportRow.id == row.id).update(
                {
                    ImportRow.status: ImportRowStatus.ok,
                    ImportRow.ref_id: ref_id or "",
                    ImportRow.reason: "",
                    ImportRow.updated_at: utcnow(),
                },
                synchronize_session=False,
            )
            db.commit()
            if notify:
                to_notify.append(notify)
        except Exception as exc:  # noqa: BLE001 — 跨行异常只影响该行，批次继续
            db.rollback()
            reason = str(exc)[:255] or exc.__class__.__name__
            db.query(ImportRow).filter(ImportRow.id == row.id).update(
                {
                    ImportRow.status: ImportRowStatus.failed,
                    ImportRow.reason: reason,
                    ImportRow.updated_at: utcnow(),
                },
                synchronize_session=False,
            )
            db.commit()

    counts = dict(
        db.query(ImportRow.status, func.count())
        .filter(ImportRow.batch_id == batch.id)
        .group_by(ImportRow.status)
        .all()
    )
    ok = int(counts.get(ImportRowStatus.ok, 0))
    failed = batch.total - ok
    db.query(ImportBatch).filter(ImportBatch.id == batch.id).update(
        {
            ImportBatch.status: ImportBatchStatus.completed,
            ImportBatch.succeeded: ok,
            ImportBatch.failed: failed,
            ImportBatch.executed_at: utcnow(),
            ImportBatch.message: f"执行完成：共 {batch.total} 行，成功 {ok} 行，失败 {failed} 行",
        },
        synchronize_session=False,
    )
    write_audit(
        db,
        actor_id=admin.id,
        action="import_execute",
        target_type="import_batch",
        target_id=batch.id,
        detail=f"kind={batch.kind}, ok={ok}, fail={failed}",
    )
    db.commit()
    return {"total": batch.total, "succeeded": ok, "failed": failed, "to_notify": to_notify}
