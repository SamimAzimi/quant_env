"""CSV-backed market data for the Stats page.

Reads the existing per-asset CSV store maintained by libs/data_manager.py
(<MARKET_DATA_DIR>/<ASSET>/<tf>.csv, UTC bar-open times) on request — no
duplication into MySQL, per the chosen architecture.

Provides:
  - the last completed trading day's bars per asset ("yesterday")
  - key levels: pre-day high/low plus each major session's high/low
  - DST-accurate session spans (drawn as chart backgrounds)
  - cumulative log returns across yesterday for the Pre-day stats chart

Sessions come from libs/market_sessions.py: defined in local wall-clock
time per financial centre, so every UTC footprint (backgrounds, session
key levels, and the trading-day window itself) shifts correctly with DST
across all of history. A "trading day" is Tokyo open → New York close for
that specific date. Every endpoint accepts an as-of date so the website's
date selector can replay any past day.
"""
from __future__ import annotations

import os
from datetime import date, datetime, timedelta
from functools import lru_cache

import numpy as np
import pandas as pd

from config.config import MARKET_DATA_DIR
from libs.data_loader import load_csv
from libs.market_sessions import DEFAULT_SESSIONS as LIB_SESSIONS, local_to_utc

CHART_ASSETS = ["NDX", "XAUUSD", "XAGUSD", "USDJPY", "EURUSD"]
TIMEFRAMES = ["5m", "15m", "30m", "1h", "2h", "4h"]

# The four majors shown as chart backgrounds and session key levels.
MAJOR_SESSIONS = ("Sydney", "Tokyo", "London", "NewYork")
_SESSIONS = {s.name: s for s in LIB_SESSIONS if s.name in MAJOR_SESSIONS}

_PRETTY = {"NewYork": "New York"}


def _pretty(name: str) -> str:
    return _PRETTY.get(name, name)


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


# --------------------------------------------------------------------------
# DST-aware session windows (all naive-UTC, matching the CSV timestamps)
# --------------------------------------------------------------------------

def _session_utc(name: str, anchor: date) -> tuple[pd.Timestamp, pd.Timestamp]:
    """One session's [open, close) as naive UTC for a local anchor date.

    The session is defined in local wall-clock time, so converting each
    anchor date separately applies that date's DST rules exactly.
    """
    s = _SESSIONS[name]
    lo = local_to_utc(datetime.combine(anchor, s.open), s.tz)
    hi = local_to_utc(datetime.combine(anchor, s.close), s.tz)
    return lo.tz_localize(None), hi.tz_localize(None)


def day_window(day: date) -> tuple[pd.Timestamp, pd.Timestamp]:
    """Trading day: Tokyo open → New York close of `day`, DST-correct."""
    start, _ = _session_utc("Tokyo", day)
    _, end = _session_utc("NewYork", day)
    return start, end


def session_spans(day: date) -> list[dict]:
    """Each major session's UTC span(s) intersected with the trading day.

    A session anchored on the previous local date (Sydney evening) can
    reach into this trading day, so anchors day-1 .. day+1 are checked.
    Weekend anchors are skipped, matching market_sessions semantics.
    """
    win_start, win_end = day_window(day)
    spans = []
    for name in MAJOR_SESSIONS:
        for offset in (-1, 0, 1):
            anchor = day + timedelta(days=offset)
            if anchor.weekday() >= 5:      # Sat/Sun local anchor: closed
                continue
            lo, hi = _session_utc(name, anchor)
            start, end = max(lo, win_start), min(hi, win_end)
            if start < end:
                spans.append({
                    "name": _pretty(name),
                    "key": name.lower(),
                    "start": int(start.tz_localize("UTC").timestamp()),
                    "end": int(end.tz_localize("UTC").timestamp()),
                })
    spans.sort(key=lambda s: s["start"])
    return spans


def last_trading_day(df: pd.DataFrame, today: date | None = None) -> date:
    """Most recent trading day with bars strictly before `today` (UTC).

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
    """Bars in the Tokyo-open → NY-close window of `day` (DST-correct)."""
    start, end = day_window(day)
    return df[(df["Datetime"] >= start) & (df["Datetime"] < end)]


def key_levels(df: pd.DataFrame, day: date) -> list[dict]:
    """Pre-day H/L and per-session H/L for the charted day.

    Session windows come from libs/market_sessions.py (local wall-clock ×
    IANA tz), so the exact same regions shaded on the chart produce the
    session high/low levels.
    """
    levels: list[dict] = []

    days = sorted(set(df["Datetime"].dt.date))
    prior = [d for d in days if d < day]
    if prior:
        pre = _day_slice(df, prior[-1])
        if not pre.empty:
            levels.append({"label": "Pre-day High", "kind": "preday",
                           "value": float(pre["High"].max())})
            levels.append({"label": "Pre-day Low", "kind": "preday",
                           "value": float(pre["Low"].min())})

    for span in session_spans(day):
        lo = pd.Timestamp(span["start"], unit="s")
        hi = pd.Timestamp(span["end"], unit="s")
        window = df[(df["Datetime"] >= lo) & (df["Datetime"] < hi)]
        if window.empty:
            continue
        levels.append({"label": f"{span['name']} High",
                       "kind": f"session:{span['key']}",
                       "value": float(window["High"].max())})
        levels.append({"label": f"{span['name']} Low",
                       "kind": f"session:{span['key']}",
                       "value": float(window["Low"].min())})
    return levels


def yesterday_chart(asset: str, tf: str = "15m", as_of: date | None = None) -> dict:
    """Bars + key levels + session spans for the last completed trading day."""
    df = load_bars(asset, tf)
    day = last_trading_day(df, as_of)
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
        "sessions": session_spans(day),
    }


def bars_range(asset: str, tf: str, start: date, end: date) -> dict:
    """All bars between two dates inclusive — used to map news onto candles."""
    df = load_bars(asset, tf)
    lo = pd.Timestamp(start)
    hi = pd.Timestamp(end) + pd.Timedelta(days=1)
    window = df[(df["Datetime"] >= lo) & (df["Datetime"] < hi)]
    return {
        "asset": asset,
        "timeframe": tf,
        "bars": [
            {
                "time": int(row.Datetime.timestamp()),
                "open": float(row.Open),
                "high": float(row.High),
                "low": float(row.Low),
                "close": float(row.Close),
            }
            for row in window.itertuples()
        ],
    }


def yesterday_log_returns(assets: list[str], tf: str = "15m",
                          as_of: date | None = None) -> dict:
    """Cumulative intraday log returns over each asset's last trading day."""
    series = []
    day = None
    for asset in assets:
        try:
            df = load_bars(asset, tf)
            asset_day = last_trading_day(df, as_of)
        except (FileNotFoundError, ValueError):
            continue
        bars = _day_slice(df, asset_day)
        if len(bars) < 2:
            continue
        day = day or asset_day
        cum = np.log(bars["Close"]).diff().fillna(0.0).cumsum()
        series.append({
            "asset": asset,
            "day": asset_day.isoformat(),
            "points": [
                {"time": int(t.timestamp()), "value": round(float(v) * 100, 4)}
                for t, v in zip(bars["Datetime"], cum)
            ],
        })
    return {
        "timeframe": tf,
        "series": series,
        "sessions": session_spans(day) if day else [],
    }
