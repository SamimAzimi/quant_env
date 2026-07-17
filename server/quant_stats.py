"""Day-over-day + quant/hedge-fund character statistics for one asset.

Two layers over the CSV bar store (asset + intraday timeframe + date range):

1. DAY-OVER-DAY — the full trading-day return r = ln(day_close/day_open)
   (Tokyo open → New York close, DST-correct):
     * daily return distribution (μ, σ, skew, ±0.5/1/1.5/2σ bands, tails);
     * intraday continuation — anchored at the day open, the full
       breakout×target band matrix and per-adjacent-segment clean move
       (reuses the session engine's machinery);
     * day-to-day transition — given the previous day's σ-bucket, what the
       current day does;
     * overnight gap analysis (size, fill probability, continuation);
     * streak / run statistics.

2. QUANT CHARACTER — a curated hedge-fund-style report:
     * performance ratios from daily returns: annualised return/vol,
       Sharpe, Sortino, Calmar, max drawdown (+ duration), VaR/CVaR at
       95/99, profit factor, Omega, tail ratio, win rate, best/worst day;
     * distribution shape, volatility (multi-estimator + GARCH + cones),
       mean-reversion/trend (Hurst, variance ratio, ADF, half-life), and
       predictability (Markov, conditional direction, touch, MFE/MAE) from
       libs/market_stats.py.
"""
from __future__ import annotations

import math
from datetime import date

import numpy as np
import pandas as pd

from .asset_stats import BANDS, _Bars, _dist, _side_stats
from .marketdata import day_window, load_bars

TRADING_DAYS = 252


def _finite(x):
    """Recursively make the payload valid JSON: NaN/Inf → None and numpy
    scalars → native python (market_metrics returns plenty of both)."""
    if isinstance(x, dict):
        return {str(k): _finite(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_finite(v) for v in x]
    if isinstance(x, np.bool_):
        return bool(x)
    if isinstance(x, np.integer):
        return int(x)
    if isinstance(x, (float, np.floating)):
        x = float(x)
        return x if math.isfinite(x) else None
    return x


# --------------------------------------------------------------------------
# Daily series (trading-day window)
# --------------------------------------------------------------------------

def _daily(bars: _Bars, days: list[date]) -> dict:
    o, c, hi, lo, rets, gaps, dts = [], [], [], [], [], [], []
    prev_c = None
    for day in days:
        ws, we = day_window(day)
        i0, i1 = bars.idx(ws, we)
        if i1 <= i0:
            continue
        op, cl = bars.o[i0], bars.c[i1 - 1]
        if op <= 0 or cl <= 0:
            continue
        h = float(bars.h[i0:i1].max())
        l = float(bars.l[i0:i1].min())
        o.append(op); c.append(cl); hi.append(h); lo.append(l)
        rets.append(math.log(cl / op)); dts.append(day)
        gaps.append(math.log(op / prev_c) if prev_c and prev_c > 0 else float("nan"))
        prev_c = cl
    return {"open": np.array(o), "close": np.array(c), "high": np.array(hi),
            "low": np.array(lo), "ret": np.array(rets), "gap": np.array(gaps),
            "days": dts}


# --------------------------------------------------------------------------
# Intraday continuation (day open anchor) — reuse the session engine
# --------------------------------------------------------------------------

def _intraday_continuation(bars: _Bars, days: list[date], mu: float, sd: float) -> dict:
    cu, eu, pu, cd, ed, pd_ = [], [], [], [], [], []
    n = 0
    for day in days:
        ws, we = day_window(day)
        i0, i1 = bars.idx(ws, we)
        if i1 <= i0:
            continue
        p0 = bars.o[i0]
        if p0 <= 0:
            continue
        cc = np.log(bars.c[i0:i1] / p0)
        hc = np.log(bars.h[i0:i1] / p0)
        lc = np.log(bars.l[i0:i1] / p0)
        n += 1
        cu.append(float(cc[-1])); eu.append(float(hc.max())); pu.append((cc, hc, lc))
        cd.append(float(cc[-1])); ed.append(float(lc.min())); pd_.append((cc, hc, lc))
    return {"n_days": n, "up": _side_stats(mu, sd, cu, eu, True, pu),
            "down": _side_stats(mu, sd, cd, ed, False, pd_)}


# --------------------------------------------------------------------------
# Day-to-day transition + gaps + streaks
# --------------------------------------------------------------------------

def _day_to_day(ret: np.ndarray, mu: float, sd: float) -> list[dict]:
    up1, dn1 = mu + sd, mu - sd
    states = [
        ("strong_up", "prev > +1σ", lambda x: x > up1),
        ("mild_up", "prev 0…+1σ", lambda x: mu < x <= up1),
        ("mild_down", "prev −1σ…0", lambda x: dn1 <= x <= mu),
        ("strong_down", "prev < −1σ", lambda x: x < dn1),
    ]
    out = []
    for key, label, pred in states:
        nxt = np.array([ret[i] for i in range(1, len(ret))
                        if np.isfinite(ret[i - 1]) and pred(ret[i - 1])
                        and np.isfinite(ret[i])])
        if nxt.size == 0:
            out.append({"key": key, "label": label, "n": 0})
            continue
        out.append({"key": key, "label": label, "n": int(nxt.size),
                    "p_next_up": float(np.mean(nxt > 0)),
                    "p_next_gt_1sd": float(np.mean(nxt > up1)),
                    "p_next_lt_1sd": float(np.mean(nxt < dn1)),
                    "mean_next": float(np.mean(nxt))})
    return out


def _gaps(d: dict) -> dict:
    gap = d["gap"]
    g = gap[np.isfinite(gap)]
    if g.size < 5:
        return {"note": "insufficient data"}
    op, hi, lo, cl = d["open"], d["high"], d["low"], d["close"]
    # a gap "fills" if the day trades back to the prior close
    prev_c = op / np.exp(gap)           # reconstruct prior close
    up_mask = np.isfinite(gap) & (gap > 0)
    dn_mask = np.isfinite(gap) & (gap < 0)
    fill_up = (lo[up_mask] <= prev_c[up_mask]).mean() if up_mask.any() else float("nan")
    fill_dn = (hi[dn_mask] >= prev_c[dn_mask]).mean() if dn_mask.any() else float("nan")
    day_ret = d["ret"]
    cont_up = (day_ret[up_mask] > 0).mean() if up_mask.any() else float("nan")
    cont_dn = (day_ret[dn_mask] < 0).mean() if dn_mask.any() else float("nan")
    return {
        "dist": _dist(g),
        "p_gap_up": float(up_mask.mean()),
        "fill_prob_up": float(fill_up),
        "fill_prob_down": float(fill_dn),
        "continue_up": float(cont_up),
        "continue_down": float(cont_dn),
    }


def _streaks(ret: np.ndarray) -> dict:
    up = (ret > 0).astype(int)
    up = up[np.isfinite(ret)]
    if up.size < 10:
        return {"note": "insufficient data"}
    p_up = float(up.mean())
    prev_up = up[:-1] == 1
    p_up_given_up = float(up[1:][prev_up].mean()) if prev_up.any() else float("nan")
    two = (up[:-2] == 1) & (up[1:-1] == 1)
    p_up_given_2up = float(up[2:][two].mean()) if two.any() else float("nan")

    def longest(val):
        best = cur = 0
        for x in up:
            cur = cur + 1 if x == val else 0
            best = max(best, cur)
        return best
    return {"p_up": p_up, "p_up_given_up": p_up_given_up,
            "p_up_given_2up": p_up_given_2up,
            "longest_up": longest(1), "longest_down": longest(0)}


# --------------------------------------------------------------------------
# Performance ratios (daily)
# --------------------------------------------------------------------------

def _max_dd_duration(dd: np.ndarray) -> int:
    best = cur = 0
    for x in dd:
        cur = cur + 1 if x < 0 else 0
        best = max(best, cur)
    return best


def _performance(ret: np.ndarray) -> dict:
    r = ret[np.isfinite(ret)]
    if r.size < 20:
        return {"note": "insufficient data"}
    mu = float(r.mean()); sd = float(r.std(ddof=1))
    ann_ret = mu * TRADING_DAYS
    ann_vol = sd * math.sqrt(TRADING_DAYS)
    neg = r[r < 0]
    dsd = float(np.sqrt(np.mean(neg ** 2))) if neg.size else 0.0
    equity = np.exp(np.cumsum(r))
    peak = np.maximum.accumulate(equity)
    dd = equity / peak - 1.0
    max_dd = float(dd.min())
    q05, q01 = np.quantile(r, 0.05), np.quantile(r, 0.01)
    q95 = np.quantile(r, 0.95)
    pos, negs = r[r > 0], r[r < 0]
    gains, losses = float(pos.sum()), float(-negs.sum())
    return {
        "n_days": int(r.size),
        "ann_return": ann_ret, "ann_vol": ann_vol,
        "sharpe": ann_ret / ann_vol if ann_vol else None,
        "sortino": ann_ret / (dsd * math.sqrt(TRADING_DAYS)) if dsd else None,
        "calmar": ann_ret / abs(max_dd) if max_dd < 0 else None,
        "max_drawdown": max_dd,
        "max_dd_duration_days": _max_dd_duration(dd),
        "current_drawdown": float(dd[-1]),
        "var_95": float(-q05), "cvar_95": float(-r[r <= q05].mean()),
        "var_99": float(-q01), "cvar_99": float(-r[r <= q01].mean()),
        "win_rate": float((r > 0).mean()),
        "avg_win": float(pos.mean()) if pos.size else None,
        "avg_loss": float(negs.mean()) if negs.size else None,
        "profit_factor": gains / losses if losses else None,
        "omega_0": gains / losses if losses else None,
        "tail_ratio": abs(float(q95)) / abs(float(q05)) if q05 else None,
        "best_day": float(r.max()), "worst_day": float(r.min()),
        "pct_positive": float((r > 0).mean()),
        "skew": float(_dist(r).get("skew", float("nan"))),
    }


# --------------------------------------------------------------------------
# Quant character from libs/market_stats.py (optional deps)
# --------------------------------------------------------------------------

def _character(df: pd.DataFrame, name: str) -> dict:
    """The FULL libs/market_stats.market_metrics dict (every block —
    distribution, volatility, mean-reversion, sessions, calendar,
    probability) plus the libs/desk_card cards. Nothing curated away."""
    try:
        from libs.desk_card import desk_card
        from libs.market_stats import analyze as ms_analyze
    except Exception as e:                       # scipy/sklearn missing
        return {"note": f"quant character unavailable ({e})"}
    try:
        idx = pd.DatetimeIndex(df["Datetime"])
        ohlc = df[["Open", "High", "Low", "Close"]].copy()
        ohlc.index = idx
        ms = ms_analyze(ohlc, tz="UTC", name=name)
        metrics = ms.to_dict()                   # = market_metrics(...)
        cards = desk_card(metrics, print_out=False)
        return {"market_metrics": metrics,
                "character_report": ms.report(),
                "desk_card": cards}
    except Exception as e:                       # pragma: no cover
        return {"note": f"quant character failed ({e})"}


# --------------------------------------------------------------------------
# Public entry points
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
    d = _daily(bars, days)
    daily_dist = _dist(d["ret"])
    mu = daily_dist.get("mean", 0.0)
    sd = daily_dist.get("std", 0.0)

    result = {
        "asset": asset, "timeframe": tf,
        "n_bars": int(len(df)), "n_days": len(d["ret"]),
        "date_range": [days[0].isoformat(), days[-1].isoformat()],
        "available_range": list(full),
        "bands": BANDS,
        "daily_distribution": daily_dist,
        "intraday_continuation": _intraday_continuation(bars, days, mu, sd)
        if sd > 0 else {"note": "insufficient data"},
        "day_to_day": _day_to_day(d["ret"], mu, sd) if sd > 0 else [],
        "gaps": _gaps(d),
        "streaks": _streaks(d["ret"]),
        "performance": _performance(d["ret"]),
        "character": _character(df, f"{asset} {tf}"),
    }
    return _finite(result)
