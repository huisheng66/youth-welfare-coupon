"""Add import_batches / import_rows tables for unified import flow (T14).

预检 → 确认执行 → 逐行结果：批次保存类型/操作者/文件摘要/参数/状态/计数，
逐行保存预检与执行状态、失败原因和业务对象关联；断点续执只处理未完成行。

Revision ID: c7e1d95b3a10
Revises: b6c2f84a1d09
Create Date: 2026-09-06
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "c7e1d95b3a10"
down_revision: Union[str, None] = "b6c2f84a1d09"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "import_batches",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("actor_id", sa.String(length=36), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("file_sha256", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("params_json", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="previewed"),
        sa.Column("total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("succeeded", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("message", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_import_batches_kind", "import_batches", ["kind"])
    op.create_index("ix_import_batches_actor_id", "import_batches", ["actor_id"])
    op.create_index("ix_import_batches_status", "import_batches", ["status"])
    op.create_index(
        "ix_import_batches_actor_created_at", "import_batches", ["actor_id", "created_at"]
    )
    op.create_table(
        "import_rows",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "batch_id",
            sa.String(length=36),
            sa.ForeignKey("import_batches.id"),
            nullable=False,
        ),
        sa.Column("row_no", sa.Integer(), nullable=False),
        sa.Column("identifier", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("reason", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("ref_id", sa.String(length=36), nullable=False, server_default=""),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_import_rows_batch_id", "import_rows", ["batch_id"])
    op.create_index("ix_import_rows_batch_row_no", "import_rows", ["batch_id", "row_no"])
    op.create_index("ix_import_rows_batch_status", "import_rows", ["batch_id", "status"])


def downgrade() -> None:
    op.drop_table("import_rows")
    op.drop_table("import_batches")
