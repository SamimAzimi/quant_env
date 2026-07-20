"""session_sigma_strategy.py — evidence-based session σ plays.

Pipeline-compatible: same ``(run_id=, **params).backtest(df) -> (trades_df,
details)`` shape and ledger as the other strategies (CFDCostModel →
CFDAccountSimulator → PerformanceAnalytics → store → dashboard).

Empirical basis
───────────────
The rules below are calibrated on the band-behaviour study
(``server/band_behavior.py`` — Asset Stats → band study, sections A–G) run
on XAUUSD 5m, 2024-06-30 → 2026-07-16 (523–526 days per pair; all four
session pairs verdict "structured", 7/7 tests rejecting Gaussian noise).
What the study established, and what each finding does to the strategy:

1. The mean is NOT a magnet. From every occupied band the next close moves
   toward the analyze mean less than 50% of the time (0.24–0.48), price
   beyond ±4σ re-enters the grid on only 7–12% of next candles, and the
   tail bands are the stickiest states of the whole transition matrix
   (diagonal 0.88–0.93).
   → the old EXTENSION-FADE setup (limit against a stretch, TP = μ) is
     REMOVED. It stood directly in front of measured persistence.

2. Breakouts persist. Outer-band hits cluster massively (runs-test z from
   −34 down to −103: streaks, not chop), ±2σ→tail continuation is the
   historical norm, and band exits jump 1.3–3.6 bands per candle.
   → NEW BREAKOUT-CONTINUATION setup: the first trigger-segment close
     beyond ±breakout_k·σ enters WITH the break, one trade per direction
     per transition (hits cluster — the first hit marks the episode),
     scale-out at pair-calibrated outer levels.

3. Adverse excursion sets the minimum stop, per pair. Typical wrong-way
   travel en route to a target: ≈0.26σ (Tokyo→overlap), ≈0.7σ
   (overlap→London solo), ≈1.0σ (London solo→US overlap), ≈0.37σ
   (US overlap→NY solo).
   → the universal 0.5σ stop is REMOVED; each pair's ``sl_k`` covers its
     measured adverse excursion plus a buffer.

4. Ruler quality depends on the pair. σ from a quiet segment applied to a
   louder one is decorative: overlap→London solo puts 8% of closes beyond
   ±4σ and London solo→US overlap puts ≈35% beyond ±4σ (KS 0.293) — the
   1/2/3σ targets there are incidental traffic, not levels.
   → MEAN-CROSS momentum is kept only on the two calibrated rulers
     (Tokyo→overlap KS 0.174, US overlap→NY solo KS 0.146); on the two
     under-scaled pairs only the breakout setup runs, with targets pushed
     out to where the study says price actually travels.

5. Price passes through the mean instead of resting there (centre bands
   hold ~3–5% vs 9.9% expected; centre diagonal 0.20–0.46) and sides of μ
   run in streaks (runs z −30…−90).
   → MEAN-CROSS is kept on calibrated pairs: when the analyze segment
     closed near μ and the trigger's running mean crosses μ, trade in the
     direction of the cross. 3-lot scale-out at μ±1/2/3σ with breakeven
     after lot 2 stays — exit direction from inner bands is ~50/50, so
     banking the near bands and letting a protected runner ride the streak
     is exactly what the escape/oscillation numbers support.

The play
────────
Each trading day is cut into the five-part session partition (DST-correct,
via libs/market_sessions.py local wall-clock definitions):

    Tokyo(solo) → Tokyo∩London → London(solo) → London∩NY → NewYork(solo)

Every consecutive pair is an (ANALYZE, TRIGGER) transition — four per day.
ANALYZE: μ and σ of the analyze segment's closes. TRIGGER (per-pair
parameters from ``PAIR_PARAMS``, override via the constructor):

• BREAKOUT CONTINUATION (all pairs): first trigger close beyond
  μ ± breakout_k·σ → enter with the break at that close, one per direction
  per transition. Targets: the pair's ``breakout_tp_ks`` σ-levels beyond
  the entry (levels the entry already passed are dropped; if none remain
  the break is skipped). SL = entry ∓ sl_k·σ; breakeven after lot 2.

• MEAN-CROSS (calibrated pairs only, analyze close within ±0.5σ of μ):
  the first trigger bar whose running mean of closes crosses μ → 3 lots in
  the cross direction, TPs at μ±1/2/3σ, SL = sl_k·σ against the trade,
  breakeven after lot 2.

REFERENCE MODE (``reference="london_solo"`` etc.): trade ONLY the chosen
session's levels. Each occurrence of that session is the analyze window,
and its trades run from the session's end until the NEXT occurrence of
that same session (the following trading day; weekend/holiday days with
no bars in the window are skipped, so a Friday reference trades through
to Monday's occurrence). Both setups apply inside that whole window, with
the reference's band-study pair calibration (NY solo, which has no
studied following pair, defaults to breakout-only with the mildest
parameters). ``reference=None`` (default) keeps the four-adjacent-pairs
behaviour unchanged.

Any lot still open when the trading window ends — the trigger segment, or
in reference mode the last bar before the next reference occurrence — is
flattened at its last close (``segment_close``). Exits are conservative:
SL checked before TP on the same bar, and never on the entry bar itself.
Everything is causal — the analyze stats are fully known before the
trading window starts.

Returns ``(trades_df, details)``; ``details["trades"]`` is the full per-lot
ledger (with ``sl_price``) the account simulator needs, and
``details["segments"]`` records each transition's μ/σ/deviation/setups.
"""
from __future__ import annotations

from functools import partial
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

# The DST-correct session windows live in ONE place — libs/market_sessions.
# Re-exported here (SEGMENT_CHAIN / SEGMENT_LABEL / segment_windows) so
# existing imports from this module keep working.
from libs.market_sessions import SEGMENT_CHAIN, SEGMENT_LABEL, segment_windows
from strategies.common import build_trades_df, canonicalize_ohlc

__all__ = ["SEGMENT_CHAIN", "SEGMENT_LABEL", "segment_windows",
           "PAIR_PARAMS", "SessionSigmaStrategy"]

# Per-pair calibration from the XAUUSD 5m band study (see module docstring).
#   mean_cross      — only where the analyze σ is a trustworthy ruler for
#                     the trigger segment (KS 0.174 / 0.146; the other two
#                     pairs put 8% / 35% of closes beyond ±4σ).
#   sl_k            — measured mean adverse excursion + buffer
#                     (≈0.26σ / 0.7σ / 1.0σ / 0.37σ per pair).
#   breakout_tp_ks  — σ-levels sized by measured tail reach: penetration
#                     beyond ±4σ averages ≈0.4σ / 1.0σ / 1.6σ / 0.6σ, and
#                     the two under-scaled rulers see the tails on
#                     22–28% / 42–44% of days, so their targets sit further
#                     out.
PAIR_PARAMS: Dict[Tuple[str, str], Dict] = {
    ("tokyo_solo", "tokyo_london"): dict(
        mean_cross=True,  sl_k=0.50, breakout_k=2.0,
        breakout_tp_ks=(3.0, 3.5, 4.0)),
    ("tokyo_london", "london_solo"): dict(
        mean_cross=False, sl_k=1.00, breakout_k=2.0,
        breakout_tp_ks=(3.0, 4.0, 5.0)),
    ("london_solo", "london_ny"): dict(
        mean_cross=False, sl_k=1.25, breakout_k=2.0,
        breakout_tp_ks=(4.0, 5.0, 6.0)),
    ("london_ny", "ny_solo"): dict(
        mean_cross=True,  sl_k=0.60, breakout_k=2.0,
        breakout_tp_ks=(3.0, 3.5, 4.0)),
}


class SessionSigmaStrategy:
    # exit reasons
    EXIT_TP      = "TP"
    EXIT_SL      = "SL"
    EXIT_BE      = "breakeven_stop"
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
        # mean-cross gate: analyze close within ±level_step·σ of μ
        level_step:  float = 0.5,
        # mean-cross scale-out σ-multiples (3 lots)
        tp_ks:       tuple = (1.0, 2.0, 3.0),
        breakeven_after_lot: int = 2,           # move SL to entry once this lot TPs
        # setup switches
        enable_mean_cross: bool = True,
        enable_breakout:   bool = True,
        # REFERENCE MODE: pick ONE segment of SEGMENT_CHAIN (e.g.
        # "london_solo") — only that session's μ/σ are traded, and its
        # trading window runs from the session's end until the NEXT
        # occurrence of that same session (next trading day). None keeps
        # the default four-adjacent-pairs behaviour.
        reference: Optional[str] = None,
        # per-pair overrides merged over PAIR_PARAMS, keyed (analyze, trigger)
        pair_params: Optional[Dict[Tuple[str, str], Dict]] = None,
        # gating / hygiene
        min_bars_analyze:  int = 5,
        min_bars_trigger:  int = 3,
    ) -> None:
        self.run_id = run_id
        self.asset_class = asset_class
        self.timeframe = timeframe
        self.level_step = float(level_step)
        self.tp_ks = tuple(float(k) for k in tp_ks)
        self.breakeven_after_lot = int(breakeven_after_lot)
        self.enable_mean_cross = enable_mean_cross
        self.enable_breakout = enable_breakout
        if reference is not None and reference not in SEGMENT_CHAIN:
            raise ValueError(f"reference must be one of {SEGMENT_CHAIN}, "
                             f"got {reference!r}")
        self.reference = reference
        self.pair_params = {k: dict(v) for k, v in PAIR_PARAMS.items()}
        for k, v in (pair_params or {}).items():
            self.pair_params.setdefault(k, {}).update(v)
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

        if self.reference is not None:
            self._run_reference(t)
            return
        for day in sorted(set(t.date)):
            wins = segment_windows(day)
            idx = {k: self._slice(*wins[k]) for k in SEGMENT_CHAIN}
            for a_key, b_key in zip(SEGMENT_CHAIN[:-1], SEGMENT_CHAIN[1:]):
                self._transition(day, a_key, b_key, idx[a_key], idx[b_key])

    def _run_reference(self, t: pd.DatetimeIndex) -> None:
        """Reference mode: each occurrence of the chosen session is the
        analyze window; its trades run until the NEXT occurrence starts.

        An 'occurrence' is a calendar day whose reference window actually
        contains enough bars — weekend/holiday windows have none and are
        skipped, so a Friday reference naturally trades through the weekend
        gap until Monday's occurrence begins.
        """
        ref = self.reference
        occ = []                              # (day, window_start, window_end)
        for day in sorted(set(t.date)):
            r0, r1 = segment_windows(day)[ref]
            a0, a1 = self._slice(r0, r1)
            if a1 - a0 >= self.min_bars_analyze:
                occ.append((day, r0, r1))
        pp = self._reference_params()
        label = f"until next {SEGMENT_LABEL[ref]}"
        for k, (day, r0, r1) in enumerate(occ):
            a_rng = self._slice(r0, r1)
            b0 = int(np.searchsorted(self._T, np.datetime64(r1), "left"))
            b1 = (int(np.searchsorted(self._T, np.datetime64(occ[k + 1][1]), "left"))
                  if k + 1 < len(occ) else len(self._T))
            self._transition(day, ref, ref, a_rng, (b0, b1),
                             pp=pp, trigger_label=label)

    def _reference_params(self) -> Dict:
        """Band-study calibration for the reference: its adjacent-pair entry
        when one exists (the study measured those four), else the mildest
        defaults (NY solo has no following segment in the study)."""
        i = SEGMENT_CHAIN.index(self.reference)
        if i + 1 < len(SEGMENT_CHAIN):
            pp = self.pair_params.get((self.reference, SEGMENT_CHAIN[i + 1]))
            if pp:
                return pp
        return dict(mean_cross=False, sl_k=0.60, breakout_k=2.0,
                    breakout_tp_ks=(3.0, 3.5, 4.0))

    def _slice(self, lo: pd.Timestamp, hi: pd.Timestamp) -> Tuple[int, int]:
        if lo >= hi:
            return 0, 0
        i0 = int(np.searchsorted(self._T, np.datetime64(lo), "left"))
        i1 = int(np.searchsorted(self._T, np.datetime64(hi), "left"))
        return i0, i1

    # ── one transition ─────────────────────────────────────────────────────────

    def _transition(self, day, a_key, b_key, a_rng, b_rng,
                    pp: Optional[Dict] = None,
                    trigger_label: Optional[str] = None) -> None:
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
        if pp is None:
            pp = self.pair_params.get((a_key, b_key), {})
        a_label = SEGMENT_LABEL[a_key]
        b_label = trigger_label or SEGMENT_LABEL[b_key]

        seg_row = {"day": day, "analyze": a_key,
                   "trigger": trigger_label or b_key,
                   "mu": mu, "sigma": sd, "close_dev": dev,
                   "setup": None, "breakouts": 0}

        if (self.enable_mean_cross and pp.get("mean_cross", False)
                and abs(dev) < self.level_step):
            seg_row["setup"] = "mean_cross"
            self._mean_cross(day, a_label, b_label, b0, b1, mu, sd, dev,
                             sl_k=float(pp.get("sl_k", 0.5)))

        if self.enable_breakout and pp:
            seg_row["breakouts"] = self._breakout(
                day, a_label, b_label, b0, b1, mu, sd, dev,
                k=float(pp.get("breakout_k", 2.0)),
                tp_ks=tuple(pp.get("breakout_tp_ks", (3.0, 3.5, 4.0))),
                sl_k=float(pp.get("sl_k", 0.5)))
        self.segment_rows.append(seg_row)

    # ── setup 1: mean-cross momentum with 3-lot scale-out ─────────────────────

    def _mean_cross(self, day, a_label, b_label, b0, b1, mu, sd, dev, sl_k) -> None:
        short = dev > 0                       # closed above μ → cross plays down
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
        sl0 = entry - sgn * sl_k * sd

        lots = []
        for n, tp_k in enumerate(self.tp_ks, start=1):
            tp = mu + sgn * tp_k * sd
            lots.append(self._new_trade(side, entry_i, entry, sl0, tp,
                                        setup="mean_cross", lot=n,
                                        day=day, a_label=a_label, b_label=b_label,
                                        mu=mu, sd=sd, dev=dev))
        self._manage(lots, short, entry, entry_i + 1, b1)

    # ── setup 2: breakout continuation beyond ±kσ ─────────────────────────────

    def _breakout(self, day, a_label, b_label, b0, b1, mu, sd, dev,
                  k, tp_ks, sl_k) -> int:
        """First close beyond μ±kσ enters WITH the break, once per direction.
        Returns the number of breakout entries taken this transition."""
        done = set()
        entries = 0
        for i in range(b0, b1 - 1):           # leave ≥1 bar to manage
            z = (float(self._C[i]) - mu) / sd
            if z >= k and "long" not in done:
                side, sgn = "long", 1.0
            elif z <= -k and "short" not in done:
                side, sgn = "short", -1.0
            else:
                continue
            done.add(side)                    # hits cluster: first hit = episode
            entry = float(self._C[i])
            # targets the entry already passed carry no information — drop
            # them; an entry beyond the top target has nothing left to aim at
            tps = [mu + sgn * t * sd for t in tp_ks if t > abs(z) + 1e-12]
            if not tps:
                continue
            sl0 = entry - sgn * sl_k * sd
            lots = []
            for n, tp in enumerate(tps, start=1):
                lots.append(self._new_trade(side, i, entry, sl0, float(tp),
                                            setup="breakout", lot=n,
                                            day=day, a_label=a_label, b_label=b_label,
                                            mu=mu, sd=sd, dev=dev, k_level=k))
            self._manage(lots, side == "short", entry, i + 1, b1)
            entries += 1
        return entries

    # ── shared lot management ─────────────────────────────────────────────────

    def _manage(self, lots, short, entry, start_i, b1) -> None:
        """Bar-by-bar exits: SL before TP on the same bar; breakeven for the
        remaining lots once lot ``breakeven_after_lot`` takes profit."""
        be_armed = False
        for i in range(start_i, b1):
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

    # ── records ────────────────────────────────────────────────────────────────

    def _new_trade(self, side, bar_i, entry, sl, tp, *, setup, lot,
                   day, a_label, b_label, mu, sd, dev, k_level=None) -> Dict:
        rec = {
            "trade_id":    self._next_id(),
            "side":        side,
            "setup_time":  self._time(bar_i),
            "entry_time":  self._time(bar_i),
            "entry_price": entry,
            "exit_time":   None,
            "exit_price":  None,
            "sl_price":    sl,
            "tp_price":    tp,
            "risk":        abs(entry - sl),
            "exit_reason": None,
            "setup":       setup,
            "lot":         lot,
            "day":         day,
            "analyze_segment": a_label,
            "trigger_segment": b_label,
            "mu": mu, "sigma": sd, "close_dev": dev, "k_level": k_level,
            "entry_bar": bar_i,
            "exit_bar": None, "bars_held": None,
        }
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

    # shared implementation (strategies/common.py) with this strategy's
    # historical options: no index reset, "open time" accepted as time alias
    _canonicalize = staticmethod(partial(
        canonicalize_ohlc, reset_index=False,
        time_aliases=("datetime", "date", "time", "timestamp", "open time")))

    def _build_trades_df(self) -> pd.DataFrame:
        return build_trades_df(self.trades, self.TRADE_COLUMNS)

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
                "level_step": self.level_step,
                "tp_ks": list(self.tp_ks),
                "breakeven_after_lot": self.breakeven_after_lot,
                "enable_mean_cross": self.enable_mean_cross,
                "enable_breakout": self.enable_breakout,
                "reference": self.reference,
                "pair_params": {f"{a}->{b}": {
                    kk: (list(vv) if isinstance(vv, tuple) else vv)
                    for kk, vv in p.items()}
                    for (a, b), p in self.pair_params.items()},
                "min_bars_analyze": self.min_bars_analyze,
                "min_bars_trigger": self.min_bars_trigger,
                "calibration": "XAUUSD 5m band study 2024-06-30…2026-07-16",
            },
        }
