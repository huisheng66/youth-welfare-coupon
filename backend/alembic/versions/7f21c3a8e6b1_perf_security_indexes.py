"""Add composite indexes for paginated, filtered, and audit-heavy queries."""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op


revision: str = "7f21c3a8e6b1"
down_revision: Union[str, None] = "2c984c17c453"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


INDEXES = (
    ("ix_accounts_role_created_at", "accounts", ("role", "created_at")),
    ("ix_user_verifications_profile_created_at", "user_verifications", ("profile_id", "created_at")),
    ("ix_user_verifications_status_created_at", "user_verifications", ("status", "created_at")),
    ("ix_coupon_templates_merchant_created_at", "coupon_templates", ("merchant_id", "created_at")),
    ("ix_coupon_instances_user_issued_at", "coupon_instances", ("user_id", "issued_at")),
    ("ix_coupon_instances_merchant_issued_at", "coupon_instances", ("merchant_id", "issued_at")),
    ("ix_coupon_instances_status_issued_at", "coupon_instances", ("status", "issued_at")),
    ("ix_coupon_instances_status_expires_at", "coupon_instances", ("status", "expires_at")),
    ("ix_redemption_logs_merchant_created_at", "redemption_logs", ("merchant_id", "created_at")),
    ("ix_redemption_logs_result_created_at", "redemption_logs", ("result", "created_at")),
    ("ix_audit_logs_created_at", "audit_logs", ("created_at",)),
    ("ix_point_ledgers_user_created_at", "point_ledgers", ("user_id", "created_at")),
    ("ix_email_codes_email_purpose_created_at", "email_codes", ("email", "purpose", "created_at")),
)


def upgrade() -> None:
    for name, table, columns in INDEXES:
        op.create_index(name, table, list(columns), unique=False)


def downgrade() -> None:
    for name, table, _ in reversed(INDEXES):
        op.drop_index(name, table_name=table)
