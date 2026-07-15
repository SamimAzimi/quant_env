"""Asset behaviour statistics — session/overlap segments, σ-bands, matrix.

Answers "how does this instrument move" for one asset + one intraday
timeframe, over a chosen date range of history. Everything is session-based
around the three majors (Tokyo, London, New York) and their overlaps, with
DST-correct windows from libs/market_sessions.py (via marketdata._session_utc).

SEGMENTS. Each UTC trading day is cut into sub-windows using the real
session bounds for that date:
    Tokyo, Tokyo∖London, Tokyo∩London,
    London, London∖Tokyo, London∖NY, London∩NY,
    New York, New York∖London, Full trading day.
Each segment's log return r = ln(close/open) across days gives a
distribution: mean μ, std σ, skew, ±0.5/1/1.5/2σ bands, tail probabilities.

REFERENCES → TRIGGERS. Six reference sub-sessions each set ±0.5/1/1.5/2σ
bands from their own return distribution, anchored at the reference open.
A trigger window (defined per reference) is then measured on a
cumulative-log-return axis anchored at that reference open:

  reference                         trigger window(s)
  --------------------------------  ------------------------------------
  Tokyo∖London                      London∖NY  and  London∩NY (separately)
  Tokyo∩London                      London-after-Tokyo ∖NY  and  ∩NY
  London∩NY                         NY-after-London → NY close
  London∖NY                         New York session
  overlap Tokyo∩London              end-of-overlap → next overlap start
  overlap London∩NY                 end-of-overlap → next overlap (overnight)

For each trigger we report, up and down:
  * P(close beyond each band), P(touch each band);
  * the full MATRIX  P(touch target band | close beyond breakout band);
  * CLEAN MOVE per adjacent band segment (0.5→1, 1→1.5, 1.5→2): path
    efficiency |net| / Σ|bar move|, mean adverse excursion (in σ), bar count.
"""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

from .marketdata import _session_utc, load_bars

BANDS = [0.5, 1.0, 1.5, 2.0]
ADJ = [(0.5, 1.0), (1.0, 1.5), (1.5, 2.0)]

# Distribution segments: key -> display label.
DIST_SEGMENTS = {
    "tokyo": "Tokyo",
    "tokyo_wo_london": "Tokyo ∖ London",
    "tokyo_x_london": "Tokyo ∩ London",
    "london": "London",
    "london_wo_tokyo": "London ∖ Tokyo (after Tokyo)",
    "london_wo_ny": "London ∖ NY (before NY)",
    "london_x_ny": "London ∩ NY",
    "newyork": "New York",
    "newyork_wo_london": "New York ∖ London (after London)",
    "fullday": "Full trading day",
}

# References and their trigger windows.
REFERENCES = [
    {"key": "tokyo_wo_london", "label": "Tokyo (without London overlap)",
     "window": "tokyo_wo_london", "triggers": [
         {"key": "london_wo_ny", "label": "London ∖ NY", "window": "london_wo_ny"},
         {"key": "london_x_ny", "label": "London ∩ NY", "window": "london_x_ny"},
     ]},
    {"key": "tokyo_x_london", "label": "Tokyo (with London overlap)",
     "window": "tokyo_x_london", "triggers": [
         {"key": "london_after_tokyo_wo_ny",
          "label": "London after Tokyo ∖ NY", "window": "london_after_tokyo_wo_ny"},
         {"key": "london_after_tokyo_w_ny",
          "label": "London after Tokyo ∩ NY", "window": "london_after_tokyo_w_ny"},
     ]},
    {"key": "london_x_ny", "label": "London (with NY overlap)",
     "window": "london_x_ny", "triggers": [
         {"key": "ny_after_london", "label": "NY after London → close",
          "window": "newyork_wo_london"},
     ]},
    {"key": "london_wo_ny", "label": "London (without NY overlap)",
     "window": "london_wo_ny", "triggers": [
         {"key": "newyork", "label": "New York session", "window": "newyork"},
     ]},
    {"key": "ov_tokyo_london", "label": "Overlap: Tokyo ∩ London",
     "window": "tokyo_x_london", "triggers": [
         {"key": "tk_ln_ov_to_next", "label": "End of overlap → next overlap",
          "window": "tk_ln_ov_to_next"},
     ]},
    {"key": "ov_london_ny", "label": "Overlap: London ∩ NY",
     "window": "london_x_ny", "triggers": [
         {"key": "ln_ny_ov_to_next",
          "label": "End of overlap → next overlap (overnight)",
          "window": "ln_ny_ov_to_next", "overnight": True},
     ]},
]


# --------------------------------------------------------------------------
# Per-day segment windows (DST-correct)
# --------------------------------------------------------------------------

def _seg_windows(day: date) -> dict[str, tuple[pd.Timestamp, pd.Timestamp]]:
    tk_o, tk_c = _session_utc("Tokyo", day)
    ln_o, ln_c = _session_utc("London", day)
    ny_o, ny_c = _session_utc("NewYork", day)
    nxt_ln_o, _ = _session_utc("London", day + timedelta(days=1))
    return {
        "tokyo": (tk_o, tk_c),
        "tokyo_wo_london": (tk_o, ln_o),
        "tokyo_x_london": (ln_o, tk_c),
        "london": (ln_o, ln_c),
        "london_wo_tokyo": (tk_c, ln_c),
        "london_wo_ny": (ln_o, ny_o),
        "london_x_ny": (ny_o, ln_c),
        "newyork": (ny_o, ny_c),
        "newyork_wo_london": (ln_c, ny_c),
        "fullday": (tk_o, ny_c),
        "london_after_tokyo_wo_ny": (tk_c, ny_o),
        "london_after_tokyo_w_ny": (ny_o, ln_c),
        "tk_ln_ov_to_next": (tk_c, ny_o),
        "ln_ny_ov_to_next": (ln_c, nxt_ln_o),
    }


# --------------------------------------------------------------------------
# Distribution summary
# --------------------------------------------------------------------------

def _skew(r: np.ndarray) -> float:
    if r.size < 3:
        return float("nan")
    s = r.std(ddof=0)
    return 0.0 if s == 0 else float(np.mean(((r - r.mean()) / s) ** 3))


def _dist(returns: np.ndarray) -> dict:
    r = returns[np.isfinite(returns)]
    if r.size < 5:
        return {"n": int(r.size), "note": "insufficient data"}
    mu = float(np.mean(r))
    sd = float(np.std(r, ddof=1))
    counts, edges = np.histogram(r, bins=min(40, max(10, r.size // 20)))
    up = {str(b): float(np.mean(r > mu + b * sd)) for b in BANDS}
    dn = {str(b): float(np.mean(r < mu - b * sd)) for b in BANDS}
    return {
        "n": int(r.size), "mean": mu, "std": sd, "skew": _skew(r),
        "probs": {"p_up": float(np.mean(r > 0)), "up": up, "down": dn},
        "hist": {"edges": [float(x) for x in edges],
                 "counts": [int(x) for x in counts]},
    }


# --------------------------------------------------------------------------
# Clean-move segment measurement
# --------------------------------------------------------------------------

def _clean_segment(close_c, high_c, low_c, lvlL, lvlU, sd, up):
    """Cleanliness of the move from band level lvlL to lvlU within a path.

    Returns (reached, efficiency, adverse_sd, bars) or None if not reached.
    """
    reach_l = (high_c >= lvlL) if up else (low_c <= lvlL)
    reach_u = (high_c >= lvlU) if up else (low_c <= lvlU)
    if not reach_l.any() or not reach_u.any():
        return None
    i1 = int(np.argmax(reach_l))
    after = reach_u.copy()
    after[:i1] = False
    if not after.any():
        return None
    i2 = int(np.argmax(after))
    if i2 < i1:
        return None
    seg = close_c[i1:i2 + 1]
    net = abs(lvlU - lvlL)
    gross = float(np.sum(np.abs(np.diff(seg)))) if seg.size > 1 else net
    eff = 1.0 if gross <= 0 else min(net / gross, 1.0)
    if up:
        adverse = max(0.0, lvlL - float(low_c[i1:i2 + 1].min()))
    else:
        adverse = max(0.0, float(high_c[i1:i2 + 1].max()) - lvlL)
    return True, float(eff), float(adverse / sd) if sd > 0 else 0.0, int(i2 - i1)


def _agg_segments(rows):
    """Aggregate per-day clean-segment tuples into means."""
    got = [r for r in rows if r is not None]
    if not got:
        return {"n": 0, "eff_mean": None, "adverse_mean": None, "bars_mean": None}
    effs = [g[1] for g in got]
    advs = [g[2] for g in got]
    bars = [g[3] for g in got]
    return {"n": len(got), "eff_mean": float(np.mean(effs)),
            "adverse_mean": float(np.mean(advs)), "bars_mean": float(np.mean(bars))}


# --------------------------------------------------------------------------
# Fast window slicing
# --------------------------------------------------------------------------

class _Bars:
    def __init__(self, df: pd.DataFrame):
        self.t = df["Datetime"].values.astype("datetime64[ns]")
        self.o = df["Open"].to_numpy(float)
        self.h = df["High"].to_numpy(float)
        self.l = df["Low"].to_numpy(float)
        self.c = df["Close"].to_numpy(float)

    def idx(self, start, end):
        i0 = int(np.searchsorted(self.t, np.datetime64(start), "left"))
        i1 = int(np.searchsorted(self.t, np.datetime64(end), "left"))
        return i0, i1


# --------------------------------------------------------------------------
# Transition (reference → trigger)
# --------------------------------------------------------------------------

def _side_stats(mu, sd, close_rets, extremes, up, paths):
    """Build matrix + clean segments for one side (up or down)."""
    levels = [mu + (b if up else -b) * sd for b in BANDS]
    nb = len(BANDS)
    beyond = np.zeros(nb)          # close beyond band i
    touch = np.zeros(nb)           # touched band j
    joint = np.zeros((nb, nb))     # close beyond i AND touch j
    n = 0
    for cr, ext in zip(close_rets, extremes):
        n += 1
        cb = [(cr > levels[i]) if up else (cr < levels[i]) for i in range(nb)]
        tc = [(ext >= levels[j]) if up else (ext <= levels[j]) for j in range(nb)]
        for i in range(nb):
            beyond[i] += cb[i]
            touch[i] += tc[i]
            if cb[i]:
                for j in range(nb):
                    if tc[j]:
                        joint[i][j] += 1
    matrix = [[(joint[i][j] / beyond[i]) if beyond[i] else None
               for j in range(nb)] for i in range(nb)]

    clean = []
    for bL, bU in ADJ:
        lvlL = mu + (bL if up else -bL) * sd
        lvlU = mu + (bU if up else -bU) * sd
        rows = [_clean_segment(cc, hc, lc, lvlL, lvlU, sd, up) for cc, hc, lc in paths]
        seg = _agg_segments(rows)
        seg.update(**{"from": bL, "to": bU})
        clean.append(seg)

    return {
        "bands": BANDS,
        "n": n,
        "p_breakout": [(beyond[i] / n) if n else None for i in range(nb)],
        "p_touch": [(touch[i] / n) if n else None for i in range(nb)],
        "breakout_counts": [int(beyond[i]) for i in range(nb)],
        "matrix": matrix,
        "clean_segments": clean,
    }


def _transition(bars, segwins, days, ref_win, trig_win, mu, sd):
    close_up, ext_up, paths_up = [], [], []
    close_dn, ext_dn, paths_dn = [], [], []
    n_days = 0
    for day in days:
        rw = segwins[day].get(ref_win)
        tw = segwins[day].get(trig_win)
        if rw is None or tw is None or rw[0] >= rw[1] or tw[0] >= tw[1]:
            continue
        ri0, ri1 = bars.idx(*rw)
        if ri1 <= ri0:
            continue
        p0 = bars.o[ri0]
        if p0 <= 0:
            continue
        ti0, ti1 = bars.idx(*tw)
        if ti1 <= ti0:
            continue
        cc = np.log(bars.c[ti0:ti1] / p0)
        hc = np.log(bars.h[ti0:ti1] / p0)
        lc = np.log(bars.l[ti0:ti1] / p0)
        n_days += 1
        close_up.append(float(cc[-1])); ext_up.append(float(hc.max()))
        paths_up.append((cc, hc, lc))
        close_dn.append(float(cc[-1])); ext_dn.append(float(lc.min()))
        paths_dn.append((cc, hc, lc))
    return {
        "n_days": n_days,
        "up": _side_stats(mu, sd, close_up, ext_up, True, paths_up),
        "down": _side_stats(mu, sd, close_dn, ext_dn, False, paths_dn),
    }


# --------------------------------------------------------------------------
# Public entry point
# --------------------------------------------------------------------------

def available_range(asset: str, tf: str) -> dict:
    df = load_bars(asset, tf).dropna(subset=["Datetime"])
    if df.empty:
        raise ValueError(f"No {tf} data for {asset}")
    d = df["Datetime"]
    return {"start": d.iloc[0].date().isoformat(),
            "end": d.iloc[-1].date().isoformat(),
            "n_days": int(d.dt.date.nunique())}


def analyze(asset: str, tf: str, start: date | None = None,
            end: date | None = None) -> dict:
    df = load_bars(asset, tf).dropna(subset=["Datetime"]).sort_values("Datetime")
    df = df.reset_index(drop=True)
    full = (df["Datetime"].iloc[0].date().isoformat(),
            df["Datetime"].iloc[-1].date().isoformat()) if len(df) else (None, None)

    if start is not None:
        df = df[df["Datetime"].dt.date >= start]
    if end is not None:
        df = df[df["Datetime"].dt.date <= end]
    df = df.reset_index(drop=True)
    if len(df) < 50:
        raise ValueError(f"Not enough {tf} bars for {asset} in that range")

    bars = _Bars(df)
    days = sorted(set(df["Datetime"].dt.date))
    segwins = {day: _seg_windows(day) for day in days}

    # distributions
    seg_returns = {k: [] for k in DIST_SEGMENTS}
    for day in days:
        w = segwins[day]
        for k in DIST_SEGMENTS:
            s, e = w[k]
            if s >= e:
                continue
            i0, i1 = bars.idx(s, e)
            if i1 <= i0:
                continue
            o, c = bars.o[i0], bars.c[i1 - 1]
            if o > 0 and c > 0:
                seg_returns[k].append(np.log(c / o))
    sessions = {DIST_SEGMENTS[k]: _dist(np.array(v)) for k, v in seg_returns.items()}

    # references -> triggers
    references = []
    for ref in REFERENCES:
        ref_rets = []
        for day in days:
            rw = segwins[day].get(ref["window"])
            if rw is None or rw[0] >= rw[1]:
                continue
            i0, i1 = bars.idx(*rw)
            if i1 <= i0:
                continue
            o, c = bars.o[i0], bars.c[i1 - 1]
            if o > 0 and c > 0:
                ref_rets.append(np.log(c / o))
        rdist = _dist(np.array(ref_rets))
        entry = {"key": ref["key"], "label": ref["label"],
                 "reference_dist": rdist, "triggers": []}
        if "note" not in rdist and rdist["std"] > 0:
            mu, sd = rdist["mean"], rdist["std"]
            for trig in ref["triggers"]:
                t = _transition(bars, segwins, days, ref["window"],
                                trig["window"], mu, sd)
                t.update(key=trig["key"], label=trig["label"],
                         overnight=trig.get("overnight", False))
                entry["triggers"].append(t)
        references.append(entry)

    return {
        "asset": asset, "timeframe": tf,
        "n_bars": int(len(df)), "n_days": len(days),
        "date_range": [days[0].isoformat(), days[-1].isoformat()],
        "available_range": list(full),
        "bands": BANDS,
        "sessions": sessions,
        "references": references,
    }
