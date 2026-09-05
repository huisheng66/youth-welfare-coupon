"""Email verification codes stored as keyed hash instead of plaintext.

email_codes.code 从验证码明文（VARCHAR(16)）改为 HMAC-SHA256 摘要
（VARCHAR(128)）。库被拖走后无法从摘要枚举还原六位验证码；
迁移前已入库的明文码由应用层兼容读取，过期后自然淘汰。

Revision ID: b7e42a9013dd
Revises: c3e5a281d942
Create Date: 2026-09-05
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "b7e42a9013dd"
down_revision: Union[str, None] = "c3e5a281d942"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        # SQLite 的 VARCHAR 长度只是类型亲和性，存 64 字符摘要不需要重建表
        return
    op.alter_column(
        "email_codes",
        "code",
        existing_type=sa.String(length=16),
        type_=sa.String(length=128),
        existing_nullable=False,
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        return
    op.alter_column(
        "email_codes",
        "code",
        existing_type=sa.String(length=128),
        type_=sa.String(length=16),
        existing_nullable=False,
    )
