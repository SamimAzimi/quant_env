"""
anti_breakout_strategy.py — channel breakout / false-breakout strategy.

Port of capissimo's "Anti-Breakout Strategy" (Pine v4, MPL-2.0) into the
framework's strategy contract: same `(run_id=, **params).backtest(df) ->
(trades_df, details)` shape and slim ledger as the other strategies, so it
drops into the pipeline (CFDCostModel → CFDAccountSimulator →
PerformanceAnalytics → ResultStore → dashboard / tv_chart) unchanged.

NAME ↔ CODE MISMATCH (read this)
────────────────────────────────
The indicator is titled "Anti-Breakout" and its description says it fades false
breakouts ("the high/low of the breakout bar is used for entry in the OPPOSITE
direction"), but the published CODE does the opposite — it BUYS upside breakouts
and SELLS downside breakouts:
    long  = crossover(price,  highest(high[1], lag))   -> BUY
    short = crossunder(price, lowest(low[1],  lag))    -> SELL
This port implements what the code DOES under `mode="breakout"` (default), and
the contrarian reading the title/description imply under `mode="fade"` (a plain
directional inversion of the signal). Choose whichever you actually want.

How it trades
─────────────
• CHANNEL  — hHigh = highest high of the previous `lag` bars, lLow = lowest low
  of the previous `lag` bars (both exclude the current bar).
• SIGNAL   — `price_type` crossing ABOVE hHigh = long breakout; crossing BELOW
  lLow = short breakout; optionally gated by a volume/volatility `filter`. The
  signal is a PERSISTENT regime — it holds until the opposite break flips it, so
  consecutive same-direction breaks do NOT re-enter (trades alternate L/S).
• ENTRY    — at the CLOSE of the signal bar (the crossover is confirmed on
  close). The original enters at the bar OPEN, which peeks ahead of its own
  close-based signal; this port avoids that lookahead.
• EXIT     — after `holding_period` bars, OR immediately on the opposite signal
  (stop-and-reverse). The original has no SL/TP.
• STOP     — optional protective stop (`use_stop`, OFF by default to stay
  faithful). `stop_mode="channel"` → opposite channel edge (the "breakout
  failed" level); `"atr"` → `atr_stop_mult * ATR` away. The stop LEVEL is always
  recorded (so risk-sizing / charts have it); it only triggers an exit when
  `use_stop=True`.

`tthres` (the original's real-time "bar life" guard) is omitted: on closed
historical bars it is always satisfied, so it has no backtest effect. The doji
marker module is cosmetic and is not ported.

Returns `(trades_df, details)`:
    trades_df : trade_id, side, setup_time, entry_time, entry_price,
                exit_time, exit_price, exit_reason
    details   : {"trades" (full per-trade frame), "signals", "metadata"}
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd


class AntiBreakoutStrategy:
    # ── exit reasons ─────────────────────────────────────────────────────────
    EXIT_HOLD    = "holding_period"      # held `holding_period` bars
    EXIT_REVERSE = "reverse"             # opposite breakout flipped the position
    EXIT_SL      = "SL"                  # optional protective stop
    EXIT_MANUAL  = "manual_exit"         # position still open at the last bar

    # ── slim trades_df columns ───────────────────────────────────────────────
    TRADE_COLUMNS: List[str] = [
        "trade_id", "side", "setup_time", "entry_time", "entry_price",
        "exit_time", "exit_price", "exit_reason",
    ]

    # volume filter internals (hardcoded in the original; kept as constants)
    _VOL_RSI_LEN = 14
    _VOL_HMA_LEN = 10
    _PRICE_KINDS = ("open", "high", "low", "close", "hl2", "oc2", "ohl3", "hlc3", "ohlc4")

    def __init__(
        self,
        run_id:        str   = "default_run",
        asset_class:   str = "NDX",
        # ── channel / signal ─────────────────────────────────────────────────
        price_type:    str   = "close",      # one of _PRICE_KINDS
        lag:           int   = 3,            # channel lookback (prev `lag` bars)
        mode:          str   = "breakout",   # "breakout" (code) | "fade" (title/description)
        # ── signal filter ────────────────────────────────────────────────────
        filter_type:   str   = "volume",     # "volatility" | "volume" | "both" | "none"
        vol_min_atr:   int   = 1,            # volatility filter: ATR(vol_min) > ATR(vol_max)
        vol_max_atr:   int   = 2,
        volume_level:  float = 49.0,         # hma(rsi(volume,14),10) threshold
        # ── trade management ─────────────────────────────────────────────────
        holding_period: int  = 1,            # bars to hold (or until the opposite signal)
        # ── optional protective stop (off = faithful to the indicator) ───────
        use_stop:      bool  = False,
        stop_mode:     str   = "channel",    # "channel" (opposite edge) | "atr"
        atr_length:    int   = 14,
        atr_stop_mult: float = 1.5,
        # ── label ────────────────────────────────────────────────────────────
        timeframe:     str   = "",
    ) -> None:
        self.run_id         = run_id
        self.price_type     = price_type.lower()
        self.lag            = max(int(lag), 1)
        self.mode           = mode.lower()
        self.filter_type    = filter_type.lower()
        self.vol_min_atr    = max(int(vol_min_atr), 1)
        self.vol_max_atr    = max(int(vol_max_atr), 1)
        self.volume_level   = volume_level
        self.holding_period = max(int(holding_period), 1)
        self.use_stop       = use_stop
        self.stop_mode      = stop_mode.lower()
        self.atr_length     = atr_length
        self.atr_stop_mult  = atr_stop_mult
        self.timeframe      = timeframe
        self._volume_missing = False
        self.asset_class = asset_class

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
        self.trades:  List[Dict] = []
        self.signals: List[Dict] = []
        self.position: int = 0               # 0 flat, +1 long, -1 short
        self.trade_counter: int = 0

    def _run(self, df: pd.DataFrame) -> None:
        self._df = self._canonicalize(df)
        self._reset_state()
        d = self._df
        n = len(d)

        # ── vectorised signal construction ──────────────────────────────────
        ds   = self._price_series(d, self.price_type)
        hH   = d["High"].astype(float).shift(1).rolling(self.lag).max()
        lL   = d["Low"].astype(float).shift(1).rolling(self.lag).min()
        cross_up = (ds > hH) & (ds.shift(1) <= hH.shift(1))
        cross_dn = (ds < lL) & (ds.shift(1) >= lL.shift(1))
        filt = self._filter_series(d)

        long_break  = (cross_up & filt).fillna(False).to_numpy()
        short_break = (cross_dn & filt).fillna(False).to_numpy()
        if self.mode == "fade":              # trade AGAINST the break
            long_break, short_break = short_break, long_break

        # arrays for the loop
        self._ds  = ds.to_numpy()
        self._hH  = hH.to_numpy()
        self._lL  = lL.to_numpy()
        self._O   = d["Open"].astype(float).to_numpy()
        self._H   = d["High"].astype(float).to_numpy()
        self._L   = d["Low"].astype(float).to_numpy()
        self._C   = d["Close"].astype(float).to_numpy()
        self._atr = self._atr(d, self.atr_length).to_numpy()

        # first usable bar: channel + filter warmups satisfied
        warm = max(self.lag + 1, self.vol_max_atr + 1,
                   self._VOL_RSI_LEN + self._VOL_HMA_LEN + 2)
        start = min(warm, max(n - 1, 0))

        # ── state machine (faithful to the Pine signal/holding logic) ────────
        signal = 0
        hp = 0
        for i in range(start, n):
            new_signal = signal
            if long_break[i]:
                new_signal = +1
            elif short_break[i]:
                new_signal = -1
            changed = (new_signal != signal) and (new_signal != 0)
            hp = 0 if changed else hp + 1

            # optional protective stop (intrabar), never on the entry bar
            if self.position != 0 and self.use_stop and i > self.trades[-1]["entry_bar"]:
                hit = self._stop_hit(i)
                if hit is not None:
                    self._close_trade(i, hit, self.EXIT_SL)

            # exits (holding period reached, or stop-and-reverse)
            if self.position == 1:
                if changed and new_signal == -1:
                    self._close_trade(i, self._C[i], self.EXIT_REVERSE)
                elif (not changed) and hp == self.holding_period:
                    self._close_trade(i, self._C[i], self.EXIT_HOLD)
            elif self.position == -1:
                if changed and new_signal == +1:
                    self._close_trade(i, self._C[i], self.EXIT_REVERSE)
                elif (not changed) and hp == self.holding_period:
                    self._close_trade(i, self._C[i], self.EXIT_HOLD)

            # entries (only when the regime actually flips, and we are flat)
            if changed and self.position == 0:
                self._open_trade(i, "long" if new_signal == +1 else "short")

            signal = new_signal

        self._finalize_open_trade()

    # ─────────────────────────────────────────────────────────────────────────
    # Data prep + indicators (self-contained)
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

    def _price_series(self, df: pd.DataFrame, kind: str) -> pd.Series:
        O, H, L, C = (df["Open"].astype(float), df["High"].astype(float),
                      df["Low"].astype(float), df["Close"].astype(float))
        table = {
            "open": O, "high": H, "low": L, "close": C,
            "hl2": (H + L) / 2, "oc2": (O + C) / 2, "ohl3": (O + H + L) / 3,
            "hlc3": (H + L + C) / 3, "ohlc4": (O + H + L + C) / 4,
        }
        return table.get(kind, C)

    @staticmethod
    def _atr(df: pd.DataFrame, length: int) -> pd.Series:
        h, l, c = df["High"].astype(float), df["Low"].astype(float), df["Close"].astype(float)
        pc = c.shift(1)
        tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
        return tr.ewm(alpha=1.0 / max(int(length), 1), adjust=False).mean()   # Wilder; atr(1)=tr

    @staticmethod
    def _rsi(series: pd.Series, length: int) -> pd.Series:
        d = series.astype(float).diff()
        up = d.clip(lower=0).ewm(alpha=1.0 / length, adjust=False).mean()
        dn = (-d).clip(lower=0).ewm(alpha=1.0 / length, adjust=False).mean()
        return 100 - 100 / (1 + up / dn)

    @staticmethod
    def _wma(series: pd.Series, length: int) -> pd.Series:
        length = max(int(length), 1)
        w = np.arange(1, length + 1)
        return series.rolling(length).apply(lambda x: float(np.dot(x, w) / w.sum()), raw=True)

    def _hma(self, series: pd.Series, length: int) -> pd.Series:
        half = max(int(length // 2), 1)
        sq   = max(int(round(length ** 0.5)), 1)
        return self._wma(2 * self._wma(series, half) - self._wma(series, length), sq)

    def _volume_col(self, df: pd.DataFrame) -> Optional[pd.Series]:
        low = {c.lower(): c for c in df.columns}
        for name in ("volume", "vol", "tick_volume", "tickvolume", "tickvol"):
            if name in low:
                return df[low[name]].astype(float)
        return None

    def _filter_series(self, df: pd.DataFrame) -> pd.Series:
        ft = self.filter_type
        if ft == "none":
            return pd.Series(True, index=df.index)
        volat = self._atr(df, self.vol_min_atr) > self._atr(df, self.vol_max_atr)
        if ft == "volatility":
            return volat
        vol = self._volume_col(df)
        if vol is None:
            self._volume_missing = True
            volb = pd.Series(True, index=df.index)     # no volume → don't filter on it
        else:
            volb = self._hma(self._rsi(vol, self._VOL_RSI_LEN), self._VOL_HMA_LEN) > self.volume_level
        if ft == "volume":
            return volb
        if ft == "both":
            return volat & volb
        return pd.Series(True, index=df.index)

    # ─────────────────────────────────────────────────────────────────────────
    # Stop helper
    # ─────────────────────────────────────────────────────────────────────────

    def _stop_level(self, i: int, side: str, entry_price: float) -> float:
        if self.stop_mode == "atr":
            a = self._atr[i]
            a = float(a) if np.isfinite(a) else 0.0
            return entry_price - a * self.atr_stop_mult if side == "long" \
                else entry_price + a * self.atr_stop_mult
        # "channel": opposite edge of the breakout channel
        return float(self._lL[i]) if side == "long" else float(self._hH[i])

    def _stop_hit(self, i: int) -> Optional[float]:
        trade = self.trades[-1]
        sl = trade["sl_price"]
        if sl is None or not np.isfinite(sl):
            return None
        if self.position == 1 and self._L[i] <= sl:
            return sl
        if self.position == -1 and self._H[i] >= sl:
            return sl
        return None

    # ─────────────────────────────────────────────────────────────────────────
    # Trade records
    # ─────────────────────────────────────────────────────────────────────────

    def _open_trade(self, i: int, side: str) -> None:
        self.position = 1 if side == "long" else -1
        entry_price = self._C[i]
        sl_price = self._stop_level(i, side, entry_price)
        atr_val = float(self._atr[i]) if np.isfinite(self._atr[i]) else None
        self.signals.append({"bar": i, "side": side, "ds": float(self._ds[i]),
                             "hHigh": float(self._hH[i]), "lLow": float(self._lL[i])})
        self.trades.append({
            "trade_id":       self._next_trade_id(),
            "side":           side,
            "setup_time":     self._bar_time(i),
            "entry_time":     self._bar_time(i),
            "exit_time":      None,
            "entry_price":    entry_price,
            "exit_price":     None,
            "sl_price":       sl_price,
            "tp_price":       None,
            # channel / signal context (key levels)
            "channel_high":   float(self._hH[i]),
            "channel_low":    float(self._lL[i]),
            "signal_price":   float(self._ds[i]),
            "atr_at_entry":   atr_val,
            # params for this trade
            "price_type":     self.price_type,
            "lag":            self.lag,
            "mode":           self.mode,
            "filter_type":    self.filter_type,
            "holding_period": self.holding_period,
            "stop_mode":      self.stop_mode,
            "use_stop":       self.use_stop,
            # bar indices
            "setup_bar":      i,
            "entry_bar":      i,
            "exit_bar":       None,
            "bars_held":      None,
            "exit_reason":    None,
        })

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

    def _next_trade_id(self) -> str:
        self.trade_counter += 1
        return f"T{self.trade_counter:05d}"

    def _bar_time(self, idx: int):
        d = self._df
        return d["Datetime"].iloc[idx] if "Datetime" in d.columns else idx

    # ─────────────────────────────────────────────────────────────────────────
    # Output builders
    # ─────────────────────────────────────────────────────────────────────────

    def _build_trades_df(self) -> pd.DataFrame:
        if not self.trades:
            return pd.DataFrame(columns=self.TRADE_COLUMNS)
        return pd.DataFrame(self.trades)[self.TRADE_COLUMNS].copy()

    def _build_details(self) -> Dict:
        return {
            "trades":   pd.DataFrame(self.trades),
            "signals":  pd.DataFrame(self.signals, columns=["bar", "side", "ds", "hHigh", "lLow"]),
            "metadata": self._build_metadata(),
        }

    def _build_metadata(self) -> Dict:
        return {
            "run_id":         self.run_id,
            "asset_class":    self.asset_class,
            "strategy":       "Anti-Breakout",
            "timeframe":      self.timeframe,
            "price_type":     self.price_type,
            "lag":            self.lag,
            "mode":           self.mode,
            "filter_type":    self.filter_type,
            "vol_min_atr":    self.vol_min_atr,
            "vol_max_atr":    self.vol_max_atr,
            "volume_level":   self.volume_level,
            "holding_period": self.holding_period,
            "use_stop":       self.use_stop,
            "stop_mode":      self.stop_mode,
            "atr_length":     self.atr_length,
            "atr_stop_mult":  self.atr_stop_mult,
            "volume_missing": self._volume_missing,
        }