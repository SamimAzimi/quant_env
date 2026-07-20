"""session_extreme_fade.py — fade a touch of the previous session's ±4σ.

Pipeline-compatible: same ``(run_id=, **params).backtest(df) -> (trades_df,
details)`` shape and ledger as the other strategies.

The play
────────
Pick one or more REFERENCE sessions from the five-part day partition
(DST-correct, libs/market_sessions.py):

    tokyo_solo → tokyo_london → london_solo → london_ny → ny_solo

When a reference session closes, μ and σ of its closes define the levels
μ ± touch_k·σ (default ±4σ). From the moment the next session opens:

• price touches μ + 4σ  →  SHORT at the level, target μ, SL 1σ ABOVE entry
• price touches μ − 4σ  →  LONG  at the level, target μ, SL 1σ BELOW entry

One trade per direction per validity window (first touch = the episode).
Fills are conservative: a limit at the band — if a bar OPENS beyond the
level the fill is that (better) open price; the stop distance is measured
from the actual entry. SL is checked before TP on the same bar, never on
the entry bar itself. Anything still open when the bands expire is
flattened at the last bar inside the window (``segment_close``).

How long the bands stay valid — ``valid_for``:
    "next_segment"           only while the adjacent next session runs
    "until_next_occurrence"  until the reference session opens again
                             (the whole rest of the trading day; weekend
                             days without bars are bridged)  [default]
    a number                 that many HOURS after the reference close
                             (capped at the next occurrence so two rulers
                             never overlap)

Honest note: the band study measured momentum beyond ±2σ (tail
re-entry 7–12%/candle, toward-centre < 0.5), so this is a deliberate
counter-thesis strategy — it exists to price the fade at the very extreme,
where the study's first-touch numbers stop. Compare it against
SessionSigmaStrategy runs in the web app's Strategies page.
"""
from __future__ import annotations

from datetime import timedelta
from functools import partial
from typing import Dict, List, Sequence, Tuple, Union

import numpy as np
import pandas as pd

from libs.market_sessions import SEGMENT_CHAIN, SEGMENT_LABEL, segment_windows
from strategies.common import build_trades_df, canonicalize_ohlc

VALID_MODES = ("next_segment", "until_next_occurrence")


class SessionExtremeFadeStrategy:
    # exit reasons
    EXIT_TP      = "TP"
    EXIT_SL      = "SL"
    EXIT_SEGMENT = "segment_close"

    TRADE_COLUMNS: List[str] = [
        "trade_id", "side", "setup_time", "entry_time", "entry_price",
        "exit_time", "exit_price", "exit_reason",
    ]

    def __init__(
        self,
        run_id:      str = "default_run",
        asset_class: str = "FX",
        timeframe:   str = "",
        # which reference session(s): one key, a list of keys, or None = all
        sessions: Union[str, Sequence[str], None] = None,
        touch_k: float = 4.0,          # band to touch: μ ± touch_k·σ
        sl_k:    float = 1.0,          # stop: 1σ beyond the entry
        # band validity: "next_segment" | "until_next_occurrence" | hours
        valid_for: Union[str, float] = "until_next_occurrence",
        min_bars_analyze: int = 5,
        min_bars_window:  int = 3,
    ) -> None:
        self.run_id = run_id
        self.asset_class = asset_class
        self.timeframe = timeframe
        if sessions is None:
            self.sessions: Tuple[str, ...] = tuple(SEGMENT_CHAIN)
        elif isinstance(sessions, str):
            self.sessions = (sessions,)
        else:
            self.sessions = tuple(sessions)
        for s in self.sessions:
            if s not in SEGMENT_CHAIN:
                raise ValueError(f"unknown session {s!r}; choose from {SEGMENT_CHAIN}")
        self.touch_k = float(touch_k)
        self.sl_k = float(sl_k)
        if isinstance(valid_for, str):
            if valid_for not in VALID_MODES:
                raise ValueError(f"valid_for must be one of {VALID_MODES} "
                                 f"or a number of hours, got {valid_for!r}")
            self.valid_for: Union[str, float] = valid_for
        else:
            self.valid_for = float(valid_for)
            if self.valid_for <= 0:
                raise ValueError("valid_for hours must be positive")
        self.min_bars_analyze = int(min_bars_analyze)
        self.min_bars_window = int(min_bars_window)

    # ── public API ───────────────────────────────────────────────────────────

    def backtest(self, df: pd.DataFrame) -> Tuple[pd.DataFrame, Dict]:
        self._run(df)
        return build_trades_df(self.trades, self.TRADE_COLUMNS), self._build_details()

    # ── orchestration ─────────────────────────────────────────────────────────

    _canonicalize = staticmethod(partial(
        canonicalize_ohlc, reset_index=False,
        time_aliases=("datetime", "date", "time", "timestamp", "open time")))

    def _run(self, df: pd.DataFrame) -> None:
        d = self._canonicalize(df)
        if "Datetime" not in d.columns:
            raise ValueError("SessionExtremeFadeStrategy needs a Datetime column (UTC).")
        d = d.dropna(subset=["Datetime"]).sort_values("Datetime").reset_index(drop=True)
        self._df = d
        self.trades: List[Dict] = []
        self.segment_rows: List[Dict] = []
        self.trade_counter = 0

        t = pd.DatetimeIndex(d["Datetime"])
        if t.tz is not None:
            t = t.tz_localize(None)
        self._T = t.values.astype("datetime64[ns]")
        self._O = d["Open"].to_numpy(float)
        self._H = d["High"].to_numpy(float)
        self._L = d["Low"].to_numpy(float)
        self._C = d["Close"].to_numpy(float)

        days = sorted(set(t.date))
        for ref in self.sessions:
            self._run_reference(ref, days)

    def _slice(self, lo, hi) -> Tuple[int, int]:
        if lo >= hi:
            return 0, 0
        i0 = int(np.searchsorted(self._T, np.datetime64(lo), "left"))
        i1 = int(np.searchsorted(self._T, np.datetime64(hi), "left"))
        return i0, i1

    def _run_reference(self, ref: str, days: list) -> None:
        # occurrences = days whose reference window actually has bars
        occ = []
        for day in days:
            r0, r1 = segment_windows(day)[ref]
            a0, a1 = self._slice(r0, r1)
            if a1 - a0 >= self.min_bars_analyze:
                occ.append((day, r0, r1))
        for k, (day, r0, r1) in enumerate(occ):
            next_r0 = occ[k + 1][1] if k + 1 < len(occ) else None
            end = self._window_end(ref, day, r1, next_r0, occ, k)
            b0 = int(np.searchsorted(self._T, np.datetime64(r1), "left"))
            b1 = (int(np.searchsorted(self._T, np.datetime64(end), "left"))
                  if end is not None else len(self._T))
            self._fade_window(ref, day, self._slice(r0, r1), (b0, b1))

    def _window_end(self, ref, day, r1, next_r0, occ, k):
        """Timestamp when this occurrence's bands expire (None = end of data)."""
        if self.valid_for == "until_next_occurrence":
            return next_r0
        if self.valid_for == "next_segment":
            i = SEGMENT_CHAIN.index(ref)
            if i + 1 < len(SEGMENT_CHAIN):
                return segment_windows(day)[SEGMENT_CHAIN[i + 1]][1]
            # ny_solo: the next segment is the following occurrence day's tokyo_solo
            if k + 1 < len(occ):
                return segment_windows(occ[k + 1][0])["tokyo_solo"][1]
            return None
        end = r1 + timedelta(hours=float(self.valid_for))
        # never let two occurrences' rulers overlap
        if next_r0 is not None and end > next_r0:
            end = next_r0
        return end

    # ── one validity window ───────────────────────────────────────────────────

    def _fade_window(self, ref, day, a_rng, b_rng) -> None:
        a0, a1 = a_rng
        b0, b1 = b_rng
        if b1 - b0 < self.min_bars_window:
            return
        closesA = self._C[a0:a1]
        mu = float(np.mean(closesA))
        sd = float(np.std(closesA, ddof=1))
        if not np.isfinite(sd) or sd <= 0:
            return
        hi_lvl = mu + self.touch_k * sd
        lo_lvl = mu - self.touch_k * sd

        seg_row = {"day": day, "reference": ref, "mu": mu, "sigma": sd,
                   "window_start": pd.Timestamp(self._T[b0]),
                   "touched_up": False, "touched_down": False}

        done = set()
        for i in range(b0, b1 - 1):           # leave ≥1 bar to manage
            if "short" not in done and (self._O[i] >= hi_lvl or self._H[i] >= hi_lvl):
                done.add("short")
                seg_row["touched_up"] = True
                entry = float(max(self._O[i], hi_lvl) if self._O[i] >= hi_lvl else hi_lvl)
                self._trade("short", ref, day, i, b1, entry, mu, sd)
            if "long" not in done and (self._O[i] <= lo_lvl or self._L[i] <= lo_lvl):
                done.add("long")
                seg_row["touched_down"] = True
                entry = float(min(self._O[i], lo_lvl) if self._O[i] <= lo_lvl else lo_lvl)
                self._trade("long", ref, day, i, b1, entry, mu, sd)
            if done == {"short", "long"}:
                break
        self.segment_rows.append(seg_row)

    def _trade(self, side, ref, day, entry_i, b1, entry, mu, sd) -> None:
        short = side == "short"
        sgn = -1.0 if short else 1.0
        sl = entry - sgn * self.sl_k * sd     # 1σ beyond the entry
        tp = mu                               # target: the reference mean
        rec = {
            "trade_id":    self._next_id(),
            "side":        side,
            "setup_time":  self._time(entry_i),
            "entry_time":  self._time(entry_i),
            "entry_price": entry,
            "exit_time":   None, "exit_price": None, "exit_reason": None,
            "sl_price":    float(sl), "tp_price": float(tp),
            "risk":        abs(entry - sl),
            "setup":       "extreme_fade", "lot": 1,
            "day":         day,
            "analyze_segment": SEGMENT_LABEL[ref],
            "trigger_segment": f"fade window ({self.valid_for})",
            "mu": mu, "sigma": sd, "k_level": self.touch_k,
            "entry_bar": entry_i, "exit_bar": None, "bars_held": None,
        }
        self.trades.append(rec)

        for i in range(entry_i + 1, b1):      # SL before TP; not on entry bar
            if short:
                if self._H[i] >= rec["sl_price"]:
                    return self._close(rec, i, rec["sl_price"], self.EXIT_SL)
                if self._L[i] <= tp:
                    return self._close(rec, i, tp, self.EXIT_TP)
            else:
                if self._L[i] <= rec["sl_price"]:
                    return self._close(rec, i, rec["sl_price"], self.EXIT_SL)
                if self._H[i] >= tp:
                    return self._close(rec, i, tp, self.EXIT_TP)
        self._close(rec, b1 - 1, float(self._C[b1 - 1]), self.EXIT_SEGMENT)

    # ── records ────────────────────────────────────────────────────────────────

    def _close(self, rec, i, price, reason) -> None:
        rec.update(exit_time=self._time(i), exit_price=float(price),
                   exit_bar=i, exit_reason=reason,
                   bars_held=i - rec["entry_bar"])

    def _next_id(self) -> str:
        self.trade_counter += 1
        return f"T{self.trade_counter:05d}"

    def _time(self, i: int):
        return self._df["Datetime"].iloc[i]

    def _build_details(self) -> Dict:
        return {
            "trades":   pd.DataFrame(self.trades),
            "segments": pd.DataFrame(self.segment_rows),
            "metadata": {
                "run_id": self.run_id,
                "strategy": "SessionExtremeFade",
                "asset_class": self.asset_class,
                "timeframe": self.timeframe,
                "sessions": list(self.sessions),
                "touch_k": self.touch_k,
                "sl_k": self.sl_k,
                "valid_for": self.valid_for,
                "min_bars_analyze": self.min_bars_analyze,
                "min_bars_window": self.min_bars_window,
            },
        }
