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
    op.add_column("merchants", sa.Column("photo_blob", sa.LargeBinary(16777215), nullable=True))
    op.add_column(
        "merchants",
        sa.Column("photo_content_type", sa.String(length=50), nullable=False, server_default=""),
    )
    op.add_column("merchants", sa.Column("photo_updated_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "merchants",
        sa.Column("longitude", sa.String(length=32), nullable=False, server_default=""),
    )
    op.add_column(
        "merchants",
        sa.Column("latitude", sa.String(length=32), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("merchants", "latitude")
    op.drop_column("merchants", "longitude")
    op.drop_column("merchants", "photo_updated_at")
    op.drop_column("merchants", "photo_content_type")
    op.drop_column("merchants", "photo_blob")
