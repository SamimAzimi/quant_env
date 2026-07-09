"""
intraday_profile.py
===================
Time-of-day microstructure profiling for intraday OHLCV data.

What it does (plain English)
----------------------------
Takes minute/tick-level bars, chops each trading day into fixed time
buckets (default 30 min), and asks four questions:

1. SHAPE      — For each time-of-day bucket, what is the average return,
                average range, realized volatility, and volume share?
2. EVENTS     — Where do session opens, closes, and scheduled news land on
                that clock? Event times are defined in their LOCAL timezone
                (e.g. 08:30 America/New_York) so DST is handled by zoneinfo;
                if the event's zone and the profiling zone shift on different
                dates, the event band is drawn at every position it occupies
                in the sample.
3. DAY TYPES  — Each day is classified three ways:
                * direction: bull / bear / flat (sign of the day's log return)
                * activity:  high / low volume (median split; falls back to
                  gross movement if there is no volume column)
                * character: trend / mixed / mean-revert via the efficiency
                  ratio ER = |sum of bucket returns| / sum of |bucket returns|.
                  Under a pure random walk with N buckets, E[ER] ~ 1/sqrt(N)
                  (~0.14 for 48 buckets). Defaults: trend if ER >= 2.0x that
                  baseline, mean-revert if ER <= 0.5x. Both multipliers are
                  parameters, and the resolved absolute thresholds are printed
                  on the report so the decision rule is explicit.
4. CONTRASTS  — The bucket profiles are recomputed conditionally so you can
                see how the intraday shape differs on bull vs bear days,
                high- vs low-volume days, and trend vs mean-reversion days.

Output is a single self-contained dark HTML report (charts embedded as
base64 PNGs — no CDN, no JS, opens anywhere).

Usage
-----
    from intraday_profile import build_report, make_demo_data
    build_report(df, "intraday_report.html")            # df: UTC OHLCV bars

    # or from the command line:
    python intraday_profile.py --demo --out intraday_report.html
    python intraday_profile.py --csv bars.csv --ts-col timestamp \
        --bucket 30 --tz America/New_York --out report.html

Input expectations: a DataFrame with a UTC DatetimeIndex (naive is assumed
UTC) or a timestamp column, and columns open/high/low/close (+ volume).
A single price column (close / price / mid) also works — OHLC per bucket is
then derived from first/max/min/last of that column.
"""
from __future__ import annotations

import argparse
import base64
import io
from dataclasses import dataclass, field
from datetime import date, datetime, time
from typing import Iterable, Sequence
from zoneinfo import ZoneInfo

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

try:
    from config.config import output_path
except ImportError:                       # script run from inside libs/
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from config.config import output_path

__all__ = [
    "EventWindow", "DEFAULT_EVENTS", "bucketize", "bucket_profile",
    "classify_days", "mean_cum_path", "event_positions", "build_report",
    "make_demo_data",
]

UTC = ZoneInfo("UTC")

# --------------------------------------------------------------------------
# Design tokens (shared by charts and the HTML shell)
# --------------------------------------------------------------------------
T = {
    "bg":      "#0B0E14",
    "panel":   "#121826",
    "border":  "#243047",
    "text":    "#D7DEE9",
    "muted":   "#8A94A6",
    "up":      "#34D399",
    "down":    "#F87171",
    "vol":     "#60A5FA",
    "range":   "#38BDF8",
    "volume":  "#A78BFA",
    "mixed":   "#94A3B8",
    "ev_open":  "#22D3EE",
    "ev_news":  "#FBBF24",
    "ev_close": "#C084FC",
}


# --------------------------------------------------------------------------
# Event windows
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class EventWindow:
    """A recurring intraday event, defined in its own LOCAL timezone.

    kind: 'open' | 'news' | 'close' (controls band colour).
    dates: optional collection of dates — restricts the event to specific
    days (e.g. FOMC decision dates); the band is still drawn, flagged as
    applying to a subset of the sample.
    """
    name: str
    tz: str
    start: time
    minutes: int = 30
    kind: str = "news"
    dates: frozenset = field(default=None)  # frozenset[date] | None


DEFAULT_EVENTS: tuple[EventWindow, ...] = (
    EventWindow("Tokyo open",   "Asia/Tokyo",       time(9, 0),  30, "open"),
    EventWindow("London open",  "Europe/London",    time(8, 0),  30, "open"),
    EventWindow("NY open",      "America/New_York", time(8, 0),  30, "open"),
    EventWindow("US data 08:30","America/New_York", time(8, 30), 15, "news"),
    EventWindow("NY cut 10:00", "America/New_York", time(10, 0), 15, "news"),
    EventWindow("London fix",   "Europe/London",    time(16, 0), 15, "news"),
    EventWindow("NY close",     "America/New_York", time(17, 0), 30, "close"),
)


def event_positions(event: EventWindow, days: Iterable[date],
                    anchor_tz: str) -> list[int]:
    """Minutes-after-midnight (in `anchor_tz`) where `event` lands across
    the sampled days. Usually one value; two when the event's zone and the
    anchor zone switch DST on different dates."""
    anchor = ZoneInfo(anchor_tz)
    days = list(days)
    if event.dates is not None:
        days = [d for d in days if d in event.dates] or days
    pos = set()
    for d in days:
        local = datetime.combine(d, event.start, tzinfo=ZoneInfo(event.tz))
        a = local.astimezone(anchor)
        pos.add(a.hour * 60 + a.minute)
    return sorted(pos)


# --------------------------------------------------------------------------
# Bucketing
# --------------------------------------------------------------------------

def _utc_index(df: pd.DataFrame, ts_col: str | None) -> pd.DatetimeIndex:
    idx = pd.DatetimeIndex(df[ts_col]) if ts_col else pd.DatetimeIndex(df.index)
    return idx.tz_localize("UTC") if idx.tz is None else idx.tz_convert("UTC")


def _detect_cols(df: pd.DataFrame) -> dict:
    low = {c.lower(): c for c in df.columns}
    out = {k: low[k] for k in ("open", "high", "low", "close", "volume") if k in low}
    if "close" not in out:
        for alias in ("price", "mid", "px", "last"):
            if alias in low:
                out["close"] = low[alias]
                break
    if "close" not in out:
        raise ValueError("need a close/price/mid column")
    return out


def bucketize(df: pd.DataFrame, bucket_minutes: int = 30, tz: str = "UTC",
              ts_col: str | None = None,
              day_roll: tuple[str, int] | None = None) -> pd.DataFrame:
    """Aggregate bars into fixed time-of-day buckets.

    tz        : timezone whose WALL CLOCK defines the buckets. Profile in
                'America/New_York' if your events are NY-anchored — US data
                then always lands in the same bucket regardless of DST.
    day_roll  : optional (tz, hour) defining the trading-day boundary, e.g.
                ('America/New_York', 17) for the conventional FX day. Default
                None = calendar date in `tz`.

    Returns one row per (day, bucket): day, tod (bucket-start minutes after
    midnight in `tz`), ts_first, open/high/low/close, volume, ret_bps,
    range_bps, vol_share.

    ret_bps is close-to-close between consecutive buckets of the same day
    (first bucket: open-to-close), so bucket returns SUM EXACTLY to the
    day's log return — cumulative paths and ER decompose cleanly.
    """
    if not 1 <= bucket_minutes <= 720 or 1440 % bucket_minutes:
        raise ValueError("bucket_minutes must divide 1440")
    idx = _utc_index(df, ts_col)
    cols = _detect_cols(df)
    loc = idx.tz_convert(tz)

    tod = (loc.hour * 60 + loc.minute).values // bucket_minutes * bucket_minutes
    if day_roll is not None:
        roll = idx.tz_convert(day_roll[0]) - pd.Timedelta(hours=day_roll[1])
        day = roll.date
    else:
        day = loc.date

    px = df[cols["close"]].values.astype(float)
    work = pd.DataFrame({
        "day": day, "tod": tod, "ts": idx,
        "open":  df[cols.get("open",  cols["close"])].values.astype(float),
        "high":  df[cols.get("high",  cols["close"])].values.astype(float),
        "low":   df[cols.get("low",   cols["close"])].values.astype(float),
        "close": px,
        "volume": (df[cols["volume"]].values.astype(float)
                   if "volume" in cols else np.nan),
    })
    b = (work.groupby(["day", "tod"], sort=True)
             .agg(ts_first=("ts", "first"), open=("open", "first"),
                  high=("high", "max"), low=("low", "min"),
                  close=("close", "last"), volume=("volume", "sum"))
             .reset_index()
             .sort_values(["day", "ts_first"], ignore_index=True))

    lc = np.log(b["close"])
    b["ret_bps"] = lc.groupby(b["day"]).diff() * 1e4
    first = b["ret_bps"].isna()
    b.loc[first, "ret_bps"] = np.log(b.loc[first, "close"] /
                                     b.loc[first, "open"]) * 1e4
    b["range_bps"] = (b["high"] - b["low"]) / b["open"] * 1e4
    day_vol = b.groupby("day")["volume"].transform("sum")
    b["vol_share"] = np.where(day_vol > 0, b["volume"] / day_vol, np.nan)
    return b


# --------------------------------------------------------------------------
# Per-bucket profile and day classification
# --------------------------------------------------------------------------

def bucket_profile(b: pd.DataFrame) -> pd.DataFrame:
    """Aggregate bucketized rows across days. Indexed by tod, columns:
    n, ret_mean, ret_se, t_stat, vol (std of bucket returns, bps),
    abs_ret, range_mean, vol_share (mean fraction of daily volume)."""
    g = b.groupby("tod")
    p = pd.DataFrame({
        "n": g["ret_bps"].count(),
        "ret_mean": g["ret_bps"].mean(),
        "vol": g["ret_bps"].std(ddof=1),
        "abs_ret": g["ret_bps"].apply(lambda s: s.abs().mean()),
        "range_mean": g["range_bps"].mean(),
        "vol_share": g["vol_share"].mean(),
    })
    p["ret_se"] = p["vol"] / np.sqrt(p["n"].clip(lower=1))
    p["t_stat"] = np.where(p["ret_se"] > 0, p["ret_mean"] / p["ret_se"], 0.0)
    return p.sort_index()


def classify_days(b: pd.DataFrame, *, trend_mult: float = 2.0,
                  revert_mult: float = 0.5,
                  direction_thr_bps: float = 0.0) -> tuple[pd.DataFrame, dict]:
    """One row per day with the three classifications.

    direction : 'bull' / 'bear' / 'flat' from the day's summed log return
                vs +-direction_thr_bps.
    activity  : 'high' / 'low' — median split on daily volume; if no usable
                volume, median split on gross movement (sum |ret|), and the
                basis is reported in the returned meta dict.
    character : 'trend' / 'mixed' / 'revert' from the efficiency ratio
                ER = |day_ret| / gross. Random-walk baseline 1/sqrt(N):
                trend if ER >= trend_mult * baseline, revert if
                ER <= revert_mult * baseline.
    Returns (days_frame, meta) where meta records every resolved threshold.
    """
    g = b.groupby("day")
    d = pd.DataFrame({
        "day_ret": g["ret_bps"].sum(),
        "gross": g["ret_bps"].apply(lambda s: s.abs().sum()),
        "volume": g["volume"].sum(min_count=1),
        "n_buckets": g["ret_bps"].count(),
    })
    d["er"] = np.where(d["gross"] > 0, d["day_ret"].abs() / d["gross"], 0.0)

    d["direction"] = np.select(
        [d["day_ret"] > direction_thr_bps, d["day_ret"] < -direction_thr_bps],
        ["bull", "bear"], default="flat")

    has_volume = d["volume"].notna().any() and np.nansum(d["volume"]) > 0
    basis = d["volume"] if has_volume else d["gross"]
    split = float(np.nanmedian(basis))
    d["activity"] = np.where(basis > split, "high", "low")

    baseline = 1.0 / np.sqrt(max(float(d["n_buckets"].median()), 1.0))
    thr_trend, thr_revert = trend_mult * baseline, revert_mult * baseline
    d["character"] = np.select(
        [d["er"] >= thr_trend, d["er"] <= thr_revert],
        ["trend", "revert"], default="mixed")

    meta = {
        "direction_thr_bps": direction_thr_bps,
        "activity_basis": "volume" if has_volume else "gross movement (bps)",
        "activity_split": split,
        "er_baseline_rw": baseline,
        "er_trend_thr": thr_trend,
        "er_revert_thr": thr_revert,
        "has_volume": has_volume,
    }
    return d, meta


def mean_cum_path(b: pd.DataFrame, days: Iterable[date],
                  bucket_minutes: int) -> pd.Series:
    """Average cumulative intraday return path (bps) over `days`, indexed
    by minutes since the day's first bucket."""
    sub = b[b["day"].isin(set(days))].sort_values(["day", "ts_first"])
    if sub.empty:
        return pd.Series(dtype=float)
    k = sub.groupby("day").cumcount()
    path = sub.groupby(k)["ret_bps"].mean().cumsum()
    path.index = path.index * bucket_minutes
    return path


# --------------------------------------------------------------------------
# Charts
# --------------------------------------------------------------------------

def _style():
    plt.rcParams.update({
        "figure.facecolor": T["panel"], "axes.facecolor": T["panel"],
        "savefig.facecolor": T["panel"], "text.color": T["text"],
        "axes.edgecolor": T["border"], "axes.labelcolor": T["muted"],
        "xtick.color": T["muted"], "ytick.color": T["muted"],
        "axes.grid": True, "grid.color": T["border"], "grid.alpha": 0.45,
        "grid.linewidth": 0.6, "font.size": 10.5, "axes.titlesize": 12,
        "axes.titleweight": "bold", "legend.frameon": False,
        "axes.spines.top": False, "axes.spines.right": False,
    })


def _tod_axis(ax, tz):
    ticks = np.arange(0, 1441, 120)
    ax.set_xticks(ticks)
    ax.set_xticklabels([f"{m // 60:02d}:00" for m in ticks])
    ax.set_xlim(-10, 1450)
    ax.set_xlabel(f"time of day ({tz})")


def _event_bands(ax, events, days, tz):
    seen = set()
    for ev in events:
        color = T[f"ev_{ev.kind}"]
        for pos in event_positions(ev, days, tz):
            ax.axvspan(pos, pos + ev.minutes, color=color, alpha=0.14, lw=0)
        if ev.kind not in seen:
            seen.add(ev.kind)
            ax.axvspan(np.nan, np.nan, color=color, alpha=0.35,
                       label=f"{ev.kind} windows")


def _fig_b64(fig) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=115, bbox_inches="tight")
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode()


def _chart_returns(p, events, days, tz):
    fig, ax = plt.subplots(figsize=(11.5, 3.6))
    colors = np.where(p["ret_mean"] >= 0, T["up"], T["down"])
    ax.bar(p.index, p["ret_mean"], width=0.8 * (p.index[1] - p.index[0]),
           color=colors, yerr=1.96 * p["ret_se"],
           error_kw={"ecolor": T["muted"], "elinewidth": 0.8, "capsize": 0})
    ax.axhline(0, color=T["muted"], lw=0.8)
    _event_bands(ax, events, days, tz)
    _tod_axis(ax, tz)
    ax.set_ylabel("bps")
    ax.set_title("Mean return per bucket (±1.96·SE) — bars clearing the whisker are the |t|≥2 buckets")
    ax.legend(loc="upper right", ncols=3, fontsize=9)
    return _fig_b64(fig)


def _chart_vol_range(p, events, days, tz):
    fig, ax = plt.subplots(figsize=(11.5, 3.6))
    ax.plot(p.index, p["vol"], color=T["vol"], lw=2.0,
            label="realized vol (std of bucket ret)")
    ax.plot(p.index, p["range_mean"], color=T["range"], lw=1.4, ls="--",
            label="mean high-low range")
    _event_bands(ax, events, days, tz)
    _tod_axis(ax, tz)
    ax.set_ylabel("bps")
    ax.set_title("Volatility and range by time of day")
    ax.legend(loc="upper right", ncols=2, fontsize=9)
    return _fig_b64(fig)


def _chart_volume(p, events, days, tz):
    fig, ax = plt.subplots(figsize=(11.5, 3.3))
    ax.bar(p.index, p["vol_share"] * 100,
           width=0.8 * (p.index[1] - p.index[0]), color=T["volume"])
    _event_bands(ax, events, days, tz)
    _tod_axis(ax, tz)
    ax.set_ylabel("% of daily volume")
    ax.set_title("Volume shape (mean share of the day's volume)")
    return _fig_b64(fig)


def _chart_cum_paths(b, dcls, bucket_minutes):
    fig, ax = plt.subplots(figsize=(11.5, 3.8))
    spec = [("bull", T["up"]), ("bear", T["down"]), ("flat", T["mixed"])]
    for label, color in spec:
        days = dcls.index[dcls["direction"] == label]
        if len(days) == 0:
            continue
        path = mean_cum_path(b, days, bucket_minutes)
        ax.plot(path.index, path.values, color=color, lw=2.0,
                label=f"{label} days (n={len(days)})")
    ax.axhline(0, color=T["muted"], lw=0.8)
    ax.set_xlabel("minutes since day start")
    ax.set_ylabel("cumulative bps")
    ax.set_title("Average intraday path — bullish vs bearish days (when the day's edge accrues)")
    ax.legend(loc="upper left", fontsize=9)
    return _fig_b64(fig)


def _chart_activity_volume(b, dcls, meta, events, days, tz):
    fig, ax = plt.subplots(figsize=(11.5, 3.6))
    for label, color in (("high", T["volume"]), ("low", T["mixed"])):
        dd = dcls.index[dcls["activity"] == label]
        if len(dd) == 0:
            continue
        pp = bucket_profile(b[b["day"].isin(set(dd))])
        y = (pp["vol_share"] * 100) if meta["has_volume"] else pp["vol"]
        ax.plot(pp.index, y, color=color, lw=2.0,
                label=f"{label}-{'volume' if meta['has_volume'] else 'activity'} days (n={len(dd)})")
    _event_bands(ax, events, days, tz)
    _tod_axis(ax, tz)
    ax.set_ylabel("% of daily volume" if meta["has_volume"] else "bps")
    ax.set_title("Intraday shape: high- vs low-volume days")
    ax.legend(loc="upper right", fontsize=9)
    return _fig_b64(fig)


def _chart_character_vol(b, dcls, events, days, tz):
    fig, ax = plt.subplots(figsize=(11.5, 3.6))
    spec = [("trend", T["up"]), ("mixed", T["mixed"]), ("revert", T["down"])]
    for label, color in spec:
        dd = dcls.index[dcls["character"] == label]
        if len(dd) == 0:
            continue
        pp = bucket_profile(b[b["day"].isin(set(dd))])
        ax.plot(pp.index, pp["vol"], color=color, lw=2.0,
                label=f"{label} days (n={len(dd)})")
    _event_bands(ax, events, days, tz)
    _tod_axis(ax, tz)
    ax.set_ylabel("bps")
    ax.set_title("Realized vol by time of day: trend vs mean-reversion days")
    ax.legend(loc="upper right", fontsize=9)
    return _fig_b64(fig)


# --------------------------------------------------------------------------
# HTML report
# --------------------------------------------------------------------------

_CARD = """<div class="card"><div class="k">{title}</div>{rows}</div>"""
_ROW = """<div class="r"><span>{k}</span><b>{v}</b></div>"""

_PAGE = """<!doctype html><html><head><meta charset="utf-8">
<title>{title}</title><style>
:root {{ color-scheme: dark; }}
body {{ background:{bg}; color:{text}; margin:0;
  font:14px/1.5 -apple-system,'Segoe UI',Roboto,sans-serif; }}
.wrap {{ max-width:1180px; margin:0 auto; padding:28px 22px 60px; }}
h1 {{ font-size:21px; margin:0 0 2px; letter-spacing:.3px; }}
.sub {{ color:{muted}; font-size:12.5px; margin-bottom:22px;
  font-family:ui-monospace,'SF Mono',Menlo,Consolas,monospace; }}
.cards {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(250px,1fr));
  gap:12px; margin-bottom:26px; }}
.card {{ background:{panel}; border:1px solid {border}; border-radius:10px;
  padding:13px 15px; }}
.card .k {{ color:{muted}; font-size:11px; text-transform:uppercase;
  letter-spacing:.12em; margin-bottom:8px; }}
.card .r {{ display:flex; justify-content:space-between; gap:10px;
  padding:2.5px 0; font-size:13px; }}
.card .r b {{ font-family:ui-monospace,'SF Mono',Menlo,Consolas,monospace;
  font-weight:600; color:{text}; text-align:right; }}
h2 {{ font-size:13px; color:{muted}; text-transform:uppercase;
  letter-spacing:.14em; margin:30px 0 10px; }}
.fig {{ background:{panel}; border:1px solid {border}; border-radius:10px;
  padding:10px; }}
.fig img {{ width:100%; display:block; border-radius:6px; }}
.note {{ color:{muted}; font-size:12px; margin-top:6px; }}
</style></head><body><div class="wrap">
<h1>{title}</h1><div class="sub">{subtitle}</div>
<div class="cards">{cards}</div>
{sections}
</div></body></html>"""


def _fmt_bucket(m: int) -> str:
    return f"{m // 60:02d}:{m % 60:02d}"


def _cards_html(b, p, dcls, meta, tz, bucket_minutes, events) -> str:
    n_days = len(dcls)
    vc_dir = dcls["direction"].value_counts()
    vc_act = dcls["activity"].value_counts()
    vc_chr = dcls["character"].value_counts()
    hot = p["vol"].nlargest(3)
    sig = p[np.abs(p["t_stat"]) >= 2.0].sort_values("t_stat")

    cards = []
    cards.append(_CARD.format(title="Sample", rows="".join([
        _ROW.format(k="days", v=n_days),
        _ROW.format(k="buckets/day", v=f"{int(p['n'].count())} × {bucket_minutes}m"),
        _ROW.format(k="clock", v=tz),
        _ROW.format(k="span", v=f"{min(dcls.index)} → {max(dcls.index)}"),
    ])))
    cards.append(_CARD.format(title="Direction", rows="".join([
        _ROW.format(k="bull / bear / flat",
                    v=f"{vc_dir.get('bull',0)} / {vc_dir.get('bear',0)} / {vc_dir.get('flat',0)}"),
        _ROW.format(k="median |day ret|", v=f"{dcls['day_ret'].abs().median():.1f} bps"),
        _ROW.format(k="threshold", v=f"±{meta['direction_thr_bps']:.1f} bps"),
    ])))
    cards.append(_CARD.format(title="Activity", rows="".join([
        _ROW.format(k="high / low", v=f"{vc_act.get('high',0)} / {vc_act.get('low',0)}"),
        _ROW.format(k="basis", v=meta["activity_basis"]),
        _ROW.format(k="median split", v=f"{meta['activity_split']:,.0f}"),
    ])))
    cards.append(_CARD.format(title="Character (efficiency ratio)", rows="".join([
        _ROW.format(k="trend / mixed / revert",
                    v=f"{vc_chr.get('trend',0)} / {vc_chr.get('mixed',0)} / {vc_chr.get('revert',0)}"),
        _ROW.format(k="RW baseline 1/√N", v=f"{meta['er_baseline_rw']:.3f}"),
        _ROW.format(k="trend if ER ≥", v=f"{meta['er_trend_thr']:.3f}"),
        _ROW.format(k="revert if ER ≤", v=f"{meta['er_revert_thr']:.3f}"),
    ])))
    cards.append(_CARD.format(title="Hottest buckets (realized vol)", rows="".join(
        _ROW.format(k=_fmt_bucket(m), v=f"{v:.1f} bps") for m, v in hot.items())))
    sig_rows = ("".join(_ROW.format(k=_fmt_bucket(m),
                                    v=f"{r.ret_mean:+.2f} bps  t={r.t_stat:+.1f}")
                for m, r in sig.iterrows())
                or _ROW.format(k="none", v="—"))
    cards.append(_CARD.format(title="Watchlist: |t| ≥ 2 mean-return buckets",
                              rows=sig_rows))
    return "".join(cards)


def build_report(df: pd.DataFrame, out_html: str, *, bucket_minutes: int = 30,
                 tz: str = "UTC", ts_col: str | None = None,
                 day_roll: tuple[str, int] | None = None,
                 events: Sequence[EventWindow] = DEFAULT_EVENTS,
                 title: str = "Intraday time-of-day profile",
                 trend_mult: float = 2.0, revert_mult: float = 0.5,
                 direction_thr_bps: float = 0.0) -> str:
    """End to end: bucketize -> profile -> classify -> render HTML report.
    Returns the output path."""
    _style()
    b = bucketize(df, bucket_minutes, tz, ts_col=ts_col, day_roll=day_roll)
    p = bucket_profile(b)
    dcls, meta = classify_days(b, trend_mult=trend_mult,
                               revert_mult=revert_mult,
                               direction_thr_bps=direction_thr_bps)
    days = list(dcls.index)

    sections = []
    def add(name, img_b64, note=""):
        note_html = f'<div class="note">{note}</div>' if note else ""
        sections.append(f'<h2>{name}</h2><div class="fig">'
                        f'<img src="data:image/png;base64,{img_b64}">'
                        f'{note_html}</div>')

    add("Bucket returns", _chart_returns(p, events, days, tz),
        "Shaded bands: cyan = session opens, amber = scheduled news, violet = closes. "
        "Two bands for one event mean its home timezone and the profile clock switch DST on different dates.")
    add("Volatility &amp; range", _chart_vol_range(p, events, days, tz))
    if meta["has_volume"]:
        add("Volume shape", _chart_volume(p, events, days, tz))
    add("Bull vs bear days", _chart_cum_paths(b, dcls, bucket_minutes))
    add("High vs low volume days",
        _chart_activity_volume(b, dcls, meta, events, days, tz))
    add("Trend vs mean-reversion days",
        _chart_character_vol(b, dcls, events, days, tz))

    n_days = len(dcls)
    html = _PAGE.format(
        title=title,
        subtitle=(f"{n_days} days · {bucket_minutes}-min buckets · clock {tz}"
                  + (f" · day roll {day_roll[0]} {day_roll[1]:02d}:00" if day_roll else "")
                  + f" · generated {datetime.now(UTC):%Y-%m-%d %H:%M UTC}"),
        cards=_cards_html(b, p, dcls, meta, tz, bucket_minutes, events),
        sections="".join(sections),
        **{k: T[k] for k in ("bg", "panel", "border", "text", "muted")},
    )
    out_html = output_path(out_html)      # relative names land in output/
    with open(out_html, "w") as f:
        f.write(html)
    return out_html


# --------------------------------------------------------------------------
# Synthetic demo data (for testing the pipeline end to end)
# --------------------------------------------------------------------------

def make_demo_data(n_days: int = 240, seed: int = 7,
                   start: str = "2025-01-06") -> pd.DataFrame:
    """Minute FX-like bars with known structure the report should recover:
    vol humps at London/NY opens, a 12:30 UTC news spike on ~40% of days,
    a quiet Asian afternoon, U-shaped volume, and a mix of drift (trend),
    OU (mean-revert), and random-walk days."""
    rng = np.random.default_rng(seed)
    days = pd.bdate_range(start, periods=n_days)
    minutes = np.arange(1440)

    volmap = np.full(1440, 0.55)                       # bps per minute
    volmap[0:6 * 60] *= 0.65                           # Asia overnight
    volmap[7 * 60:10 * 60] *= 2.1                      # London open
    volmap[12 * 60 + 30 - 10:16 * 60] *= 1.8           # NY morning
    volmap[21 * 60:] *= 0.6

    frames = []
    px = 1.0800
    for d in days:
        u = rng.uniform()
        kind = "trend" if u < 0.25 else ("revert" if u < 0.50 else "rw")
        vol = volmap * rng.lognormal(0, 0.15)
        news = rng.uniform() < 0.4
        if news:
            vol[12 * 60 + 30:12 * 60 + 45] *= 4.0
        eps = rng.standard_normal(1440) * vol * 1e-4
        if kind == "trend":
            eps += np.sign(rng.standard_normal()) * 0.055 * 1e-4
        logp = np.log(px) + np.cumsum(eps)
        if kind == "revert":
            k = np.exp(-minutes / 300)                  # pull back toward open
            logp = np.log(px) + (logp - np.log(px)) * (1 - 0.85 * (minutes / 1439))
        close = np.exp(logp)
        opens = np.concatenate([[px], close[:-1]])
        spread = np.abs(rng.standard_normal(1440)) * vol * 0.6e-4 * opens
        high = np.maximum(opens, close) + spread
        low = np.minimum(opens, close) - spread
        volume = (vol ** 2) * rng.lognormal(0, 0.35, 1440) * 900
        volume *= rng.lognormal(0, 0.5)                 # day-level regime
        ts = pd.date_range(d, periods=1440, freq="min", tz="UTC")
        frames.append(pd.DataFrame({"open": opens, "high": high, "low": low,
                                    "close": close, "volume": volume}, index=ts))
        px = close[-1]
    return pd.concat(frames)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(description="Intraday time-of-day profiler")
    ap.add_argument("--csv", help="input CSV of intraday bars")
    ap.add_argument("--ts-col", default=None, help="timestamp column (default: index/first)")
    ap.add_argument("--demo", action="store_true", help="use synthetic demo data")
    ap.add_argument("--bucket", type=int, default=30, help="bucket size, minutes")
    ap.add_argument("--tz", default="UTC", help="wall clock defining the buckets")
    ap.add_argument("--day-roll", default=None,
                    help="trading-day boundary as tz:hour, e.g. America/New_York:17")
    ap.add_argument("--out", default="intraday_report.html")
    a = ap.parse_args(argv)

    if a.demo:
        df = make_demo_data()
    elif a.csv:
        df = pd.read_csv(a.csv)
        ts = a.ts_col or df.columns[0]
        df[ts] = pd.to_datetime(df[ts], utc=True)
        df = df.set_index(ts)
        a.ts_col = None
    else:
        ap.error("provide --csv or --demo")

    roll = None
    if a.day_roll:
        z, h = a.day_roll.rsplit(":", 1)
        roll = (z, int(h))
    out = build_report(df, a.out, bucket_minutes=a.bucket, tz=a.tz,
                       ts_col=a.ts_col, day_roll=roll)
    print(f"report written: {out}")


if __name__ == "__main__":
    main()