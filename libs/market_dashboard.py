"""
market_dashboard.py
===================
Interactive visual dashboard for the `market_stats` character reports.

Takes one or many OHLC assets, runs `MarketStats` on each, and writes a single
self-contained HTML file you open in any browser. Charts render with Plotly.js
loaded from a CDN, so there is **nothing extra to pip-install** — the only
runtime dependency beyond `market_stats` is a browser with internet access (for
the CDN). Pass `inline_plotly=True` if you need a fully offline file.

Design goals
------------
* **Every metric group is shown** — distribution, volatility, memory, sessions,
  calendar, probability and regimes each get their own tab.
* **Similar magnitudes are packed together.** Metrics that live on the same scale
  or measure the same thing share a chart so you read them in context:
    - mean + std + the 1/5/25/50/75/95/99% quantiles -> one "return quantile fan"
      (all in log-return units; this is the signature view you asked for)
    - the five annualised vol estimators -> one grouped bar
    - GARCH alpha/beta/persistence (all 0..1) -> one chart
    - Hurst + DFA (both ~0.5) -> one chart, etc.
* **Multiple assets compare everywhere.** Each asset gets a fixed colour used on
  every chart; a chip row at the top toggles assets in/out of *all* charts at once.

Quick start
-----------
    import pandas as pd
    from market_dashboard import build_dashboard

    data = {
        "EURUSD H1": pd.read_csv("EURUSD_H1.csv", parse_dates=["time"], index_col="time"),
        "GBPJPY H1": pd.read_csv("GBPJPY_H1.csv", parse_dates=["time"], index_col="time"),
    }
    build_dashboard(data, output="dashboard.html")   # opens in your browser

`build_dashboard` accepts a single DataFrame too, or a dict of name -> DataFrame.
Any keyword it doesn't recognise is forwarded to `MarketStats` (e.g. tz="UTC").

Run this file directly for a three-asset synthetic demo:  python market_dashboard.py
"""

from __future__ import annotations

import json
import math
import os
import webbrowser
from typing import Mapping

import numpy as np
import pandas as pd

from .market_stats import MarketStats
from config.config import PALETTE, _PLOTLY_CDN, output_path



# ----------------------------------------------------------------------
# JSON sanitising — Plotly/JSON cannot carry NaN/Infinity or numpy scalars
# ----------------------------------------------------------------------

def _clean(obj):
    """Recursively convert a metrics tree into JSON-safe primitives.

    NaN / +-Inf -> None, numpy scalars/arrays -> python, tuples -> lists.
    """
    if obj is None:
        return None
    if isinstance(obj, (bool, str, int)):
        return obj
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, (np.floating,)):
        v = float(obj)
        return v if math.isfinite(v) else None
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, np.ndarray):
        return [_clean(x) for x in obj.tolist()]
    if isinstance(obj, Mapping):
        return {str(k): _clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [_clean(x) for x in obj]
    # last resort: stringify unknown objects (e.g. Timestamps that slipped through)
    try:
        v = float(obj)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return str(obj)


# ----------------------------------------------------------------------
# Public entry point
# ----------------------------------------------------------------------

def build_dashboard(data, output="market_dashboard.html", title="Market Character Dashboard",
                    open_browser=True, inline_plotly=False, **stats_kwargs) -> str:
    """Build the HTML dashboard for one or many assets.

    Parameters
    ----------
    data : DataFrame | dict[str, DataFrame]
        A single OHLC frame, or a mapping of asset label -> OHLC frame.
    output : str
        Path of the HTML file to write. Relative paths land in the project
        output/ folder (config.paths.OUTPUT_DIR).
    title : str
        Page title / header.
    open_browser : bool
        Open the file in the default browser when done.
    inline_plotly : bool
        Embed plotly.js in the file (large, but works fully offline) instead of
        linking the CDN.
    **stats_kwargs
        Forwarded to MarketStats (e.g. tz, periods_per_year, session_windows).

    Returns
    -------
    str : the absolute path of the written HTML file.
    """
    if isinstance(data, pd.DataFrame):
        data = {stats_kwargs.pop("name", "instrument"): data}
    if not isinstance(data, Mapping) or not data:
        raise ValueError("data must be a DataFrame or a non-empty {name: DataFrame} mapping")

    reports = {}
    for name, df in data.items():
        kw = dict(stats_kwargs)
        kw.setdefault("name", name)
        reports[name] = MarketStats(df, **kw).to_dict()

    assets = list(reports.keys())
    colors = {a: PALETTE[i % len(PALETTE)] for i, a in enumerate(assets)}

    payload = {
        "title": title,
        "assets": assets,
        "colors": colors,
        "reports": _clean(reports),
    }
    payload_json = json.dumps(payload, allow_nan=False).replace("</", "<\\/")

    if inline_plotly:
        plotly_tag = _inline_plotly_tag()
    else:
        plotly_tag = f'<script src="{_PLOTLY_CDN}" charset="utf-8"></script>'

    html = (_TEMPLATE
            .replace("/*__PAYLOAD__*/", payload_json)
            .replace("<!--__PLOTLY__-->", plotly_tag)
            .replace("__TITLE__", _esc(title)))

    out_path = output_path(output)
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(html)

    if open_browser:
        try:
            webbrowser.open("file://" + out_path)
        except Exception:
            pass
    return out_path


def _esc(s: str) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def _inline_plotly_tag() -> str:
    """Best-effort inline of a locally installed plotly.js for offline files."""
    try:
        import plotly  # noqa
        from plotly.offline import get_plotlyjs
        return "<script>" + get_plotlyjs() + "</script>"
    except Exception:
        # fall back to CDN if plotly isn't installed locally
        return f'<script src="{_PLOTLY_CDN}" charset="utf-8"></script>'


# The big HTML/CSS/JS template lives in its own module to keep this file readable.
from ._dashboard_template import TEMPLATE as _TEMPLATE  # noqa: E402


# ----------------------------------------------------------------------
# Synthetic multi-asset demo
# ----------------------------------------------------------------------

def _synth_asset(seed, n_days=180, base=1.10, ann_size=6e-4,
                 omega=0.02, alpha=0.08, beta=0.90, reversion=0.05,
                 drift=0.0, tail_boost=0.0):
    """Generate one synthetic hourly FX-like OHLCV frame with controllable
    volatility clustering, an intraday London/NY bump, drift and tail weight."""
    rng = np.random.default_rng(seed)
    hours = pd.date_range("2024-01-01", periods=n_days * 24, freq="h", tz="UTC")
    hours = hours[hours.dayofweek < 5]
    n = len(hours)

    z = rng.standard_normal(n)
    if tail_boost > 0:  # mix in heavier tails
        z = z + tail_boost * rng.standard_t(3, size=n)
    var = np.empty(n)
    ret = np.empty(n)
    var[0] = 1.0
    for t in range(n):
        if t > 0:
            var[t] = omega + alpha * ret[t - 1] ** 2 + beta * var[t - 1]
        ret[t] = np.sqrt(var[t]) * z[t]

    hod = hours.hour.to_numpy()
    bump = np.where((hod >= 7) & (hod < 21), 1.4, 0.6)
    ret = ret / np.std(ret) * ann_size * bump
    for t in range(1, n):
        ret[t] -= reversion * ret[t - 1]
    ret = ret + drift

    close = base * np.exp(np.cumsum(ret))
    open_ = np.concatenate([[close[0]], close[:-1]])
    wick = np.abs(rng.normal(0, 1, n)) * ann_size * bump
    high = np.maximum(open_, close) + wick
    low = np.minimum(open_, close) - wick
    volume = (1000 * bump * (1 + np.abs(z))).round()
    return pd.DataFrame({"open": open_, "high": high, "low": low,
                         "close": close, "volume": volume}, index=hours)


def _demo():
    data = {
        "EURUSD H1": _synth_asset(7, ann_size=5e-4, alpha=0.06, beta=0.92,
                                  reversion=0.07, drift=2e-6),
        "GBPJPY H1": _synth_asset(11, ann_size=1.1e-3, alpha=0.12, beta=0.85,
                                  reversion=0.02, drift=-3e-6),
        "XAUUSD H1": _synth_asset(19, base=2000.0, ann_size=9e-4, alpha=0.10,
                                  beta=0.88, reversion=0.0, tail_boost=0.4),
    }
    path = build_dashboard(data, output="market_dashboard.html",
                           title="Market Character Dashboard — Demo",
                           open_browser=False)
    print("wrote", path)
    return path


if __name__ == "__main__":
    _demo()