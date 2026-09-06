"""Add activation_tokens and email_outbox tables (T15).

一次性激活链接（HMAC 摘要存储、单次消费）逐步替代共用初始密码；
邮件 outbox 与业务事务一起记录待发送任务，worker 领取/退避重试。

Revision ID: d8f2a06c4b11
Revises: c7e1d95b3a10
Create Date: 2026-09-06
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "d8f2a06c4b11"
down_revision: Union[str, None] = "c7e1d95b3a10"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "activation_tokens",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "account_id", sa.String(length=36), sa.ForeignKey("accounts.id"), nullable=False
        ),
        sa.Column("token_hash", sa.String(length=64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_activation_tokens_account_id", "activation_tokens", ["account_id"])
    op.create_index(
        "ix_activation_tokens_account_created_at",
        "activation_tokens",
        ["account_id", "created_at"],
    )
    op.create_table(
        "email_outbox",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("kind", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("to_email", sa.String(length=128), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("html", sa.Text(), nullable=False),
        sa.Column("ref_type", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("ref_id", sa.String(length=36), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="queued"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_error", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_email_outbox_to_email", "email_outbox", ["to_email"])
    op.create_index("ix_email_outbox_status", "email_outbox", ["status"])
    op.create_index(
        "ix_email_outbox_status_next_retry", "email_outbox", ["status", "next_retry_at"]
    )
    op.create_index("ix_email_outbox_created_at", "email_outbox", ["created_at"])


def downgrade() -> None:
    op.drop_table("email_outbox")
    op.drop_table("activation_tokens")
