"""
backtester.py — CHOCHFibBacktester (orchestrator only).

This class owns NO implementation details.  It:
  1. Holds configuration.
  2. Delegates every concern to the appropriate module:
       • indicators.py   — fractals, fib, session, ATR
  3. Runs the bar loop and assembles trade records.


  CHOCH detected        retrace fills          SL/TP or timeout
   (setup_bar)          (entry_bar)              (exit_bar)
       │                    │                        │
       ●────────────────────●────────────────────────●
       │   max_bars_to_entry │   max_bars_in_trade    │
       │   (kill setup if    │   (force exit if no    │
       │    no fill here)    │    SL/TP hit here)     │
"""
from __future__ import annotations

from typing import Dict
from libs import indicators as ind 
import pandas as pd



# ─────────────────────────────────────────────────────────────────────────────
# Backtester
# ─────────────────────────────────────────────────────────────────────────────

class CHOCHFibBacktester:
    """
    Change-of-Character (CHOCH) + Fibonacci retracement backtester.

    Parameters
    ----------
    run_id : str
        Unique label for this configuration (e.g. "EURUSD_1h_fib50").
        Used as the key when saving results to a ResultStore.
    """



    def __init__(
        self,
        # ── identity / persistence ────────────────────────────────────────────
        run_id:                  str   = "default_run",
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
        timeframes:              str   = "",
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
        max_bars_to_entry:       int    = 10
    ) -> None:

        # Identity / persistence
        self.run_id         = run_id
        # Strategy params
        self.fractal_left            = fractal_left
        self.fractal_right           = fractal_right
        self.choch_back_bars         = choch_back_bars
        self.use_close_for_choch     = use_close_for_choch
        self.entry_fib_level         = entry_fib_level
        self.tp_fib_level            = tp_fib_level
        self.sl_fib_level            = sl_fib_level
        self.entry_tolerance         = entry_tolerance
        self.pinbar_wick_ratio       = pinbar_wick_ratio
        self.pinbar_body_ratio       = pinbar_body_ratio
        self.require_rejection       = require_rejection
        self.timeframes              = timeframes
        self.volume_exist            = volume_exist
        self.use_volume_profile      = use_volume_profile
        self.vp_num_bins             = vp_num_bins
        self.vp_value_area_pct       = vp_value_area_pct
        self.vp_confluence_weight    = vp_confluence_weight
        self.minimum_volume_segement = minimum_volume_segement
        self.use_atr_sl_tp           = use_atr_sl_tp
        self.atr_sl_mult             = atr_sl_mult
        self.atr_tp_mult             = atr_tp_mult
        self.max_bars_in_trade       = max_bars_in_trade
        self.max_bars_to_entry       = max_bars_to_entry

    # ── public entry point ────────────────────────────────────────────────────

    def backtest(self, df: pd.DataFrame) -> Dict:
        """
        Run the strategy on `df` and return
        {"trades_df": pd.DataFrame

        If store_filepath was set at construction, results are automatically
        saved (overwrite=True) after the run.
        """
        result = self._run(df)
        return result

    # ── metadata helper ───────────────────────────────────────────────────────

    def _build_metadata(self) -> Dict:
        """Collect all config params into a flat dict for the store."""
        return {
            "run_id":                  self.run_id,
            "timeframes":              self.timeframes,
            "fractal_left":            self.fractal_left,
            "fractal_right":           self.fractal_right,
            "choch_back_bars":         self.choch_back_bars,
            "use_close_for_choch":     self.use_close_for_choch,
            "entry_fib_level":         self.entry_fib_level,
            "tp_fib_level":            self.tp_fib_level,
            "sl_fib_level":            self.sl_fib_level,
            "pinbar_wick_ratio":       self.pinbar_wick_ratio,
            "pinbar_body_ratio":       self.pinbar_body_ratio,
            "require_rejection":       self.require_rejection,
            "use_volume_profile":      self.use_volume_profile,
            "use_atr_sl_tp":           self.use_atr_sl_tp,
            "atr_length":              self.atr_length,
            "atr_sl_mult":             self.atr_sl_mult,
            "atr_tp_mult":             self.atr_tp_mult,
            "entry_tolerance":         self.entry_tolerance,
            "max_bars_in_trade":       self.max_bars_in_trade,
            "max_bars_to_entry ":      self.max_bars_to_entry,
        }

    # ── internal bar loop ─────────────────────────────────────────────────────

    def _run(self, df: pd.DataFrame) -> Dict:
        df = df.copy().reset_index(drop=True)
        # ── state reset ───────────────────────────────────────────────────────
        self.trades       = []
        position          = 0
        entry_price = sl_price = tp_price = 0.0
        active_setup      = None
        trade_counter     = 0

        last_swing_high_price = last_swing_low_price = None
        last_swing_high_idx   = last_swing_low_idx   = -1

        start = max(self.choch_back_bars, self.fractal_left + self.fractal_right)

        for i in range(start, len(df)):
            center         = i
            range_of_check = center - self.choch_back_bars - self.fractal_left
            candidate      = center - self.choch_back_bars

            # ── fractal update ────────────────────────────────────────────────
            if range_of_check >= 0:
                if ind.is_fractal_high(df, candidate, self.fractal_left, self.fractal_right):
                    last_swing_high_price = df["High"].iloc[candidate]
                    last_swing_high_idx   = candidate
                if ind.is_fractal_low(df, candidate, self.fractal_left, self.fractal_right):
                    last_swing_low_price  = df["Low"].iloc[candidate]
                    last_swing_low_idx    = candidate

            # ── CHOCH detection ───────────────────────────────────────────────
            choch_detected = False

            # Bullish CHOCH
            if (position == 0 and not choch_detected
                    and last_swing_high_price is not None
                    and last_swing_high_idx >= 0
                    and (self.choch_back_bars == 0
                         or (i - last_swing_high_idx) <= self.choch_back_bars)):
                    
                bp = df["Close"].iloc[center] if self.use_close_for_choch else df["High"].iloc[center]
                if bp > last_swing_high_price:
                    rs        = max(0, range_of_check) if last_swing_low_idx >= 0 else 0
                    lowest_low = df["Low"].iloc[rs:center].min()
                    active_setup = {
                        "direction":     "bullish",
                        "highest_price": df["High"].iloc[center],
                        "lowest_price":  lowest_low,
                        "setup_bar":     i,
                        "fractal_price": last_swing_high_price,
                        "fractal_idx":   last_swing_high_idx,
                    }
                    choch_detected = True

            # Bearish CHOCH
            if (position == 0 and not choch_detected
                    and last_swing_low_price is not None
                    and last_swing_low_idx >= 0
                    and (self.choch_back_bars == 0
                         or (i - last_swing_low_idx) <= self.choch_back_bars)):
                bp = df["Close"].iloc[i] if self.use_close_for_choch else df["Low"].iloc[i]
                if bp < last_swing_low_price:
                    rs           = max(0, range_of_check) if last_swing_high_idx >= 0 else 0
                    highest_high = df["High"].iloc[rs:center].max()
                    active_setup = {
                        "direction":     "bearish",
                        "lowest_price":  df["Low"].iloc[i],
                        "highest_price": highest_high,
                        "setup_bar":     i,
                        "fractal_price": last_swing_low_price,
                        "fractal_idx":   last_swing_low_idx,
                    }
                    choch_detected = True

            # ── setup invalidation ────────────────────────────────────────────
            if active_setup and position == 0 and not choch_detected:
                d = active_setup["direction"]
                if d == "bullish" and df["Close"].iloc[i] < active_setup["lowest_price"]:
                    self._record_invalidation(active_setup, df, i, trade_counter)
                    trade_counter += 1
                    active_setup   = None
                elif d == "bearish" and df["Close"].iloc[i] > active_setup["highest_price"]:
                    self._record_invalidation(active_setup, df, i, trade_counter)
                    trade_counter += 1
                    active_setup  = None

            # ── entry ─────────────────────────────────────────────────────────
            if active_setup and position == 0 and i > active_setup["setup_bar"]:
                if (i - active_setup["setup_bar"]) > self.max_bars_to_entry:   # new param
                        active_setup = None
                else: 
                    direction     = active_setup["direction"]
                    lowest_price  = active_setup["lowest_price"]
                    highest_price = active_setup["highest_price"]

                    raw_entry_level   = ind.get_fib_price(lowest_price, highest_price,
                                                        self.entry_fib_level, direction)
                    entry_level_price = raw_entry_level
                    vp_poc = vp_vah = vp_val = None
                    entryFibVsVP = None

                    # Volume profile blend
                    if self.use_volume_profile:
                        vp_poc, vp_vah, vp_val = ind.calculate_volume_profile(
                            df,
                            start_idx        = active_setup["fractal_idx"],
                            end_idx          = active_setup["setup_bar"],
                            num_bins         = self.vp_num_bins,
                            value_area_pct   = self.vp_value_area_pct,
                            min_segment_bars = self.minimum_volume_segement,
                        )
                        if vp_val is not None and vp_vah is not None:
                            entryFibVsVP = entry_level_price
                            vp_ref = vp_val if direction == "bullish" else vp_vah
                            entry_level_price = (entry_level_price * (1 - self.vp_confluence_weight)
                                                + vp_ref * self.vp_confluence_weight)

                    # Candle touch check
                    if direction == 'bullish':
                        candle_touches = (df['Low'].iloc[i] <= entry_level_price + self.entry_tolerance and
                                        df['High'].iloc[i] >= entry_level_price - self.entry_tolerance)
                    else:
                        candle_touches = (df['High'].iloc[i] >= entry_level_price - self.entry_tolerance and
                                        df['Low'].iloc[i] <= entry_level_price + self.entry_tolerance)

                    if (candle_touches
                            and ind.is_rejection_candle(df, i, direction, self.require_rejection,
                                                        self.pinbar_wick_ratio, self.pinbar_body_ratio)):

                        o = df["Open"].iloc[i]
                        if direction == "bullish":
                            entry_price = min(entry_level_price, o)   # gap-down → fill at open
                        else:
                            entry_price = max(entry_level_price, o) 
                        position    = 1 if direction == "bullish" else -1

                        if self.use_atr_sl_tp:
                            atr_val = df["ATR"].iloc[i]
                            if pd.isna(atr_val):
                                position = 0
                                continue
                            sl_price = (entry_price - atr_val * self.atr_sl_mult if direction == "bullish"
                                        else entry_price + atr_val * self.atr_sl_mult)
                            tp_price = (entry_price + atr_val * self.atr_tp_mult if direction == "bullish"
                                        else entry_price - atr_val * self.atr_tp_mult)
                        else:
                            sl_price = ind.get_fib_price(lowest_price, highest_price,
                                                        self.sl_fib_level, direction)
                            tp_price = ind.get_fib_price(lowest_price, highest_price,
                                                        self.tp_fib_level, direction)


                        trade_counter += 1
                        self.trades.append({
                            # identity
                            "trade_id":                  f"T{trade_counter:05d}",
                            "side":                      "long" if direction == "bullish" else "short",
                            # timestamps
                            "entry_time":                df["Datetime"].iloc[i] if "Datetime" in df.columns else i,
                            "exit_time":                 None,
                            # prices
                            "entry_price":               entry_price,
                            "exit_price":                None,
                            "sl_price":                  sl_price,
                            "tp_price":                  tp_price,
                            "entry_fib_price":           raw_entry_level,
                            "entry_fib_vp_blended":      entry_level_price if self.use_volume_profile else None,
                            "fractal_price":             active_setup["fractal_price"],
                            "highest_price":             highest_price,
                            "lowest_price":              lowest_price,
                            # setup info
                            "setup_bar":                 active_setup["setup_bar"],
                            "fractal_idx":               active_setup["fractal_idx"],
                            "entry_bar":                 i,
                            "exit_bar":                  None,
                            "bars_to_entry_from_choch":  i - active_setup["setup_bar"],
                            # volume profile
                            "vp_poc": vp_poc, "vp_vah": vp_vah, "vp_val": vp_val,
                            "entry_fib_vs_vp": entryFibVsVP,
                            "exit_reason": None,
                        })
            # ── trade management ──────────────────────────────────────────────
            if position != 0 and i > self.trades[-1]["entry_bar"]:
                hit_sl = hit_tp = hit_timeout = False
                direction = self.trades[-1]["side"]

                if position == 1:
                    if   df["Low"].iloc[i]  <= sl_price: 
                        hit_sl = True; 
                        exit_price_final = sl_price
                    elif df["High"].iloc[i] >= tp_price: 
                        hit_tp = True; 
                        exit_price_final = tp_price
                else:
                    if   df["High"].iloc[i] >= sl_price: 
                        hit_sl = True; 
                        exit_price_final = sl_price
                    elif df["Low"].iloc[i]  <= tp_price: 
                        hit_tp = True; 
                        exit_price_final = tp_price



                # ── time-stop ─────────────────────────────────────────────────
                # If neither SL nor TP hit within N bars of entry, force exit
                # at this bar's close.
                if (not hit_sl and not hit_tp and self.max_bars_in_trade > 0
                     and (i - self.trades[-1]["entry_bar"]) >= self.max_bars_in_trade):
                    hit_timeout      = True
                    exit_price_final = df["Close"].iloc[i]

                if hit_sl or hit_tp or hit_timeout:
                    self._close_trade(
                        i, exit_price_final,
                        "TP" if hit_tp else ("SL" if hit_sl else "timeout"),
                        df,
                    )
                    position     = 0
                    active_setup = None

        # ── open trade at end of data ─────────────────────────────────────────
        if position != 0 and self.trades:
            last_i = len(df) - 1
            self._close_trade(
                last_i, df["Close"].iloc[last_i], "manual_exit", df,
            )

        return self.trades
    # ── trade closing helper ──────────────────────────────────────────────────

    def _close_trade(
        self,
        i: int, exit_price_final: float, 
        exit_reason: str, df: pd.DataFrame,
    ) -> float:
        """
        Finalise the open trade record,
        """
        trade      = self.trades[-1]
        trade.update({
            "exit_time":           df["Datetime"].iloc[i] if "Datetime" in df.columns else i,
            "exit_price":          exit_price_final,
            "exit_bar":            i,
            "exit_reason":         exit_reason,

        })


    def _record_invalidation(
        self, active_setup: Dict, df: pd.DataFrame,
        i: int, trade_counter: int,
    ) -> None:
        self.trades.append({
            "trade_id":    f"T{trade_counter + 1:05d}",
            "side":        "long" if active_setup["direction"] == "bullish" else "short",
            "entry_time":  None,
            "exit_time":   df["Datetime"].iloc[i] if "Datetime" in df.columns else i,
            "entry_price": None, "exit_price": None, "sl_price": None, "tp_price": None,
            "entry_fib_price": None, "entry_fib_vp_blended": None,
            "fractal_price":  active_setup.get("fractal_price"),
            "highest_price":  active_setup.get("highest_price"),
            "lowest_price":   active_setup.get("lowest_price"),
            "setup_bar":      active_setup["setup_bar"],
            "fractal_idx":    active_setup.get("fractal_idx"),
            "entry_bar": None, "exit_bar": i,
            "bars_to_entry_from_choch": None,
            "vp_poc": None, "vp_vah": None, "vp_val": None, "entry_fib_vs_vp": None,
            "exit_reason": "invalidation"
        })



