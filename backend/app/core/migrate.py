"""Lightweight schema patches for SQLite/dev (create_all does not alter columns)."""

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine


def _add_column_if_missing(engine: Engine, table: str, column: str, ddl: str) -> None:
    insp = inspect(engine)
    if table not in insp.get_table_names():
        return
    cols = {c["name"] for c in insp.get_columns(table)}
    if column not in cols:
        with engine.begin() as conn:
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {ddl}"))


def ensure_schema(engine: Engine) -> None:
    _add_column_if_missing(engine, "coupon_templates", "cost_points", "cost_points INTEGER DEFAULT 0 NOT NULL")
    _add_column_if_missing(engine, "point_ledgers", "balance_after", "balance_after INTEGER DEFAULT 0 NOT NULL")
    _add_column_if_missing(engine, "point_ledgers", "operator_id", "operator_id VARCHAR(36)")
    _add_column_if_missing(engine, "point_ledgers", "ref_type", "ref_type VARCHAR(32) DEFAULT ''")
    _add_column_if_missing(engine, "point_ledgers", "ref_id", "ref_id VARCHAR(36) DEFAULT ''")
    _add_column_if_missing(engine, "accounts", "email", "email VARCHAR(128)")
    _add_column_if_missing(engine, "user_profiles", "student_no", "student_no VARCHAR(64) DEFAULT ''")
    # 旧字段 id_number_masked 保留在库中（SQLite 不便删列），业务已改用 student_no
    _add_column_if_missing(engine, "user_profiles", "bank_card_encrypted", "bank_card_encrypted TEXT")
    _add_column_if_missing(engine, "user_profiles", "bank_card_last4", "bank_card_last4 VARCHAR(4) DEFAULT ''")
    _add_column_if_missing(engine, "user_profiles", "bank_card_bank_name", "bank_card_bank_name VARCHAR(64) DEFAULT ''")
    _add_column_if_missing(engine, "user_profiles", "bank_card_bound_at", "bank_card_bound_at DATETIME")
