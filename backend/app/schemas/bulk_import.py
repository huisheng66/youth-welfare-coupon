"""Bulk-import endpoints share one result shape (users / coupons / points)."""

from __future__ import annotations

from pydantic import BaseModel


class ImportRowError(BaseModel):
    row: int  # 数据行号（从 1 开始，不含表头）
    identifier: str = ""  # 该行的姓名 / 用户标识等定位信息
    reason: str


class ImportResultOut(BaseModel):
    total: int
    succeeded: int
    failed: int
    errors: list[ImportRowError] = []
    message: str = ""
    # 仅用户名单导入且成功时返回，供管理员分发给用户
    default_password: str | None = None
