# ─────────────────────────────────────────────────────────────────────────────
# Dashboard / visualization metadata
# (consumed by libs/dashboard.py, libs/market_dashboard.py, libs/tv_chart.py)
# ─────────────────────────────────────────────────────────────────────────────

import re

# curated headline metrics for the top KPI strip (universal across strategies)
METRIC_FMT = {
    "net_profit":       ("Net profit",     "money"),
    "total_return_pct": ("Total return",   "pct"),
    "final_equity":     ("Final equity",   "money"),
    "win_rate":         ("Win rate",       "pct_frac"),
    "profit_factor":    ("Profit factor",  "num"),
    "sharpe":           ("Sharpe",         "num"),
    "sortino":          ("Sortino",        "num"),
    "max_drawdown_pct": ("Max drawdown",   "pct"),
    "expectancy_r":     ("Expectancy (R)", "num"),
    "total_trades":     ("Trades",         "int"),
}
FILTERABLE = ["net_profit", "sharpe", "win_rate", "profit_factor",
              "max_drawdown_pct", "total_trades"]

# composite score weights (adapted from the Flask analyzer to the stored metric
# names; only metrics promoted to SQL columns are used so ranking stays cheap).
# (col, weight, scale)  — win_rate is a fraction here, scaled to a % like the rest.
SCORE_TERMS = [
    ("total_return_pct", 0.20, 1.0),
    ("win_rate",         0.15, 100.0),
    ("profit_factor",    0.15, 1.0),
    ("sharpe",           0.12, 1.0),
    ("sortino",          0.08, 1.0),
    ("expectancy_r",     0.02, 1.0),
    ("max_drawdown_pct", -0.08, 1.0),   # positive magnitude → penalised
]

# label + format for every metric, used by the grouped panels
METRIC_META = {
    # performance
    "net_profit": ("Net profit", "money"), "gross_profit": ("Gross profit", "money"),
    "gross_loss": ("Gross loss", "money"), "total_return_pct": ("Total return", "pct"),
    "final_equity": ("Final equity", "money"), "win_rate": ("Win rate", "pct_frac"),
    "loss_rate": ("Loss rate", "pct_frac"), "profit_factor": ("Profit factor", "num"),
    "avg_win": ("Avg win", "money"), "avg_loss": ("Avg loss", "money"),
    "expectancy_per_trade": ("Expectancy / trade", "money"), "expectancy_r": ("Expectancy (R)", "num"),
    "payoff_ratio": ("Payoff ratio", "num"), "avg_pnl_per_trade": ("Avg P&L / trade", "money"),
    "median_pnl_per_trade": ("Median P&L / trade", "money"),
    # risk & return
    "sharpe": ("Sharpe", "num"), "sortino": ("Sortino", "num"), "calmar": ("Calmar", "num"),
    "return_to_drawdown": ("Return / DD", "num"), "cagr_pct": ("CAGR", "pct"),
    "volatility": ("Volatility (ann.)", "pct_frac"), "downside_volatility": ("Downside vol (ann.)", "pct_frac"),
    "ulcer_index": ("Ulcer index", "num"), "jensen_alpha": ("Jensen alpha (ann.)", "pct_frac"),
    "beta": ("Beta", "num"), "equity_smoothness_r2": ("Equity R²", "num"),
    # drawdown
    "max_drawdown_pct": ("Max drawdown", "pct"), "max_drawdown": ("Max drawdown ($)", "money"),
    "max_drawdown_duration_days": ("Max DD duration (d)", "num"), "recovery_time_days": ("Recovery (d)", "num"),
    # distribution & tail
    "var_95": ("VaR 95%", "pct_frac"), "var_99": ("VaR 99%", "pct_frac"),
    "cvar_95": ("CVaR 95%", "pct_frac"), "cvar_99": ("CVaR 99%", "pct_frac"),
    "tail_ratio": ("Tail ratio", "num"), "skew": ("Skew", "num"), "kurtosis": ("Kurtosis", "num"),
    # streaks
    "max_win_streak": ("Max win streak", "int"), "max_loss_streak": ("Max loss streak", "int"),
    "avg_win_streak": ("Avg win streak", "num"), "avg_loss_streak": ("Avg loss streak", "num"),
    "current_streak": ("Current streak", "int"),
    # trade stats & conversion
    "total_trades": ("Trades", "int"), "total_setups": ("Setups", "int"),
    "invalidations": ("Invalidations", "int"), "n_long": ("Longs", "int"), "n_short": ("Shorts", "int"),
    "long_short_ratio": ("Long / short", "num"), "setup_to_entry_rate": ("Setup→entry", "pct_frac"),
    "setup_to_win_rate": ("Setup→win", "pct_frac"), "reject_rate": ("Reject rate", "pct_frac"),
    "exposure_pct": ("Exposure", "pct"), "trades_per_day": ("Trades / day", "num"),
    "trades_per_week": ("Trades / week", "num"), "trades_per_month": ("Trades / month", "num"),
    # timing
    "avg_setup_to_entry_hrs": ("Setup→entry (h)", "num"), "median_setup_to_entry_hrs": ("Median setup→entry (h)", "num"),
    "avg_entry_delay_hrs": ("Entry delay (h)", "num"), "avg_exit_delay_hrs": ("Hold time (h)", "num"),
    "median_hold_hrs": ("Median hold (h)", "num"),
    # monthly & rolling
    "pct_profitable_months": ("Profitable months", "pct"), "monthly_return_mean": ("Monthly return (mean)", "pct_frac"),
    "monthly_return_std": ("Monthly return (std)", "pct_frac"), "rolling_return_pct_positive": ("Rolling +ve windows", "pct"),
    "rolling_return_mean": ("Rolling return (mean)", "pct_frac"), "rolling_return_std": ("Rolling return (std)", "pct_frac"),
    "rolling_window_days": ("Rolling window (d)", "int"),
    # basis
    "returns_annualized": ("Returns annualised", "bool"), "return_frequency": ("Return frequency", "str"),
}

METRIC_GROUPS = {
    "Performance": ["net_profit", "gross_profit", "gross_loss", "total_return_pct", "final_equity",
                    "win_rate", "loss_rate", "profit_factor", "avg_win", "avg_loss",
                    "expectancy_per_trade", "expectancy_r", "payoff_ratio",
                    "avg_pnl_per_trade", "median_pnl_per_trade"],
    "Risk & return": ["sharpe", "sortino", "calmar", "return_to_drawdown", "cagr_pct",
                      "volatility", "downside_volatility", "ulcer_index",
                      "jensen_alpha", "beta", "equity_smoothness_r2"],
    "Drawdown & recovery": ["max_drawdown_pct", "max_drawdown", "max_drawdown_duration_days", "recovery_time_days"],
    "Distribution & tail": ["var_95", "var_99", "cvar_95", "cvar_99", "tail_ratio", "skew", "kurtosis"],
    "Streaks": ["max_win_streak", "max_loss_streak", "avg_win_streak", "avg_loss_streak", "current_streak"],
    "Trade stats & conversion": ["total_trades", "total_setups", "invalidations", "n_long", "n_short",
                                 "long_short_ratio", "setup_to_entry_rate", "setup_to_win_rate",
                                 "reject_rate", "exposure_pct", "trades_per_day", "trades_per_week", "trades_per_month"],
    "Timing": ["avg_setup_to_entry_hrs", "median_setup_to_entry_hrs", "avg_entry_delay_hrs",
               "avg_exit_delay_hrs", "median_hold_hrs"],
    "Monthly & rolling": ["pct_profitable_months", "monthly_return_mean", "monthly_return_std",
                          "rolling_return_pct_positive", "rolling_return_mean", "rolling_return_std", "rolling_window_days"],
    "Return basis": ["returns_annualized", "return_frequency"],
}

# ── market_dashboard.py ──────────────────────────────────────────────────────
# Per-asset colourway: vivid but harmonious on the dark console background.
PALETTE = [
    "#5ec8f0",  # cyan
    "#f0a35e",  # amber
    "#9d7cf0",  # violet
    "#5ef0a8",  # mint
    "#f05e8a",  # pink
    "#f0d65e",  # gold
    "#7c9cf0",  # blue
    "#f07c5e",  # coral
    "#5ef0d6",  # teal
    "#c9f05e",  # lime
]

_PLOTLY_CDN = "https://cdn.plot.ly/plotly-2.35.2.min.js"

# ── tv_chart.py ──────────────────────────────────────────────────────────────
# pinned CDN build (v4 standalone exposes global `LightweightCharts`)
LWC_CDN = "https://unpkg.com/lightweight-charts@4.2.0/dist/lightweight-charts.standalone.production.js"

# column-name heuristics (discovery + styling only)
_TIME_NAME = re.compile(r"(^|_)(time|date|datetime|timestamp|ts)(_|$)", re.I)
_LEVEL_NAME = re.compile(
    r"(^|_)(sl|tp|stop|target|take|price|level|fib|vwap|band|sma|ema|ma)(_|$)|price",
    re.I,
)
