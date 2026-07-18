"""
strategy_msb.py — Market-Structure-Break + Fibonacci retracement backtester.

A causal Python port of the "Market Structure Break & Order Block" (MSB-OB)
indicator by EmreKb (MPL-2.0), turned into a tradable strategy with the SAME
output contract as CHOCHFibBacktester so it drops straight into the pipeline
(CFDCostModel → CFDAccountSimulator → PerformanceAnalytics → ResultStore →
dashboard / tv_chart).

How it trades
─────────────
1. SETUP  — wait for a Market Structure Break (MSB). A zigzag (swing highs/lows
   confirmed via the `zigzag_len`-bar highest/lowest rule) feeds the indicator's
   regime test:
       bullish MSB :  h0 > h1 + |h1 - l0| * fib_factor      (higher high, beyond a buffer)
       bearish MSB :  l0 < l1 - |h0 - l1| * fib_factor      (lower low,  beyond a buffer)
   h0/l0 are the latest swing high/low, h1/l1 the previous ones.

2. ENTRY  — after the MSB, wait for price to retrace into a fib level (or a fib
   ZONE) of the broken leg [swing_low, swing_high]:
       • bullish: price comes DOWN to `entry_fib_level`, go long, target the high (or beyond)
       • bearish: price comes UP   to `entry_fib_level`, go short, target the low (or beyond)
   `entry_fib_range` widens the single level into a zone [level, level+range].

3. SL / TP — from fib levels (`sl_fib_level` = stop side, `tp_fib_level` = the
   broken extreme at 1.0, >1 for extensions), OR from ATR if `use_atr_sl_tp`.

4. INVALIDATION — an MSB in the OPPOSITE direction kills a pending setup (records
   an "Invalidation" row) and, if `invalidate_on_opposite_msb`, closes an open
   trade early ("Invalidation").

5. WINDOWS — `max_bars_to_entry` bounds setup→entry (an unfilled setup expires
   silently); `max_bars_in_trade` force-exits a stale open trade ("timeout").

Returns `(trades_df, details)` exactly like CHOCHFibBacktester:
    trades_df : slim ledger — trade_id, side, setup_time, entry_time, entry_price,
                exit_time, exit_price, exit_reason
    details   : {"trades" (full per-trade frame with every key level/bar),
                 "swings", "msb_events", "metadata"}
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import pandas as pd

from libs import indicators as ind
from strategies.common import ScaffoldMixin, canonicalize_ohlc


class MSBOBFibBacktester(ScaffoldMixin):
    # shared scaffolding (strategies/common.py): reset_index + standard
    # aliases; _next_trade_id/_bar_time/_build_trades_df from ScaffoldMixin.
    # _close_trade/_finalize_open_trade stay local (variant clears
    # active_setup and skips bars_held).
    _canonicalize = staticmethod(canonicalize_ohlc)

    # ── exit_reason vocabulary (same as CHOCHFibBacktester) ──────────────────
    EXIT_TP           = "TP"
    EXIT_SL           = "SL"
    EXIT_INVALIDATION = "Invalidation"
    EXIT_TIMEOUT      = "timeout"
    EXIT_MANUAL       = "manual_exit"        # position still open at last bar

    # ── columns of the slim trades_df (identical to CHOCHFibBacktester) ──────
    TRADE_COLUMNS: List[str] = [
        "trade_id", "side", "setup_time", "entry_time", "entry_price",
        "exit_time", "exit_price", "exit_reason",
    ]

    def __init__(
        self,
        # ── identity ──────────────────────────────────────────────────────────
        run_id:                     str   = "default_run",
        # ── structure / zigzag ────────────────────────────────────────────────
        zigzag_len:                 int   = 9,
        fib_factor:                 float = 0.33,    # break-confirmation buffer (0..1)
        asset_class:                str = "NDX",
        # ── fib entry / targets ───────────────────────────────────────────────
        entry_fib_level:            float = 0.5,     # retrace level for entry
        entry_fib_range:            float = 0.0,     # >0 → entry ZONE [level, level+range]
        tp_fib_level:               float = 1.0,     # 1.0 = swing extreme; >1 = extension
        sl_fib_level:               float = 0.0,     # 0.0 = leg base (stop side)
        entry_tolerance:            float = 0.0005,
        # ── rejection candle (optional confirmation) ──────────────────────────
        require_rejection:          bool  = False,
        pinbar_wick_ratio:          float = 2.0,
        pinbar_body_ratio:          float = 0.5,
        # ── ATR SL/TP (overrides fib SL/TP when on) ───────────────────────────
        use_atr_sl_tp:              bool  = False,
        atr_sl_mult:                float = 1.5,
        atr_tp_mult:                float = 2.0,
        atr_length:                 int   = 14,      # used only if df has no ATR column
        # ── trade management ──────────────────────────────────────────────────
        max_bars_in_trade:          int   = 20,
        max_bars_to_entry:          int   = 10,
        # ── invalidation ──────────────────────────────────────────────────────
        invalidate_on_opposite_msb: bool  = True,
        regime_flip_only:           bool  = True,   # True = exact indicator regime-flip MSBs (rarer)
        # ── label ─────────────────────────────────────────────────────────────
        timeframe:                  str   = "",
    ) -> None:
        self.run_id                     = run_id
        self.zigzag_len                 = max(int(zigzag_len), 1)
        self.fib_factor                 = fib_factor
        self.entry_fib_level            = entry_fib_level
        self.entry_fib_range            = entry_fib_range
        self.tp_fib_level               = tp_fib_level
        self.sl_fib_level               = sl_fib_level
        self.entry_tolerance            = entry_tolerance
        self.require_rejection          = require_rejection
        self.pinbar_wick_ratio          = pinbar_wick_ratio
        self.pinbar_body_ratio          = pinbar_body_ratio
        self.use_atr_sl_tp              = use_atr_sl_tp
        self.atr_sl_mult                = atr_sl_mult
        self.atr_tp_mult                = atr_tp_mult
        self.atr_length                 = atr_length
        self.max_bars_in_trade          = max_bars_in_trade
        self.max_bars_to_entry          = max_bars_to_entry
        self.invalidate_on_opposite_msb = invalidate_on_opposite_msb
        self.regime_flip_only           = regime_flip_only
        self.timeframe                 = timeframe
        self.asset_class                = asset_class

    # ─────────────────────────────────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────────────────────────────────

    def backtest(self, df: pd.DataFrame) -> Tuple[pd.DataFrame, Dict]:
        """Run the strategy on `df` and return ``(trades_df, details)``."""
        self._run(df)
        return self._build_trades_df(), self._build_details()

    # ─────────────────────────────────────────────────────────────────────────
    # Run-state
    # ─────────────────────────────────────────────────────────────────────────

    def _reset_state(self) -> None:
        self.trades:       List[Dict] = []
        self.swings:       List[Dict] = []
        self.msb_events:   List[Dict] = []
        self.position:     int        = 0           # 0 flat, +1 long, -1 short
        self.active_setup: Optional[Dict] = None
        self.trade_counter: int       = 0
        # zigzag state
        self._zz_init = False
        self.trend = 1
        self._phase_high = None; self._phase_high_idx = -1
        self._phase_low  = None; self._phase_low_idx  = -1
        self.swing_high_prices: List[float] = []
        self.swing_high_idx:    List[int]   = []
        self.swing_low_prices:  List[float] = []
        self.swing_low_idx:     List[int]   = []
        # market-structure state
        self.market = 1                             # +1 bullish regime, -1 bearish
        self._just_pushed: Optional[str] = None     # "high"/"low" confirmed on the current bar

    # ─────────────────────────────────────────────────────────────────────────
    # Orchestrator (the only place that walks the bars)
    # ─────────────────────────────────────────────────────────────────────────

    def _run(self, df: pd.DataFrame) -> None:
        self._df = self._canonicalize(df)
        self._reset_state()

        if self.use_atr_sl_tp and "ATR" not in self._df.columns:
            self._df["ATR"] = ind.calculate_atr(self._df, self.atr_length)

        n = len(self._df)
        start = min(self.zigzag_len, max(n - 1, 0))
        for i in range(start, n):
            self._update_zigzag(i)               # maintain swing highs/lows
            direction = self._detect_msb(i)      # regime flip → setup signal
            if direction is not None:
                self._on_msb(i, direction)       # invalidate opposite + create setup
            self._check_entry(i)                 # fill pending setup at the fib zone
            if self.position != 0:
                self._manage_open_trade(i)       # SL/TP/timeout

        self._finalize_open_trade()


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

        # extend the extreme of the CURRENT phase
        if self.trend == 1:
            if hi >= self._phase_high:
                self._phase_high, self._phase_high_idx = hi, i
        else:
            if lo <= self._phase_low:
                self._phase_low, self._phase_low_idx = lo, i

        # new `zigzag_len`-bar extreme on this bar?
        lo_win = i - self.zigzag_len + 1
        win_high = float(df["High"].iloc[max(lo_win, 0):i + 1].max())
        win_low  = float(df["Low"].iloc[max(lo_win, 0):i + 1].min())
        to_up   = hi >= win_high
        to_down = lo <= win_low

        if self.trend == 1 and to_down:
            # up-phase ends → confirm the swing HIGH (the phase peak)
            self._push_swing("high", self._phase_high_idx, self._phase_high)
            self.trend = -1
            self._phase_low, self._phase_low_idx = lo, i
        elif self.trend == -1 and to_up:
            # down-phase ends → confirm the swing LOW (the phase trough)
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
    # MSB detection — regime flip (faithful to the indicator's `market` logic)
    # ─────────────────────────────────────────────────────────────────────────

    def _detect_msb(self, i: int) -> Optional[str]:
        """
        Fire an MSB the bar a qualifying swing is confirmed:
          • new swing HIGH and  h0 > h1 + |h1 - l0|*fib_factor  → bullish
          • new swing LOW  and  l0 < l1 - |h0 - l1|*fib_factor  → bearish
        With `regime_flip_only`, a break only counts when it flips the regime
        (bullish needs market==-1, bearish needs market==1) — the indicator's
        exact, rarer behaviour. Otherwise every qualifying break signals (BoS).
        """
        pushed = self._just_pushed
        if pushed is None:
            return None

        h0, _ = self._last_high(0); h1, _ = self._last_high(1)
        l0, _ = self._last_low(0);  l1, _ = self._last_low(1)

        direction = broken = None
        if pushed == "high" and None not in (h0, h1, l0):
            if h0 > h1 + abs(h1 - l0) * self.fib_factor and (
                    not self.regime_flip_only or self.market == -1):
                direction, broken = "bullish", h1
                self.market = 1
        elif pushed == "low" and None not in (l0, l1, h0):
            if l0 < l1 - abs(h0 - l1) * self.fib_factor and (
                    not self.regime_flip_only or self.market == 1):
                direction, broken = "bearish", l1
                self.market = -1

        if direction is None:
            return None

        self.msb_events.append({
            "bar": i, "direction": direction, "market": self.market,
            "swing_high": h0, "swing_low": l0, "broken_level": broken,
        })
        return direction

    def _on_msb(self, i: int, direction: str) -> None:
        # opposite-side handling first
        if self.position != 0:
            cur = "bullish" if self.position == 1 else "bearish"
            if direction != cur and self.invalidate_on_opposite_msb:
                self._close_trade(i, float(self._df["Close"].iloc[i]), self.EXIT_INVALIDATION)
            else:
                return                                   # keep the open trade
        elif self.active_setup is not None:
            if self.active_setup["direction"] != direction:
                if self.invalidate_on_opposite_msb:
                    self._record_invalidation(i)
                self.active_setup = None
            else:
                return                                   # same-direction setup already pending
        # flat now → arm the new setup
        self._create_setup(i, direction)

    def _create_setup(self, i: int, direction: str) -> None:
        h0, h0i = self._last_high(0); h1, _ = self._last_high(1)
        l0, l0i = self._last_low(0);  l1, _ = self._last_low(1)
        if None in (h0, l0):
            return
        highest, lowest = float(h0), float(l0)
        if not (highest > lowest):                       # degenerate leg
            return
        self.active_setup = {
            "direction":      direction,
            "lowest_price":   lowest,
            "highest_price":  highest,
            "swing_high":     highest,
            "swing_low":      lowest,
            "swing_high_idx": h0i,
            "swing_low_idx":  l0i,
            "broken_level":   float(h1) if direction == "bullish" else float(l1),
            "setup_bar":      i,
            "market":         self.market,
        }

    # ─────────────────────────────────────────────────────────────────────────
    # Entry
    # ─────────────────────────────────────────────────────────────────────────

    def _check_entry(self, i: int) -> None:
        setup = self.active_setup
        if not setup or self.position != 0 or i <= setup["setup_bar"]:
            return

        # setup expiry — unfilled within the window → drop silently
        if (i - setup["setup_bar"]) > self.max_bars_to_entry:
            self.active_setup = None
            return

        df         = self._df
        direction  = setup["direction"]
        low_p      = setup["lowest_price"]
        high_p     = setup["highest_price"]
        tol        = self.entry_tolerance

        entry_level = ind.get_fib_price(low_p, high_p, self.entry_fib_level, direction)
        if self.entry_fib_range > 0:
            deep = ind.get_fib_price(low_p, high_p,
                                     self.entry_fib_level + self.entry_fib_range, direction)
            zone_lo, zone_hi = (entry_level, deep) if entry_level <= deep else (deep, entry_level)
        else:
            zone_lo = zone_hi = entry_level

        bar_low  = float(df["Low"].iloc[i])
        bar_high = float(df["High"].iloc[i])
        touched = (bar_low <= zone_hi + tol) and (bar_high >= zone_lo - tol)
        if not touched:
            return

        if self.require_rejection and not ind.is_rejection_candle(
                df, i, direction, True, self.pinbar_wick_ratio, self.pinbar_body_ratio):
            return

        o = float(df["Open"].iloc[i])
        entry_price = min(entry_level, o) if direction == "bullish" else max(entry_level, o)

        # SL / TP
        atr_val = None
        if "ATR" in df.columns:
            atr_val = df["ATR"].iloc[i]
            atr_val = float(atr_val) if pd.notna(atr_val) else None
        if self.use_atr_sl_tp:
            if atr_val is None:
                return                                   # cannot size the stop — skip
            if direction == "bullish":
                sl_price = entry_price - atr_val * self.atr_sl_mult
                tp_price = entry_price + atr_val * self.atr_tp_mult
            else:
                sl_price = entry_price + atr_val * self.atr_sl_mult
                tp_price = entry_price - atr_val * self.atr_tp_mult
            sl_tp_mode = "atr"
        else:
            sl_price = ind.get_fib_price(low_p, high_p, self.sl_fib_level, direction)
            tp_price = ind.get_fib_price(low_p, high_p, self.tp_fib_level, direction)
            sl_tp_mode = "fib"

        self._open_trade(i, direction, entry_price, sl_price, tp_price,
                         entry_level, zone_lo, zone_hi, sl_tp_mode, atr_val)

    # ─────────────────────────────────────────────────────────────────────────
    # Trade management — exit + timeout
    # ─────────────────────────────────────────────────────────────────────────

    def _manage_open_trade(self, i: int) -> None:
        if i <= self.trades[-1]["entry_bar"]:            # never on the entry bar
            return
        signal = self._check_exit(i) or self._check_timeout(i)
        if signal is not None:
            exit_price, exit_reason = signal
            self._close_trade(i, exit_price, exit_reason)

    def _check_exit(self, i: int) -> Optional[Tuple[float, str]]:
        df = self._df
        trade = self.trades[-1]
        sl_price, tp_price = trade["sl_price"], trade["tp_price"]
        if self.position == 1:                           # long — SL first on conflict
            if float(df["Low"].iloc[i])  <= sl_price:
                return sl_price, self.EXIT_SL
            if float(df["High"].iloc[i]) >= tp_price:
                return tp_price, self.EXIT_TP
        else:                                            # short
            if float(df["High"].iloc[i]) >= sl_price:
                return sl_price, self.EXIT_SL
            if float(df["Low"].iloc[i])  <= tp_price:
                return tp_price, self.EXIT_TP
        return None

    def _check_timeout(self, i: int) -> Optional[Tuple[float, str]]:
        if self.max_bars_in_trade <= 0:
            return None
        trade = self.trades[-1]
        if (i - trade["entry_bar"]) >= self.max_bars_in_trade:
            return float(self._df["Close"].iloc[i]), self.EXIT_TIMEOUT
        return None

    def _finalize_open_trade(self) -> None:
        if self.position != 0 and self.trades:
            last_i = len(self._df) - 1
            self._close_trade(last_i, float(self._df["Close"].iloc[last_i]), self.EXIT_MANUAL)

    # ─────────────────────────────────────────────────────────────────────────
    # Trade-record helpers
    # ─────────────────────────────────────────────────────────────────────────

    def _open_trade(self, i, direction, entry_price, sl_price, tp_price,
                    entry_fib_price, zone_lo, zone_hi, sl_tp_mode, atr_val) -> None:
        s = self.active_setup
        self.position = 1 if direction == "bullish" else -1
        self.trades.append({
            # identity
            "trade_id":               self._next_trade_id(),
            "side":                   "long" if direction == "bullish" else "short",
            # timestamps
            "setup_time":             self._bar_time(s["setup_bar"]),
            "entry_time":             self._bar_time(i),
            "exit_time":              None,
            # prices
            "entry_price":            entry_price,
            "exit_price":             None,
            "sl_price":               sl_price,
            "tp_price":               tp_price,
            "entry_fib_price":        entry_fib_price,
            "entry_zone_low":         zone_lo,
            "entry_zone_high":        zone_hi,
            # the leg + structure (key plotting levels)
            "swing_high":             s["swing_high"],
            "swing_low":              s["swing_low"],
            "highest_price":          s["highest_price"],
            "lowest_price":           s["lowest_price"],
            "msb_level":              s["broken_level"],
            "broken_level":           s["broken_level"],
            # fib ratios used
            "entry_fib_level":        self.entry_fib_level,
            "sl_fib_level":           self.sl_fib_level,
            "tp_fib_level":           self.tp_fib_level,
            "sl_tp_mode":             sl_tp_mode,
            "atr_at_entry":           atr_val,
            # regime + params for this trade
            "market_at_setup":        s["market"],
            "fib_factor":             self.fib_factor,
            "zigzag_len":             self.zigzag_len,
            # bar indices
            "setup_bar":              s["setup_bar"],
            "swing_high_idx":         s["swing_high_idx"],
            "swing_low_idx":          s["swing_low_idx"],
            "entry_bar":              i,
            "exit_bar":               None,
            "bars_to_entry_from_msb": i - s["setup_bar"],
            # outcome
            "exit_reason":            None,
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
        """Row for a setup invalidated (by an opposite MSB) before it could fill."""
        s = self.active_setup
        self.trades.append({
            "trade_id":               self._next_trade_id(),
            "side":                   "long" if s["direction"] == "bullish" else "short",
            "setup_time":             self._bar_time(s["setup_bar"]),
            "entry_time":             None,
            "exit_time":              self._bar_time(i),
            "entry_price":            None,
            "exit_price":             None,
            "sl_price":               None,
            "tp_price":               None,
            "entry_fib_price":        None,
            "entry_zone_low":         None,
            "entry_zone_high":        None,
            "swing_high":             s["swing_high"],
            "swing_low":              s["swing_low"],
            "highest_price":          s["highest_price"],
            "lowest_price":           s["lowest_price"],
            "msb_level":              s["broken_level"],
            "broken_level":           s["broken_level"],
            "entry_fib_level":        self.entry_fib_level,
            "sl_fib_level":           self.sl_fib_level,
            "tp_fib_level":           self.tp_fib_level,
            "sl_tp_mode":             "atr" if self.use_atr_sl_tp else "fib",
            "atr_at_entry":           None,
            "market_at_setup":        s["market"],
            "fib_factor":             self.fib_factor,
            "zigzag_len":             self.zigzag_len,
            "setup_bar":              s["setup_bar"],
            "swing_high_idx":         s["swing_high_idx"],
            "swing_low_idx":          s["swing_low_idx"],
            "entry_bar":              None,
            "exit_bar":               i,
            "bars_to_entry_from_msb": None,
            "exit_reason":            self.EXIT_INVALIDATION,
        })



    # ─────────────────────────────────────────────────────────────────────────
    # Output builders
    # ─────────────────────────────────────────────────────────────────────────


    def _build_details(self) -> Dict:
        return {
            "trades":     pd.DataFrame(self.trades),
            "swings":     pd.DataFrame(self.swings, columns=["bar", "type", "price"]),
            "msb_events": pd.DataFrame(self.msb_events,
                                       columns=["bar", "direction", "market",
                                                "swing_high", "swing_low", "broken_level"]),
            "metadata":   self._build_metadata(),
        }

    def _build_metadata(self) -> Dict:
        return {
            "run_id":                     self.run_id,
            "strategy":                   "MSB-OB-Fib",
            'asset_class':                self.asset_class,
            "timeframe":                  self.timeframe,
            "zigzag_len":                 self.zigzag_len,
            "fib_factor":                 self.fib_factor,
            "entry_fib_level":            self.entry_fib_level,
            "entry_fib_range":            self.entry_fib_range,
            "tp_fib_level":               self.tp_fib_level,
            "sl_fib_level":               self.sl_fib_level,
            "entry_tolerance":            self.entry_tolerance,
            "require_rejection":          self.require_rejection,
            "pinbar_wick_ratio":          self.pinbar_wick_ratio,
            "pinbar_body_ratio":          self.pinbar_body_ratio,
            "use_atr_sl_tp":              self.use_atr_sl_tp,
            "atr_sl_mult":                self.atr_sl_mult,
            "atr_tp_mult":                self.atr_tp_mult,
            "atr_length":                 self.atr_length,
            "max_bars_in_trade":          self.max_bars_in_trade,
            "max_bars_to_entry":          self.max_bars_to_entry,
            "invalidate_on_opposite_msb": self.invalidate_on_opposite_msb,
            "regime_flip_only":           self.regime_flip_only,
        }