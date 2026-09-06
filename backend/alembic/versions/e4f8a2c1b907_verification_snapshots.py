"""Add profile version and verification identity snapshots.

审核必须对照申请当时的姓名/学号/组织，不能用当前资料冒充旧申请。
snapshot_version=0 表示升级前历史行，快照未知。

Revision ID: e4f8a2c1b907
Revises: cf60b31a7e22
Create Date: 2026-09-05
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "e4f8a2c1b907"
down_revision: Union[str, None] = "cf60b31a7e22"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "user_profiles",
        sa.Column("profile_version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "user_verifications",
        sa.Column("snapshot_real_name", sa.String(length=64), nullable=False, server_default=""),
    )
    op.add_column(
        "user_verifications",
        sa.Column("snapshot_student_no", sa.String(length=64), nullable=False, server_default=""),
    )
    op.add_column(
        "user_verifications",
        sa.Column(
            "snapshot_organization", sa.String(length=128), nullable=False, server_default=""
        ),
    )
    op.add_column(
        "user_verifications",
        sa.Column("snapshot_version", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "user_verifications",
        sa.Column(
            "source", sa.String(length=32), nullable=False, server_default="legacy_unknown"
        ),
    )


def downgrade() -> None:
    op.drop_column("user_verifications", "source")
    op.drop_column("user_verifications", "snapshot_version")
    op.drop_column("user_verifications", "snapshot_organization")
    op.drop_column("user_verifications", "snapshot_student_no")
    op.drop_column("user_verifications", "snapshot_real_name")
    op.drop_column("user_profiles", "profile_version")
