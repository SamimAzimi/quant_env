"""session_sigma_strategy.py — analyze-segment → trigger-segment σ plays.

Pipeline-compatible: same ``(run_id=, **params).backtest(df) -> (trades_df,
details)`` shape and ledger as the other strategies (CFDCostModel →
CFDAccountSimulator → PerformanceAnalytics → ResultStore → dashboard).

The play
────────
Each trading day is cut into the five-part session partition (DST-correct,
via libs/market_sessions.py local wall-clock definitions):

    Tokyo(solo) → Tokyo∩London → London(solo) → London∩NY → NewYork(solo)

Every consecutive pair is an (ANALYZE, TRIGGER) transition — four per day.

ANALYZE — over the analyze segment's bar closes compute the price mean μ and
std σ, and mark the levels μ ± kσ for k = 0.5, 1.0, …, 3.0.

TRIGGER — two setups, judged by where the analyze segment CLOSED:

1. MEAN-CROSS (analyze close within ±0.5σ of μ):
   • close above μ → watch the trigger segment's RUNNING MEAN of closes;
     the first bar it drops below μ → SHORT 3 lots at that bar's close.
   • close below μ → mirror: running mean rises above μ → LONG 3 lots.
   Initial SL for every lot: 0.5σ against the trade. Scale-out targets:
   lot 1 at the 1st σ, lot 2 at the 2nd σ, lot 3 at the 3rd σ (in the trade
   direction from μ; multiples configurable via ``tp_ks``). When lot 2's
   target fills, the remaining lot's stop moves to entry (breakeven).

2. EXTENSION FADE (analyze close already beyond ±0.5σ, in level k):
   • above → SHORT limit one level further at μ + (k+0.5)σ;
   • below → LONG limit at μ − (k+0.5)σ.
   SL 0.5σ beyond the entry level; TP = μ (the analyze segment's mean) for
   all 3 lots. Unfilled orders are recorded as no-entry rows. Closes beyond
   the top marked level (k ≥ 3) are skipped — there is no level above.

Any lot still open when the trigger segment ends is flattened at its last
close (``segment_close``). Exits are conservative: SL checked before TP on
the same bar, and never on the entry bar itself. Everything is causal — the
analyze stats are fully known before the trigger segment starts.

Returns ``(trades_df, details)``; ``details["trades"]`` is the full per-lot
ledger (with ``sl_price``) the account simulator needs, and
``details["segments"]`` records each transition's μ/σ/deviation/setup.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from libs.market_sessions import DEFAULT_SESSIONS as _LIB_SESSIONS, local_to_utc

_SESS = {s.name: s for s in _LIB_SESSIONS}

# (analyze, trigger) chain — the five-part day partition, in day order.
SEGMENT_CHAIN = ["tokyo_solo", "tokyo_london", "london_solo", "london_ny", "ny_solo"]
SEGMENT_LABEL = {
    "tokyo_solo": "Tokyo (solo)", "tokyo_london": "Tokyo ∩ London",
    "london_solo": "London (solo)", "london_ny": "London ∩ NY",
    "ny_solo": "New York (solo)",
}


def _session_utc(name: str, day: date) -> Tuple[pd.Timestamp, pd.Timestamp]:
    s = _SESS[name]
    lo = local_to_utc(datetime.combine(day, s.open), s.tz)
    hi = local_to_utc(datetime.combine(day, s.close), s.tz)
    return lo.tz_localize(None), hi.tz_localize(None)


def segment_windows(day: date) -> Dict[str, Tuple[pd.Timestamp, pd.Timestamp]]:
    """The five-part partition of one trading day, naive-UTC, DST-correct."""
    tk_o, tk_c = _session_utc("Tokyo", day)
    ln_o, ln_c = _session_utc("London", day)
    ny_o, ny_c = _session_utc("NewYork", day)
    return {
        "tokyo_solo":   (tk_o, ln_o),
        "tokyo_london": (ln_o, tk_c),
        "london_solo":  (tk_c, ny_o),
        "london_ny":    (ny_o, ln_c),
        "ny_solo":      (ln_c, ny_c),
    }


class SessionSigmaStrategy:
    # exit / no-entry reasons
    EXIT_TP      = "TP"
    EXIT_SL      = "SL"
    EXIT_BE      = "breakeven_stop"
    EXIT_SEGMENT = "segment_close"
    NO_FILL      = "no_fill"

    TRADE_COLUMNS: List[str] = [
        "trade_id", "side", "setup_time", "entry_time", "entry_price",
        "exit_time", "exit_price", "exit_reason",
    ]

    def __init__(
        self,
        run_id:      str = "default_run",
        asset_class: str = "FX",
        timeframe:   str = "",
        # levels: μ ± kσ marked from level_step to level_max
        level_step:  float = 0.5,
        level_max:   float = 3.0,
        # mean-cross setup
        tp_ks:       tuple = (1.0, 2.0, 3.0),   # scale-out σ-multiples (3 lots)
        sl_k:        float = 0.5,               # initial stop, σ against the trade
        breakeven_after_lot: int = 2,           # move SL to entry once this lot TPs
        # fade setup
        fade_entry_step: float = 0.5,           # entry = one level further
        fade_sl_k:       float = 0.5,           # SL beyond the entry level
        # gating / hygiene
        enable_mean_cross: bool = True,
        enable_fade:       bool = True,
        min_bars_analyze:  int = 5,
        min_bars_trigger:  int = 3,
    ) -> None:
        self.run_id = run_id
        self.asset_class = asset_class
        self.timeframe = timeframe
        self.level_step = float(level_step)
        self.level_max = float(level_max)
        self.tp_ks = tuple(float(k) for k in tp_ks)
        self.sl_k = float(sl_k)
        self.breakeven_after_lot = int(breakeven_after_lot)
        self.fade_entry_step = float(fade_entry_step)
        self.fade_sl_k = float(fade_sl_k)
        self.enable_mean_cross = enable_mean_cross
        self.enable_fade = enable_fade
        self.min_bars_analyze = int(min_bars_analyze)
        self.min_bars_trigger = int(min_bars_trigger)

    # ── public API ───────────────────────────────────────────────────────────

    def backtest(self, df: pd.DataFrame) -> Tuple[pd.DataFrame, Dict]:
        self._run(df)
        return self._build_trades_df(), self._build_details()

    # ── orchestration ─────────────────────────────────────────────────────────

    def _run(self, df: pd.DataFrame) -> None:
        d = self._canonicalize(df)
        if "Datetime" not in d.columns:
            raise ValueError("SessionSigmaStrategy needs a Datetime column (UTC).")
        d = d.dropna(subset=["Datetime"]).sort_values("Datetime").reset_index(drop=True)
        self._df = d
        self.trades: List[Dict] = []
        self.segment_rows: List[Dict] = []
        self.trade_counter = 0

        t = pd.DatetimeIndex(d["Datetime"]).tz_localize(None) \
            if getattr(pd.DatetimeIndex(d["Datetime"]), "tz", None) is not None \
            else pd.DatetimeIndex(d["Datetime"])
        self._T = t.values.astype("datetime64[ns]")
        self._O = d["Open"].to_numpy(float)
        self._H = d["High"].to_numpy(float)
        self._L = d["Low"].to_numpy(float)
        self._C = d["Close"].to_numpy(float)

        for day in sorted(set(t.date)):
            wins = segment_windows(day)
            idx = {k: self._slice(*wins[k]) for k in SEGMENT_CHAIN}
            for a_key, b_key in zip(SEGMENT_CHAIN[:-1], SEGMENT_CHAIN[1:]):
                self._transition(day, a_key, b_key, idx[a_key], idx[b_key])

    def _slice(self, lo: pd.Timestamp, hi: pd.Timestamp) -> Tuple[int, int]:
        if lo >= hi:
            return 0, 0
        i0 = int(np.searchsorted(self._T, np.datetime64(lo), "left"))
        i1 = int(np.searchsorted(self._T, np.datetime64(hi), "left"))
        return i0, i1

    # ── one transition ─────────────────────────────────────────────────────────

    def _transition(self, day, a_key, b_key, a_rng, b_rng) -> None:
        a0, a1 = a_rng
        b0, b1 = b_rng
        if a1 - a0 < self.min_bars_analyze or b1 - b0 < self.min_bars_trigger:
            return
        closesA = self._C[a0:a1]
        mu = float(np.mean(closesA))
        sd = float(np.std(closesA, ddof=1))
        if not np.isfinite(sd) or sd <= 0:
            return
        cA = float(closesA[-1])
        dev = (cA - mu) / sd

        seg_row = {"day": day, "analyze": a_key, "trigger": b_key,
                   "mu": mu, "sigma": sd, "close_dev": dev, "setup": None}

        if abs(dev) < self.level_step:
            if self.enable_mean_cross:
                seg_row["setup"] = "mean_cross"
                self._mean_cross(day, a_key, b_key, b0, b1, mu, sd, dev)
        else:
            k = min(np.floor(abs(dev) / self.level_step) * self.level_step,
                    self.level_max)
            seg_row["k_level"] = float(k)
            if self.enable_fade and k < self.level_max:
                seg_row["setup"] = "fade"
                self._fade(day, a_key, b_key, b0, b1, mu, sd, dev, float(k))
        self.segment_rows.append(seg_row)

    # ── setup 1: mean-cross with 3-lot scale-out ───────────────────────────────

    def _mean_cross(self, day, a_key, b_key, b0, b1, mu, sd, dev) -> None:
        short = dev > 0                       # closed above μ → look to fade down
        sgn = -1.0 if short else 1.0
        # find the first trigger bar whose RUNNING MEAN crosses μ
        csum = 0.0
        entry_i = None
        for i in range(b0, b1):
            csum += self._C[i]
            m = csum / (i - b0 + 1)
            if (short and m < mu) or (not short and m > mu):
                entry_i = i
                break
        if entry_i is None or entry_i >= b1 - 1:
            return                            # no cross, or no bars left to manage
        entry = float(self._C[entry_i])
        side = "short" if short else "long"
        sl0 = entry - sgn * self.sl_k * sd    # 0.5σ against the trade

        lots = []
        for n, tp_k in enumerate(self.tp_ks, start=1):
            tp = mu + sgn * tp_k * sd
            rec = self._new_trade(side, entry_i, entry, sl0, tp,
                                  setup="mean_cross", lot=n,
                                  day=day, a_key=a_key, b_key=b_key,
                                  mu=mu, sd=sd, dev=dev)
            lots.append(rec)

        # manage bar-by-bar; SL before TP on the same bar; not on the entry bar
        be_armed = False
        for i in range(entry_i + 1, b1):
            for rec in lots:
                if rec["exit_time"] is not None:
                    continue
                sl = rec["sl_price"]
                hit = None
                if short:
                    if self._H[i] >= sl:
                        hit = (sl, self.EXIT_BE if be_armed and sl == entry else self.EXIT_SL)
                    elif self._L[i] <= rec["tp_price"]:
                        hit = (rec["tp_price"], self.EXIT_TP)
                else:
                    if self._L[i] <= sl:
                        hit = (sl, self.EXIT_BE if be_armed and sl == entry else self.EXIT_SL)
                    elif self._H[i] >= rec["tp_price"]:
                        hit = (rec["tp_price"], self.EXIT_TP)
                if hit is not None:
                    self._close(rec, i, hit[0], hit[1])
                    if (rec["exit_reason"] == self.EXIT_TP
                            and rec["lot"] == self.breakeven_after_lot):
                        be_armed = True
                        for other in lots:
                            if other["exit_time"] is None:
                                other["sl_price"] = entry
            if all(r["exit_time"] is not None for r in lots):
                return
        for rec in lots:                      # flatten at segment end
            if rec["exit_time"] is None:
                self._close(rec, b1 - 1, float(self._C[b1 - 1]), self.EXIT_SEGMENT)

    # ── setup 2: extension fade back to the mean ───────────────────────────────

    def _fade(self, day, a_key, b_key, b0, b1, mu, sd, dev, k) -> None:
        short = dev > 0                       # extended above → fade short
        sgn = -1.0 if short else 1.0
        entry_lvl = mu - sgn * (k + self.fade_entry_step) * sd   # one level further
        sl = entry_lvl - sgn * self.fade_sl_k * sd               # 0.5σ beyond entry
        tp = mu                                                  # back to the mean

        fill_i = None
        for i in range(b0, b1 - 1):           # leave ≥1 bar to manage
            if (short and self._H[i] >= entry_lvl) or \
               (not short and self._L[i] <= entry_lvl):
                fill_i = i
                break
        side = "short" if short else "long"
        if fill_i is None:
            rec = self._new_trade(side, b0, None, None, None,
                                  setup="fade", lot=0,
                                  day=day, a_key=a_key, b_key=b_key,
                                  mu=mu, sd=sd, dev=dev, k_level=k)
            rec.update(exit_time=self._time(b1 - 1), exit_bar=b1 - 1,
                       exit_reason=self.NO_FILL)
            self.trades.append(rec)
            return

        lots = []
        for n in range(1, len(self.tp_ks) + 1):
            rec = self._new_trade(side, fill_i, float(entry_lvl), float(sl),
                                  float(tp), setup="fade", lot=n,
                                  day=day, a_key=a_key, b_key=b_key,
                                  mu=mu, sd=sd, dev=dev, k_level=k)
            lots.append(rec)

        for i in range(fill_i + 1, b1):
            for rec in lots:
                if rec["exit_time"] is not None:
                    continue
                hit = None
                if short:
                    if self._H[i] >= rec["sl_price"]:
                        hit = (rec["sl_price"], self.EXIT_SL)
                    elif self._L[i] <= rec["tp_price"]:
                        hit = (rec["tp_price"], self.EXIT_TP)
                else:
                    if self._L[i] <= rec["sl_price"]:
                        hit = (rec["sl_price"], self.EXIT_SL)
                    elif self._H[i] >= rec["tp_price"]:
                        hit = (rec["tp_price"], self.EXIT_TP)
                if hit is not None:
                    self._close(rec, i, hit[0], hit[1])
            if all(r["exit_time"] is not None for r in lots):
                return
        for rec in lots:
            if rec["exit_time"] is None:
                self._close(rec, b1 - 1, float(self._C[b1 - 1]), self.EXIT_SEGMENT)

    # ── records ────────────────────────────────────────────────────────────────

    def _new_trade(self, side, bar_i, entry, sl, tp, *, setup, lot,
                   day, a_key, b_key, mu, sd, dev, k_level=None) -> Dict:
        rec = {
            "trade_id":    self._next_id(),
            "side":        side,
            "setup_time":  self._time(bar_i),
            "entry_time":  self._time(bar_i) if entry is not None else None,
            "entry_price": entry,
            "exit_time":   None,
            "exit_price":  None,
            "sl_price":    sl,
            "tp_price":    tp,
            "risk":        abs(entry - sl) if entry is not None and sl is not None else None,
            "exit_reason": None,
            "setup":       setup,
            "lot":         lot,
            "day":         day,
            "analyze_segment": SEGMENT_LABEL[a_key],
            "trigger_segment": SEGMENT_LABEL[b_key],
            "mu": mu, "sigma": sd, "close_dev": dev, "k_level": k_level,
            "entry_bar": bar_i if entry is not None else None,
            "exit_bar": None, "bars_held": None,
        }
        if entry is not None:
            self.trades.append(rec)
        return rec

    def _close(self, rec: Dict, i: int, price: float, reason: str) -> None:
        rec.update(exit_time=self._time(i), exit_price=float(price),
                   exit_bar=i, exit_reason=reason,
                   bars_held=(i - rec["entry_bar"]) if rec["entry_bar"] is not None else None)

    def _next_id(self) -> str:
        self.trade_counter += 1
        return f"T{self.trade_counter:05d}"

    def _time(self, i: int):
        return self._df["Datetime"].iloc[i]

    # ── io helpers ─────────────────────────────────────────────────────────────

    @staticmethod
    def _canonicalize(df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()
        low = {c.lower(): c for c in out.columns}
        ren = {}
        for canon in ("Open", "High", "Low", "Close"):
            if canon not in out.columns and canon.lower() in low:
                ren[low[canon.lower()]] = canon
        if "Datetime" not in out.columns:
            for alt in ("datetime", "date", "time", "timestamp", "open time"):
                if alt in low:
                    ren[low[alt]] = "Datetime"
                    break
        return out.rename(columns=ren) if ren else out

    def _build_trades_df(self) -> pd.DataFrame:
        if not self.trades:
            return pd.DataFrame(columns=self.TRADE_COLUMNS)
        return pd.DataFrame(self.trades)[self.TRADE_COLUMNS].copy()

    def _build_details(self) -> Dict:
        return {
            "trades":   pd.DataFrame(self.trades),
            "segments": pd.DataFrame(self.segment_rows),
            "metadata": {
                "run_id": self.run_id,
                "strategy": "SessionSigma",
                "asset_class": self.asset_class,
                "timeframe": self.timeframe,
                "segment_chain": SEGMENT_CHAIN,
                "level_step": self.level_step, "level_max": self.level_max,
                "tp_ks": list(self.tp_ks), "sl_k": self.sl_k,
                "breakeven_after_lot": self.breakeven_after_lot,
                "fade_entry_step": self.fade_entry_step,
                "fade_sl_k": self.fade_sl_k,
                "enable_mean_cross": self.enable_mean_cross,
                "enable_fade": self.enable_fade,
                "min_bars_analyze": self.min_bars_analyze,
                "min_bars_trigger": self.min_bars_trigger,
            },
        }
