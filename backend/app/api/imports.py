"""统一导入入口（T14）：上传解析 → 预检 → 确认执行 → 批次结果。

- `POST /imports/preview`：解析 + 预检并持久化批次，不写业务数据；
- `POST /imports/{id}/execute`：确认执行，执行时重新验证；可安全重试，
  只处理未完成行（断点续执不重复入账/发券）；
- `GET /imports/{id}` / `rows` / `rows.csv`：状态、计数与全部逐行明细。

旧三类导入端点阶段性保留；新流程以此为准。
"""

from __future__ import annotations

import csv
import io
import json

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, Response, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.core.deps import require_roles
from app.models.entities import (
    Account,
    ImportBatch,
    ImportBatchStatus,
    ImportRow,
    ImportRowStatus,
    Role,
)
from app.services.import_file import KIND_ISSUE, KIND_POINTS, KIND_USERS, read_upload_bytes
from app.services.imports import create_preview_batch, execute_batch

router = APIRouter(prefix="/imports", tags=["统一导入"])

_ADMIN_ROLES = (Role.super_admin, Role.issue_admin)


class ExecuteIn(BaseModel):
    # 客户端确认预检内容：与批次文件摘要不一致则拒绝执行
    file_sha256: str | None = None


def _get_batch(db: Session, batch_id: str) -> ImportBatch:
    batch = db.get(ImportBatch, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="导入批次不存在")
    return batch


def _row_dict(r: ImportRow) -> dict:
    return {
        "row": r.row_no,
        "identifier": r.identifier,
        "status": r.status.value if isinstance(r.status, ImportRowStatus) else r.status,
        "reason": r.reason,
        "ref_id": r.ref_id,
    }


def _batch_dict(db: Session, batch: ImportBatch, *, errors_limit: int = 0) -> dict:
    out = {
        "id": batch.id,
        "kind": batch.kind,
        "filename": batch.filename,
        "file_sha256": batch.file_sha256,
        "status": batch.status.value if isinstance(batch.status, ImportBatchStatus) else batch.status,
        "total": batch.total,
        "succeeded": batch.succeeded,
        "failed": batch.failed,
        "message": batch.message,
        "created_at": batch.created_at,
        "executed_at": batch.executed_at,
    }
    if errors_limit > 0:
        q = (
            db.query(ImportRow)
            .filter(
                ImportRow.batch_id == batch.id,
                ImportRow.status.in_([ImportRowStatus.precheck_failed, ImportRowStatus.failed]),
            )
            .order_by(ImportRow.row_no)
        )
        total_errors = q.count()
        out["errors"] = [_row_dict(r) for r in q.limit(errors_limit).all()]
        out["errors_truncated"] = total_errors > errors_limit
    return out


@router.post("/preview")
def import_preview(
    file: UploadFile = File(..., description="名单文件（.xlsx / .csv / .txt / .docx）"),
    kind: str = Form(..., description="users / issue / points"),
    template_id: str = Form("", description="kind=issue 时的券模板"),
    quantity: int = Form(1, ge=1, le=10),
    reason: str = Form("", description="kind=points 时的默认说明"),
    notify: bool = Form(True, description="kind=users 时是否发送开通邮件"),
    db: Session = Depends(get_db),
    admin: Account = Depends(require_roles(*_ADMIN_ROLES)),
) -> dict:
    """上传解析 + 预检：返回批次 id 与逐行预检结果，不写业务数据。"""
    try:
        data = read_upload_bytes(file.file)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    params: dict = {"notify": notify}
    if kind == KIND_ISSUE:
        if not template_id:
            raise HTTPException(status_code=400, detail="kind=issue 需要 template_id")
        params.update({"template_id": template_id, "quantity": quantity})
    elif kind == KIND_POINTS:
        params.update({"reason": reason})
    elif kind != KIND_USERS:
        raise HTTPException(status_code=400, detail=f"不支持的导入类型：{kind}")

    try:
        batch = create_preview_batch(
            db,
            kind=kind,
            filename=(file.filename or "unnamed").strip() or "unnamed",
            data=data,
            params=params,
            admin=admin,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    out = _batch_dict(db, batch, errors_limit=100)
    out["executable"] = batch.total - batch.failed
    return out


@router.post("/{batch_id}/execute")
def import_execute(
    batch_id: str,
    body: ExecuteIn | None = None,
    background: BackgroundTasks = None,
    db: Session = Depends(get_db),
    admin: Account = Depends(require_roles(*_ADMIN_ROLES)),
) -> dict:
    """确认执行批次：执行时重新验证；重试只处理未完成行，不重复入账/发券。"""
    if background is None:  # 直接调用（测试）时退化为无后台任务
        background = BackgroundTasks()
    batch = _get_batch(db, batch_id)
    if batch.actor_id != admin.id:
        raise HTTPException(status_code=403, detail="仅批次创建者可执行该批次")
    if body and body.file_sha256 and body.file_sha256 != batch.file_sha256:
        raise HTTPException(status_code=409, detail="文件摘要与预检时不一致，请重新预检")

    try:
        summary = execute_batch(db, batch, admin)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    db.refresh(batch)
    out = _batch_dict(db, batch, errors_limit=100)
    settings = get_settings()
    to_notify = summary.get("to_notify") or []
    if batch.kind == KIND_USERS and summary["succeeded"] > 0:
        out["default_password"] = settings.import_initial_password
        if to_notify:
            params = json.loads(batch.params_json or "{}")
            if params.get("notify", True) and settings.smtp_configured:
                from app.api.users import _send_import_password_emails

                background.add_task(
                    _send_import_password_emails, to_notify, settings.import_initial_password
                )
                out["email_queued"] = len(to_notify)
            else:
                out["email_queued"] = 0
    return out


@router.get("/{batch_id}")
def import_detail(
    batch_id: str,
    db: Session = Depends(get_db),
    _: Account = Depends(require_roles(*_ADMIN_ROLES)),
) -> dict:
    batch = _get_batch(db, batch_id)
    return _batch_dict(db, batch, errors_limit=100)


@router.get("/{batch_id}/rows")
def import_rows(
    batch_id: str,
    status: str | None = Query(default=None, description="pending/precheck_failed/running/ok/failed"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    _: Account = Depends(require_roles(*_ADMIN_ROLES)),
) -> dict:
    batch = _get_batch(db, batch_id)
    q = db.query(ImportRow).filter(ImportRow.batch_id == batch.id).order_by(ImportRow.row_no)
    if status:
        q = q.filter(ImportRow.status == status)
    total = q.count()
    rows = q.offset(skip).limit(limit).all()
    return {"total": total, "items": [_row_dict(r) for r in rows]}


@router.get("/{batch_id}/rows.csv")
def import_rows_csv(
    batch_id: str,
    db: Session = Depends(get_db),
    _: Account = Depends(require_roles(*_ADMIN_ROLES)),
) -> Response:
    """全部逐行明细 CSV（utf-8-sig，Excel 可直接打开）；错误证据不截断。"""
    batch = _get_batch(db, batch_id)
    rows = (
        db.query(ImportRow)
        .filter(ImportRow.batch_id == batch.id)
        .order_by(ImportRow.row_no)
        .all()
    )
    buf = io.StringIO()
    buf.write("﻿")
    writer = csv.writer(buf)
    writer.writerow(["行号", "标识", "状态", "原因", "关联对象"])
    for r in rows:
        status = r.status.value if isinstance(r.status, ImportRowStatus) else r.status
        writer.writerow([r.row_no, r.identifier, status, r.reason, r.ref_id])
    return Response(
        content=buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="import_{batch.id}_rows.csv"'},
    )
