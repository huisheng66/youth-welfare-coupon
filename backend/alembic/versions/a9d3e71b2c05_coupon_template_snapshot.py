"""Add issue-time template snapshot columns to coupon instances.

模板名称/描述是权益内容，发放后模板编辑不应改变已发券的券面；
快照列可空——历史行无快照，展示回退模板当前值，不回填伪造历史。

Revision ID: a9d3e71b2c05
Revises: e4f8a2c1b907
Create Date: 2026-09-06
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "a9d3e71b2c05"
down_revision: Union[str, None] = "e4f8a2c1b907"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "coupon_instances",
        sa.Column("template_name", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "coupon_instances",
        sa.Column("template_description", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("coupon_instances", "template_description")
    op.drop_column("coupon_instances", "template_name")
