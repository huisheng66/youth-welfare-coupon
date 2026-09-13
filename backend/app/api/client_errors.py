"""客户端（前端）未捕获错误上报：极简、免登录、只进审计日志。

设计约束（安全考量）：
- 免登录可写：错误常发生在登录前；防滥用靠全局限流闸门 + 严格字段上限
  （pydantic 长度截断），单条不入库超过 4KB 的堆栈；
- 只写不读：响应 204 无内容；查询走既有 /admin/audit（action=client_error）；
- detail 为 JSON 文本，不含 Cookie/Token 等敏感头，前端上报端不收集。
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.services.audit import write_audit

router = APIRouter(tags=["客户端错误"])


class ClientErrorIn(BaseModel):
    kind: str = Field(default="error", max_length=32)  # vue | unhandledrejection | error
    message: str = Field(min_length=1, max_length=500)
    stack: str = Field(default="", max_length=4000)
    route: str = Field(default="", max_length=200)


@router.post("/client-errors", status_code=204)
def report_client_error(
    body: ClientErrorIn,
    request: Request,
    db: Session = Depends(get_db),
) -> None:
    detail = json.dumps(
        {
            "kind": body.kind,
            "message": body.message,
            "stack": body.stack,
            "route": body.route,
            "ua": request.headers.get("user-agent", "")[:200],
        },
        ensure_ascii=False,
    )
    write_audit(
        db,
        actor_id=None,
        action="client_error",
        target_type="frontend",
        target_id="",
        detail=detail,
    )
    db.commit()
    return None
