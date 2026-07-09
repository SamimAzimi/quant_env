"""
tv_chart.py — schema-agnostic TradingView (Lightweight Charts) panel for the
backtest dashboard.

Drop next to dashboard.py and call `tradingview_panel(...)` from the Run-detail
tab (see the integration snippet at the bottom of this file).

WHY THIS IS NOT HARDCODED
─────────────────────────
Nothing about a strategy's trade schema is baked in. Given a trades DataFrame,
`classify_trade_columns()` buckets every column by *shape*, not name:

  • datetime-ish columns  -> marker layers  (a flag/arrow at that bar)
  • numeric price-level columns -> horizontal segments across the trade's span
  • a `side`-like column (if any) -> orients entry arrows (optional)
  • everything else -> tooltip / table metadata

Name patterns are used only to *discover* and *style* columns. A column is only
drawn as a price level if its values actually fall inside the candle price range,
so multipliers / counts that merely match a name pattern (e.g. atr_sl_multiple,
bars_to_entry) are excluded automatically. A new strategy with new columns just
shows up as new toggles — no code changes.

PREREQUISITE: OHLC bars
───────────────────────
The store keeps results, not candles. `load_prices()` is the single adapter you
point at your price data (defaults to a CSV per asset+timeframe). If no bars are
found the panel still plots a fallback price path built from the trade fills, so
you always see something — just clearly labelled.

Lightweight Charts version is pinned to v4 (stable standalone API:
addCandlestickSeries / setMarkers / createPriceLine). v5 changed the series API.
"""
from __future__ import annotations

import json
import os
import re
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from config.config import LWC_CDN,_TIME_NAME,_LEVEL_NAME




# ─────────────────────────────────────────────────────────────────────────────
# Classification
# ─────────────────────────────────────────────────────────────────────────────

def _dt(s):
    """pd.to_datetime(errors='coerce') without the noisy 'could not infer format' warning."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return pd.to_datetime(s, errors="coerce")


def _looks_datetime(s: pd.Series, name: str | None = None) -> bool:
    if pd.api.types.is_datetime64_any_dtype(s):
        return True
    if not (pd.api.types.is_object_dtype(s) or pd.api.types.is_string_dtype(s)):
        return False
    sample = s.dropna()
    if sample.empty:
        return False
    # only parse strings that plausibly hold a date — avoids the warning and
    # misreading code-like columns ('TP', 'long', trade ids) as datetimes
    if not (name and _TIME_NAME.search(name)):
        head = sample.head(20).astype(str)
        if not head.str.contains(r"[-/:]", regex=True).any():
            return False
    parsed = _dt(sample)
    return float(parsed.notna().mean()) >= 0.5


def classify_trade_columns(trades: pd.DataFrame) -> dict:
    """Bucket trade columns by shape. Returns {time, level, side, other}."""
    time_cols, level_cols, other = [], [], []
    side_col = None
    for col in trades.columns:
        s = trades[col]
        if _looks_datetime(s, col):
            time_cols.append(col)
        elif pd.api.types.is_numeric_dtype(s) and _LEVEL_NAME.search(col):
            level_cols.append(col)
        else:
            if side_col is None and re.search(r"(^|_)(side|direction|dir)(_|$)", col, re.I):
                side_col = col
            other.append(col)
    return {"time": time_cols, "level": level_cols, "side": side_col, "other": other}


# ─────────────────────────────────────────────────────────────────────────────
# Styling per column role (purely cosmetic; derived from the name)
# ─────────────────────────────────────────────────────────────────────────────

def _role(col: str) -> dict:
    c = col.lower()
    if re.search(r"(^|_)(sl|stop)(_|$)", c):
        return dict(line="#ef5350", dash=2, shape="square", pos="inBar", color="#ef5350")
    if re.search(r"(^|_)(tp|target|take)(_|$)", c):
        return dict(line="#26a69a", dash=2, shape="square", pos="inBar", color="#26a69a")
    if "entry" in c:
        return dict(line="#5b8def", dash=0, shape="arrowUp", pos="belowBar", color="#5b8def")
    if "exit" in c:
        return dict(line="#9aa4b2", dash=0, shape="arrowDown", pos="aboveBar", color="#cbd5e1")
    if "setup" in c or "choch" in c:
        return dict(line="#c084fc", dash=1, shape="circle", pos="inBar", color="#c084fc")
    if "fib" in c:
        return dict(line="#f0b429", dash=1, shape="circle", pos="inBar", color="#f0b429")
    return dict(line="#f0b429", dash=1, shape="circle", pos="inBar", color="#f0b429")


def _pretty(col: str) -> str:
    return col.replace("_", " ").strip()


# ─────────────────────────────────────────────────────────────────────────────
# Time / candle helpers  (Lightweight Charts wants UTC *seconds* for intraday)
# ─────────────────────────────────────────────────────────────────────────────

def _epoch(ts) -> int | None:
    try:
        t = pd.Timestamp(ts)
    except (ValueError, TypeError):
        return None
    if t is pd.NaT or pd.isna(t):
        return None
    if t.tz is not None:
        t = t.tz_convert("UTC").tz_localize(None)
    return int(t.value // 1_000_000_000)


def _f(x):
    """float() if finite else None (keeps payload JSON-valid: no NaN/Inf)."""
    try:
        v = float(x)
    except (ValueError, TypeError):
        return None
    return v if np.isfinite(v) else None


def detect_ohlc_columns(df: pd.DataFrame) -> dict | None:
    """Best-effort detection of time + O/H/L/C columns by name."""
    cols = {c.lower(): c for c in df.columns}

    def pick(*names):
        for n in names:
            if n in cols:
                return cols[n]
        return None

    tcol = None
    for c in df.columns:
        if _looks_datetime(df[c], c):
            tcol = c
            break
    tcol = tcol or pick("time", "date", "datetime", "timestamp")
    o = pick("open", "o")
    h = pick("high", "h")
    l = pick("low", "l")
    c = pick("close", "c", "adj close", "adj_close")
    if tcol and o and h and l and c:
        return {"time": tcol, "open": o, "high": h, "low": l, "close": c}
    return None


def build_candles(prices: pd.DataFrame, ohlc: dict, t0: int | None = None, t1: int | None = None):
    """OHLC DataFrame -> list[{time,open,high,low,close}] (sorted, unique, JSON-native)."""
    o, h, l, c = ohlc["open"], ohlc["high"], ohlc["low"], ohlc["close"]
    d = prices[[ohlc["time"], o, h, l, c]].copy()
    t = _dt(d[ohlc["time"]])
    mask = t.notna()
    d, t = d[mask], t[mask]
    if getattr(t.dt, "tz", None) is not None:
        t = t.dt.tz_convert("UTC").dt.tz_localize(None)
    ep = (t.astype("int64") // 1_000_000_000).to_numpy()
    cd = pd.DataFrame({
        "time": ep,
        "open": d[o].to_numpy(), "high": d[h].to_numpy(),
        "low": d[l].to_numpy(), "close": d[c].to_numpy(),
    }).sort_values("time").drop_duplicates("time", keep="last")
    if t0 is not None:
        cd = cd[cd["time"] >= t0]
    if t1 is not None:
        cd = cd[cd["time"] <= t1]
    out = []
    for r in cd.itertuples(index=False):
        vals = [_f(r.open), _f(r.high), _f(r.low), _f(r.close)]
        if any(v is None for v in vals):
            continue
        out.append({"time": int(r.time), "open": vals[0], "high": vals[1], "low": vals[2], "close": vals[3]})
    return out


def _snap(ep_sorted: np.ndarray, t: int) -> int:
    if ep_sorted.size == 0:
        return t
    i = int(np.searchsorted(ep_sorted, t, side="right")) - 1
    return int(ep_sorted[max(i, 0)])


# ─────────────────────────────────────────────────────────────────────────────
# Overlays: markers (per time col) + segments (per in-range level col)
# ─────────────────────────────────────────────────────────────────────────────

def build_overlays(trades: pd.DataFrame, classes: dict, grid_epochs: np.ndarray,
                   price_lo: float, price_hi: float,
                   markers_on: list, levels_on: list,
                   side_col: str | None, id_col: str | None):
    grid = np.sort(np.asarray(grid_epochs, dtype="int64")) if grid_epochs is not None else np.array([], dtype="int64")
    interval = int(np.median(np.diff(grid))) if grid.size > 1 else 3600
    markers, segments = [], []

    for _, row in trades.iterrows():
        tid = row[id_col] if id_col and id_col in row else None
        # all event times present on this row
        times = {col: _epoch(row[col]) for col in classes["time"] if col in row and pd.notna(row[col])}
        times = {k: v for k, v in times.items() if v is not None}
        span_lo = min(times.values()) if times else None
        span_hi = max(times.values()) if times else None
        if span_lo is not None and span_lo == span_hi:
            span_hi = span_lo + 3 * interval  # extend a point so the segment is visible

        side_val = str(row[side_col]).lower() if side_col and side_col in row and pd.notna(row[side_col]) else ""

        # markers — one per enabled time column
        for col in markers_on:
            if col not in times:
                continue
            st_ = _role(col)
            pos, shape = st_["pos"], st_["shape"]
            if "entry" in col.lower() and side_val in ("short", "sell", "s", "-1", "down"):
                pos, shape = "aboveBar", "arrowDown"
            txt = _pretty(col) + (f" · {tid}" if tid is not None else "")
            markers.append({"time": _snap(grid, times[col]), "position": pos,
                            "color": st_["color"], "shape": shape, "text": txt})

        # segments — one per enabled, in-range level column
        if span_lo is not None:
            for col in levels_on:
                if col not in row:
                    continue
                v = _f(row[col])
                if v is None or not (price_lo <= v <= price_hi):
                    continue
                st_ = _role(col)
                a, b = _snap(grid, span_lo), _snap(grid, span_hi)
                if a == b:
                    b = a + interval
                segments.append({
                    "title": _pretty(col), "color": st_["line"], "dash": st_["dash"],
                    "data": [{"time": a, "value": v}, {"time": b, "value": v}],
                })

    markers.sort(key=lambda m: m["time"])
    return markers, segments


def fallback_line(trades: pd.DataFrame, classes: dict):
    """No candles? Build a price path from trade fills so the chart isn't empty."""
    pts = []
    price_cols = [c for c in classes["level"] if "price" in c.lower()] or classes["level"]
    for _, row in trades.iterrows():
        for col in classes["time"]:
            if col not in row or pd.isna(row[col]):
                continue
            ep = _epoch(row[col])
            if ep is None:
                continue
            base = col.lower().replace("_time", "")
            pcol = next((p for p in price_cols if base in p.lower()), price_cols[0] if price_cols else None)
            v = _f(row[pcol]) if pcol and pcol in row else None
            if v is not None:
                pts.append((ep, v))
    pts = sorted(dict(pts).items())  # dedupe by time, keep last
    return [{"time": int(t), "value": float(v)} for t, v in pts]


# ─────────────────────────────────────────────────────────────────────────────
# HTML / JS (pure string — no Streamlit, so it's unit-testable)
# ─────────────────────────────────────────────────────────────────────────────

def build_html(payload: dict) -> str:
    data = json.dumps(payload, allow_nan=False).replace("</", "<\\/")
    return f"""
<div id="tvwrap" style="width:100%;background:#0d0f14;border-radius:8px;overflow:hidden">
  <div id="tvchart" style="width:100%"></div>
</div>
<script src="{LWC_CDN}"></script>
<script>
(function() {{
  var P = {data};
  var el = document.getElementById('tvchart');
  if (typeof LightweightCharts === 'undefined') {{
    el.innerHTML = '<div style="color:#ef5350;padding:16px;font-family:monospace">'
      + 'Could not load Lightweight Charts (no network access in the browser?).</div>';
    return;
  }}
  var chart = LightweightCharts.createChart(el, {{
    height: P.height, width: el.clientWidth,
    layout: {{ background: {{ type:'solid', color:'#0d0f14' }}, textColor:'#cbd5e1', fontFamily:'monospace', fontSize:11 }},
    grid: {{ vertLines: {{ color:'#1b2230' }}, horzLines: {{ color:'#1b2230' }} }},
    timeScale: {{ timeVisible:true, secondsVisible:false, borderColor:'#1b2230' }},
    rightPriceScale: {{ borderColor:'#1b2230' }},
    crosshair: {{ mode: 0 }},
  }});
  var main;
  if (P.candles && P.candles.length) {{
    main = chart.addCandlestickSeries({{ upColor:'#26a69a', downColor:'#ef5350', borderVisible:false,
                                         wickUpColor:'#26a69a', wickDownColor:'#ef5350' }});
    main.setData(P.candles);
  }} else {{
    main = chart.addLineSeries({{ color:'#5b8def', lineWidth:2 }});
    main.setData(P.fallback || []);
  }}
  (P.segments || []).forEach(function(seg) {{
    var s = chart.addLineSeries({{ color:seg.color, lineWidth:1, lineStyle:seg.dash,
                                   lastValueVisible:false, priceLineVisible:false, crosshairMarkerVisible:false }});
    s.setData(seg.data);
  }});
  if (P.markers && P.markers.length) main.setMarkers(P.markers);
  chart.timeScale().fitContent();
  if (window.ResizeObserver) {{
    new ResizeObserver(function() {{ chart.applyOptions({{ width: el.clientWidth }}); }}).observe(el);
  }}
}})();
</script>
"""


# ─────────────────────────────────────────────────────────────────────────────
# Price-data adapter — wired to your layout: {base}{asset_class}:{asset}/{tf}.csv
# ─────────────────────────────────────────────────────────────────────────────

def _timeframe(metadata: dict) -> str | None:
    for k in ("timeframe","timeframes", "tf", "interval", "resolution", "bar", "granularity"):
        if metadata and metadata.get(k) not in (None, ""):
            return str(metadata[k])
    return None


def _asset_class(metadata: dict) -> str | None:
    for k in ("asset_class", "assetClass", "assetclass", "instrument_class", "class", "cls"):
        if metadata and metadata.get(k) not in (None, ""):
            return str(metadata[k])
    return None


def _load_csv(path: str):
    """Prefer the project's own data_loader.load_csv (so parsing matches the
    backtest exactly); fall back to pd.read_csv if it isn't importable."""
    for modname in ("libs.data_loader", "data_loader"):
        try:
            mod = __import__(modname, fromlist=["load_csv"])
        except Exception:  # noqa: BLE001 - import may fail for many reasons
            continue
        fn = getattr(mod, "load_csv", None)
        if callable(fn):
            return fn(path)
    return pd.read_csv(path)


def _normalize_prices(df):
    """Promote a datetime index to a column (loaders often return time-indexed
    frames) and strip column whitespace, so OHLC detection can find everything."""
    if not isinstance(df, pd.DataFrame) or df.empty:
        return df
    idx_name = df.index.name
    if isinstance(df.index, pd.DatetimeIndex) or (idx_name and _TIME_NAME.search(str(idx_name))):
        df = df.reset_index()
    df.columns = [str(c).strip() for c in df.columns]
    return df


def load_prices(asset: str, metadata: dict | None = None, *, marketdata_path: str | None = None):
    """
    Resolve OHLC for a run using your layout:

        {marketdata_path}{asset_class}:{asset}/{timeframe}.csv
        e.g.   ../data/marketdata/I:NDX/1h.csv

    `asset_class` and `timeframe` are read from the run's saved metadata; the base
    dir defaults to '../data/marketdata/' (override via the marketdata_path arg or
    the MARKETDATA_PATH env var). A few simpler paths are tried as fallbacks, and
    pd.read_csv is used if your data_loader isn't importable. Returns a DataFrame
    (time + OHLC) or None if nothing is found.
    """
    metadata = metadata or {}
    base = marketdata_path or os.environ.get("MARKETDATA_PATH", "../data/marketdata/")
    if not base.endswith("/"):
        base += "/"
    tf = _timeframe(metadata)
    ac = _asset_class(metadata)
    print(tf,ac)
    candidates = []
    if ac and tf:
        candidates.append(f"{base}{ac}:{asset}/{tf}.csv")           # your convention
    else:
        return None
    candidates.append(f"{base}{ac}:{asset}/{tf}.csv")
    print(f"{base}{ac}:{asset}/{tf}.csv")
    for path in candidates:
        try:
            if Path(path).exists():
                return _normalize_prices(_load_csv(path))
        except (OSError, pd.errors.ParserError, ValueError):
            continue   # unparseable/missing → try the next candidate
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Streamlit panel (lazy-imports streamlit so the logic above stays importable)
# ─────────────────────────────────────────────────────────────────────────────

def _render_iframe(html: str, height: int):
    """
    Render an HTML/JS string in a sandboxed iframe, preferring the current
    `st.iframe` API and falling back to the (deprecated) components.v1.html on
    older Streamlit. Signature introspection picks the right keyword for the HTML
    body (html= / srcdoc=) so it works across versions without guessing.
    """
    import inspect
    import streamlit as st
    fn = getattr(st, "iframe", None)
    if fn is not None:
        try:
            params = list(inspect.signature(fn).parameters)
        except (TypeError, ValueError):
            params = []
        kw = {}
        if "height" in params:
            kw["height"] = height
        if "scrolling" in params:
            kw["scrolling"] = False
        if "html" in params:
            return fn(html=html, **kw)
        if "srcdoc" in params:
            return fn(srcdoc=html, **kw)
        if params and params[0] not in ("src", "url"):   # promoted components.html → first arg is the body
            try:
                return fn(html, **kw)
            except TypeError:
                pass
    import streamlit.components.v1 as components          # fallback (older Streamlit)
    return components.html(html, height=height, scrolling=False)


def tradingview_panel(run: dict, prices: pd.DataFrame | None, *, key: str = "", height: int = 520,
                      max_trades_default: int = 25):
    import streamlit as st

    trades = run.get("trades_full")
    if not isinstance(trades, pd.DataFrame) or trades.empty:
        trades = run.get("trades")
    if not isinstance(trades, pd.DataFrame) or trades.empty:
        st.caption("No trades to chart for this run.")
        return

    classes = classify_trade_columns(trades)
    if not classes["time"]:
        st.caption("No time columns detected in the trades — cannot place anything on a time axis.")
        return

    id_col = next((c for c in ("trade_id", "id", "trade", "tradeno") if c in trades.columns), None)

    # default level toggles: SL/TP/entry/exit-price first, fib/others off
    def _default_level(c):
        return bool(re.search(r"(^|_)(sl|tp|stop|target|take)(_|$)", c, re.I)) or \
               bool(re.search(r"(entry|exit).*price|price.*(entry|exit)", c, re.I))
    default_levels = [c for c in classes["level"] if _default_level(c)] or classes["level"][:4]
    default_markers = [c for c in classes["time"] if re.search(r"(entry|exit)", c, re.I)] or classes["time"][:2]

    c1, c2 = st.columns(2)
    with c1:
        markers_on = st.multiselect("Markers (event times)", classes["time"], default=default_markers, key=f"tvm_{key}")
        levels_on = st.multiselect("Price levels", classes["level"], default=default_levels, key=f"tvl_{key}")
    with c2:
        opts = list(trades[id_col]) if id_col else list(range(len(trades)))
        default_ids = opts[:max_trades_default]
        sel = st.multiselect(f"Trades to overlay ({len(opts)} total)", opts, default=default_ids, key=f"tvt_{key}")
        height = st.slider("Chart height", 360, 900, height, 20, key=f"tvh_{key}")

    sub = trades[trades[id_col].isin(sel)] if id_col else trades.iloc[[i for i in sel if isinstance(i, int)]]
    if sub.empty:
        st.info("Select at least one trade to overlay.")
        return

    # candle window = selected trades' time span ± padding
    ep_all = []
    for col in classes["time"]:
        for v in _dt(sub[col]).dropna():
            e = _epoch(v)
            if e is not None:
                ep_all.append(e)
    span_lo, span_hi = (min(ep_all), max(ep_all)) if ep_all else (None, None)

    ohlc = detect_ohlc_columns(prices) if isinstance(prices, pd.DataFrame) else None
    candles, fb, grid = [], [], np.array([], dtype="int64")
    if ohlc and span_lo is not None:
        pad = max(int((span_hi - span_lo) * 0.08), 20 * 3600)
        candles = build_candles(prices, ohlc, t0=span_lo - pad, t1=span_hi + pad)
        grid = np.array([c["time"] for c in candles], dtype="int64")

    if candles:
        lo = min(c["low"] for c in candles)
        hi = max(c["high"] for c in candles)
    else:
        fb = fallback_line(sub, classes)
        vals = [p["value"] for p in fb] or [v for v in (sub[classes["level"]].to_numpy().ravel() if classes["level"] else []) if np.isfinite(v)]
        lo, hi = (min(vals), max(vals)) if vals else (0.0, 1.0)
        grid = np.array([p["time"] for p in fb], dtype="int64")
        st.caption("No OHLC bars found — showing a price path built from trade fills. "
                   "Point `load_prices()` at your candle data for a real chart.")

    rng = (hi - lo) or 1.0
    price_lo, price_hi = lo - 0.5 * rng, hi + 0.5 * rng  # generous gate to keep nearby SL/TP, drop multipliers

    markers, segments = build_overlays(sub, classes, grid, price_lo, price_hi,
                                       markers_on, levels_on, classes["side"], id_col)

    payload = {"height": int(height), "candles": candles, "fallback": fb,
               "markers": markers, "segments": segments}
    try:
        html = build_html(payload)
    except ValueError:  # e.g. a stray non-finite value
        st.error("Could not serialise chart data (non-finite value).")
        return
    _render_iframe(html, int(height) + 16)

    legend = []
    for col in markers_on:
        legend.append(f"{_pretty(col)} ▸ marker")
    for col in levels_on:
        legend.append(f"{_pretty(col)} ▸ line")
    if legend:
        st.caption("Overlays: " + "   ".join(legend))

    with st.expander("Selected trades (all columns)"):
        st.dataframe(sub, width="stretch", hide_index=True)


# ─────────────────────────────────────────────────────────────────────────────
# INTEGRATION (add to dashboard.py, inside the Run-detail tab)
# ─────────────────────────────────────────────────────────────────────────────
#
#   from tv_chart import tradingview_panel, load_prices
#   ...
#   st.divider()
#   st.markdown("### Price chart")
#   prices = load_prices(sel_asset, run.get("metadata", {}))   # adapt load_prices to your data
#   tradingview_panel(run, prices, key=sel_run)
#
# Requires browser internet access for the pinned CDN script. To vendor it
# offline, download lightweight-charts.standalone.production.js and serve it
# locally, then change LWC_CDN to that path.