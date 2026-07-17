"""Normalized schema for the Market Preparation app.

All datetimes are stored as naive UTC (the repo-wide convention: market data
CSVs are UTC bar-open times, sessions are defined in UTC hours).

Entity relationships:
    news        *--* tag           (news_tags)
    news        *--* asset         (news_effects — the "Effect" multi-select)
    news        *--1 source        (optional origin of the story)
    news        *--* news          (news_relationships: parent story → child
                                    follow-up/supporting/contradicting story)
    asset       *--1 asset_category (Forex, Crypto, ... each hard or soft)
    rate_prob   *--1 rate_snapshot  (one snapshot per recorded FedWatch table)
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    Column, Date, DateTime, Enum, Float, ForeignKey, Integer,
    String, Table, Text, UniqueConstraint,
)
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.orm import relationship

from .db import Base

# Machine-generated JSON blobs (report frames, band studies, trade extras)
# routinely exceed MySQL TEXT's 64 KB — store them as LONGTEXT there.
# SQLite has no length classes, so plain TEXT elsewhere.
BigJSON = Text().with_variant(LONGTEXT(), "mysql")


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


class Country(Base):
    """Lookup for economic-report countries (normalized, user-extendable)."""
    __tablename__ = "countries"
    id = Column(Integer, primary_key=True)
    name = Column(String(80), unique=True, nullable=False)


class Source(Base):
    """Where a story came from (Bloomberg, Reuters, X, ...)."""
    __tablename__ = "sources"
    id = Column(Integer, primary_key=True)
    name = Column(String(120), unique=True, nullable=False)


NEWS_ROLES = ("primary", "supporting", "contradicting", "duplicate", "update")


class News(Base):
    __tablename__ = "news"
    id = Column(Integer, primary_key=True)
    title = Column(String(300), nullable=False)
    body = Column(Text, nullable=False, default="")
    role = Column(Enum(*NEWS_ROLES, name="news_role"),
                  nullable=False, default="primary")
    source_id = Column(ForeignKey("sources.id"), nullable=True)
    # open stories appear in To Watch until closed (replaces old to_watch)
    status = Column(Enum("open", "close", name="news_status"),
                    nullable=False, default="close")
    publish_time = Column(DateTime, nullable=False, default=utcnow)  # UTC
    created_at = Column(DateTime, nullable=False, default=utcnow)

    source = relationship("Source", lazy="joined")
    tags = relationship("Tag", secondary=news_tags, lazy="selectin")
    effects = relationship("Asset", secondary=news_effects, lazy="selectin")


class NewsRelationship(Base):
    """Directed story link: parent (original) → child (follow-up)."""
    __tablename__ = "news_relationships"
    __table_args__ = (
        UniqueConstraint("parent_id", "child_id", name="uq_news_rel"),
    )
    id = Column(Integer, primary_key=True)
    parent_id = Column(ForeignKey("news.id", ondelete="CASCADE"), nullable=False)
    child_id = Column(ForeignKey("news.id", ondelete="CASCADE"), nullable=False)


class Trade(Base):
    __tablename__ = "trades"
    id = Column(Integer, primary_key=True)
    asset_id = Column(ForeignKey("assets.id"), nullable=True)
    entry_time = Column(DateTime, nullable=False)          # UTC
    exit_time = Column(DateTime, nullable=True)            # UTC, added later
    entry_price = Column(Float, nullable=True)
    exit_price = Column(Float, nullable=True)
    entry_reason = Column(Text, nullable=False, default="")
    exit_reason = Column(Text, nullable=True)
    tp = Column(Float, nullable=True)
    sl = Column(Float, nullable=True)
    remarks = Column(Text, nullable=False, default="")
    created_at = Column(DateTime, nullable=False, default=utcnow)

    asset = relationship("Asset", lazy="joined")


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
    country_id = Column(ForeignKey("countries.id"), nullable=True)
    name = Column(String(200), nullable=False)
    forecast = Column(String(50), nullable=False, default="")
    previous = Column(String(50), nullable=False, default="")
    actual = Column(String(50), nullable=True)             # filled when released
    outcome = Column(Enum("beat", "miss", "inline", name="econ_outcome"),
                     nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)

    country = relationship("Country", lazy="joined")


class Thought(Base):
    __tablename__ = "thoughts"
    id = Column(Integer, primary_key=True)
    ts = Column(DateTime, nullable=False, default=utcnow)  # UTC
    body = Column(Text, nullable=False)


class Alert(Base):
    """A one-shot reminder: sent to the Telegram alert chat at due_time
    (UTC) and deleted once delivered."""
    __tablename__ = "alerts"
    id = Column(Integer, primary_key=True)
    due_time = Column(DateTime, nullable=False)            # UTC
    message = Column(Text, nullable=False)
    created_at = Column(DateTime, nullable=False, default=utcnow)


class SavedReport(Base):
    """A saved analysis payload (e.g. a band-behaviour study) kept for later
    review or for feeding to another AI prompt."""
    __tablename__ = "saved_reports"
    id = Column(Integer, primary_key=True)
    kind = Column(String(40), nullable=False)            # e.g. "band_study"
    title = Column(String(200), nullable=False)
    params_json = Column(BigJSON, nullable=False, default="{}")
    payload = Column(BigJSON, nullable=False)            # JSON blob
    created_at = Column(DateTime, nullable=False, default=utcnow)


class BtRun(Base):
    """One persisted backtest run (pipeline execution)."""
    __tablename__ = "bt_runs"
    id = Column(Integer, primary_key=True)
    run_id = Column(String(120), unique=True, nullable=False)
    asset = Column(String(40), nullable=False)
    strategy = Column(String(80), nullable=False, default="")
    timeframe = Column(String(20), nullable=False, default="")
    asset_class = Column(String(40), nullable=False, default="")
    saved_at = Column(DateTime, nullable=False, default=utcnow)
    n_trades = Column(Integer, nullable=False, default=0)
    metadata_json = Column(BigJSON, nullable=False, default="{}")

    metrics = relationship("BtMetric", back_populates="run",
                           cascade="all, delete-orphan", lazy="selectin")
    trades = relationship("BtTrade", back_populates="run",
                          cascade="all, delete-orphan")
    equity = relationship("BtEquityPoint", back_populates="run",
                          cascade="all, delete-orphan")
    frames = relationship("BtFrame", back_populates="run",
                          cascade="all, delete-orphan")


class BtMetric(Base):
    """One scalar KPI of a run (normalized key/value; text fallback)."""
    __tablename__ = "bt_metrics"
    __table_args__ = (UniqueConstraint("run_pk", "name", name="uq_bt_metric"),)
    id = Column(Integer, primary_key=True)
    run_pk = Column(ForeignKey("bt_runs.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(80), nullable=False)
    value = Column(Float, nullable=True)
    text_value = Column(String(120), nullable=True)

    run = relationship("BtRun", back_populates="metrics")


class BtTrade(Base):
    """One ledger row (per lot) with account outcomes; strategy-specific
    fields (setup, lot, mu, sigma, segments, ...) live in extra_json."""
    __tablename__ = "bt_trades"
    id = Column(Integer, primary_key=True)
    run_pk = Column(ForeignKey("bt_runs.id", ondelete="CASCADE"), nullable=False)
    trade_id = Column(String(20), nullable=False)
    side = Column(String(10), nullable=True)
    setup_time = Column(DateTime, nullable=True)
    entry_time = Column(DateTime, nullable=True)
    exit_time = Column(DateTime, nullable=True)
    entry_price = Column(Float, nullable=True)
    exit_price = Column(Float, nullable=True)
    sl_price = Column(Float, nullable=True)
    tp_price = Column(Float, nullable=True)
    exit_reason = Column(String(40), nullable=True)
    lots = Column(Float, nullable=True)
    units = Column(Float, nullable=True)
    notional = Column(Float, nullable=True)
    spread_cost = Column(Float, nullable=True)
    commission_cost = Column(Float, nullable=True)
    financing_cost = Column(Float, nullable=True)
    total_cost = Column(Float, nullable=True)
    gross_pnl = Column(Float, nullable=True)
    net_pnl = Column(Float, nullable=True)
    r_multiple = Column(Float, nullable=True)
    equity_after = Column(Float, nullable=True)
    extra_json = Column(BigJSON, nullable=False, default="{}")

    run = relationship("BtRun", back_populates="trades")


class BtEquityPoint(Base):
    __tablename__ = "bt_equity"
    id = Column(Integer, primary_key=True)
    run_pk = Column(ForeignKey("bt_runs.id", ondelete="CASCADE"), nullable=False)
    step = Column(Integer, nullable=False)
    time = Column(DateTime, nullable=True)
    trade_id = Column(String(20), nullable=True)
    equity = Column(Float, nullable=False)

    run = relationship("BtRun", back_populates="equity")


class BtFrame(Base):
    """A report/detail frame (exit_reasons, monthly_returns, rolling series,
    by-period breakdowns, costed, strategy detail frames) as JSON payload."""
    __tablename__ = "bt_frames"
    __table_args__ = (UniqueConstraint("run_pk", "name", name="uq_bt_frame"),)
    id = Column(Integer, primary_key=True)
    run_pk = Column(ForeignKey("bt_runs.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(80), nullable=False)
    payload = Column(BigJSON, nullable=False)

    run = relationship("BtRun", back_populates="frames")


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
