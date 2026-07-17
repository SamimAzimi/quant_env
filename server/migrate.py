"""Minimal forward-only migration: add tables/columns the models define but
the live database lacks.

`Base.metadata.create_all` creates missing tables but never alters existing
ones, so evolving an installed database would otherwise require manual DDL.
This inspects each model table and issues ADD COLUMN for anything missing —
sufficient while all schema changes are additive (new nullable columns).
Works on both MySQL and SQLite.
"""
from __future__ import annotations

import logging

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from .db import Base
from . import models  # noqa: F401  — registers all tables on Base.metadata

logger = logging.getLogger(__name__)

# Columns the models no longer write. Left in place they break MySQL strict
# mode (NOT NULL, no default → error 1364 on INSERT), so they are dropped
# after their data has been backfilled into the replacement column.
RETIRED_COLUMNS: list[tuple[str, str]] = [
    ("news", "to_watch"),      # replaced by news.status (backfilled below)
]


def migrate(engine: Engine) -> None:
    Base.metadata.create_all(engine)   # new tables (and no-op for existing)

    inspector = inspect(engine)
    added: set[tuple[str, str]] = set()
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            existing = {c["name"] for c in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in existing:
                    continue
                if not (column.nullable or column.default is not None
                        or column.server_default is not None):
                    logger.warning(
                        "Skipping non-nullable column %s.%s — add it manually",
                        table.name, column.name)
                    continue
                ddl = (f"ALTER TABLE {table.name} ADD COLUMN {column.name} "
                       f"{column.type.compile(engine.dialect)}")
                logger.info("Migrating: %s", ddl)
                conn.execute(text(ddl))
                added.add((table.name, column.name))

        _widen_varchars(engine, conn, inspector)
        _backfill_news(conn, inspector, added)

        for table_name, column_name in RETIRED_COLUMNS:
            existing = {c["name"] for c in inspector.get_columns(table_name)}
            if column_name not in existing:
                continue
            ddl = f"ALTER TABLE {table_name} DROP COLUMN {column_name}"
            logger.info("Migrating: %s", ddl)
            try:
                conn.execute(text(ddl))
            except Exception:   # very old SQLite: neutralize instead
                logger.warning("DROP COLUMN failed; leaving %s.%s in place",
                               table_name, column_name)


# TEXT-family capacity order — used to decide whether a MODIFY grows a column
_TEXT_RANK = {"TINYTEXT": 0, "TEXT": 1, "MEDIUMTEXT": 2, "LONGTEXT": 3}


def _widen_varchars(engine: Engine, conn, inspector) -> None:
    """Enlarge columns the models have grown since the table was created —
    in place with MODIFY, so existing rows are untouched. Covers VARCHAR
    length increases (e.g. bt_runs.asset_class 10 → 40) and TEXT-family
    upgrades (e.g. bt_frames.payload TEXT 64 KB → LONGTEXT for the big JSON
    report frames). MySQL only: SQLite enforces neither, so there is
    nothing to widen there. Only ever grows a column, never shrinks.
    """
    if engine.dialect.name != "mysql":
        return
    for table in Base.metadata.sorted_tables:
        db_cols = {c["name"]: c for c in inspector.get_columns(table.name)}
        for column in table.columns:
            dbc = db_cols.get(column.name)
            if dbc is None:
                continue
            new_type = None
            model_len = getattr(column.type, "length", None)
            db_len = getattr(dbc["type"], "length", None)
            if model_len and db_len and db_len < model_len:
                new_type = f"VARCHAR({model_len})"
            else:
                model_txt = column.type.compile(engine.dialect).upper()
                db_txt = str(dbc["type"]).upper()
                if (model_txt in _TEXT_RANK and db_txt in _TEXT_RANK
                        and _TEXT_RANK[db_txt] < _TEXT_RANK[model_txt]):
                    new_type = model_txt
            if new_type is None:
                continue
            null_sql = "" if column.nullable else " NOT NULL"
            ddl = (f"ALTER TABLE {table.name} MODIFY COLUMN {column.name} "
                   f"{new_type}{null_sql}")
            logger.info("Migrating: %s", ddl)
            conn.execute(text(ddl))


def _backfill_news(conn, inspector, added: set[tuple[str, str]]) -> None:
    """Populate the v3 news columns on databases upgraded in place.

    status derives from the retired to_watch flag (open = was watched);
    publish_time and role fall back to the recording time / 'primary'.
    """
    news_cols = {c["name"] for c in inspector.get_columns("news")}
    if ("news", "status") in added:
        if "to_watch" in news_cols:
            conn.execute(text(
                "UPDATE news SET status = CASE WHEN to_watch THEN 'open' "
                "ELSE 'close' END WHERE status IS NULL"))
        else:
            conn.execute(text(
                "UPDATE news SET status = 'close' WHERE status IS NULL"))
    if ("news", "publish_time") in added:
        conn.execute(text(
            "UPDATE news SET publish_time = created_at "
            "WHERE publish_time IS NULL"))
    if ("news", "role") in added:
        conn.execute(text(
            "UPDATE news SET role = 'primary' WHERE role IS NULL"))
