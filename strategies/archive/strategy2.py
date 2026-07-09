"""
backtester.py — CHOCHFibBacktester (orchestrator + strategy logic).

Change-of-Character (CHOCH) + Fibonacci-retracement backtester.

The bar loop in `_run` is a thin orchestrator. Every decision is delegated to a
single-responsibility method, and all of them are driven from that loop:

    _update_swings      → maintain the most recent fractal swing high / low
    _detect_setup       → a CHOCH break creates an `active_setup`     (setup logic)
    _check_invalidation → setup killed before entry                   (invalidation logic)
    _check_entry        → fib (± volume-profile) retrace fill         (entry logic)
    _check_exit         → SL / TP hit                                 (exit logic)
    _check_timeout      → max-bars-in-trade force-exit                (timeout logic)

Indicator maths (fractals, fib, ATR, volume profile, rejection candle) live in
`libs/indicators.py`; this class never re-implements them.

Lifecycle of one trade
----------------------

  CHOCH detected        retrace fills          SL/TP or timeout
   (setup_bar)          (entry_bar)              (exit_bar)
       │                    │                        │
       ●────────────────────●────────────────────────●
       │  max_bars_to_entry  │   max_bars_in_trade    │
       │  (kill setup if     │   (force exit if no    │
       │   no fill here)     │    SL/TP hit here)     │

`backtest()` returns a 2-tuple ── trades_df, details = bt.backtest(df):

  • trades_df : slim ledger, one row per trade / invalidation, with columns
                trade_id, side, setup_time, entry_time, entry_price,
                exit_time, exit_price, exit_reason.
  • details   : dict of richer, plot-ready data for a future visualisation
                class (TradingView etc.) — full per-trade fields, swing points,
                CHOCH events and the run configuration.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import pandas as pd

from libs import indicators as ind


class CHOCHFibBacktester:
    # ── exit_reason vocabulary ───────────────────────────────────────────────
    EXIT_TP           = "TP"
    EXIT_SL           = "SL"
    EXIT_INVALIDATION = "Invalidation"
    EXIT_TIMEOUT      = "timeout"
    EXIT_MANUAL       = "manual_exit"        # open position at end of data

    # ── columns of the slim trades_df ────────────────────────────────────────
    TRADE_COLUMNS: List[str] = [
        "trade_id", "side", "setup_time", "entry_time", "entry_price",
        "exit_time", "exit_price", "exit_reason",
    ]

    def __init__(
        self,
        # ── identity / persistence ────────────────────────────────────────────
        run_id:                  str   = "default_run",
        asset_class :            str = "I",
        # ── core strategy ─────────────────────────────────────────────────────
        fractal_left:            int   = 2,
        fractal_right:           int   = 2,
        choch_back_bars:         int   = 5,
        use_close_for_choch:     bool  = True,
        entry_fib_level:         float = 0.5,
        tp_fib_level:            float = 1,
        sl_fib_level:            float = 0,
        entry_tolerance:         float = 0.0005,
        # ── rejection candle ──────────────────────────────────────────────────
        pinbar_wick_ratio:       float = 2.0,
        pinbar_body_ratio:       float = 0.5,
        require_rejection:       bool  = True,
        # ── timeframe / market ────────────────────────────────────────────────
        timeframe:              str   = "",
        # ── volume profile ────────────────────────────────────────────────────
        volume_exist:            bool  = False,
        use_volume_profile:      bool  = False,
        vp_num_bins:             int   = 60,
        vp_value_area_pct:       float = 0.70,
        vp_confluence_weight:    float = 0.6,
        minimum_volume_segement: int   = 2,
        # ── ATR SL/TP ─────────────────────────────────────────────────────────
        use_atr_sl_tp:           bool  = False,
        atr_sl_mult:             float = 1.5,
        atr_tp_mult:             float = 2.0,
        # ── trade management ──────────────────────────────────────────────────
        max_bars_in_trade:       int   = 20,
        max_bars_to_entry:       int   = 10,
    ) -> None:
        # identity
        self.run_id                  = run_id
        self.asset_class             = asset_class
        # timeframe
        self.timeframe               = timeframe
        # trade management
        self.max_bars_in_trade       = max_bars_in_trade
        self.max_bars_to_entry       = max_bars_to_entry
        # strategy
        self.fractal_left            = fractal_left
        self.fractal_right           = fractal_right
        self.choch_back_bars         = choch_back_bars
        self.use_close_for_choch     = use_close_for_choch
        self.entry_fib_level         = entry_fib_level
        self.tp_fib_level            = tp_fib_level
        self.sl_fib_level            = sl_fib_level
        self.entry_tolerance         = entry_tolerance
        # rejection candle
        self.pinbar_wick_ratio       = pinbar_wick_ratio
        self.pinbar_body_ratio       = pinbar_body_ratio
        self.require_rejection       = require_rejection

        # volume profile
        self.volume_exist            = volume_exist
        self.use_volume_profile      = use_volume_profile
        self.vp_num_bins             = vp_num_bins
        self.vp_value_area_pct       = vp_value_area_pct
        self.vp_confluence_weight    = vp_confluence_weight
        self.minimum_volume_segement = minimum_volume_segement
        # ATR
        self.use_atr_sl_tp           = use_atr_sl_tp
        self.atr_sl_mult             = atr_sl_mult
        self.atr_tp_mult             = atr_tp_mult
    

    # ─────────────────────────────────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────────────────────────────────

    def backtest(self, df: pd.DataFrame) -> Tuple[pd.DataFrame, Dict]:
        """
        Run the strategy on `df` and return ``(trades_df, details)``.

        Returns
        -------
        trades_df : pd.DataFrame
            Slim trade ledger with columns:
            ``trade_id, side, setup_time, entry_time, entry_price,
            exit_time, exit_price, exit_reason``.
            ``exit_reason`` ∈ {"TP", "SL", "Invalidation", "timeout", "manual_exit"}.
            ("manual_exit" = a position still open at the last bar; relabel or
            drop it if you only want the four primary reasons.)
        details : dict
            Richer, plot-ready strategy data for a separate visualisation class:
              - "trades"       : full per-trade DataFrame (fib levels, VP, anchors, bars)
              - "swings"       : detected fractal swing highs / lows
              - "choch_events" : CHOCH break markers
              - "metadata"     : the run configuration
        """
        self._run(df)
        return self._build_trades_df(), self._build_details()

    # ─────────────────────────────────────────────────────────────────────────
    # Run-state
    # ─────────────────────────────────────────────────────────────────────────

    def _reset_state(self) -> None:
        """(Re)initialise all per-run mutable state."""
        self.trades:       List[Dict]     = []
        self.swings:       List[Dict]     = []
        self.choch_events: List[Dict]     = []
        self.position:     int            = 0      # 0 flat, +1 long, -1 short
        self.active_setup: Optional[Dict] = None
        self.trade_counter: int           = 0
        self.last_swing_high_price = None
        self.last_swing_low_price  = None
        self.last_swing_high_idx   = -1
        self.last_swing_low_idx    = -1

    # ─────────────────────────────────────────────────────────────────────────
    # Orchestrator (the only place that walks the bars)
    # ─────────────────────────────────────────────────────────────────────────

    def _run(self, df: pd.DataFrame) -> None:
        self._df = df.copy().reset_index(drop=True)
        self._reset_state()

        start = max(self.choch_back_bars, self.fractal_left + self.fractal_right)
        for i in range(start, len(self._df)):
            self._update_swings(i)              # maintain swing pivots
            choch = self._detect_setup(i)       # setup logic
            if not choch:
                self._check_invalidation(i)     # invalidation logic
            self._check_entry(i)                # entry logic
            if self.position != 0:
                self._manage_open_trade(i)      # exit + timeout logic

        self._finalize_open_trade()             # close anything still open

    # ─────────────────────────────────────────────────────────────────────────
    # Swing pivots
    # ─────────────────────────────────────────────────────────────────────────

    def _update_swings(self, i: int) -> None:
        """Confirm the fractal `choch_back_bars` behind `i` and cache it."""
        df             = self._df
        candidate      = i - self.choch_back_bars
        range_of_check = i - self.choch_back_bars - self.fractal_left
        if range_of_check < 0:
            return

        if ind.is_fractal_high(df, candidate, self.fractal_left, self.fractal_right):
            self.last_swing_high_price = df["High"].iloc[candidate]
            self.last_swing_high_idx   = candidate
            self.swings.append({"bar": candidate, "type": "high",
                                "price": df["High"].iloc[candidate]})

        if ind.is_fractal_low(df, candidate, self.fractal_left, self.fractal_right):
            self.last_swing_low_price = df["Low"].iloc[candidate]
            self.last_swing_low_idx   = candidate
            self.swings.append({"bar": candidate, "type": "low",
                                "price": df["Low"].iloc[candidate]})

    # ─────────────────────────────────────────────────────────────────────────
    # Setup logic — CHOCH detection
    # ─────────────────────────────────────────────────────────────────────────

    def _detect_setup(self, i: int) -> bool:
        """
        Detect a Change-of-Character break and, on success, store `active_setup`.
        Returns True when a CHOCH fired on this bar.
        """
        if self.position != 0 or self.active_setup is not None:
            return False

        df             = self._df
        range_of_check = i - self.choch_back_bars - self.fractal_left

        # ── bullish CHOCH: break above the last swing high ────────────────────
        if (self.last_swing_high_price is not None
                and self.last_swing_high_idx >= 0
                and (self.choch_back_bars == 0
                     or (i - self.last_swing_high_idx) <= self.choch_back_bars)):
            bp = (df["Close"].iloc[i] if self.use_close_for_choch
                  else df["High"].iloc[i])
            if bp > self.last_swing_high_price:
                rs = max(0, range_of_check) if self.last_swing_low_idx >= 0 else 0
                self.active_setup = {
                    "direction":     "bullish",
                    "highest_price": df["High"].iloc[i],
                    "lowest_price":  df["Low"].iloc[rs:i].min(),
                    "setup_bar":     i,
                    "fractal_price": self.last_swing_high_price,
                    "fractal_idx":   self.last_swing_high_idx,
                }
                self._record_choch(i, "bullish", self.last_swing_high_price,
                                   self.last_swing_high_idx)
                return True

        # ── bearish CHOCH: break below the last swing low ─────────────────────
        if (self.last_swing_low_price is not None
                and self.last_swing_low_idx >= 0
                and (self.choch_back_bars == 0
                     or (i - self.last_swing_low_idx) <= self.choch_back_bars)):
            bp = (df["Close"].iloc[i] if self.use_close_for_choch
                  else df["Low"].iloc[i])
            if bp < self.last_swing_low_price:
                rs = max(0, range_of_check) if self.last_swing_high_idx >= 0 else 0
                self.active_setup = {
                    "direction":     "bearish",
                    "lowest_price":  df["Low"].iloc[i],
                    "highest_price": df["High"].iloc[rs:i].max(),
                    "setup_bar":     i,
                    "fractal_price": self.last_swing_low_price,
                    "fractal_idx":   self.last_swing_low_idx,
                }
                self._record_choch(i, "bearish", self.last_swing_low_price,
                                   self.last_swing_low_idx)
                return True

        return False

    # ─────────────────────────────────────────────────────────────────────────
    # Invalidation logic
    # ─────────────────────────────────────────────────────────────────────────

    def _check_invalidation(self, i: int) -> None:
        """Kill a still-pending setup if price closes back through its range."""
        if not self.active_setup or self.position != 0:
            return

        close = self._df["Close"].iloc[i]
        direction = self.active_setup["direction"]
        if direction == "bullish" and close < self.active_setup["lowest_price"]:
            self._record_invalidation(i)
            self.active_setup = None
        elif direction == "bearish" and close > self.active_setup["highest_price"]:
            self._record_invalidation(i)
            self.active_setup = None

    # ─────────────────────────────────────────────────────────────────────────
    # Entry logic
    # ─────────────────────────────────────────────────────────────────────────

    def _check_entry(self, i: int) -> None:
        """
        Try to fill the active setup at the fib retrace (optionally blended with
        the volume profile) on a confirming rejection candle.

        Also enforces the setup-expiry window (`max_bars_to_entry`): a setup that
        has not filled within the window is discarded silently (no trade row).
        """
        setup = self.active_setup
        if not setup or self.position != 0 or i <= setup["setup_bar"]:
            return

        # setup expiry — no fill in time, drop it
        if (i - setup["setup_bar"]) > self.max_bars_to_entry:
            self.active_setup = None
            return

        df            = self._df
        direction     = setup["direction"]
        lowest_price  = setup["lowest_price"]
        highest_price = setup["highest_price"]

        # fib retrace entry (raw), optionally blended with the volume profile
        raw_entry_level   = ind.get_fib_price(lowest_price, highest_price,
                                              self.entry_fib_level, direction)
        entry_level_price = raw_entry_level
        vp_poc = vp_vah = vp_val = None
        entry_fib_vs_vp = None

        if self.use_volume_profile:
            vp_poc, vp_vah, vp_val = ind.calculate_volume_profile(
                df,
                start_idx        = setup["fractal_idx"],
                end_idx          = setup["setup_bar"],
                num_bins         = self.vp_num_bins,
                value_area_pct   = self.vp_value_area_pct,
                min_segment_bars = self.minimum_volume_segement,
            )
            if vp_val is not None and vp_vah is not None:
                entry_fib_vs_vp = entry_level_price
                vp_ref = vp_val if direction == "bullish" else vp_vah
                entry_level_price = (entry_level_price * (1 - self.vp_confluence_weight)
                                     + vp_ref * self.vp_confluence_weight)

        # does this bar reach the entry level (within tolerance)?
        if direction == "bullish":
            candle_touches = (df["Low"].iloc[i]  <= entry_level_price + self.entry_tolerance
                              and df["High"].iloc[i] >= entry_level_price - self.entry_tolerance)
        else:
            candle_touches = (df["High"].iloc[i] >= entry_level_price - self.entry_tolerance
                              and df["Low"].iloc[i]  <= entry_level_price + self.entry_tolerance)
        if not candle_touches:
            return

        # confirming rejection candle
        if not ind.is_rejection_candle(df, i, direction, self.require_rejection,
                                       self.pinbar_wick_ratio, self.pinbar_body_ratio):
            return

        # fill price — never worse than the open (handles gaps through the level)
        o = df["Open"].iloc[i]
        entry_price = min(entry_level_price, o) if direction == "bullish" \
            else max(entry_level_price, o)

        # SL / TP
        if self.use_atr_sl_tp:
            atr_val = df["ATR"].iloc[i]
            if pd.isna(atr_val):
                return                       # cannot size the stop — skip this bar
            if direction == "bullish":
                sl_price = entry_price - atr_val * self.atr_sl_mult
                tp_price = entry_price + atr_val * self.atr_tp_mult
            else:
                sl_price = entry_price + atr_val * self.atr_sl_mult
                tp_price = entry_price - atr_val * self.atr_tp_mult
        else:
            sl_price = ind.get_fib_price(lowest_price, highest_price,
                                         self.sl_fib_level, direction)
            tp_price = ind.get_fib_price(lowest_price, highest_price,
                                         self.tp_fib_level, direction)

        self._open_trade(
            i, direction, entry_price, sl_price, tp_price,
            raw_entry_level, entry_level_price,
            vp_poc, vp_vah, vp_val, entry_fib_vs_vp,
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Trade management — exit + timeout
    # ─────────────────────────────────────────────────────────────────────────

    def _manage_open_trade(self, i: int) -> None:
        """Run exit checks for the open trade (SL/TP first, then timeout)."""
        if i <= self.trades[-1]["entry_bar"]:        # never on the entry bar
            return

        signal = self._check_exit(i) or self._check_timeout(i)
        if signal is not None:
            exit_price, exit_reason = signal
            self._close_trade(i, exit_price, exit_reason)

    def _check_exit(self, i: int) -> Optional[Tuple[float, str]]:
        """Exit logic: stop-loss / take-profit. SL is assumed first on conflict."""
        df       = self._df
        trade    = self.trades[-1]
        sl_price = trade["sl_price"]
        tp_price = trade["tp_price"]

        if self.position == 1:                       # long
            if df["Low"].iloc[i] <= sl_price:
                return sl_price, self.EXIT_SL
            if df["High"].iloc[i] >= tp_price:
                return tp_price, self.EXIT_TP
        else:                                        # short
            if df["High"].iloc[i] >= sl_price:
                return sl_price, self.EXIT_SL
            if df["Low"].iloc[i] <= tp_price:
                return tp_price, self.EXIT_TP
        return None

    def _check_timeout(self, i: int) -> Optional[Tuple[float, str]]:
        """Timeout logic: force-exit at close after `max_bars_in_trade` bars."""
        if self.max_bars_in_trade <= 0:
            return None
        trade = self.trades[-1]
        if (i - trade["entry_bar"]) >= self.max_bars_in_trade:
            return self._df["Close"].iloc[i], self.EXIT_TIMEOUT
        return None

    def _finalize_open_trade(self) -> None:
        """Close any position still open at the last bar of the data."""
        if self.position != 0 and self.trades:
            last_i = len(self._df) - 1
            self._close_trade(last_i, self._df["Close"].iloc[last_i], self.EXIT_MANUAL)

    # ─────────────────────────────────────────────────────────────────────────
    # Trade-record helpers
    # ─────────────────────────────────────────────────────────────────────────

    def _open_trade(
        self, i: int, direction: str,
        entry_price: float, sl_price: float, tp_price: float,
        raw_entry_level: float, entry_level_price: float,
        vp_poc, vp_vah, vp_val, entry_fib_vs_vp,
    ) -> None:
        setup = self.active_setup
        self.position = 1 if direction == "bullish" else -1
        self.trades.append({
            # identity
            "trade_id":                 self._next_trade_id(),
            "side":                     "long" if direction == "bullish" else "short",
            # timestamps
            "setup_time":               self._bar_time(setup["setup_bar"]),
            "entry_time":               self._bar_time(i),
            "exit_time":                None,
            # prices
            "entry_price":              entry_price,
            "exit_price":               None,
            "sl_price":                 sl_price,
            "tp_price":                 tp_price,
            "entry_fib_price":          raw_entry_level,
            "entry_fib_vp_blended":     entry_level_price if self.use_volume_profile else None,
            "fractal_price":            setup["fractal_price"],
            "highest_price":            setup["highest_price"],
            "lowest_price":             setup["lowest_price"],
            # setup info / bar indices (for plotting)
            "setup_bar":                setup["setup_bar"],
            "fractal_idx":              setup["fractal_idx"],
            "entry_bar":                i,
            "exit_bar":                 None,
            "bars_to_entry_from_choch": i - setup["setup_bar"],
            # volume profile
            "vp_poc": vp_poc, "vp_vah": vp_vah, "vp_val": vp_val,
            "entry_fib_vs_vp": entry_fib_vs_vp,
            # outcome
            "exit_reason": None,
        })

    def _close_trade(self, i: int, exit_price: float, exit_reason: str) -> None:
        """Finalise the open trade record and return to a flat state."""
        self.trades[-1].update({
            "exit_time":   self._bar_time(i),
            "exit_price":  exit_price,
            "exit_bar":    i,
            "exit_reason": exit_reason,
        })
        self.position     = 0
        self.active_setup = None

    def _record_invalidation(self, i: int) -> None:
        """Append a row for a setup that was invalidated before it could fill."""
        setup = self.active_setup
        self.trades.append({
            "trade_id":                 self._next_trade_id(),
            "side":                     "long" if setup["direction"] == "bullish" else "short",
            "setup_time":               self._bar_time(setup["setup_bar"]),
            "entry_time":               None,
            "exit_time":                self._bar_time(i),
            "entry_price":              None,
            "exit_price":               None,
            "sl_price":                 None,
            "tp_price":                 None,
            "entry_fib_price":          None,
            "entry_fib_vp_blended":     None,
            "fractal_price":            setup.get("fractal_price"),
            "highest_price":            setup.get("highest_price"),
            "lowest_price":             setup.get("lowest_price"),
            "setup_bar":                setup["setup_bar"],
            "fractal_idx":              setup.get("fractal_idx"),
            "entry_bar":                None,
            "exit_bar":                 i,
            "bars_to_entry_from_choch": None,
            "vp_poc": None, "vp_vah": None, "vp_val": None, "entry_fib_vs_vp": None,
            "exit_reason": self.EXIT_INVALIDATION,
        })

    def _record_choch(self, i: int, direction: str,
                      fractal_price: float, fractal_idx: int) -> None:
        """Log a CHOCH break for the visualisation layer."""
        self.choch_events.append({
            "bar": i, "direction": direction,
            "fractal_price": fractal_price, "fractal_idx": fractal_idx,
        })

    def _next_trade_id(self) -> str:
        self.trade_counter += 1
        return f"T{self.trade_counter:05d}"

    def _bar_time(self, idx: int):
        """Datetime for `idx` if the column exists, else the bar index itself."""
        df = self._df
        return df["Datetime"].iloc[idx] if "Datetime" in df.columns else idx

    # ─────────────────────────────────────────────────────────────────────────
    # Output builders
    # ─────────────────────────────────────────────────────────────────────────

    def _build_trades_df(self) -> pd.DataFrame:
        """Slim ledger with exactly the requested columns."""
        if not self.trades:
            return pd.DataFrame(columns=self.TRADE_COLUMNS)
        return pd.DataFrame(self.trades)[self.TRADE_COLUMNS].copy()

    def _build_details(self) -> Dict:
        """Everything a future (e.g. TradingView) visualisation class might need."""
        return {
            "trades":       pd.DataFrame(self.trades),
            "swings":       pd.DataFrame(self.swings,
                                         columns=["bar", "type", "price"]),
            "choch_events": pd.DataFrame(self.choch_events,
                                         columns=["bar", "direction",
                                                  "fractal_price", "fractal_idx"]),
            "metadata":     self._build_metadata(),
        }

    def _build_metadata(self) -> Dict:
        """Flat dict of the run configuration."""
        return {
            "run_id":                  self.run_id,
            "timeframe":               self.timeframe,
            "asset_class":             self.asset_class,
            "fractal_left":            self.fractal_left,
            "fractal_right":           self.fractal_right,
            "choch_back_bars":         self.choch_back_bars,
            "use_close_for_choch":     self.use_close_for_choch,
            "entry_fib_level":         self.entry_fib_level,
            "tp_fib_level":            self.tp_fib_level,
            "sl_fib_level":            self.sl_fib_level,
            "entry_tolerance":         self.entry_tolerance,
            "pinbar_wick_ratio":       self.pinbar_wick_ratio,
            "pinbar_body_ratio":       self.pinbar_body_ratio,
            "require_rejection":       self.require_rejection,
            "use_volume_profile":      self.use_volume_profile,
            "vp_num_bins":             self.vp_num_bins,
            "vp_value_area_pct":       self.vp_value_area_pct,
            "vp_confluence_weight":    self.vp_confluence_weight,
            "minimum_volume_segement": self.minimum_volume_segement,
            "use_atr_sl_tp":           self.use_atr_sl_tp,
            "atr_sl_mult":             self.atr_sl_mult,
            "atr_tp_mult":             self.atr_tp_mult,
            "max_bars_in_trade":       self.max_bars_in_trade,
            "max_bars_to_entry":       self.max_bars_to_entry,
        }