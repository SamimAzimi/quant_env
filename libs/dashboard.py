"""
dashboard.py — web dashboard over the ResultStore (Streamlit).

Run with:
    streamlit run dashboard.py
(optionally point it at a DB:  BACKTEST_DB=../DB/all_backtests.db streamlit run dashboard.py)

Tabs:
  • Overview  — every saved run, grouped by asset, with a composite score + rank
  • Run detail — per-run visualisations from the PerformanceAnalytics report
    (equity, drawdown, exit pie, monthly returns, rolling Sharpe, profit by
    session / hour …) PLUS, computed from the stored data:
        – composite score & rank
        – grouped metric panels (Performance / Risk / Trade-stats / …)
        – long-vs-short (bull/bear) breakdown
        – Monte Carlo (bootstrap of trade returns)
  • Compare — side-by-side metrics, normalised equity overlay, metric bars

Nothing about `details`/metadata is hardcoded — metadata renders dynamically, so
different strategies with different `details['metadata']` shapes just work.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

# ── make `libs`/`config` importable regardless of where streamlit is launched ─
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from config.config import DEFAULT_DB, METRIC_FMT, FILTERABLE, SCORE_TERMS, METRIC_META, METRIC_GROUPS
from libs.result_store import ResultStore

import altair as alt
import streamlit as st

st.set_page_config(page_title="CFD Backtest Dashboard", page_icon="📈", layout="wide")


# ─────────────────────────────────────────────────────────────────────────────
# Cached data access (keyed on DB mtime so it refreshes when you save new runs)
# ─────────────────────────────────────────────────────────────────────────────

def _mtime(db: str) -> float:
    try:
        return os.path.getmtime(db)
    except OSError:
        return 0.0


@st.cache_data(show_spinner=False)
def load_catalog(db: str, _mt: float):
    s = ResultStore(db)
    return s.summary_table(), s.list_assets(), s.load_all_metadata()


@st.cache_data(show_spinner=False)
def load_run(db: str, run_id: str, _mt: float):
    return ResultStore(db).load_run(run_id)


# ─────────────────────────────────────────────────────────────────────────────
# Formatting / Arrow-safety helpers
# ─────────────────────────────────────────────────────────────────────────────

def fmt(value, kind: str) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "—"
    try:
        if kind == "money":
            return f"{value:,.0f}"
        if kind == "pct":
            return f"{value:.2f}%"
        if kind == "pct_frac":
            return f"{value * 100:.1f}%"
        if kind == "int":
            return f"{int(value):,}"
        if kind == "bool":
            return "Yes" if value else "No"
        if kind == "str":
            return str(value)
        return f"{value:,.3f}"
    except (TypeError, ValueError):
        return str(value)


def _cell_to_str(v) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, float):
        return f"{v:.10g}"
    return str(v)


def arrow_safe(df: pd.DataFrame) -> pd.DataFrame:
    """Numeric-but-object columns stay numeric; mixed/string ones are stringified."""
    if not isinstance(df, pd.DataFrame):
        return df
    out = df.copy()
    for c in out.columns:
        if out[c].dtype == object:
            num = pd.to_numeric(out[c], errors="coerce")
            if out[c].notna().any() and num.notna().sum() == out[c].notna().sum():
                out[c] = num
            else:
                out[c] = out[c].map(_cell_to_str)
    return out


def show_df(df, **kwargs):
    st.dataframe(arrow_safe(df), width="stretch", **kwargs)


def indexed(df: pd.DataFrame, prefer=("time", "step")) -> pd.DataFrame:
    for col in prefer:
        if col in df.columns and df[col].notna().any():
            return df.set_index(col)
    return df


def kv_table(d: dict) -> pd.DataFrame:
    return pd.DataFrame({"field": list(d.keys()), "value": list(d.values())})


# ─────────────────────────────────────────────────────────────────────────────
# Composite score / rank (added from the Flask analyzer)
# ─────────────────────────────────────────────────────────────────────────────

def _score_row(row: pd.Series) -> float:
    s = 0.0
    for col, w, scale in SCORE_TERMS:
        v = row.get(col)
        if v is None:
            continue
        try:
            v = float(v)
        except (TypeError, ValueError):
            continue
        if np.isfinite(v):
            s += w * (v * scale)
    return round(s, 4)


def enrich_scores(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    if df.empty:
        df["composite_score"] = pd.Series(dtype=float)
        df["rank"] = pd.Series(dtype=int)
        return df
    df["composite_score"] = df.apply(_score_row, axis=1)
    df["rank"] = df["composite_score"].rank(ascending=False, method="min").astype(int)
    return df


# ─────────────────────────────────────────────────────────────────────────────
# Grouped metric panels (added — mirrors the Flask detail drawer)
# ─────────────────────────────────────────────────────────────────────────────

def _present(metrics: dict, keys) -> list:
    out = []
    for k in keys:
        if k in metrics:
            v = metrics[k]
            if v is None or (isinstance(v, float) and pd.isna(v)):
                continue
            out.append(k)
    return out


def metric_grid(metrics: dict, keys: list, ncols: int = 4):
    keys = _present(metrics, keys)
    if not keys:
        st.caption("—"); return
    cols = st.columns(ncols)
    for i, k in enumerate(keys):
        label, kind = METRIC_META.get(k, (k.replace("_", " "), "num"))
        cols[i % ncols].metric(label, fmt(metrics.get(k), kind))


def render_groups(metrics: dict):
    shown = set()
    for gname, keys in METRIC_GROUPS.items():
        present = _present(metrics, keys)
        if not present:
            continue
        with st.expander(gname, expanded=gname in ("Performance", "Risk & return")):
            metric_grid(metrics, present)
        shown.update(present)
    others = [k for k in metrics if k not in shown]
    if others:
        with st.expander("Other metrics"):
            metric_grid(metrics, others)


# ─────────────────────────────────────────────────────────────────────────────
# Long vs short (bull/bear) and Monte Carlo (added)
# ─────────────────────────────────────────────────────────────────────────────

def long_short_stats(result, initial=None):
    if not isinstance(result, pd.DataFrame) or "net_pnl" not in result or "side" not in result:
        return None
    f = result[result["net_pnl"].notna()]
    rows = []
    for side in ("long", "short"):
        s = f[f["side"] == side]
        n = len(s)
        if n == 0:
            continue
        wins = int((s["net_pnl"] > 0).sum())
        net = float(s["net_pnl"].sum())
        rows.append({"side": side, "trades": n, "wins": wins,
                     "win_rate_%": round(100 * wins / n, 1),
                     "net_pnl": round(net, 2),
                     "return_%": round(100 * net / float(initial), 2) if initial else None,
                     "avg_pnl": round(float(s["net_pnl"].mean()), 2)})
    return pd.DataFrame(rows) if rows else None


def monte_carlo(result, initial=None, n_paths: int = 1000, seed: int = 0):
    if not isinstance(result, pd.DataFrame) or "net_pnl" not in result:
        return None
    f = result[result["net_pnl"].notna()]
    if "equity_before" in f:
        r = (f["net_pnl"] / f["equity_before"]).replace([np.inf, -np.inf], np.nan).dropna().to_numpy()
    elif initial:
        r = (f["net_pnl"] / float(initial)).dropna().to_numpy()
    else:
        return None
    n = len(r)
    if n < 5:
        return None
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, n, size=(n_paths, n))
    paths = np.cumprod(1.0 + r[idx], axis=1)
    terminal = (paths[:, -1] - 1.0) * 100.0
    runmax = np.maximum.accumulate(paths, axis=1)
    maxdd = (1.0 - paths / runmax).max(axis=1) * 100.0
    stats = {
        "median_return": float(np.median(terminal)),
        "p10_return": float(np.percentile(terminal, 10)),
        "p90_return": float(np.percentile(terminal, 90)),
        "prob_profit": float((terminal > 0).mean() * 100),
        "median_maxdd": float(np.median(maxdd)),
        "p90_maxdd": float(np.percentile(maxdd, 90)),
        "worst_maxdd": float(maxdd.max()),
    }
    return {"terminal": terminal, "maxdd": maxdd, "stats": stats, "n_paths": n_paths, "n_trades": n}


def chart_mc(mc: dict):
    s = mc["stats"]
    hist = (alt.Chart(pd.DataFrame({"terminal": mc["terminal"]})).mark_bar(opacity=0.85)
            .encode(x=alt.X("terminal:Q", bin=alt.Bin(maxbins=40), title="Terminal return %"),
                    y=alt.Y("count()", title="paths"))
            .properties(width="container", height=260))
    marks = pd.DataFrame({"v": [s["p10_return"], s["median_return"], s["p90_return"]],
                          "label": ["P10", "Median", "P90"]})
    rules = (alt.Chart(marks).mark_rule(color="#ff4d6d", strokeDash=[4, 3])
             .encode(x="v:Q", tooltip=["label:N", "v:Q"]))
    return hist + rules


def initial_capital(run: dict):
    ec = run.get("equity_curve")
    if isinstance(ec, pd.DataFrame) and "equity" in ec and len(ec):
        try:
            return float(ec["equity"].iloc[0])
        except (TypeError, ValueError):
            pass
    return (run.get("metadata") or {}).get("initial_capital")


# ─────────────────────────────────────────────────────────────────────────────
# Chart renderers (existing — kept)
# ─────────────────────────────────────────────────────────────────────────────

def chart_equity(run: dict):
    ec = run.get("equity_curve")
    if not isinstance(ec, pd.DataFrame) or ec.empty:
        st.caption("No equity curve saved.")
        return
    e = indexed(ec)
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Equity curve**")
        st.line_chart(e["equity"], height=260)
    with c2:
        st.markdown("**Drawdown (%)**")
        if "drawdown_pct" in e:
            st.area_chart(e["drawdown_pct"], height=260)
        else:
            st.caption("No drawdown column.")


def chart_exit_reasons(run: dict):
    df = run.get("breakdowns", {}).get("exit_reasons")
    if not isinstance(df, pd.DataFrame) or df.empty:
        st.caption("No exit-reason data."); return
    donut = (alt.Chart(df).mark_arc(innerRadius=55)
             .encode(theta=alt.Theta("count:Q", stack=True),
                     color=alt.Color("exit_reason:N", legend=alt.Legend(title="Exit reason")),
                     tooltip=["exit_reason:N", "count:Q", "pct:Q"])
             .properties(width="container", height=260))
    st.altair_chart(donut)


def chart_monthly(run: dict):
    s = run.get("breakdowns", {}).get("monthly_returns")
    if not isinstance(s, pd.Series) or s.empty:
        st.caption("No monthly returns."); return
    d = pd.DataFrame({"month": s.index.astype(str), "return_%": (s.values * 100)}).set_index("month")
    st.bar_chart(d, height=260)


def chart_series(run: dict, key: str, label: str, scale: float = 1.0):
    s = run.get("breakdowns", {}).get(key)
    if not isinstance(s, pd.Series) or s.dropna().empty:
        st.caption(f"No {label.lower()}."); return
    st.markdown(f"**{label}**")
    st.line_chart(s * scale, height=240)


def chart_profit_breakdown(run: dict, key: str, label: str):
    s = run.get("breakdowns", {}).get(key)
    if not isinstance(s, pd.Series) or s.empty:
        st.caption(f"No {label.lower()}."); return
    st.markdown(f"**{label}**")
    st.bar_chart(s.rename("net P&L"), height=240)


# ─────────────────────────────────────────────────────────────────────────────
# Sidebar — source, refresh, KPIs and filters
# ─────────────────────────────────────────────────────────────────────────────

st.sidebar.title("📈 Backtest dashboard")
db = st.sidebar.text_input("Store path", value=DEFAULT_DB)
if st.sidebar.button("↻ Refresh data"):
    st.cache_data.clear()
    st.rerun()

if not os.path.exists(db):
    st.sidebar.error("Store not found.")
    st.title("CFD Backtest Dashboard")
    st.info(f"No store at `{db}`. Run a backtest pipeline first, or set the path in the sidebar.")
    st.stop()

summary, assets, meta_wide = load_catalog(db, _mtime(db))
if summary.empty:
    st.title("CFD Backtest Dashboard")
    st.info("The store has no runs yet. Save a pipeline run, then refresh.")
    st.stop()

summary = enrich_scores(summary)          # composite_score + rank for the whole store

st.sidebar.metric("Runs saved", len(summary))
st.sidebar.metric("Assets", len(assets))
st.sidebar.divider()

st.sidebar.subheader("Filters")
chosen_assets = st.sidebar.multiselect("Asset", options=assets, default=assets)
flt = summary[summary["asset"].isin(chosen_assets)].copy() if chosen_assets else summary.copy()

q = st.sidebar.text_input("Search run id", "")
if q:
    flt = flt[flt["run_id"].str.contains(q, case=False, na=False)]


def range_filter(frame: pd.DataFrame, col: str, label: str) -> pd.DataFrame:
    if col not in frame.columns:
        return frame
    vals = pd.to_numeric(frame[col], errors="coerce").dropna()
    if vals.empty or float(vals.min()) == float(vals.max()):
        return frame
    lo, hi = float(vals.min()), float(vals.max())
    a, b = st.sidebar.slider(label, lo, hi, (lo, hi))
    keep = pd.to_numeric(frame[col], errors="coerce")
    return frame[keep.isna() | keep.between(a, b)]


with st.sidebar.expander("Performance thresholds", expanded=True):
    for _c in FILTERABLE:
        lbl = METRIC_FMT.get(_c, (_c, "num"))[0]
        flt = range_filter(flt, _c, lbl)

with st.sidebar.expander("Strategy / metadata filter"):
    meta_cols = [c for c in meta_wide.columns if c != "run_id"] if not meta_wide.empty else []
    pick = st.selectbox("Field", ["(none)"] + sorted(meta_cols))
    if pick != "(none)" and not meta_wide.empty:
        col = meta_wide[["run_id", pick]].dropna()
        if pd.api.types.is_numeric_dtype(col[pick]) and col[pick].nunique() > 1:
            lo, hi = float(col[pick].min()), float(col[pick].max())
            a, b = st.slider(f"{pick} range", lo, hi, (lo, hi))
            keep_ids = set(col[col[pick].between(a, b)]["run_id"])
        else:
            opts = sorted(col[pick].astype(str).unique())
            chosen = st.multiselect(f"{pick} values", opts, default=opts)
            keep_ids = set(col[col[pick].astype(str).isin(chosen)]["run_id"])
        flt = flt[flt["run_id"].isin(keep_ids)]

filtered_ids = flt["run_id"].tolist()


# ─────────────────────────────────────────────────────────────────────────────
# Main — tabs
# ─────────────────────────────────────────────────────────────────────────────

st.title("CFD Backtest Dashboard")
tab_overview, tab_detail, tab_compare = st.tabs(["📋 Overview", "🔍 Run detail", "⚖️ Compare"])

# ── Overview ──────────────────────────────────────────────────────────────────
with tab_overview:
    a, b, c, d = st.columns(4)
    a.metric("Runs (filtered)", len(flt))
    b.metric("Assets", flt["asset"].nunique())
    if "composite_score" in flt and flt["composite_score"].notna().any():
        best = flt.loc[flt["composite_score"].idxmax()]
        c.metric("Best score", fmt(best["composite_score"], "num"), help=str(best["run_id"]))
    if "net_profit" in flt and flt["net_profit"].notna().any():
        bp = flt.loc[flt["net_profit"].idxmax()]
        d.metric("Best net profit", fmt(bp["net_profit"], "money"), help=str(bp["run_id"]))

    st.divider()
    if flt.empty:
        st.warning("No runs match the current filters.")
    else:
        st.caption("Runs grouped by asset, ranked by composite score — sortable.")
        show_cols = ["rank", "composite_score", "run_id", "saved_at"] + \
                    [m for m in METRIC_FMT if m in flt.columns]
        for asset in sorted(flt["asset"].unique()):
            sub = flt[flt["asset"] == asset].sort_values("rank")
            st.subheader(f"{asset}  ·  {len(sub)} run(s)")
            show_df(sub[show_cols], hide_index=True)

# ── Run detail ────────────────────────────────────────────────────────────────
with tab_detail:
    if not filtered_ids:
        st.warning("No runs match the current filters.")
    else:
        det_assets = sorted(flt["asset"].unique())
        sel_asset = st.selectbox("Asset", det_assets, key="detail_asset")
        runs_for_asset = flt[flt["asset"] == sel_asset].sort_values("rank")["run_id"].tolist()
        sel_run = st.selectbox("Run", runs_for_asset, key="detail_run")

        run = load_run(db, sel_run, _mtime(db))
        metrics = run.get("metrics", {}) or {}
        initial = initial_capital(run)

        srow = summary[summary["run_id"] == sel_run]
        score = float(srow["composite_score"].iloc[0]) if not srow.empty else None
        rnk = int(srow["rank"].iloc[0]) if not srow.empty else None

        st.markdown(f"### {sel_run}  —  `{sel_asset}`")
        h1, h2, h3 = st.columns(3)
        h1.metric("Composite score", fmt(score, "num"))
        h2.metric("Rank", f"#{rnk} / {len(summary)}" if rnk else "—")
        h3.metric("Saved", str(run.get("saved_at", ""))[:19] or "—")

        # curated headline KPIs (existing)
        cards = [k for k in METRIC_FMT if k in metrics]
        cols = st.columns(min(5, len(cards)) or 1)
        for i, key in enumerate(cards):
            label, kind = METRIC_FMT[key]
            cols[i % len(cols)].metric(label, fmt(metrics.get(key), kind))

        st.divider()
        chart_equity(run)
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**Exit reasons**")
            chart_exit_reasons(run)
        with c2:
            st.markdown("**Monthly returns (%)**")
            chart_monthly(run)
        chart_series(run, "rolling_sharpe", "Rolling Sharpe")

        # ── ADDED: TradingView price chart (schema-agnostic trade overlays) ───
        st.divider()
        st.markdown("### Price chart")
        try:
            from libs.tv_chart import tradingview_panel, load_prices
        except Exception:                       # noqa: BLE001
            try:
                from tv_chart import tradingview_panel, load_prices
            except Exception:                   # noqa: BLE001
                tradingview_panel = load_prices = None
        if tradingview_panel is None:
            st.caption("tv_chart.py not found — place it beside the dashboard (or in libs/) to enable the chart.")
        else:
            try:
                prices = load_prices(sel_asset, run.get("metadata", {}))
                if prices is None:
                    st.caption("No OHLC CSV found for this run — check the marketdata path / asset_class in metadata "
                               "(expected like ../data/marketdata/{asset_class}:{asset}/{timeframe}.csv).")
                tradingview_panel(run, prices, key=sel_run)
            except Exception as _e:             # never let the chart break the page
                st.caption(f"Price chart unavailable: {_e}")

        # ── ADDED: long vs short ──────────────────────────────────────────────
        st.divider()
        st.markdown("### Long vs short")
        lsdf = long_short_stats(run.get("result"), initial)
        if isinstance(lsdf, pd.DataFrame) and not lsdf.empty:
            lc1, lc2 = st.columns([3, 2])
            with lc1:
                show_df(lsdf, hide_index=True)
            with lc2:
                st.bar_chart(lsdf.set_index("side")["net_pnl"], height=220)
        else:
            st.caption("No filled trades to split by direction.")

        # ── ADDED: Monte Carlo ────────────────────────────────────────────────
        st.divider()
        st.markdown("### Monte Carlo (bootstrap of trade returns)")
        mc = monte_carlo(run.get("result"), initial)
        if mc is None:
            st.caption("Not enough trades for a Monte Carlo simulation.")
        else:
            s = mc["stats"]
            mcols = st.columns(4)
            mcols[0].metric("Median return", fmt(s["median_return"], "pct"))
            mcols[1].metric("P10 / P90 return", f"{fmt(s['p10_return'], 'pct')} / {fmt(s['p90_return'], 'pct')}")
            mcols[2].metric("Prob. profit", fmt(s["prob_profit"], "pct"))
            mcols[3].metric("Median / worst maxDD", f"{fmt(s['median_maxdd'], 'pct')} / {fmt(s['worst_maxdd'], 'pct')}")
            st.altair_chart(chart_mc(mc))
            st.caption(f"{mc['n_paths']:,} bootstrapped paths over {mc['n_trades']} trades.")

        # profit-by breakdowns (KEPT — incl. session & hour)
        with st.expander("Profit breakdowns (session / hour / day-of-week)"):
            cc1, cc2 = st.columns(2)
            with cc1:
                chart_profit_breakdown(run, "by_session", "Profit by session")
                chart_profit_breakdown(run, "by_dow", "Profit by day of week")
            with cc2:
                chart_profit_breakdown(run, "by_hour", "Profit by hour")
                chart_series(run, "rolling_win_rate", "Rolling win rate")

        # ── ADDED: grouped metric panels ─────────────────────────────────────
        st.divider()
        st.markdown("#### Detailed metrics")
        render_groups(metrics)

        st.divider()
        st.markdown("**Strategy / run metadata**")
        show_df(kv_table(run.get("metadata", {})), hide_index=True)

        # data tables (existing)
        with st.expander("Trade details (details['trades'])"):
            tf = run.get("trades_full")
            show_df(tf) if isinstance(tf, pd.DataFrame) else st.caption("none")
        with st.expander("Costs (CFDCostModel.add_costs)"):
            cd = run.get("costed")
            if isinstance(cd, pd.DataFrame) and not cd.empty:
                cost_cols = [c for c in ("spread_cost", "commission_cost", "financing_cost", "total_cost") if c in cd]
                if cost_cols:
                    st.write({k: round(float(v), 2) for k, v in cd[cost_cols].sum().items()})
                show_df(cd)
            else:
                st.caption("none")
        with st.expander("Account result (result_df)"):
            rdf = run.get("result")
            show_df(rdf) if isinstance(rdf, pd.DataFrame) else st.caption("none")
        with st.expander("Equity curve table"):
            ec = run.get("equity_curve")
            show_df(ec) if isinstance(ec, pd.DataFrame) else st.caption("none")

# ── Compare ───────────────────────────────────────────────────────────────────
with tab_compare:
    st.caption("Pick two or more runs to compare side by side.")
    picks = st.multiselect("Runs", options=filtered_ids,
                           default=filtered_ids[: min(3, len(filtered_ids))])
    if len(picks) < 2:
        st.info("Select at least two runs.")
    else:
        runs = {rid: load_run(db, rid, _mtime(db)) for rid in picks}

        all_keys: list = []
        for r in runs.values():
            for k in (r.get("metrics") or {}):
                if k not in all_keys:
                    all_keys.append(k)
        table = pd.DataFrame(
            {rid: [(r.get("metrics") or {}).get(k) for k in all_keys] for rid, r in runs.items()},
            index=all_keys,
        )
        st.markdown("**Metrics**")
        show_df(table)

        frames = []
        for rid, r in runs.items():
            ec = r.get("equity_curve")
            if isinstance(ec, pd.DataFrame) and not ec.empty and "equity" in ec:
                e = ec["equity"].reset_index(drop=True).astype(float)
                if len(e) and e.iloc[0]:
                    frames.append(pd.DataFrame({"step": range(len(e)),
                                                "equity_index": e / e.iloc[0] * 100, "run": rid}))
        if frames:
            comp = pd.concat(frames, ignore_index=True)
            line = (alt.Chart(comp).mark_line()
                    .encode(x=alt.X("step:Q", title="Trade #"),
                            y=alt.Y("equity_index:Q", title="Equity (start = 100)"),
                            color=alt.Color("run:N"), tooltip=["run:N", "step:Q", "equity_index:Q"])
                    .properties(width="container", height=320))
            st.markdown("**Equity curves (normalised to 100)**")
            st.altair_chart(line)

        numeric_keys = [k for k in all_keys
                        if pd.to_numeric(table.loc[k], errors="coerce").notna().any()]
        if numeric_keys:
            metric_key = st.selectbox("Compare metric", numeric_keys,
                                      index=numeric_keys.index("net_profit") if "net_profit" in numeric_keys else 0)
            bar = pd.to_numeric(table.loc[metric_key], errors="coerce")
            st.bar_chart(bar.rename(metric_key))