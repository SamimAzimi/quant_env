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


def migrate(engine: Engine) -> None:
    Base.metadata.create_all(engine)   # new tables (and no-op for existing)

    inspector = inspect(engine)
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
