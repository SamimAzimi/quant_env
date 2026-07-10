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


# --- news ---------------------------------------------------------------

class NewsIn(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    body: str = ""
    tag_ids: list[int] = []
    effect_ids: list[int] = []
    to_watch: bool = False


class NewsPatch(BaseModel):
    to_watch: Optional[bool] = None


class NewsOut(OrmModel):
    id: int
    title: str
    body: str
    to_watch: bool
    created_at: datetime
    tags: list[TagOut]
    effects: list[AssetOut]


# --- trades -------------------------------------------------------------

class TradeIn(BaseModel):
    entry_time: datetime
    exit_time: Optional[datetime] = None
    entry_reason: str = ""
    exit_reason: Optional[str] = None
    tp: Optional[float] = None
    sl: Optional[float] = None
    remarks: str = ""


class TradePatch(BaseModel):
    entry_time: Optional[datetime] = None
    exit_time: Optional[datetime] = None
    entry_reason: Optional[str] = None
    exit_reason: Optional[str] = None
    tp: Optional[float] = None
    sl: Optional[float] = None
    remarks: Optional[str] = None


class TradeOut(OrmModel):
    id: int
    entry_time: datetime
    exit_time: Optional[datetime]
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
    forecast: str = ""
    previous: str = ""
    actual: Optional[str] = None
    outcome: Optional[Literal["beat", "miss", "inline"]] = None


class EconReportPatch(BaseModel):
    actual: Optional[str] = None
    outcome: Optional[Literal["beat", "miss", "inline"]] = None


class EconReportOut(OrmModel):
    id: int
    name: str
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
