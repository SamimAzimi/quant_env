"""Asset behaviour statistics: session-transition and day-over-day analysis.

Answers "how does this instrument move" for one asset + one intraday
timeframe, over all available history. Two studies:

1. SESSION TRANSITIONS. Each major session (Tokyo, London, New York) has a
   log-return distribution across days: r = ln(close/open). Its mean μ and
   std σ give bands μ±1σ, μ±2σ. For an ordered pair (reference → trigger)
   we ask: when the trigger session closes beyond the *reference* session's
   ±1σ band, how often — and how cleanly — does price go on to reach the
   reference's ±2σ level within that trigger session?

     Tokyo → London,  London → New York,  New York → London (overnight).

   Everything is measured on a cumulative-log-return axis anchored at the
   reference session's open, so the reference bands and the trigger path
   live on the same scale.

2. DAY-OVER-DAY. The same idea without sessions: the full trading-day
   return r = ln(day_close/day_open) has μ, σ and ±1σ/±2σ bands. We report
   the intraday continuation (does a day that closes beyond +1σ reach +2σ
   intraday, and how cleanly) and the day-to-day conditional transition
   (given the previous day closed beyond ±1σ, what does the current day do).

"Clean move" = for the segment from the first 1σ crossing to the first 2σ
touch: path efficiency |net| / Σ|bar move| ∈ (0,1] (1 = perfectly direct),
the max adverse excursion back toward the mean (in σ), and the bar count.

Sessions come from libs/market_sessions.py (DST-correct, local wall-clock),
via server.marketdata._session_utc.
"""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from .marketdata import _pretty, _session_utc, load_bars

MAJORS = ("Tokyo", "London", "NewYork")
# ordered (reference, trigger, overnight) pairs
TRANSITIONS = (
    ("Tokyo", "London", False),
    ("London", "NewYork", False),
    ("NewYork", "London", True),
)


# --------------------------------------------------------------------------
# Per-session, per-day slices
# --------------------------------------------------------------------------

def _session_days(df: pd.DataFrame, name: str) -> dict[date, pd.DataFrame]:
    """Map each UTC trading date → that day's bars for one session.

    Tokyo/London/New York windows never cross UTC midnight in the modern
    era, so the UTC calendar date is a safe day key; the window itself is
    DST-correct (from _session_utc).
    """
    dt = df["Datetime"]
    out: dict[date, pd.DataFrame] = {}
    for day in sorted(set(dt.dt.date)):
        lo, hi = _session_utc(name, day)
        bars = df[(dt >= lo) & (dt < hi)]
        if not bars.empty:
            out[day] = bars
    return out


def _session_return(bars: pd.DataFrame) -> float:
    """Open→close log return of a session's bars."""
    o = float(bars["Open"].iloc[0])
    c = float(bars["Close"].iloc[-1])
    if o <= 0 or c <= 0:
        return float("nan")
    return float(np.log(c / o))


def _dist(returns: np.ndarray) -> dict:
    """Distribution summary + empirical band-exceedance probabilities."""
    r = returns[np.isfinite(returns)]
    if r.size < 5:
        return {"n": int(r.size), "note": "insufficient data"}
    mu = float(np.mean(r))
    sd = float(np.std(r, ddof=1))
    up1, up2 = mu + sd, mu + 2 * sd
    dn1, dn2 = mu - sd, mu - 2 * sd
    counts, edges = np.histogram(r, bins=min(40, max(10, r.size // 20)))
    return {
        "n": int(r.size),
        "mean": mu,
        "std": sd,
        "skew": float(_skew(r)),
        "bands": {"up1": up1, "up2": up2, "dn1": dn1, "dn2": dn2},
        "probs": {
            "p_up": float(np.mean(r > 0)),
            "p_gt_1sd": float(np.mean(r > up1)),
            "p_gt_2sd": float(np.mean(r > up2)),
            "p_lt_1sd": float(np.mean(r < dn1)),
            "p_lt_2sd": float(np.mean(r < dn2)),
        },
        "hist": {"edges": [float(x) for x in edges],
                 "counts": [int(x) for x in counts]},
    }


def _skew(r: np.ndarray) -> float:
    if r.size < 3:
        return float("nan")
    m = r.mean()
    s = r.std(ddof=0)
    if s == 0:
        return 0.0
    return float(np.mean(((r - m) / s) ** 3))


# --------------------------------------------------------------------------
# Clean-move measurement on a trigger session anchored at a reference open
# --------------------------------------------------------------------------

def _clean_move(bars: pd.DataFrame, p0: float, b1: float, b2: float,
                sd: float, direction: str) -> dict:
    """Measure the move of a trigger session toward the reference ±2σ level.

    p0    reference-session open (anchor for cumulative log return)
    b1/b2 the reference ±1σ / ±2σ levels on the cumulative-return axis
    sd    reference σ (for expressing adverse excursion in σ units)
    Returns per-day event flags and, when the 2σ target is hit, the
    cleanliness of the 1σ→2σ segment.
    """
    close_c = np.log(bars["Close"].to_numpy() / p0)
    high_c = np.log(bars["High"].to_numpy() / p0)
    low_c = np.log(bars["Low"].to_numpy() / p0)
    close_ret = float(close_c[-1])

    up = direction == "up"
    breakout = close_ret > b1 if up else close_ret < b1
    reach1 = (high_c >= b1) if up else (low_c <= b1)
    reach2 = (high_c >= b2) if up else (low_c <= b2)
    target = bool(reach2.any())

    out = {"breakout": bool(breakout), "target": target,
           "efficiency": None, "mae_sd": None, "bars": None}
    if not (target and reach1.any()):
        return out

    i1 = int(np.argmax(reach1))                 # first 1σ crossing
    after = reach2.copy()
    after[:i1] = False
    if not after.any():
        return out
    i2 = int(np.argmax(after))                  # first 2σ touch at/after i1
    if i2 < i1:
        return out

    seg = close_c[i1:i2 + 1]
    net = abs(b2 - b1)
    gross = float(np.sum(np.abs(np.diff(seg)))) if seg.size > 1 else net
    eff = net / gross if gross > 0 else 1.0
    if up:
        mae = max(0.0, b1 - float(low_c[i1:i2 + 1].min()))
    else:
        mae = max(0.0, float(high_c[i1:i2 + 1].max()) - b1)
    out.update(efficiency=float(min(eff, 1.0)),
               mae_sd=float(mae / sd) if sd > 0 else None,
               bars=int(i2 - i1))
    return out


def _summarize_side(rows: list[dict], n_days: int) -> dict:
    """Aggregate per-day clean-move rows into conditional probabilities."""
    n_break = sum(r["breakout"] for r in rows)
    n_target = sum(r["target"] for r in rows)
    both = [r for r in rows if r["breakout"] and r["target"]]
    effs = [r["efficiency"] for r in both if r["efficiency"] is not None]
    maes = [r["mae_sd"] for r in both if r["mae_sd"] is not None]
    barss = [r["bars"] for r in both if r["bars"] is not None]
    return {
        "n_days": n_days,
        "n_breakout": int(n_break),
        "n_target": int(n_target),
        "p_breakout": n_break / n_days if n_days else None,
        "p_target": n_target / n_days if n_days else None,
        "p_target_given_breakout": (len(both) / n_break) if n_break else None,
        "clean": {
            "n": len(both),
            "eff_mean": float(np.mean(effs)) if effs else None,
            "eff_median": float(np.median(effs)) if effs else None,
            "mae_sd_mean": float(np.mean(maes)) if maes else None,
            "bars_mean": float(np.mean(barss)) if barss else None,
        },
    }


# --------------------------------------------------------------------------
# Study 1: session transitions
# --------------------------------------------------------------------------

def _transition(df: pd.DataFrame, ref: str, trig: str, overnight: bool,
                sess_days: dict[str, dict]) -> dict:
    ref_days = sess_days[ref]
    trig_days = sess_days[trig]

    ref_returns = np.array([_session_return(b) for b in ref_days.values()])
    ref_stats = _dist(ref_returns)
    if "note" in ref_stats:
        return {"reference": _pretty(ref), "trigger": _pretty(trig),
                "overnight": overnight, "note": ref_stats["note"]}
    mu, sd = ref_stats["mean"], ref_stats["std"]
    up1, up2 = mu + sd, mu + 2 * sd
    dn1, dn2 = mu - sd, mu - 2 * sd

    up_rows, dn_rows = [], []
    for day, rbars in ref_days.items():
        tday = day + pd.Timedelta(days=1) if overnight else day
        tday = tday.date() if hasattr(tday, "date") else tday
        tbars = trig_days.get(tday)
        if tbars is None:
            continue
        p0 = float(rbars["Open"].iloc[0])
        if p0 <= 0:
            continue
        up_rows.append(_clean_move(tbars, p0, up1, up2, sd, "up"))
        dn_rows.append(_clean_move(tbars, p0, dn1, dn2, sd, "down"))

    n = len(up_rows)
    return {
        "reference": _pretty(ref),
        "trigger": _pretty(trig),
        "overnight": overnight,
        "ref_mean": mu,
        "ref_std": sd,
        "bands": {"up1": up1, "up2": up2, "dn1": dn1, "dn2": dn2},
        "up": _summarize_side(up_rows, n),
        "down": _summarize_side(dn_rows, n),
    }


# --------------------------------------------------------------------------
# Study 2: day-over-day
# --------------------------------------------------------------------------

def _daily_frames(df: pd.DataFrame) -> dict[date, pd.DataFrame]:
    dt = df["Datetime"]
    return {day: df[dt.dt.date == day] for day in sorted(set(dt.dt.date))}


def _daily_study(df: pd.DataFrame) -> dict:
    days = _daily_frames(df)
    ordered = sorted(days)
    rets = np.array([_session_return(days[d]) for d in ordered])
    stats = _dist(rets)
    if "note" in stats:
        return {"note": stats["note"]}
    mu, sd = stats["mean"], stats["std"]
    up1, up2 = mu + sd, mu + 2 * sd
    dn1, dn2 = mu - sd, mu - 2 * sd

    # intraday continuation: each day anchored at its own open
    up_rows, dn_rows = [], []
    for d in ordered:
        bars = days[d]
        p0 = float(bars["Open"].iloc[0])
        if p0 <= 0:
            continue
        up_rows.append(_clean_move(bars, p0, up1, up2, sd, "up"))
        dn_rows.append(_clean_move(bars, p0, dn1, dn2, sd, "down"))
    n = len(up_rows)

    # day-to-day conditional: given prev day beyond ±1σ, what does today do?
    def _after(mask_prev):
        idx = [i for i in range(1, len(rets))
               if np.isfinite(rets[i - 1]) and mask_prev(rets[i - 1])
               and np.isfinite(rets[i])]
        nxt = rets[idx]
        if nxt.size == 0:
            return {"n": 0}
        return {
            "n": int(nxt.size),
            "p_next_up": float(np.mean(nxt > 0)),
            "p_next_gt_1sd": float(np.mean(nxt > up1)),
            "p_next_lt_1sd": float(np.mean(nxt < dn1)),
            "mean_next": float(np.mean(nxt)),
        }

    return {
        **stats,
        "intraday": {
            "up": _summarize_side(up_rows, n),
            "down": _summarize_side(dn_rows, n),
        },
        "day_to_day": {
            "after_up_1sd": _after(lambda x: x > up1),
            "after_down_1sd": _after(lambda x: x < dn1),
        },
    }


# --------------------------------------------------------------------------
# Public entry point
# --------------------------------------------------------------------------

def analyze(asset: str, tf: str) -> dict:
    """Full behaviour report for one asset + intraday timeframe."""
    df = load_bars(asset, tf).dropna(subset=["Datetime"]).sort_values("Datetime")
    df = df.reset_index(drop=True)
    if len(df) < 50:
        raise ValueError(f"Not enough {tf} bars for {asset}")

    sess_days = {name: _session_days(df, name) for name in MAJORS}
    sessions = {}
    for name in MAJORS:
        rets = np.array([_session_return(b) for b in sess_days[name].values()])
        sessions[_pretty(name)] = _dist(rets)

    transitions = [_transition(df, ref, trig, overnight, sess_days)
                   for ref, trig, overnight in TRANSITIONS]

    return {
        "asset": asset,
        "timeframe": tf,
        "n_bars": int(len(df)),
        "n_days": len(set(df["Datetime"].dt.date)),
        "date_range": [df["Datetime"].iloc[0].date().isoformat(),
                       df["Datetime"].iloc[-1].date().isoformat()],
        "sessions": sessions,
        "transitions": transitions,
        "daily": _daily_study(df),
    }
