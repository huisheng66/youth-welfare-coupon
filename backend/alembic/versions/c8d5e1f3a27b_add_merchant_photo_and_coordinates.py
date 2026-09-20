"""Add merchant photo and GCJ-02 coordinates for the storefront page.

T25 商家详情页：门头照原图入库（MySQL 落 MEDIUMBLOB），经纬度存高德
坐标拾取器复制的 GCJ-02 文本，供用户端详情页唤起地图导航。

Revision ID: c8d5e1f3a27b
Revises: d8f2a06c4b11
Create Date: 2026-09-12
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "c8d5e1f3a27b"
down_revision: Union[str, None] = "d8f2a06c4b11"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 幂等：ensure_schema 时代的开发库在旧启动路径下已把这几列 ALTER 进来，
    # 但 alembic_version 仍停在上一个 revision（d8f2a06c4b11）。此时直接
    # add_column 会因 duplicate column 崩溃，导致开发库无法启动。
    # 逐列检查后再加，历史库与全新库都能平滑 upgrade。
    existing = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("merchants")}
    columns = [
        sa.Column("photo_blob", sa.LargeBinary(16777215), nullable=True),
        sa.Column("photo_content_type", sa.String(length=50), nullable=False, server_default=""),
        sa.Column("photo_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("longitude", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("latitude", sa.String(length=32), nullable=False, server_default=""),
    ]
    for column in columns:
        if column.name not in existing:
            op.add_column("merchants", column)


def downgrade() -> None:
    op.drop_column("merchants", "latitude")
    op.drop_column("merchants", "longitude")
    op.drop_column("merchants", "photo_updated_at")
    op.drop_column("merchants", "photo_content_type")
    op.drop_column("merchants", "photo_blob")
