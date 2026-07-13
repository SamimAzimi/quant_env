"""Database engine/session for the Market Preparation app.

The DSN comes from the environment (MARKET_PREP_DB_URL). Default targets a
local MySQL database per the system spec; any SQLAlchemy URL works, which is
how the test suite runs against SQLite.

    MARKET_PREP_DB_URL=mysql+pymysql://user:pass@localhost:3306/market_prep
"""
from __future__ import annotations

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

DB_URL = os.environ.get(
    "MARKET_PREP_DB_URL",
    "mysql+pymysql://root:new_password@localhost:3306/market_prep",
)

_engine_kwargs = {"pool_pre_ping": True} if DB_URL.startswith("mysql") else {}
engine = create_engine(DB_URL, **_engine_kwargs)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    """FastAPI dependency yielding a scoped session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
