"""Add redemption_logs.reason for stable failure reason codes.

核销/作废失败也要留痕，前端与报表按 reason 稳定分类
（already_used / voided / expired / wrong_merchant / invalid_live_code /
state_conflict / merchant_inactive / redeemed）。历史失败行 reason 为空，
对外展示为 legacy_unknown，不回写伪造原因。

Revision ID: cf60b31a7e22
Revises: b7e42a9013dd
Create Date: 2026-09-05
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "cf60b31a7e22"
down_revision: Union[str, None] = "b7e42a9013dd"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "redemption_logs",
        sa.Column("reason", sa.String(length=32), nullable=False, server_default=sa.text("''")),
    )


def downgrade() -> None:
    op.drop_column("redemption_logs", "reason")
