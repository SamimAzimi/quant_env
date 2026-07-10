"""Pydantic request/response schemas for the Market Preparation API."""
from __future__ import annotations

from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class OrmModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --- meta ---------------------------------------------------------------

class TagOut(OrmModel):
    id: int
    name: str


class TagIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class AssetOut(OrmModel):
    id: int
    ticker: str
    name: str


class AssetCategoryOut(OrmModel):
    id: int
    name: str
    kind: Literal["hard", "soft"]
    assets: list[AssetOut]


class AssetIn(BaseModel):
    ticker: str = Field(min_length=1, max_length=30)
    name: str = ""
    category_id: int


class CountryOut(OrmModel):
    id: int
    name: str


class CountryIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)


# --- news ---------------------------------------------------------------

NewsRole = Literal["primary", "supporting", "contradicting", "duplicate", "update"]
NewsStatus = Literal["open", "close"]


class SourceOut(OrmModel):
    id: int
    name: str


class SourceIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class NewsIn(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    body: str = ""
    role: NewsRole = "primary"
    source_id: Optional[int] = None
    status: NewsStatus = "close"
    publish_time: Optional[datetime] = None   # defaults to now (UTC)
    tag_ids: list[int] = []
    effect_ids: list[int] = []
    parent_ids: list[int] = []                # stories this one relates to


class NewsPatch(BaseModel):
    title: Optional[str] = None
    body: Optional[str] = None
    role: Optional[NewsRole] = None
    source_id: Optional[int] = None
    status: Optional[NewsStatus] = None
    publish_time: Optional[datetime] = None
    tag_ids: Optional[list[int]] = None
    effect_ids: Optional[list[int]] = None
    parent_ids: Optional[list[int]] = None    # replaces all parent links


class NewsOut(OrmModel):
    id: int
    title: str
    body: str
    role: str
    status: str
    source: Optional[SourceOut]
    publish_time: datetime
    created_at: datetime
    tags: list[TagOut]
    effects: list[AssetOut]


class NewsTreeOut(NewsOut):
    """A story with its related follow-ups nested recursively."""
    children: list["NewsTreeOut"] = []


class NewsThreadOut(BaseModel):
    """Full context of one story: ancestors up the chain + its subtree."""
    ancestors: list[NewsOut]
    parent_ids: list[int]     # the story's direct parents (for editing links)
    tree: NewsTreeOut


class NewsGroupOut(BaseModel):
    """A connected component of related stories in a date range."""
    name: str
    news: list[NewsOut]                       # sorted by publish_time
    edges: list[tuple[int, int]]              # (parent_id, child_id)


# --- trades -------------------------------------------------------------

class TradeIn(BaseModel):
    asset_id: Optional[int] = None
    entry_time: datetime
    exit_time: Optional[datetime] = None
    entry_price: Optional[float] = None
    exit_price: Optional[float] = None
    entry_reason: str = ""
    exit_reason: Optional[str] = None
    tp: Optional[float] = None
    sl: Optional[float] = None
    remarks: str = ""


class TradePatch(BaseModel):
    asset_id: Optional[int] = None
    entry_time: Optional[datetime] = None
    exit_time: Optional[datetime] = None
    entry_price: Optional[float] = None
    exit_price: Optional[float] = None
    entry_reason: Optional[str] = None
    exit_reason: Optional[str] = None
    tp: Optional[float] = None
    sl: Optional[float] = None
    remarks: Optional[str] = None


class TradeOut(OrmModel):
    id: int
    asset_id: Optional[int]
    asset: Optional[AssetOut]
    entry_time: datetime
    exit_time: Optional[datetime]
    entry_price: Optional[float]
    exit_price: Optional[float]
    entry_reason: str
    exit_reason: Optional[str]
    tp: Optional[float]
    sl: Optional[float]
    remarks: str
    created_at: datetime


# --- point readings (VIX / Fear & Greed / thoughts) ----------------------

class ReadingIn(BaseModel):
    value: float
    ts: Optional[datetime] = None      # defaults to now (UTC) server-side


class ReadingOut(OrmModel):
    id: int
    ts: datetime
    value: float


class ThoughtIn(BaseModel):
    body: str = Field(min_length=1)
    ts: Optional[datetime] = None


class ThoughtOut(OrmModel):
    id: int
    ts: datetime
    body: str


# --- economic reports -----------------------------------------------------

class EconReportIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    country_id: Optional[int] = None
    forecast: str = ""
    previous: str = ""
    actual: Optional[str] = None
    outcome: Optional[Literal["beat", "miss", "inline"]] = None


class EconReportPatch(BaseModel):
    country_id: Optional[int] = None
    actual: Optional[str] = None
    outcome: Optional[Literal["beat", "miss", "inline"]] = None


class EconReportOut(OrmModel):
    id: int
    name: str
    country: Optional[CountryOut]
    forecast: str
    previous: str
    actual: Optional[str]
    outcome: Optional[str]
    created_at: datetime


# --- rate probabilities ---------------------------------------------------

class RateTableIn(BaseModel):
    table: str = Field(min_length=1, description="Markdown FedWatch-style table")


class RateProbOut(BaseModel):
    meeting_date: date
    bucket: str            # "350-375"
    probability: float


class RateSnapshotOut(BaseModel):
    id: int
    captured_at: datetime
    probs: list[RateProbOut]
