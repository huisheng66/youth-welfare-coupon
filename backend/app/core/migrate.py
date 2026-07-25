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
