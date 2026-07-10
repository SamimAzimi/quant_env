"""CSV-backed market data for the Stats page.

Reads the existing per-asset CSV store maintained by libs/data_manager.py
(<MARKET_DATA_DIR>/<ASSET>/<tf>.csv, UTC bar-open times) on request — no
duplication into MySQL, per the chosen architecture.

Provides:
  - the last completed trading day's bars per asset ("yesterday")
  - key levels: pre-day high/low plus each FX session's high/low
  - cumulative log returns across yesterday for the Pre-day stats chart
"""
from __future__ import annotations

import os
from datetime import date, datetime, timedelta
from functools import lru_cache

import numpy as np
import pandas as pd

from config.config import MARKET_DATA_DIR, DEFAULT_SESSIONS
from libs.data_loader import load_csv

CHART_ASSETS = ["NDX", "XAUUSD", "XAGUSD", "USDJPY", "EURUSD"]
TIMEFRAMES = ["5m", "15m", "30m", "1h", "2h", "4h"]


def available_assets() -> list[str]:
    """Asset folders present in the market-data store."""
    root = str(MARKET_DATA_DIR)
    if not os.path.isdir(root):
        return []
    return sorted(
        d for d in os.listdir(root)
        if os.path.isdir(os.path.join(root, d)) and not d.startswith(".")
    )


def _csv_path(asset: str, tf: str) -> str:
    return os.path.join(str(MARKET_DATA_DIR), asset, f"{tf}.csv")


@lru_cache(maxsize=64)
def _load(asset: str, tf: str, mtime: float) -> pd.DataFrame:
    """Load a CSV, keyed by file mtime so updates invalidate the cache."""
    df = load_csv(_csv_path(asset, tf))
    return df.dropna(subset=["Datetime"]).sort_values("Datetime").reset_index(drop=True)


def load_bars(asset: str, tf: str) -> pd.DataFrame:
    path = _csv_path(asset, tf)
    if not os.path.exists(path):
        raise FileNotFoundError(f"No {tf} data for {asset} (expected {path})")
    return _load(asset, tf, os.path.getmtime(path))


def last_trading_day(df: pd.DataFrame, today: date | None = None) -> date:
    """Most recent UTC calendar day with bars strictly before today.

    Skips weekends/holidays automatically: it's simply the last day present
    in the data, so on a Monday "yesterday" resolves to Friday.
    """
    today = today or datetime.utcnow().date()
    days = df["Datetime"].dt.date
    prior = days[days < today]
    if prior.empty:
        raise ValueError("No completed trading day in the data")
    return prior.iloc[-1]


def _day_slice(df: pd.DataFrame, day: date) -> pd.DataFrame:
    mask = df["Datetime"].dt.date == day
    return df.loc[mask]


def _session_windows() -> dict[str, tuple[int, int]]:
    return dict(DEFAULT_SESSIONS)


def key_levels(df: pd.DataFrame, day: date) -> list[dict]:
    """Pre-day H/L and per-session H/L for the charted day.

    Sessions come from config.sessions.DEFAULT_SESSIONS (UTC hour windows);
    a window with start > end wraps midnight and is anchored on the day it
    starts, extending into the next day's early bars.
    """
    levels: list[dict] = []

    days = sorted(set(df["Datetime"].dt.date))
    prior = [d for d in days if d < day]
    if prior:
        pre = _day_slice(df, prior[-1])
        levels.append({"label": "Pre-day High", "kind": "preday", "value": float(pre["High"].max())})
        levels.append({"label": "Pre-day Low", "kind": "preday", "value": float(pre["Low"].min())})

    day_start = pd.Timestamp(day)
    for name, (start_h, end_h) in _session_windows().items():
        start = day_start + pd.Timedelta(hours=start_h)
        if start_h > end_h:  # wraps midnight (e.g. Sydney 21→06)
            end = day_start + pd.Timedelta(days=1, hours=end_h)
        else:
            end = day_start + pd.Timedelta(hours=end_h)
        window = df[(df["Datetime"] >= start) & (df["Datetime"] < end)]
        if window.empty:
            continue
        pretty = name.capitalize().replace("Newyork", "New York")
        levels.append({"label": f"{pretty} High", "kind": f"session:{name}",
                       "value": float(window["High"].max())})
        levels.append({"label": f"{pretty} Low", "kind": f"session:{name}",
                       "value": float(window["Low"].min())})
    return levels


def yesterday_chart(asset: str, tf: str = "15m") -> dict:
    """Bars + key levels for the last completed trading day of one asset."""
    df = load_bars(asset, tf)
    day = last_trading_day(df)
    bars = _day_slice(df, day)
    return {
        "asset": asset,
        "timeframe": tf,
        "day": day.isoformat(),
        "bars": [
            {
                "time": int(row.Datetime.timestamp()),
                "open": float(row.Open),
                "high": float(row.High),
                "low": float(row.Low),
                "close": float(row.Close),
            }
            for row in bars.itertuples()
        ],
        "levels": key_levels(df, day),
    }


def yesterday_log_returns(assets: list[str], tf: str = "15m") -> dict:
    """Cumulative intraday log returns over each asset's last trading day."""
    series = []
    for asset in assets:
        try:
            df = load_bars(asset, tf)
            day = last_trading_day(df)
        except (FileNotFoundError, ValueError):
            continue
        bars = _day_slice(df, day)
        if len(bars) < 2:
            continue
        cum = np.log(bars["Close"]).diff().fillna(0.0).cumsum()
        series.append({
            "asset": asset,
            "day": day.isoformat(),
            "points": [
                {"time": int(t.timestamp()), "value": round(float(v) * 100, 4)}
                for t, v in zip(bars["Datetime"], cum)
            ],
        })
    return {"timeframe": tf, "series": series}
