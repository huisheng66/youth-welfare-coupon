"""Add accounts.must_change_password for forced first-password change.

批量导入用户（统一初始密码）、管理员重置密码、新建商家/发券管理员账号
后，要求该账号在改密前停留在「账号设置」页。

Revision ID: 9d4c17f2ab60
Revises: 7f21c3a8e6b1
Create Date: 2026-08-30
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "9d4c17f2ab60"
down_revision: Union[str, None] = "7f21c3a8e6b1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "accounts",
        sa.Column("must_change_password", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("accounts", "must_change_password")
