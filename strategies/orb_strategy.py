"""
orb_strategy.py — 15-minute Opening Range Breakout (New York session).

Pipeline-compatible: same `(run_id=, **params).backtest(df) -> (trades_df,
details)` shape and slim ledger as the other strategies (CFDCostModel →
CFDAccountSimulator → PerformanceAnalytics → ResultStore → dashboard/tv_chart).

The play
────────
• OPENING RANGE — at the session open (default 09:30 America/New_York) take the
  first `range_minutes` (default 15) of bars; their high/low are the OR high/low.
• BREAKOUT — watched on the LOWER-timeframe candles you feed (5-minute or
  1-minute bars): after the range closes, the FIRST such candle that closes
  strictly outside the range is the signal — close above OR high → long, below
  OR low → short. The breakout candle is the input bar size, so feed 5m/1m data;
  if your data is finer, set `breakout_resample` (e.g. "5min") to confirm
  breakouts on a coarser candle. (One shot per day: a breakout rejected by a
  filter ends the day's attempt.)
• ENTRY at that candle's close (confirmed on close → no lookahead).

Trade management
────────────────
• SL  (`sl_mode`): "structural" → long: OR low, short: OR high (the spec default);
  "atr" → entry ∓ atr_sl_mult·ATR; "fib" → entry ∓ fib_sl·OR_range.
• TP  (`tp_mode`): "rr" → entry ± rr_ratio·risk (1:1.5 / 1:2, default 1.5);
  "atr" → entry ± atr_tp_mult·ATR; "fib" → entry ± fib_tp·OR_range;
  "structural" → previous-day high (long) / low (short), else falls back to rr.
• Optional `close_at_session_end` (default True) flattens at `session_end`
  (default 16:00) — ORB is intraday.

Gating
──────
• `volume_filter`: "none" | "initial" | "relative" | "session_relative".
    initial          — breakout volume vs the opening range's own mean volume.
    relative         — breakout volume vs a rolling RVOL baseline (`rvol_lookback`).
    session_relative — breakout volume vs the SAME time-of-day over the prior
                       `session_lookback` sessions (NY compared only with NY).
  A breakout failing the gate is ignored (recorded as a no-entry row).
• `use_bias` — daily-resampled Hull slope (the Hull-suite rule) from the PRIOR
  completed daily bar gates direction: longs only in an up-bias, shorts in a
  down-bias. (Undefined early bias does not block.)

Key levels recorded on every trade: previous-day high/low, OR high/low, OR range,
breakout volume + baseline, bias, SL/TP, risk.

Returns `(trades_df, details)`:
    trades_df : trade_id, side, setup_time, entry_time, entry_price,
                exit_time, exit_price, exit_reason
    details   : {"trades" (full per-trade frame), "or_levels" (per-day OR/PDH/
                 PDL/bias), "metadata"}
"""
from __future__ import annotations

from datetime import time as dtime
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd


class OpeningRangeBreakoutStrategy:
    # ── exit reasons ─────────────────────────────────────────────────────────
    EXIT_TP       = "TP"
    EXIT_SL       = "SL"
    EXIT_SESSION  = "session_close"
    EXIT_MANUAL   = "manual_exit"
    # no-entry (filtered) reasons
    FILT_VOLUME   = "vol_filtered"
    FILT_BIAS     = "bias_filtered"

    TRADE_COLUMNS: List[str] = [
        "trade_id", "side", "setup_time", "entry_time", "entry_price",
        "exit_time", "exit_price", "exit_reason",
    ]

    def __init__(
        self,
        run_id:        str   = "default_run",
        asset_class:   str   = "C",
        # ── session / timezone ───────────────────────────────────────────────
        session_tz:    str   = "America/New_York",
        data_tz:       Optional[str] = None,   # localize naive stamps as this, then convert; None = already session-local
        open_time:     str   = "09:30",
        range_minutes: int   = 15,
        breakout_resample: Optional[str] = None,   # e.g. "5min"/"1min": detect breakouts on this candle (down-samples finer data)
        session_end:   str   = "16:00",
        close_at_session_end: bool = True,
        # ── stop loss ────────────────────────────────────────────────────────
        sl_mode:       str   = "structural",   # "structural" | "atr" | "fib"
        atr_sl_mult:   float = 1.0,
        fib_sl:        float = 1.0,            # SL = entry ∓ fib_sl * OR_range
        # ── take profit ──────────────────────────────────────────────────────
        tp_mode:       str   = "rr",           # "rr" | "atr" | "fib" | "structural"
        rr_ratio:      float = 1.5,            # 1:1.5 (or 2.0 for 1:2)
        atr_tp_mult:   float = 2.0,
        fib_tp:        float = 1.618,          # TP = entry ± fib_tp * OR_range
        atr_length:    int   = 14,
        # ── volume filter ────────────────────────────────────────────────────
        volume_filter: str   = "none",         # "none"|"initial"|"relative"|"session_relative"
        vol_mult:      float = 1.0,
        rvol_lookback: int   = 20,
        session_lookback: int = 14,
        # ── market-bias filter (daily Hull) ──────────────────────────────────
        use_bias:      bool  = False,
        bias_hull_length:    int = 55,
        bias_hull_variation: str = "hma",      # "hma" | "thma" | "ehma"
        bias_source:   str   = "close",        # daily open/high/low/close/hl2/hlc3/ohlc4
        # ── label ────────────────────────────────────────────────────────────
        timeframe:     str   = "",
    ) -> None:
        self.run_id        = run_id
        self.asset_class   = asset_class
        self.session_tz    = session_tz
        self.data_tz       = data_tz
        self.open_time     = self._parse_time(open_time)
        self.range_minutes = max(int(range_minutes), 1)
        self.breakout_resample = breakout_resample
        self.session_end   = self._parse_time(session_end)
        self.close_at_session_end = close_at_session_end
        self.sl_mode       = sl_mode.lower()
        self.atr_sl_mult   = atr_sl_mult
        self.fib_sl        = fib_sl
        self.tp_mode       = tp_mode.lower()
        self.rr_ratio      = rr_ratio
        self.atr_tp_mult   = atr_tp_mult
        self.fib_tp        = fib_tp
        self.atr_length    = atr_length
        self.volume_filter = volume_filter.lower()
        self.vol_mult      = vol_mult
        self.rvol_lookback = max(int(rvol_lookback), 1)
        self.session_lookback = max(int(session_lookback), 1)
        self.use_bias      = use_bias
        self.bias_hull_length    = max(int(bias_hull_length), 2)
        self.bias_hull_variation = bias_hull_variation.lower()
        self.bias_source   = bias_source.lower()
        self.timeframe     = timeframe
        self._volume_missing = False

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
        self.trades:   List[Dict] = []
        self.position: int = 0
        self.trade_counter: int = 0

    def _run(self, df: pd.DataFrame) -> None:
        d = self._prepare(df)
        self._df = d
        self._reset_state()
        n = len(d)

        O, H, L, C = (d["Open"].to_numpy(float), d["High"].to_numpy(float),
                      d["Low"].to_numpy(float), d["Close"].to_numpy(float))
        self._C, self._H, self._L = C, H, L
        tod   = d["_tod"].to_numpy()                 # minutes since midnight (NY)
        dayid = d["_dayid"].to_numpy()
        or_hi = d["_or_high"].to_numpy(float)
        or_lo = d["_or_low"].to_numpy(float)
        self._or_high, self._or_low = or_hi, or_lo
        self._or_vol  = d["_or_vol"].to_numpy(float)  if "_or_vol"  in d else None
        self._pdh     = d["_pdh"].to_numpy(float)
        self._pdl     = d["_pdl"].to_numpy(float)
        self._atr     = d["_atr"].to_numpy(float)
        self._bias    = d["_bias"].to_numpy(float)
        self._V       = d["_V"].to_numpy(float)       if "_V"       in d else None
        self._rvol_ma = d["_rvol_ma"].to_numpy(float) if "_rvol_ma" in d else None
        self._sess_base = d["_sess_base"].to_numpy(float) if "_sess_base" in d else None

        open_min   = self.open_time.hour * 60 + self.open_time.minute
        or_end_min = open_min + self.range_minutes
        send_min   = self.session_end.hour * 60 + self.session_end.minute

        traded_today = False
        for i in range(n):
            new_day = (i == 0) or (dayid[i] != dayid[i - 1])
            if new_day:
                if i > 0 and self.position != 0 and self.close_at_session_end:
                    self._close_trade(i - 1, C[i - 1], self.EXIT_SESSION)
                traded_today = False

            t = tod[i]

            # 1) session-end flat
            if self.position != 0 and self.close_at_session_end and t >= send_min:
                self._close_trade(i, C[i], self.EXIT_SESSION)

            # 2) manage the open trade (SL/TP), never on the entry bar
            if self.position != 0 and i > self.trades[-1]["entry_bar"]:
                hit = self._check_exit(i)
                if hit is not None:
                    self._close_trade(i, hit[0], hit[1])

            # 3) breakout entry — first close outside the range, one shot per day
            if self.position == 0 and not traded_today and np.isfinite(or_hi[i]) \
                    and np.isfinite(or_lo[i]) and or_end_min <= t < send_min:
                c = C[i]
                direction = "long" if c > or_hi[i] else ("short" if c < or_lo[i] else None)
                if direction is not None:
                    traded_today = True
                    vol_ok, vinfo = self._vol_ok(i)
                    if not self._bias_ok(i, direction):
                        self._record_filtered(i, direction, self.FILT_BIAS, vinfo)
                    elif not vol_ok:
                        self._record_filtered(i, direction, self.FILT_VOLUME, vinfo)
                    else:
                        self._open_trade(i, direction, vinfo)

        self._finalize_open_trade()

    # ─────────────────────────────────────────────────────────────────────────
    # Preparation: tz, sessions, OR, PDH/PDL, ATR, volume baselines, bias
    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _parse_time(s: str) -> dtime:
        hh, mm = str(s).split(":")[:2]
        return dtime(int(hh), int(mm))

    @staticmethod
    def _canonicalize(df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()
        low = {c.lower(): c for c in out.columns}
        ren = {}
        for canon in ("Open", "High", "Low", "Close"):
            if canon not in out.columns and canon.lower() in low:
                ren[low[canon.lower()]] = canon
        if "Volume" not in out.columns:
            for alt in ("volume", "vol", "tick_volume", "tickvolume"):
                if alt in low:
                    ren[low[alt]] = "Volume"
                    break
        if "Datetime" not in out.columns:
            for alt in ("datetime", "date", "time", "timestamp"):
                if alt in low:
                    ren[low[alt]] = "Datetime"
                    break
        return out.rename(columns=ren) if ren else out

    def _volume(self, df: pd.DataFrame) -> Optional[pd.Series]:
        return df["Volume"].astype(float) if "Volume" in df.columns else None

    @staticmethod
    def _resample(d: pd.DataFrame, freq: str) -> pd.DataFrame:
        """Down-sample to the breakout candle (e.g. '5min'); empty buckets dropped."""
        g = d.set_index("_ny")
        res = g.resample(freq, label="left", closed="left").agg(
            {"Open": "first", "High": "max", "Low": "min", "Close": "last"})
        if "Volume" in g.columns:
            res["Volume"] = g["Volume"].resample(freq, label="left", closed="left").sum()
        res = res[res["Close"].notna()].copy()
        res.index.name = "_ny"
        res = res.reset_index()
        res["Datetime"] = res["_ny"]
        return res

    def _ny(self, dt_series: pd.Series) -> pd.Series:
        t = pd.to_datetime(dt_series, errors="coerce")
        if getattr(t.dt, "tz", None) is not None:
            return t.dt.tz_convert(self.session_tz)
        if self.data_tz:
            return (t.dt.tz_localize(self.data_tz, nonexistent="shift_forward", ambiguous="NaT")
                     .dt.tz_convert(self.session_tz))
        return t                                       # assume already session-local (naive)

    @staticmethod
    def _atr_series(df: pd.DataFrame, length: int) -> pd.Series:
        h, l, c = df["High"].astype(float), df["Low"].astype(float), df["Close"].astype(float)
        pc = c.shift(1)
        tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
        return tr.ewm(alpha=1.0 / max(int(length), 1), adjust=False).mean()

    def _hull_ma(self, src: pd.Series, length: int, variation: str) -> pd.Series:
        n = max(int(length), 2)
        def wma(s, L):
            L = max(int(L), 1); w = np.arange(1, L + 1)
            return s.rolling(L).apply(lambda x: float(np.dot(x, w) / w.sum()), raw=True)
        def ema(s, L):
            return s.ewm(span=max(int(L), 1), adjust=False).mean()
        half = max(n // 2, 1)
        sq   = max(int(np.floor(np.sqrt(n) + 0.5)), 1)     # real sqrt; never complex
        if variation == "ehma":
            return ema(2 * ema(src, half) - ema(src, n), sq)
        if variation == "thma":
            m = half
            return wma(3 * wma(src, max(m // 3, 1)) - wma(src, max(m // 2, 1)) - wma(src, m), m)
        return wma(2 * wma(src, half) - wma(src, n), sq)   # hma

    def _prepare(self, df: pd.DataFrame) -> pd.DataFrame:
        d = self._canonicalize(df)
        if "Datetime" not in d.columns:
            raise ValueError("ORB strategy needs a Datetime column to anchor the NY session.")
        ny = self._ny(d["Datetime"])
        d = d.assign(_ny=ny).sort_values("_ny").reset_index(drop=True)
        if self.breakout_resample:                     # detect breakouts on a coarser candle
            d = self._resample(d, self.breakout_resample)
        ny = d["_ny"]

        d["_date"]  = ny.dt.date
        d["_tod"]   = (ny.dt.hour * 60 + ny.dt.minute).astype("Int64")
        d["_dayid"] = pd.factorize(d["_date"])[0]

        vol = self._volume(d)
        has_vol = vol is not None
        if has_vol:
            d["_V"] = vol.to_numpy()

        # daily aggregates (for PDH/PDL and bias)
        agg = {"dh": ("High", "max"), "dl": ("Low", "min"),
               "do": ("Open", "first"), "dc": ("Close", "last")}
        daily = d.groupby("_date").agg(**agg)
        daily["pdh"] = daily["dh"].shift(1)
        daily["pdl"] = daily["dl"].shift(1)
        d["_pdh"] = d["_date"].map(daily["pdh"]).to_numpy()
        d["_pdl"] = d["_date"].map(daily["pdl"]).to_numpy()

        # opening range per day
        open_min   = self.open_time.hour * 60 + self.open_time.minute
        or_end_min = open_min + self.range_minutes
        tod_min = d["_tod"].astype(float)
        in_or = (tod_min >= open_min) & (tod_min < or_end_min)
        or_agg = {"orh": ("High", "max"), "orl": ("Low", "min")}
        if has_vol:
            or_agg["orv"] = ("_V", "mean")
        org = d[in_or].groupby("_date").agg(**or_agg)
        d["_or_high"] = d["_date"].map(org["orh"]).to_numpy()
        d["_or_low"]  = d["_date"].map(org["orl"]).to_numpy()
        if has_vol:
            d["_or_vol"] = d["_date"].map(org["orv"]).to_numpy()

        # ATR
        d["_atr"] = self._atr_series(d, self.atr_length).to_numpy()

        # volume baselines (causal)
        if has_vol:
            d["_rvol_ma"] = d["_V"].shift(1).rolling(self.rvol_lookback, min_periods=1).mean().to_numpy()
            d["_sess_base"] = (d.groupby("_tod")["_V"]
                               .transform(lambda s: s.shift(1)
                                          .rolling(self.session_lookback, min_periods=1).mean())
                               .to_numpy())
        elif self.volume_filter != "none":
            self._volume_missing = True

        # daily Hull bias (prior completed daily bar → no lookahead)
        if self.use_bias:
            do, dh, dl, dc = daily["do"], daily["dh"], daily["dl"], daily["dc"]
            src = {"open": do, "high": dh, "low": dl, "close": dc,
                   "hl2": (dh + dl) / 2, "hlc3": (dh + dl + dc) / 3,
                   "ohlc4": (do + dh + dl + dc) / 4}.get(self.bias_source, dc)
            hull = self._hull_ma(src, self.bias_hull_length, self.bias_hull_variation)
            diff = hull - hull.shift(2)
            bias_daily = pd.Series(np.where(diff > 0, 1.0, np.where(diff < 0, -1.0, np.nan)),
                                   index=hull.index).shift(1)
            d["_bias"] = d["_date"].map(bias_daily).to_numpy()
        else:
            d["_bias"] = np.nan

        return d

    # ─────────────────────────────────────────────────────────────────────────
    # Filters
    # ─────────────────────────────────────────────────────────────────────────

    def _vol_ok(self, i: int) -> Tuple[bool, Dict]:
        info = {"breakout_volume": None, "volume_baseline": None, "vol_ratio": None}
        if self.volume_filter == "none" or self._V is None:
            return True, info
        v = float(self._V[i]) if np.isfinite(self._V[i]) else None
        if self.volume_filter == "initial":
            base = self._or_vol[i] if self._or_vol is not None else np.nan
        elif self.volume_filter == "relative":
            base = self._rvol_ma[i] if self._rvol_ma is not None else np.nan
        else:                                            # session_relative
            base = self._sess_base[i] if self._sess_base is not None else np.nan
        base = float(base) if np.isfinite(base) else None
        info["breakout_volume"], info["volume_baseline"] = v, base
        if v is None or base is None or base <= 0:
            return True, info                            # can't evaluate → don't block
        info["vol_ratio"] = v / base
        return (v / base >= self.vol_mult), info

    def _bias_ok(self, i: int, direction: str) -> bool:
        if not self.use_bias:
            return True
        b = self._bias[i]
        if not np.isfinite(b):
            return True                                  # bias undefined early → allow
        return b > 0 if direction == "long" else b < 0

    # ─────────────────────────────────────────────────────────────────────────
    # SL / TP
    # ─────────────────────────────────────────────────────────────────────────

    def _levels(self, i: int, direction: str, entry: float) -> Tuple[float, float, float]:
        long = direction == "long"
        or_hi, or_lo = self._or_high[i], self._or_low[i]
        or_range = max(or_hi - or_lo, 0.0)
        atr = self._atr[i] if np.isfinite(self._atr[i]) else None

        # stop
        if self.sl_mode == "atr" and atr is not None:
            sl = entry - atr * self.atr_sl_mult if long else entry + atr * self.atr_sl_mult
        elif self.sl_mode == "fib" and or_range > 0:
            sl = entry - self.fib_sl * or_range if long else entry + self.fib_sl * or_range
        else:                                            # structural (default / fallback)
            sl = or_lo if long else or_hi
        risk = abs(entry - sl)
        if risk <= 0:                                    # degenerate → structural
            sl = or_lo if long else or_hi
            risk = abs(entry - sl)

        # target
        if self.tp_mode == "atr" and atr is not None:
            tp = entry + atr * self.atr_tp_mult if long else entry - atr * self.atr_tp_mult
        elif self.tp_mode == "fib" and or_range > 0:
            tp = entry + self.fib_tp * or_range if long else entry - self.fib_tp * or_range
        elif self.tp_mode == "structural":
            pdh, pdl = self._pdh[i], self._pdl[i]
            if long:
                tp = pdh if (np.isfinite(pdh) and pdh > entry) else entry + self.rr_ratio * risk
            else:
                tp = pdl if (np.isfinite(pdl) and pdl < entry) else entry - self.rr_ratio * risk
        else:                                            # rr (default)
            tp = entry + self.rr_ratio * risk if long else entry - self.rr_ratio * risk
        return float(sl), float(tp), float(risk)

    def _check_exit(self, i: int) -> Optional[Tuple[float, str]]:
        t = self.trades[-1]
        sl, tp = t["sl_price"], t["tp_price"]
        if self.position == 1:                           # long — SL first on conflict
            if self._L[i] <= sl:
                return sl, self.EXIT_SL
            if self._H[i] >= tp:
                return tp, self.EXIT_TP
        else:                                            # short
            if self._H[i] >= sl:
                return sl, self.EXIT_SL
            if self._L[i] <= tp:
                return tp, self.EXIT_TP
        return None

    # ─────────────────────────────────────────────────────────────────────────
    # Trade records
    # ─────────────────────────────────────────────────────────────────────────

    def _key_levels(self, i: int) -> Dict:
        f = lambda x: float(x) if np.isfinite(x) else None
        return {
            "previous_day_high": f(self._pdh[i]), "previous_day_low": f(self._pdl[i]),
            "or_high": f(self._or_high[i]), "or_low": f(self._or_low[i]),
            "or_range": (f(self._or_high[i] - self._or_low[i])
                         if np.isfinite(self._or_high[i]) and np.isfinite(self._or_low[i]) else None),
            "bias": f(self._bias[i]),
            "atr_at_entry": f(self._atr[i]),
        }

    def _open_trade(self, i: int, direction: str, vinfo: Dict) -> None:
        entry = self._C[i]
        sl, tp, risk = self._levels(i, direction, entry)
        self.position = 1 if direction == "long" else -1
        rec = {
            "trade_id":   self._next_trade_id(),
            "side":       direction,
            "setup_time": self._bar_time(i),
            "entry_time": self._bar_time(i),
            "exit_time":  None,
            "entry_price": entry,
            "exit_price":  None,
            "sl_price":    sl,
            "tp_price":    tp,
            "risk":        risk,
            "rr_ratio":    self.rr_ratio,
            "sl_mode":     self.sl_mode,
            "tp_mode":     self.tp_mode,
            "volume_filter": self.volume_filter,
            "use_bias":    self.use_bias,
            "setup_bar":   i,
            "entry_bar":   i,
            "exit_bar":    None,
            "bars_held":   None,
            "exit_reason": None,
        }
        rec.update(self._key_levels(i))
        rec.update(vinfo)
        self.trades.append(rec)

    def _record_filtered(self, i: int, direction: str, reason: str, vinfo: Dict) -> None:
        rec = {
            "trade_id":   self._next_trade_id(),
            "side":       direction,
            "setup_time": self._bar_time(i),
            "entry_time": None,
            "exit_time":  self._bar_time(i),
            "entry_price": None,
            "exit_price":  None,
            "sl_price":    None,
            "tp_price":    None,
            "risk":        None,
            "rr_ratio":    self.rr_ratio,
            "sl_mode":     self.sl_mode,
            "tp_mode":     self.tp_mode,
            "volume_filter": self.volume_filter,
            "use_bias":    self.use_bias,
            "setup_bar":   i,
            "entry_bar":   None,
            "exit_bar":    i,
            "bars_held":   None,
            "exit_reason": reason,
        }
        rec.update(self._key_levels(i))
        rec.update(vinfo)
        self.trades.append(rec)

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
        return self._df["Datetime"].iloc[idx] if "Datetime" in self._df.columns else idx

    # ─────────────────────────────────────────────────────────────────────────
    # Output builders
    # ─────────────────────────────────────────────────────────────────────────

    def _build_trades_df(self) -> pd.DataFrame:
        if not self.trades:
            return pd.DataFrame(columns=self.TRADE_COLUMNS)
        return pd.DataFrame(self.trades)[self.TRADE_COLUMNS].copy()

    def _build_details(self) -> Dict:
        d = self._df
        cols = ["_date", "_or_high", "_or_low", "_pdh", "_pdl", "_bias"]
        ol = (d[cols].drop_duplicates("_date").reset_index(drop=True)
              .rename(columns={"_date": "date", "_or_high": "or_high", "_or_low": "or_low",
                               "_pdh": "previous_day_high", "_pdl": "previous_day_low",
                               "_bias": "bias"}))
        return {
            "trades":    pd.DataFrame(self.trades),
            "or_levels": ol,
            "metadata":  self._build_metadata(),
        }

    def _build_metadata(self) -> Dict:
        return {
            "run_id":   self.run_id,
            "strategy": "ORB-15m",
            "asset_class": self.asset_class,
            "timeframe": self.timeframe,
            "session_tz": self.session_tz,
            "open_time": f"{self.open_time:%H:%M}",
            "range_minutes": self.range_minutes,
            "breakout_resample": self.breakout_resample,
            "session_end": f"{self.session_end:%H:%M}",
            "close_at_session_end": self.close_at_session_end,
            "sl_mode": self.sl_mode, "atr_sl_mult": self.atr_sl_mult, "fib_sl": self.fib_sl,
            "tp_mode": self.tp_mode, "rr_ratio": self.rr_ratio,
            "atr_tp_mult": self.atr_tp_mult, "fib_tp": self.fib_tp, "atr_length": self.atr_length,
            "volume_filter": self.volume_filter, "vol_mult": self.vol_mult,
            "rvol_lookback": self.rvol_lookback, "session_lookback": self.session_lookback,
            "use_bias": self.use_bias, "bias_hull_length": self.bias_hull_length,
            "bias_hull_variation": self.bias_hull_variation, "bias_source": self.bias_source,
            "volume_missing": self._volume_missing,
        }