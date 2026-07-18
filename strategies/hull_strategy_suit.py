"""
hull_suite_strategy.py — Hull Moving Average slope strategy.

Port of the "Hull Suite Strategy" (InSilico / DashTrader, Pine v4) into the
framework's contract: same `(run_id=, **params).backtest(df) -> (trades_df,
details)` shape and slim ledger as the other strategies, so it drops into the
pipeline (CFDCostModel → CFDAccountSimulator → PerformanceAnalytics →
ResultStore → dashboard / tv_chart) unchanged.

The indicator
─────────────
Computes a Hull MA of `source` over `length`, in one of three variants, and
reads its slope over a 2-bar window:
    HMA(x,n)  = wma(2*wma(x, n/2) - wma(x, n), round(sqrt(n)))
    EHMA(x,n) = ema(2*ema(x, n/2) - ema(x, n), round(sqrt(n)))
    THMA(x,n) = wma(3*wma(x, n/3) - wma(x, n/2) - wma(x, n), n)   [called with n=length/2]
Trend is UP while HULL[0] > HULL[2], DOWN while HULL[0] < HULL[2]. The native
strategy goes long on the up-turn and short on the down-turn (stop-and-reverse).

`length` is the Hull period: ~180-200 makes the Hull act as floating
support/resistance, 55 is the swing-entry default.

Two trade-management systems (`management`)
───────────────────────────────────────────
1. "signal"  — flip with the Hull. Long from the up-turn until the down-turn,
   then close and reverse short until the next up-turn, and so on (always in the
   market). The closed leg is labeled TP if it made money, SL if it lost.
2. "atr"     — same Hull-turn entries, but the position is closed by an ATR stop
   (`atr_sl_mult * ATR`) or ATR target (`atr_tp_mult * ATR`), whichever trades
   first. An opposite Hull turn before either level is hit reverses the position
   ("reverse"). After an ATR exit the strategy waits for the NEXT Hull turn to
   re-enter (it does not re-add in the same direction on the same trend).

ATR SL/TP levels are recorded on every trade in BOTH modes (so risk-sizing in
account.py and the SL/TP lines in tv_chart have values); in "signal" mode they
are reference-only and the flip is what exits.

Side (`side`, mirrors the original's long/short/all selector)
─────────────────────────────────────────────────────────────
"both" (default) is the native stop-and-reverse. "long" takes longs only and
"short" takes shorts only. The opposite Hull turn still CLOSES the open trade
(exit flat) — `side` only gates which direction may OPEN — so a long-only run is
long during up-trends and flat during down-trends, re-entering on the next
up-turn. (This is the sensible reading; the original simply ignores the blocked
entry, which with no explicit exit would never close the position.)

Entries fill at the CLOSE of the turn bar (the slope is confirmed on close — no
lookahead). The original's date-range filter is omitted per request; the band /
candle coloring is cosmetic and not ported.

Returns `(trades_df, details)`:
    trades_df : trade_id, side, setup_time, entry_time, entry_price,
                exit_time, exit_price, exit_reason
    details   : {"trades" (full per-trade frame), "signals" (turn events),
                 "hull" (the Hull line + trend per bar), "metadata"}
"""
from __future__ import annotations

import math
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from strategies.common import ScaffoldMixin, atr_wilder, canonicalize_ohlc, wma


class HullSuiteStrategy(ScaffoldMixin):
    # shared scaffolding (strategies/common.py): _canonicalize with the
    # historical options (reset_index + standard aliases), Wilder ATR, WMA;
    # _close_trade/_finalize_open_trade/_next_trade_id/_bar_time/
    # _build_trades_df come from ScaffoldMixin.
    _canonicalize = staticmethod(canonicalize_ohlc)
    _atr = staticmethod(atr_wilder)
    _wma = staticmethod(wma)

    # ── exit reasons ─────────────────────────────────────────────────────────
    EXIT_TP      = "TP"
    EXIT_SL      = "SL"
    EXIT_REVERSE = "reverse"            # atr mode: opposite Hull turn before SL/TP
    EXIT_MANUAL  = "manual_exit"        # position still open at the last bar

    # ── slim trades_df columns ───────────────────────────────────────────────
    TRADE_COLUMNS: List[str] = [
        "trade_id", "side", "setup_time", "entry_time", "entry_price",
        "exit_time", "exit_price", "exit_reason",
    ]

    _SOURCES = ("open", "high", "low", "close", "volume",
                "hl2", "hlc3", "ohlc4", "oc2")
    _VARIATIONS = ("hma", "thma", "ehma")

    def __init__(
        self,
        run_id:         str   = "default_run",
        asset_class:    str   = "NDX",
        length:         int   = 55,          # Hull period (~180-200 floating S/R, 55 swing)
        source:         str   = "close",     # open/high/low/close/volume/hl2/hlc3/ohlc4/oc2
        hull_variation: str   = "hma",       # "hma" | "thma" | "ehma"
        management:     str   = "signal",    # "signal" (flip, TP/SL by P&L) | "atr" (ATR SL/TP)
        side:           str   = "both",      # "long" | "short" | "both" (alias "all")
        atr_length:     int   = 14,
        atr_sl_mult:    float = 1.5,
        atr_tp_mult:    float = 2.0,
        timeframe:      str   = "",
    ) -> None:
        self.run_id         = run_id
        self.asset_class    = asset_class
        self.length         = max(int(length), 2)
        self.source         = source.lower()
        self.hull_variation = hull_variation.lower()
        self.management     = management.lower()
        _s = side.lower()
        self.side           = "both" if _s in ("all", "both") else _s
        self.atr_length     = atr_length
        self.atr_sl_mult    = atr_sl_mult
        self.atr_tp_mult    = atr_tp_mult
        self.timeframe      = timeframe
        self._source_missing = False

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

        src  = self._source_series(d, self.source)
        hull = self._hull(src)
        self._hull_arr = hull.to_numpy()
        self._C   = d["Close"].astype(float).to_numpy()
        self._H   = d["High"].astype(float).to_numpy()
        self._L   = d["Low"].astype(float).to_numpy()
        self._atr = self._atr(d, self.atr_length).to_numpy()

        first_valid = int(np.argmax(np.isfinite(self._hull_arr))) if np.isfinite(self._hull_arr).any() else n
        warm = self.length + self._sqrtlen(self.length) + 2
        start = min(max(warm, first_valid + 2), max(n - 1, 0))

        direction = 0
        for i in range(start, n):
            h0, h2 = self._hull_arr[i], self._hull_arr[i - 2]
            if not (np.isfinite(h0) and np.isfinite(h2)):
                continue
            new_dir = 1 if h0 > h2 else (-1 if h0 < h2 else direction)
            buy_turn  = new_dir == 1  and direction != 1
            sell_turn = new_dir == -1 and direction != -1

            # 1) ATR management exit (atr mode only), never on the entry bar
            if self.management == "atr" and self.position != 0 and i > self.trades[-1]["entry_bar"]:
                hit = self._check_atr_exit(i)
                if hit is not None:
                    self._close_trade(i, hit[0], hit[1])

            # 2) Hull turn → close the opposite leg, then open if that side is allowed.
            #    (The opposite turn always CLOSES; `side` only gates what may OPEN, so a
            #     long-only run exits flat on the down-turn and re-enters on the up-turn.)
            if buy_turn:
                if self.position == -1:
                    self._close_on_turn(i)
                if self.position == 0 and self._allow("long"):
                    self._open_trade(i, "long")
                    self.signals.append({"bar": i, "side": "long", "hull": float(h0)})
            elif sell_turn:
                if self.position == 1:
                    self._close_on_turn(i)
                if self.position == 0 and self._allow("short"):
                    self._open_trade(i, "short")
                    self.signals.append({"bar": i, "side": "short", "hull": float(h0)})

            direction = new_dir

        self._finalize_open_trade()

    def _close_on_turn(self, i: int) -> None:
        """Close the open position on an opposite Hull turn, labeled per management mode."""
        t = self.trades[-1]
        exit_price = self._C[i]
        if self.management == "atr":
            reason = self.EXIT_REVERSE
        else:                                            # "signal": TP if profitable else SL
            pnl = (exit_price - t["entry_price"]) if t["side"] == "long" \
                else (t["entry_price"] - exit_price)
            reason = self.EXIT_TP if pnl > 0 else self.EXIT_SL
        self._close_trade(i, exit_price, reason)

    def _allow(self, s: str) -> bool:
        """Is opening a position on side `s` ("long"/"short") permitted by `side`?"""
        return self.side == "both" or self.side == s

    # ─────────────────────────────────────────────────────────────────────────
    # Hull variants + data prep (self-contained)
    # ─────────────────────────────────────────────────────────────────────────


    def _source_series(self, df: pd.DataFrame, kind: str) -> pd.Series:
        O, H, L, C = (df["Open"].astype(float), df["High"].astype(float),
                      df["Low"].astype(float), df["Close"].astype(float))
        if kind in ("volume", "vol"):
            low = {c.lower(): c for c in df.columns}
            for name in ("volume", "vol", "tick_volume"):
                if name in low:
                    return df[low[name]].astype(float)
            self._source_missing = True
            return C                                     # no volume → fall back to close
        table = {
            "open": O, "high": H, "low": L, "close": C,
            "hl2": (H + L) / 2, "oc2": (O + C) / 2,
            "hlc3": (H + L + C) / 3, "ohlc4": (O + H + L + C) / 4,
        }
        return table.get(kind, C)

    @staticmethod
    def _pine_round(v: float) -> int:
        return int(math.floor(v + 0.5))                  # round half up (Pine `round`)

    def _half(self, x: int) -> int:
        return max(int(x) // 2, 1)

    def _third(self, x: int) -> int:
        return max(int(x) // 3, 1)

    def _sqrtlen(self, x: int) -> int:
        return max(self._pine_round(math.sqrt(x)), 1)


    @staticmethod
    def _ema(series: pd.Series, length: int) -> pd.Series:
        return series.ewm(span=max(int(length), 1), adjust=False).mean()

    def _hull(self, src: pd.Series) -> pd.Series:
        n = self.length
        v = self.hull_variation
        if v == "hma":
            return self._wma(2 * self._wma(src, self._half(n)) - self._wma(src, n), self._sqrtlen(n))
        if v == "ehma":
            return self._ema(2 * self._ema(src, self._half(n)) - self._ema(src, n), self._sqrtlen(n))
        if v == "thma":
            m = self._half(n)                            # THMA is called with length/2
            return self._wma(
                3 * self._wma(src, self._third(m)) - self._wma(src, self._half(m)) - self._wma(src, m), m)
        return pd.Series(np.nan, index=src.index)


    # ─────────────────────────────────────────────────────────────────────────
    # ATR exit
    # ─────────────────────────────────────────────────────────────────────────

    def _check_atr_exit(self, i: int) -> Optional[Tuple[float, str]]:
        t = self.trades[-1]
        sl, tp = t["sl_price"], t["tp_price"]
        if self.position == 1:                           # long — SL first on conflict
            if sl is not None and self._L[i] <= sl:
                return sl, self.EXIT_SL
            if tp is not None and self._H[i] >= tp:
                return tp, self.EXIT_TP
        else:                                            # short
            if sl is not None and self._H[i] >= sl:
                return sl, self.EXIT_SL
            if tp is not None and self._L[i] <= tp:
                return tp, self.EXIT_TP
        return None

    # ─────────────────────────────────────────────────────────────────────────
    # Trade records
    # ─────────────────────────────────────────────────────────────────────────

    def _open_trade(self, i: int, side: str) -> None:
        self.position = 1 if side == "long" else -1
        entry = self._C[i]
        a = self._atr[i]
        a = float(a) if np.isfinite(a) else None
        if a is None:
            sl_price = tp_price = None
        elif side == "long":
            sl_price = entry - a * self.atr_sl_mult
            tp_price = entry + a * self.atr_tp_mult
        else:
            sl_price = entry + a * self.atr_sl_mult
            tp_price = entry - a * self.atr_tp_mult
        self.trades.append({
            "trade_id":       self._next_trade_id(),
            "side":           side,
            "setup_time":     self._bar_time(i),
            "entry_time":     self._bar_time(i),
            "exit_time":      None,
            "entry_price":    entry,
            "exit_price":     None,
            "sl_price":       sl_price,
            "tp_price":       tp_price,
            # context
            "hull_at_entry":  float(self._hull_arr[i]),
            "atr_at_entry":   a,
            "management":     self.management,
            "hull_variation": self.hull_variation,
            "length":         self.length,
            "source":         self.source,
            # bar indices
            "setup_bar":      i,
            "entry_bar":      i,
            "exit_bar":       None,
            "bars_held":      None,
            "exit_reason":    None,
        })





    # ─────────────────────────────────────────────────────────────────────────
    # Output builders
    # ─────────────────────────────────────────────────────────────────────────


    def _build_details(self) -> Dict:
        hull = self._hull_arr
        rising = np.full(len(hull), np.nan, dtype=object)
        for i in range(2, len(hull)):
            if np.isfinite(hull[i]) and np.isfinite(hull[i - 2]):
                rising[i] = bool(hull[i] > hull[i - 2])
        hull_df = pd.DataFrame({"bar": np.arange(len(hull)), "hull": hull, "rising": rising})
        hull_df = hull_df[np.isfinite(hull_df["hull"].astype(float))].reset_index(drop=True)
        return {
            "trades":   pd.DataFrame(self.trades),
            "signals":  pd.DataFrame(self.signals, columns=["bar", "side", "hull"]),
            "hull":     hull_df,
            "metadata": self._build_metadata(),
        }

    def _build_metadata(self) -> Dict:
        return {
            "run_id":         self.run_id,
            "asset_class":    self.asset_class,
            "strategy":       "Hull-Suite",
            "timeframe":      self.timeframe,
            "length":         self.length,
            "source":         self.source,
            "hull_variation": self.hull_variation,
            "management":     self.management,
            "side":           self.side,
            "atr_length":     self.atr_length,
            "atr_sl_mult":    self.atr_sl_mult,
            "atr_tp_mult":    self.atr_tp_mult,
            "source_missing": self._source_missing,
        }