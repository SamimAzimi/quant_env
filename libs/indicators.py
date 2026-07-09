"""
indicators.py — Stateless technical helpers.

Every function is a pure function (or takes only the parameters it needs).
No strategy state, no cost logic, no I/O.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from typing import Optional, Tuple


# ─────────────────────────────────────────────────────────────────────────────
# ATR
# ─────────────────────────────────────────────────────────────────────────────

def calculate_atr(df: pd.DataFrame, length: int = 14) -> pd.Series:
    """Exponential ATR (Wilder-style, alpha = 1/length)."""
    hl  = df["High"] - df["Low"]
    hpc = (df["High"] - df["Close"].shift(1)).abs()
    lpc = (df["Low"]  - df["Close"].shift(1)).abs()
    tr  = pd.concat([hl, hpc, lpc], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / length, adjust=False).mean()


# ─────────────────────────────────────────────────────────────────────────────
# Volume profile
# ─────────────────────────────────────────────────────────────────────────────

def calculate_volume_profile(
    df:                  pd.DataFrame,
    start_idx:           int,
    end_idx:             int,
    num_bins:            int   = 60,
    value_area_pct:      float = 0.70,
    min_segment_bars:    int   = 2,
) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    """
    Returns (poc_price, vah_price, val_price) for the bar range [start_idx, end_idx].
    Returns (None, None, None) if volume data is absent or the range is too small.
    """
    if "Volume" not in df.columns or end_idx - start_idx < min_segment_bars:
        return None, None, None

    seg        = df.iloc[start_idx:end_idx + 1].copy()
    pmin, pmax = seg["Low"].min(), seg["High"].max()
    edges      = np.linspace(pmin, pmax, num_bins + 1)
    seg["_pb"] = pd.cut(seg["Close"], bins=edges, include_lowest=True)
    profile    = seg.groupby("_pb", observed=True)["Volume"].sum()

    if len(profile) == 0:
        return None, None, None

    poc_bin   = profile.idxmax()
    poc_price = (poc_bin.left + poc_bin.right) / 2

    tv = profile.sum()
    sp = profile.sort_values(ascending=False)
    cv = sp.cumsum()
    va = sp[cv <= tv * value_area_pct].index

    if len(va):
        vah = (va[0].right + va[0].left) / 2
        val = (va[-1].right + va[-1].left) / 2
    else:
        vah = val = poc_price

    return poc_price, vah, val


# ─────────────────────────────────────────────────────────────────────────────
# Session helpers
# ─────────────────────────────────────────────────────────────────────────────

def in_session(
    df:                pd.DataFrame,
    i:                 int,
    session_filter:    bool,
    session_start_hour: int,
    session_end_hour:   int,
    session_days:       list,
) -> bool:
    if not session_filter:
        return True
    if "Datetime" not in df.columns:
        return True
    dt = pd.to_datetime(df["Datetime"].iloc[i], utc=True, errors="coerce")
    if pd.isna(dt):
        return True
    if dt.weekday() not in session_days:
        return False
    h = dt.hour
    if session_start_hour <= session_end_hour:
        return session_start_hour <= h < session_end_hour
    return h >= session_start_hour or h < session_end_hour


def get_session_name(df: pd.DataFrame, i: int) -> str:
    """Classify a bar into a named trading session (UTC hours)."""
    if "Datetime" not in df.columns:
        return "unknown"
    dt = pd.to_datetime(df["Datetime"].iloc[i], utc=True, errors="coerce")
    if pd.isna(dt):
        return "unknown"
    h = dt.hour
    if   0 <= h <  7: return "asian"
    elif 7 <= h < 12: return "london"
    elif 12 <= h < 17: return "new_york_overlap"
    elif 17 <= h < 21: return "new_york"
    else:              return "off_hours"


# ─────────────────────────────────────────────────────────────────────────────
# Fractals
# ─────────────────────────────────────────────────────────────────────────────

def is_fractal_high(
    df: pd.DataFrame, candidate: int,
    fractal_left: int, fractal_right: int,
):
    left_start = candidate - fractal_left
    right_end = candidate + fractal_right + 1
    
    if left_start < 0 or right_end > len(df):
        return False
    high = df['High'].iloc[candidate]
    left_max = df['High'].iloc[left_start:candidate].max()
    right_max = df['High'].iloc[candidate + 1:right_end].max()
    return high > left_max and high > right_max


def is_fractal_low(
    df: pd.DataFrame, candidate: int,
    fractal_left: int, fractal_right: int,
):
    left_start = candidate - fractal_left
    right_end = candidate + fractal_right + 1

    if left_start < 0 or right_end > len(df):
        return False

    low = df['Low'].iloc[candidate]
    left_min = df['Low'].iloc[left_start:candidate].min()
    right_min = df['Low'].iloc[candidate + 1:right_end].min()

    return low < left_min and low < right_min


# ─────────────────────────────────────────────────────────────────────────────
# Rejection candle (pin bar)
# ─────────────────────────────────────────────────────────────────────────────

def is_rejection_candle(
    df: pd.DataFrame, i: int, direction: str,
    require_rejection: bool,
    wick_ratio: float, body_ratio: float,
) -> bool:
    if not require_rejection:
        return True
    o, h, l, c = df["Open"].iloc[i], df["High"].iloc[i], df["Low"].iloc[i], df["Close"].iloc[i]
    body = abs(c - o)
    if body == 0:
        return False
    uw = h - max(o, c)
    lw = min(o, c) - l
    if direction == "bullish":
        return lw >= wick_ratio * body and uw <= body_ratio * body and c > o
    return uw >= wick_ratio * body and lw <= body_ratio * body and c < o


# ─────────────────────────────────────────────────────────────────────────────
# Fibonacci price levels
# ─────────────────────────────────────────────────────────────────────────────

def get_fib_price(
    lowest_price: float, highest_price: float,
    level: float, direction: str,
) -> float:
    """
    TradingView-style fib levels.
      level 0.0  → swing high (bullish) / swing low (bearish)  [0 %]
      level 1.0  → swing low  (bullish) / swing high (bearish) [100 %]
      level >1.0 → extension beyond 100 % in trend direction
      level <0.0 → extension opposite to trend direction
    """ 
    sh   = max(lowest_price, highest_price)
    sl   = min(lowest_price, highest_price)
    diff = sh - sl
    d    = direction.lower()
    if d == "bullish":
        if level >= 0:
            return sh + (diff * (level - 1.0)) 
        else:
            return sl + (diff * level)
    elif d == "bearish":
        if level >= 0:
            return sl - (diff * (level - 1.0))
        else:
            return sh + (diff * level)
    raise ValueError(f"Unknown direction: {direction!r}")


# ─────────────────────────────────────────────────────────────────────────────
# MAE / MFE tracker
# ─────────────────────────────────────────────────────────────────────────────

def update_mae_mfe(
    direction: str,
    bar_low: float, bar_high: float,
    current_mae: float, current_mfe: float,
) -> Tuple[float, float]:
    """
    MAE = worst price against position (Maximum Adverse Excursion)
    MFE = best price in favour of position (Maximum Favourable Excursion)
    Both tracked as raw price levels.
    """
    if direction == "bullish":
        return min(current_mae, bar_low), max(current_mfe, bar_high)
    return max(current_mae, bar_high), min(current_mfe, bar_low)


# ─────────────────────────────────────────────────────────────────────────────
# Misc utilities
# ─────────────────────────────────────────────────────────────────────────────

def bars_to_hours(bars: int, tf_min: int) -> float:
    return bars * (tf_min / 60.0)


