"""common.py — shared scaffolding for the strategy classes.

Every helper here was extracted VERBATIM from the strategies (they each
carried their own identical copy); behaviour is unchanged — the strategies
now import the one shared implementation instead. Strategy-specific logic
stays in each strategy file.

    canonicalize_ohlc   column-name normalisation (parameterised so each
                        strategy keeps its exact historical variant)
    wma / atr_wilder    indicator helpers
    build_trades_df     trades list → pipeline-shaped DataFrame
    ScaffoldMixin       the identical bookkeeping methods (_bar_time,
                        _next_trade_id, _build_trades_df, _close_trade,
                        _finalize_open_trade) — strategies that used a
                        different variant simply keep their own override.
"""
from __future__ import annotations

from typing import Sequence

import numpy as np
import pandas as pd

DEFAULT_TIME_ALIASES = ("datetime", "date", "time", "timestamp")


def canonicalize_ohlc(
    df: pd.DataFrame,
    *,
    reset_index: bool = True,
    time_aliases: Sequence[str] = DEFAULT_TIME_ALIASES,
    volume_aliases: Sequence[str] | None = None,
) -> pd.DataFrame:
    """Map OHLC(/Volume)/time column names to the canonical casing.

    The flags reproduce each strategy's historical variant exactly:
    whether the index is reset, which time-column aliases are accepted,
    and whether a Volume column is mapped.
    """
    out = df.copy()
    if reset_index:
        out = out.reset_index(drop=True)
    low = {c.lower(): c for c in out.columns}
    ren = {}
    for canon in ("Open", "High", "Low", "Close"):
        if canon not in out.columns and canon.lower() in low:
            ren[low[canon.lower()]] = canon
    if volume_aliases and "Volume" not in out.columns:
        for alt in volume_aliases:
            if alt in low:
                ren[low[alt]] = "Volume"
                break
    if "Datetime" not in out.columns:
        for alt in time_aliases:
            if alt in low:
                ren[low[alt]] = "Datetime"
                break
    return out.rename(columns=ren) if ren else out


def wma(series: pd.Series, length: int) -> pd.Series:
    """Weighted moving average (linear weights)."""
    length = max(int(length), 1)
    w = np.arange(1, length + 1)
    return series.rolling(length).apply(lambda x: float(np.dot(x, w) / w.sum()), raw=True)


def atr_wilder(df: pd.DataFrame, length: int) -> pd.Series:
    """ATR with Wilder smoothing; atr(1) = true range."""
    h, l, c = df["High"].astype(float), df["Low"].astype(float), df["Close"].astype(float)
    pc = c.shift(1)
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / max(int(length), 1), adjust=False).mean()


def build_trades_df(trades: list, columns: Sequence[str]) -> pd.DataFrame:
    if not trades:
        return pd.DataFrame(columns=columns)
    return pd.DataFrame(trades)[list(columns)].copy()


class ScaffoldMixin:
    """The bookkeeping methods that were byte-identical across strategies."""

    def _bar_time(self, idx: int):
        d = self._df
        return d["Datetime"].iloc[idx] if "Datetime" in d.columns else idx

    def _next_trade_id(self) -> str:
        self.trade_counter += 1
        return f"T{self.trade_counter:05d}"

    def _build_trades_df(self) -> pd.DataFrame:
        return build_trades_df(self.trades, self.TRADE_COLUMNS)

    def _close_trade(self, i: int, exit_price: float, exit_reason: str) -> None:
        t = self.trades[-1]
        t.update({
            "exit_time":   self._bar_time(i),
            "exit_price":  float(exit_price),
            "exit_bar":    i,
            "bars_held":   i - t["entry_bar"],
            "exit_reason": exit_reason,
        })
        self.position = 0

    def _finalize_open_trade(self) -> None:
        if self.position != 0 and self.trades:
            last_i = len(self._df) - 1
            self._close_trade(last_i, self._C[last_i], self.EXIT_MANUAL)
