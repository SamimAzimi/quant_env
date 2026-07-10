"""Normalized schema for the Market Preparation app.

All datetimes are stored as naive UTC (the repo-wide convention: market data
CSVs are UTC bar-open times, sessions are defined in UTC hours).

Entity relationships:
    news        *--* tag           (news_tags)
    news        *--* asset         (news_effects — the "Effect" multi-select)
    asset       *--1 asset_category (Forex, Crypto, ... each hard or soft)
    rate_prob   *--1 rate_snapshot  (one snapshot per recorded FedWatch table)
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean, Column, Date, DateTime, Enum, Float, ForeignKey, Integer,
    String, Table, Text, UniqueConstraint,
)
from sqlalchemy.orm import relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


news_tags = Table(
    "news_tags", Base.metadata,
    Column("news_id", ForeignKey("news.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
)

news_effects = Table(
    "news_effects", Base.metadata,
    Column("news_id", ForeignKey("news.id", ondelete="CASCADE"), primary_key=True),
    Column("asset_id", ForeignKey("assets.id", ondelete="CASCADE"), primary_key=True),
)


class Tag(Base):
    __tablename__ = "tags"
    id = Column(Integer, primary_key=True)
    name = Column(String(100), unique=True, nullable=False)


class AssetCategory(Base):
    """Sub-category (Forex, Crypto, Indices, ... / Commodities) with its kind."""
    __tablename__ = "asset_categories"
    id = Column(Integer, primary_key=True)
    name = Column(String(50), unique=True, nullable=False)
    kind = Column(Enum("hard", "soft", name="asset_kind"), nullable=False)

    assets = relationship("Asset", back_populates="category")


class Asset(Base):
    """A selectable "Effect" target: GOLD, USDJPY, BTCUSDT, ..."""
    __tablename__ = "assets"
    id = Column(Integer, primary_key=True)
    ticker = Column(String(30), unique=True, nullable=False)
    name = Column(String(100), nullable=False, default="")
    category_id = Column(ForeignKey("asset_categories.id"), nullable=False)

    category = relationship("AssetCategory", back_populates="assets")


class News(Base):
    __tablename__ = "news"
    id = Column(Integer, primary_key=True)
    title = Column(String(300), nullable=False)
    body = Column(Text, nullable=False, default="")
    to_watch = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, nullable=False, default=utcnow)

    tags = relationship("Tag", secondary=news_tags, lazy="selectin")
    effects = relationship("Asset", secondary=news_effects, lazy="selectin")


class Trade(Base):
    __tablename__ = "trades"
    id = Column(Integer, primary_key=True)
    entry_time = Column(DateTime, nullable=False)          # UTC
    exit_time = Column(DateTime, nullable=True)            # UTC, added later
    entry_reason = Column(Text, nullable=False, default="")
    exit_reason = Column(Text, nullable=True)
    tp = Column(Float, nullable=True)
    sl = Column(Float, nullable=True)
    remarks = Column(Text, nullable=False, default="")
    created_at = Column(DateTime, nullable=False, default=utcnow)


class VixReading(Base):
    __tablename__ = "vix_readings"
    id = Column(Integer, primary_key=True)
    ts = Column(DateTime, nullable=False, default=utcnow)  # UTC
    value = Column(Float, nullable=False)


class FearGreedReading(Base):
    __tablename__ = "fear_greed_readings"
    id = Column(Integer, primary_key=True)
    ts = Column(DateTime, nullable=False, default=utcnow)  # UTC
    value = Column(Float, nullable=False)                  # 0..100


class EconReport(Base):
    __tablename__ = "econ_reports"
    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False)
    forecast = Column(String(50), nullable=False, default="")
    previous = Column(String(50), nullable=False, default="")
    actual = Column(String(50), nullable=True)             # filled when released
    outcome = Column(Enum("beat", "miss", "inline", name="econ_outcome"),
                     nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)


class Thought(Base):
    __tablename__ = "thoughts"
    id = Column(Integer, primary_key=True)
    ts = Column(DateTime, nullable=False, default=utcnow)  # UTC
    body = Column(Text, nullable=False)


class RateSnapshot(Base):
    """One recorded FedWatch-style probability table."""
    __tablename__ = "rate_snapshots"
    id = Column(Integer, primary_key=True)
    captured_at = Column(DateTime, nullable=False, default=utcnow)

    probs = relationship("RateProb", back_populates="snapshot",
                         cascade="all, delete-orphan", lazy="selectin")


class RateProb(Base):
    __tablename__ = "rate_probs"
    __table_args__ = (
        UniqueConstraint("snapshot_id", "meeting_date", "bucket_low",
                         name="uq_rate_prob"),
    )
    id = Column(Integer, primary_key=True)
    snapshot_id = Column(ForeignKey("rate_snapshots.id", ondelete="CASCADE"),
                         nullable=False)
    meeting_date = Column(Date, nullable=False)
    bucket_low = Column(Integer, nullable=False)    # bps, e.g. 350
    bucket_high = Column(Integer, nullable=False)   # bps, e.g. 375
    probability = Column(Float, nullable=False)     # 0..100

    snapshot = relationship("RateSnapshot", back_populates="probs")
