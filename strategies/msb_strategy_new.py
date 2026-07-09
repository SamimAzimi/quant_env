"""
msb_strategy_new.py — clean Market-Structure-Break strategy.

A trimmed strategy distilled from the "Market Structure Break & Order Block"
(MSB-OB) indicator by EmreKb (MPL-2.0). Only the structure logic is kept.

Rules
─────
• A causal zigzag (swings confirmed by the `zigzag_len`-bar highest/lowest rule)
  tracks the current/previous swing high & low: h0, h1, l0, l1.
• MSB (break of structure):
      bullish :  h0 > h1 + |h1 - l0| * fib_factor
      bearish :  l0 < l1 - |h0 - l1| * fib_factor
  `msb_price` = the broken level (h1 for bullish, l1 for bearish — where the
  indicator draws the MSB line).
• SETUP: a new MSB arms a setup recording the key points
  (current/previous high & low, previous-day high & low, msb_price).
• ENTRY:
      bullish → wait for price to come back to the setup's CURRENT LOW (l0),
                go long, target the setup's PREVIOUS HIGH (h1 = msb_price)
      bearish → wait for price to come back to the setup's CURRENT HIGH (h0),
                go short, target the setup's PREVIOUS LOW (l1 = msb_price)
• STOP: from the entry anchor (current low for longs / current high for shorts),
  either ATR-based (`atr_sl_mult * ATR`) or a fraction of price (`sl_pct`),
  selected by `sl_mode`.
• INVALIDATION (the ONLY ways a setup/trade dies early): the zigzag trend flips,
  an opposite MSB fires, or any new MSB fires. There is NO timeout.
• A position still open on the last bar is closed as "manual_exit".

Returns `(trades_df, details)`:
    trades_df : slim ledger — trade_id, side, setup_time, entry_time, entry_price,
                exit_time, exit_price, exit_reason
    details   : {"trades" (full per-trade frame with every key point),
                 "swings", "msb_events", "metadata" (class settings)}
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd


class MSBStrategy:
    # ── exit reasons (no timeout) ────────────────────────────────────────────
    EXIT_TP           = "TP"
    EXIT_SL           = "SL"
    EXIT_INVALIDATION = "Invalidation"
    EXIT_MANUAL       = "manual_exit"        # open position at the last bar

    # ── slim trades_df columns ───────────────────────────────────────────────
    TRADE_COLUMNS: List[str] = [
        "trade_id", "side", "setup_time", "entry_time", "entry_price",
        "exit_time", "exit_price", "exit_reason",
    ]

    def __init__(
        self,
        run_id:      str   = "default_run",
        asset_class: str = "",
        zigzag_len:  int   = 9,
        fib_factor:  float = 0.33,
        sl_mode:     str   = "atr",      # "atr" or "pct"
        atr_length:  int   = 14,
        atr_sl_mult: float = 1.5,
        sl_pct:      float = 0.0002,     # 0.02% of price, used when sl_mode == "pct"
        timeframe:  str   = "",
    ) -> None:
        self.run_id      = run_id
        self.asset_class = asset_class
        self.zigzag_len  = max(int(zigzag_len), 1)
        self.fib_factor  = fib_factor
        self.sl_mode     = sl_mode.lower()
        self.atr_length  = atr_length
        self.atr_sl_mult = atr_sl_mult
        self.sl_pct      = sl_pct
        self.timeframe  = timeframe

    # ─────────────────────────────────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────────────────────────────────

    def backtest(self, df: pd.DataFrame) -> Tuple[pd.DataFrame, Dict]:
        self._run(df)
        return self._build_trades_df(), self._build_details()

    # ─────────────────────────────────────────────────────────────────────────
    # Run-state + orchestration
    # ─────────────────────────────────────────────────────────────────────────

    def _reset_state(self) -> None:
        self.trades:       List[Dict]     = []
        self.swings:       List[Dict]     = []
        self.msb_events:   List[Dict]     = []
        self.position:     int            = 0      # 0 flat, +1 long, -1 short
        self.active_setup: Optional[Dict] = None
        self.trade_counter: int           = 0
        # zigzag
        self._zz_init = False
        self.trend = 1
        self._phase_high = None; self._phase_high_idx = -1
        self._phase_low  = None; self._phase_low_idx  = -1
        self._just_pushed: Optional[str] = None    # "high"/"low" → a trend flip this bar
        self.swing_high_prices: List[float] = []
        self.swing_high_idx:    List[int]   = []
        self.swing_low_prices:  List[float] = []
        self.swing_low_idx:     List[int]   = []
        self.market = 1                            # +1 / -1 structure regime

    def _run(self, df: pd.DataFrame) -> None:
        self._df = self._canonicalize(df)
        self._reset_state()

        if self.sl_mode == "atr" and "ATR" not in self._df.columns:
            self._df["ATR"] = self._atr(self._df, self.atr_length)
        self._pdh, self._pdl = self._prev_day_levels(self._df)

        n = len(self._df)
        start = min(self.zigzag_len, max(n - 1, 0))
        for i in range(start, n):
            self._update_zigzag(i)
            direction = self._detect_msb(i)
            if direction is not None:
                self._on_msb(i, direction)         # invalidate old + arm new setup
            elif self._just_pushed is not None:
                self._on_trend_change(i)           # trend flip → drop pending setup
            self._check_entry(i)
            if self.position != 0:
                self._manage_open_trade(i)         # SL / TP only (no timeout)

        self._finalize_open_trade()

    # ─────────────────────────────────────────────────────────────────────────
    # Helpers — data prep
    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _canonicalize(df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy().reset_index(drop=True)
        low = {c.lower(): c for c in out.columns}
        ren = {}
        for canon in ("Open", "High", "Low", "Close"):
            if canon not in out.columns and canon.lower() in low:
                ren[low[canon.lower()]] = canon
        if "Datetime" not in out.columns:
            for alt in ("datetime", "date", "time", "timestamp"):
                if alt in low:
                    ren[low[alt]] = "Datetime"
                    break
        return out.rename(columns=ren) if ren else out

    @staticmethod
    def _atr(df: pd.DataFrame, length: int) -> pd.Series:
        h, l, c = df["High"].astype(float), df["Low"].astype(float), df["Close"].astype(float)
        pc = c.shift(1)
        tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
        return tr.ewm(alpha=1.0 / max(int(length), 1), adjust=False).mean()   # Wilder

    @staticmethod
    def _prev_day_levels(df: pd.DataFrame) -> Tuple[pd.Series, pd.Series]:
        """Previous calendar day's high/low mapped onto every bar."""
        n = len(df)
        if "Datetime" not in df.columns:
            nan = pd.Series([np.nan] * n)
            return nan, nan.copy()
        dt = pd.to_datetime(df["Datetime"], errors="coerce")
        day = dt.dt.normalize()
        g = pd.DataFrame({"day": day, "H": df["High"].astype(float), "L": df["Low"].astype(float)})
        daily = g.groupby("day").agg(dh=("H", "max"), dl=("L", "min"))
        daily["pdh"] = daily["dh"].shift(1)
        daily["pdl"] = daily["dl"].shift(1)
        pdh = day.map(daily["pdh"]).reset_index(drop=True)
        pdl = day.map(daily["pdl"]).reset_index(drop=True)
        return pdh, pdl

    # ─────────────────────────────────────────────────────────────────────────
    # ZigZag — confirm alternating swing highs / lows causally
    # ─────────────────────────────────────────────────────────────────────────

    def _update_zigzag(self, i: int) -> None:
        self._just_pushed = None
        df = self._df
        hi = float(df["High"].iloc[i]); lo = float(df["Low"].iloc[i])

        if not self._zz_init:
            self._phase_high, self._phase_high_idx = hi, i
            self._phase_low,  self._phase_low_idx  = lo, i
            self.trend = 1
            self._zz_init = True
            return

        if self.trend == 1:
            if hi >= self._phase_high:
                self._phase_high, self._phase_high_idx = hi, i
        else:
            if lo <= self._phase_low:
                self._phase_low, self._phase_low_idx = lo, i

        lo_win = max(i - self.zigzag_len + 1, 0)
        to_up   = hi >= float(df["High"].iloc[lo_win:i + 1].max())
        to_down = lo <= float(df["Low"].iloc[lo_win:i + 1].min())

        if self.trend == 1 and to_down:                # up-phase ends → swing HIGH
            self._push_swing("high", self._phase_high_idx, self._phase_high)
            self.trend = -1
            self._phase_low, self._phase_low_idx = lo, i
        elif self.trend == -1 and to_up:               # down-phase ends → swing LOW
            self._push_swing("low", self._phase_low_idx, self._phase_low)
            self.trend = 1
            self._phase_high, self._phase_high_idx = hi, i

    def _push_swing(self, kind: str, idx: int, price: float) -> None:
        self.swings.append({"bar": idx, "type": kind, "price": price})
        self._just_pushed = kind
        if kind == "high":
            self.swing_high_prices.append(price); self.swing_high_idx.append(idx)
        else:
            self.swing_low_prices.append(price); self.swing_low_idx.append(idx)

    def _last_high(self, k: int = 0):
        a = self.swing_high_prices
        return (a[-1 - k], self.swing_high_idx[-1 - k]) if len(a) > k else (None, None)

    def _last_low(self, k: int = 0):
        a = self.swing_low_prices
        return (a[-1 - k], self.swing_low_idx[-1 - k]) if len(a) > k else (None, None)

    # ─────────────────────────────────────────────────────────────────────────
    # MSB detection (event-driven, on swing confirmation)
    # ─────────────────────────────────────────────────────────────────────────

    def _detect_msb(self, i: int) -> Optional[str]:
        pushed = self._just_pushed
        if pushed is None:
            return None
        h0, _ = self._last_high(0); h1, _ = self._last_high(1)
        l0, _ = self._last_low(0);  l1, _ = self._last_low(1)

        direction = msb_price = None
        if pushed == "high" and None not in (h0, h1, l0):
            if h0 > h1 + abs(h1 - l0) * self.fib_factor:
                direction, msb_price = "bullish", h1
                self.market = 1
        elif pushed == "low" and None not in (l0, l1, h0):
            if l0 < l1 - abs(h0 - l1) * self.fib_factor:
                direction, msb_price = "bearish", l1
                self.market = -1
        if direction is None:
            return None

        self.msb_events.append({
            "bar": i, "direction": direction, "msb_price": float(msb_price),
            "current_high": float(h0), "current_low": float(l0),
        })
        return direction

    # ─────────────────────────────────────────────────────────────────────────
    # Setup lifecycle
    # ─────────────────────────────────────────────────────────────────────────

    def _on_msb(self, i: int, direction: str) -> None:
        # a new MSB (incl. opposite) invalidates whatever is live, then re-arms
        if self.position != 0:
            self._close_trade(i, float(self._df["Close"].iloc[i]), self.EXIT_INVALIDATION)
        elif self.active_setup is not None:
            self._record_invalidation(i)
            self.active_setup = None
        self._create_setup(i, direction)

    def _on_trend_change(self, i: int) -> None:
        # zigzag trend flipped (no MSB): a still-pending setup is invalidated.
        # An open trade is left alone — it needs the move to reach its target.
        if self.position == 0 and self.active_setup is not None:
            self._record_invalidation(i)
            self.active_setup = None

    def _create_setup(self, i: int, direction: str) -> None:
        h0, h0i = self._last_high(0); h1, _ = self._last_high(1)
        l0, l0i = self._last_low(0);  l1, _ = self._last_low(1)
        if direction == "bullish":
            if None in (h0, h1, l0) or not (h1 > l0):   # TP (prev high) must sit above entry (cur low)
                return
        else:
            if None in (h0, l0, l1) or not (l1 < h0):   # TP (prev low) must sit below entry (cur high)
                return

        pdh = self._pdh.iloc[i] if i < len(self._pdh) else np.nan
        pdl = self._pdl.iloc[i] if i < len(self._pdl) else np.nan
        self.active_setup = {
            "direction":        direction,
            "current_high":     float(h0),
            "previous_high":    float(h1) if h1 is not None else None,
            "current_low":      float(l0),
            "previous_low":     float(l1) if l1 is not None else None,
            "current_high_idx": h0i,       "current_low_idx": l0i,
            "prev_day_high":    float(pdh) if pd.notna(pdh) else None,
            "prev_day_low":     float(pdl) if pd.notna(pdl) else None,
            "msb_price":        float(h1) if direction == "bullish" else float(l1),
            "entry_anchor":     float(l0) if direction == "bullish" else float(h0),
            "target":           float(h1) if direction == "bullish" else float(l1),
            "setup_bar":        i,
        }

    # ─────────────────────────────────────────────────────────────────────────
    # Entry
    # ─────────────────────────────────────────────────────────────────────────

    def _check_entry(self, i: int) -> None:
        s = self.active_setup
        if not s or self.position != 0 or i <= s["setup_bar"]:
            return
        df = self._df
        direction = s["direction"]
        anchor = s["entry_anchor"]

        if direction == "bullish":
            if float(df["Low"].iloc[i]) > anchor:        # not back down to the current low yet
                return
            entry_price = min(anchor, float(df["Open"].iloc[i]))
        else:
            if float(df["High"].iloc[i]) < anchor:       # not back up to the current high yet
                return
            entry_price = max(anchor, float(df["Open"].iloc[i]))

        atr_val = None
        if "ATR" in df.columns:
            a = df["ATR"].iloc[i]
            atr_val = float(a) if pd.notna(a) else None

        if self.sl_mode == "atr":
            if atr_val is None:
                return                                   # can't size the stop — skip
            offset = atr_val * self.atr_sl_mult
        else:
            offset = abs(anchor) * self.sl_pct
        sl_price = (anchor - offset) if direction == "bullish" else (anchor + offset)
        tp_price = s["target"]

        self._open_trade(i, direction, entry_price, sl_price, tp_price, atr_val)

    # ─────────────────────────────────────────────────────────────────────────
    # Trade management — SL / TP (no timeout)
    # ─────────────────────────────────────────────────────────────────────────

    def _manage_open_trade(self, i: int) -> None:
        if i <= self.trades[-1]["entry_bar"]:
            return
        signal = self._check_exit(i)
        if signal is not None:
            self._close_trade(i, signal[0], signal[1])

    def _check_exit(self, i: int) -> Optional[Tuple[float, str]]:
        df = self._df
        trade = self.trades[-1]
        sl, tp = trade["sl_price"], trade["tp_price"]
        if self.position == 1:                           # long — SL first on conflict
            if float(df["Low"].iloc[i])  <= sl:
                return sl, self.EXIT_SL
            if float(df["High"].iloc[i]) >= tp:
                return tp, self.EXIT_TP
        else:                                            # short
            if float(df["High"].iloc[i]) >= sl:
                return sl, self.EXIT_SL
            if float(df["Low"].iloc[i])  <= tp:
                return tp, self.EXIT_TP
        return None

    def _finalize_open_trade(self) -> None:
        if self.position != 0 and self.trades:
            last_i = len(self._df) - 1
            self._close_trade(last_i, float(self._df["Close"].iloc[last_i]), self.EXIT_MANUAL)

    # ─────────────────────────────────────────────────────────────────────────
    # Records
    # ─────────────────────────────────────────────────────────────────────────

    def _open_trade(self, i, direction, entry_price, sl_price, tp_price, atr_val) -> None:
        s = self.active_setup
        self.position = 1 if direction == "bullish" else -1
        self.trades.append({
            "trade_id":       self._next_trade_id(),
            "side":           "long" if direction == "bullish" else "short",
            "setup_time":     self._bar_time(s["setup_bar"]),
            "entry_time":     self._bar_time(i),
            "exit_time":      None,
            "entry_price":    entry_price,
            "exit_price":     None,
            "sl_price":       sl_price,
            "tp_price":       tp_price,
            # ── key points ──────────────────────────────────────────────────
            "current_high":   s["current_high"],  "previous_high": s["previous_high"],
            "current_low":    s["current_low"],   "previous_low":  s["previous_low"],
            "prev_day_high":  s["prev_day_high"], "prev_day_low":  s["prev_day_low"],
            "msb_price":      s["msb_price"],
            # ── context ─────────────────────────────────────────────────────
            "direction":      direction,
            "sl_mode":        self.sl_mode,
            "atr_at_entry":   atr_val,
            "zigzag_len":     self.zigzag_len,
            "fib_factor":     self.fib_factor,
            "setup_bar":      s["setup_bar"],
            "current_high_idx": s["current_high_idx"],
            "current_low_idx":  s["current_low_idx"],
            "entry_bar":      i,
            "exit_bar":       None,
            "bars_to_entry":  i - s["setup_bar"],
            "exit_reason":    None,
        })

    def _close_trade(self, i: int, exit_price: float, exit_reason: str) -> None:
        self.trades[-1].update({
            "exit_time":   self._bar_time(i),
            "exit_price":  exit_price,
            "exit_bar":    i,
            "exit_reason": exit_reason,
        })
        self.position     = 0
        self.active_setup = None

    def _record_invalidation(self, i: int) -> None:
        s = self.active_setup
        self.trades.append({
            "trade_id":       self._next_trade_id(),
            "side":           "long" if s["direction"] == "bullish" else "short",
            "setup_time":     self._bar_time(s["setup_bar"]),
            "entry_time":     None,
            "exit_time":      self._bar_time(i),
            "entry_price":    None,
            "exit_price":     None,
            "sl_price":       None,
            "tp_price":       None,
            "current_high":   s["current_high"],  "previous_high": s["previous_high"],
            "current_low":    s["current_low"],   "previous_low":  s["previous_low"],
            "prev_day_high":  s["prev_day_high"], "prev_day_low":  s["prev_day_low"],
            "msb_price":      s["msb_price"],
            "direction":      s["direction"],
            "sl_mode":        self.sl_mode,
            "atr_at_entry":   None,
            "zigzag_len":     self.zigzag_len,
            "fib_factor":     self.fib_factor,
            "setup_bar":      s["setup_bar"],
            "current_high_idx": s["current_high_idx"],
            "current_low_idx":  s["current_low_idx"],
            "entry_bar":      None,
            "exit_bar":       i,
            "bars_to_entry":  None,
            "exit_reason":    self.EXIT_INVALIDATION,
        })

    def _next_trade_id(self) -> str:
        self.trade_counter += 1
        return f"T{self.trade_counter:05d}"

    def _bar_time(self, idx: int):
        df = self._df
        return df["Datetime"].iloc[idx] if "Datetime" in df.columns else idx

    # ─────────────────────────────────────────────────────────────────────────
    # Output builders
    # ─────────────────────────────────────────────────────────────────────────

    def _build_trades_df(self) -> pd.DataFrame:
        if not self.trades:
            return pd.DataFrame(columns=self.TRADE_COLUMNS)
        return pd.DataFrame(self.trades)[self.TRADE_COLUMNS].copy()

    def _build_details(self) -> Dict:
        return {
            "trades":     pd.DataFrame(self.trades),
            "swings":     pd.DataFrame(self.swings, columns=["bar", "type", "price"]),
            "msb_events": pd.DataFrame(self.msb_events,
                                       columns=["bar", "direction", "msb_price",
                                                "current_high", "current_low"]),
            "metadata":   self._build_metadata(),
        }

    def _build_metadata(self) -> Dict:
        return {
            "run_id":      self.run_id,
            "asset_class": self.asset_class,
            "strategy":    "MSB-New",
            "timeframe":  self.timeframe,
            "zigzag_len":  self.zigzag_len,
            "fib_factor":  self.fib_factor,
            "sl_mode":     self.sl_mode,
            "atr_length":  self.atr_length,
            "atr_sl_mult": self.atr_sl_mult,
            "sl_pct":      self.sl_pct,
        }