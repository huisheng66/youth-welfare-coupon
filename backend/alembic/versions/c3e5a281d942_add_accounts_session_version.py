"""Add accounts.session_version for immediate JWT invalidation.

密码修改或管理员重置密码时递增该值。访问令牌写入签发版本，认证依赖比对
令牌与账户版本，从而让旧 Cookie 和 Bearer token 立即失效。

Revision ID: c3e5a281d942
Revises: 9d4c17f2ab60
Create Date: 2026-09-02
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "c3e5a281d942"
down_revision: Union[str, None] = "9d4c17f2ab60"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "accounts",
        sa.Column("session_version", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )


def downgrade() -> None:
    op.drop_column("accounts", "session_version")
