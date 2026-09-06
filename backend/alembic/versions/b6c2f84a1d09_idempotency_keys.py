"""Add idempotency_keys table for write-operation idempotency (T13).

键按 操作者+操作类型+客户端键 唯一；仅存请求摘要与结果关联，
与业务写入同事务提交，重放不重复执行。

Revision ID: b6c2f84a1d09
Revises: a9d3e71b2c05
Create Date: 2026-09-06
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "b6c2f84a1d09"
down_revision: Union[str, None] = "a9d3e71b2c05"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "idempotency_keys",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("key", sa.String(length=128), nullable=False),
        sa.Column("actor_id", sa.String(length=36), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("action", sa.String(length=48), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="completed"),
        sa.Column("result_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("actor_id", "action", "key", name="uq_idempotency_scope"),
    )
    op.create_index("ix_idempotency_keys_actor_id", "idempotency_keys", ["actor_id"])
    op.create_index("ix_idempotency_keys_created_at", "idempotency_keys", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_idempotency_keys_created_at", table_name="idempotency_keys")
    op.drop_index("ix_idempotency_keys_actor_id", table_name="idempotency_keys")
    op.drop_table("idempotency_keys")
