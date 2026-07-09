"""
performance.py — PerformanceAnalytics

Consumes the output of ``CFDAccountSimulator.simulate()`` — the per-trade
``result_df`` and the ``equity_curve`` — and returns the full performance suite:
trade statistics, risk/return ratios, drawdown analysis, time-based profit
breakdowns, rolling series and setup-conversion stats.

    perf = PerformanceAnalytics(result_df, equity_curve,
                                risk_free_rate=0.04, periods_per_year=252)
    report = perf.report()
    report["metrics"]            # flat dict of every scalar KPI
    report["exit_reasons"]       # DataFrame ready for a pie chart
    report["monthly_returns"]    # Series ready for a histogram
    report["rolling_sharpe"]     # Series ready to plot
    ...

Design
------
• Trade stats (expectancy, payoff, win/loss, R-multiples, streaks) come from the
  per-trade net_pnl / r_multiple — exact, no resampling.
• Return/risk stats (Sharpe, Sortino, VaR, vol, skew, kurtosis, drawdown
  durations, monthly/session profit, rolling series) are computed on a
  time-resampled equity series — the conventional, annualizable basis. This
  needs real timestamps; if entry/exit times are bar indices instead, those
  metrics fall back to per-trade returns and are NOT annualized (flagged in the
  output via `returns_annualized`).

Not financial advice.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple
from config.config import DEFAULT_SESSIONS1,_DOW_NAMES
import numpy as np
import pandas as pd

def _safe_div(a, b):
    try:
        return a / b if b not in (0, 0.0) and pd.notna(b) else np.nan
    except Exception:
        return np.nan


class PerformanceAnalytics:
    # default NON-overlapping session map by entry hour (assumed in the tz of
    # entry_time — override `session_bins` to match your data's timezone)


    def __init__(
        self,
        result_df: pd.DataFrame,
        equity_curve: pd.DataFrame,
        *,
        initial_capital: Optional[float] = None,
        risk_free_rate: float = 0.0,        # annual
        periods_per_year: int = 252,
        resample_freq: str = "B",           # business-daily equity series
        benchmark: Optional[pd.Series] = None,   # price OR return series (datetime index)
        rolling_window_days: int = 63,
        rolling_trades: int = 20,
        session_bins: Optional[List[Tuple[str, int, int]]] = None,
        var_confidence: float = 0.95,
    ) -> None:
        self.result = result_df.copy().reset_index(drop=True)
        self.curve  = equity_curve.copy().reset_index(drop=True)

        self.risk_free_rate     = float(risk_free_rate)
        self.periods_per_year   = int(periods_per_year)
        self.resample_freq      = resample_freq
        self.benchmark          = benchmark
        self.rolling_window_days = int(rolling_window_days)
        self.rolling_trades     = int(rolling_trades)
        self.session_bins       = session_bins or DEFAULT_SESSIONS1
        self.var_alpha          = 1.0 - float(var_confidence)
        self.var_conf           = float(var_confidence)

        # filled trades = rows that actually opened a position
        self.filled = self.result[self.result["net_pnl"].notna()].copy()
        self.pnl    = self.filled["net_pnl"].astype(float)
        self.r      = (self.filled["r_multiple"].astype(float)
                       if "r_multiple" in self.filled else pd.Series(dtype=float))

        # capital
        self.initial_capital = (float(initial_capital) if initial_capital is not None
                                else float(self.curve["equity"].iloc[0]))
        self.final_equity    = float(self.curve["equity"].iloc[-1])

        # do we have usable timestamps?
        self.has_time = ("exit_time" in self.result.columns
                         and not pd.api.types.is_numeric_dtype(self.result["exit_time"]))

        self._build_equity_series()
        self._build_returns()

    # ── series construction ──────────────────────────────────────────────────

    def _build_equity_series(self) -> None:
        if self.has_time:
            t = pd.to_datetime(self.curve["time"], errors="coerce")
            s = pd.Series(self.curve["equity"].values, index=t).dropna()
            s = s[~s.index.duplicated(keep="last")].sort_index()
            self.eq_daily = s.resample(self.resample_freq).last().ffill()
        else:
            self.eq_daily = pd.Series(dtype=float)

    def _build_returns(self) -> None:
        if self.has_time and len(self.eq_daily) >= 2:
            self.returns = self.eq_daily.pct_change().dropna()
            self.ann = float(np.sqrt(self.periods_per_year))
            self.returns_annualized = True
        else:                                  # fall back to per-trade returns
            eqb = self.filled["equity_before"].astype(float)
            self.returns = (self.pnl / eqb).replace([np.inf, -np.inf], np.nan).dropna()
            self.ann = 1.0
            self.returns_annualized = False
        self.rf_period = self.risk_free_rate / self.periods_per_year if self.returns_annualized else 0.0

    # ── 1, 16, 50-55, 17, 18 — trade counts / direction / conversion ─────────

    def _trade_counts(self) -> Dict:
        n_setups = len(self.result)
        n_filled = len(self.filled)
        n_inval  = int((self.result["exit_reason"] == "Invalidation").sum()) if "exit_reason" in self.result else n_setups - n_filled
        n_long   = int((self.filled["side"] == "long").sum())
        n_short  = int((self.filled["side"] == "short").sum())
        n_wins   = int((self.pnl > 0).sum())

        out = {
            "total_trades":        n_filled,
            "total_setups":        n_setups,
            "invalidations":       n_inval,
            "n_long":              n_long,
            "n_short":             n_short,
            "long_pct":            round(100 * _safe_div(n_long, n_filled), 2),
            "short_pct":           round(100 * _safe_div(n_short, n_filled), 2),
            "long_short_ratio":    round(_safe_div(n_long, n_short), 3),
            "setup_to_entry_rate": round(_safe_div(n_filled, n_setups), 4),
            "setup_to_win_rate":   round(_safe_div(n_wins, n_setups), 4),
            "reject_rate":         round(_safe_div(n_setups - n_filled, n_setups), 4),
        }
        # frequency & exposure need time
        if self.has_time and n_filled:
            ent = pd.to_datetime(self.filled["entry_time"], errors="coerce")
            ext = pd.to_datetime(self.filled["exit_time"],  errors="coerce")
            span_days = max((ext.max() - ent.min()).total_seconds() / 86400.0, 1e-9)
            out["trades_per_day"]   = round(n_filled / span_days, 3)
            out["trades_per_week"]  = round(n_filled / span_days * 7, 3)
            out["trades_per_month"] = round(n_filled / span_days * 30.44, 3)
            in_market = (ext - ent).dt.total_seconds().sum()
            total_sec = (ext.max() - ent.min()).total_seconds()
            out["exposure_pct"]   = round(100 * _safe_div(in_market, total_sec), 2)
            out["time_in_market_days"] = round(in_market / 86400.0, 2)
        elif {"entry_bar", "exit_bar"}.issubset(self.filled.columns) and n_filled:
            bars = (self.filled["exit_bar"] - self.filled["entry_bar"]).astype(float)
            span = max(self.filled["exit_bar"].max() - self.filled["entry_bar"].min(), 1e-9)
            out["exposure_pct"] = round(100 * bars.sum() / span, 2)
        return out

    # ── 3-15 — P&L / win-loss statistics ─────────────────────────────────────

    def _pnl_stats(self) -> Dict:
        wins   = self.pnl[self.pnl > 0]
        losses = self.pnl[self.pnl < 0]
        gross_profit = float(wins.sum())
        gross_loss   = float(losses.sum())            # negative
        n = len(self.pnl)
        win_rate  = _safe_div(len(wins), n)
        loss_rate = _safe_div(len(losses), n)
        avg_win   = float(wins.mean())   if len(wins)   else np.nan
        avg_loss  = float(losses.mean()) if len(losses) else np.nan   # negative
        expectancy = (win_rate * avg_win if len(wins) else 0.0) + \
                     (loss_rate * avg_loss if len(losses) else 0.0)
        return {
            "net_profit":           round(float(self.pnl.sum()), 2),
            "gross_profit":         round(gross_profit, 2),
            "gross_loss":           round(gross_loss, 2),
            "win_rate":             round(win_rate, 4),
            "loss_rate":            round(loss_rate, 4),
            "profit_factor":        round(_safe_div(gross_profit, abs(gross_loss)), 3),
            "avg_win":              round(avg_win, 2),
            "avg_loss":             round(avg_loss, 2),
            "expectancy_per_trade": round(expectancy, 2),
            "expectancy_r":         round(float(self.r.mean()), 3) if len(self.r.dropna()) else np.nan,
            "payoff_ratio":         round(_safe_div(avg_win, abs(avg_loss)), 3),
            "avg_pnl_per_trade":    round(float(self.pnl.mean()), 2) if n else np.nan,
            "median_pnl_per_trade": round(float(self.pnl.median()), 2) if n else np.nan,
            "final_equity":         round(self.final_equity, 2),
            "total_return_pct":     round((self.final_equity / self.initial_capital - 1) * 100, 2),
        }

    # ── 19-35 — risk / return ratios on the return series ────────────────────

    def _risk_stats(self) -> Dict:
        r = self.returns
        out: Dict = {"returns_annualized": self.returns_annualized,
                     "return_frequency": self.resample_freq if self.returns_annualized else "per_trade"}

        # drawdown (on daily equity if available, else from the event curve)
        mdd_pct, mdd_abs = self._max_drawdown()
        out["max_drawdown_pct"] = round(mdd_pct, 2)          # positive magnitude
        out["max_drawdown"]     = round(mdd_abs, 2)
        dd_dur, rec_time, ulcer = self._drawdown_timing()
        out["max_drawdown_duration_days"] = dd_dur
        out["recovery_time_days"]         = rec_time
        out["ulcer_index"]                = round(ulcer, 3) if pd.notna(ulcer) else np.nan

        # CAGR / total return
        cagr = self._cagr()
        out["cagr_pct"] = round(cagr * 100, 2) if pd.notna(cagr) else np.nan
        total_ret = self.final_equity / self.initial_capital - 1

        if len(r) >= 2:
            mean, std = r.mean(), r.std(ddof=1)
            downside = np.sqrt(np.mean(np.minimum(0.0, r - self.rf_period) ** 2))
            out["volatility"]          = round(std * self.ann, 4)
            out["downside_volatility"] = round(downside * self.ann, 4)
            out["sharpe"]              = round(_safe_div(mean - self.rf_period, std) * self.ann, 3)
            out["sortino"]             = round(_safe_div(mean - self.rf_period, downside) * self.ann, 3)
            out["var_95"]              = round(-np.percentile(r, 100 * self.var_alpha), 4)
            out["var_99"]              = round(-np.percentile(r, 1), 4)
            thr = np.percentile(r, 100 * self.var_alpha)
            tail_lo = r[r <= thr]
            out["cvar_95"]   = round(-tail_lo.mean(), 4) if len(tail_lo) else np.nan
            thr99 = np.percentile(r, 1)
            tail99 = r[r <= thr99]
            out["cvar_99"]   = round(-tail99.mean(), 4) if len(tail99) else np.nan
            q95, q05 = np.percentile(r, 95), np.percentile(r, 5)
            out["tail_ratio"] = round(_safe_div(abs(q95), abs(q05)), 3)
            out["skew"]       = round(float(r.skew()), 3)
            out["kurtosis"]   = round(float(r.kurt()), 3)   # excess (Fisher)
        else:
            for k in ("volatility", "downside_volatility", "sharpe", "sortino",
                      "var_95", "var_99", "cvar_95", "cvar_99", "tail_ratio",
                      "skew", "kurtosis"):
                out[k] = np.nan

        # ratios vs drawdown
        out["calmar"]              = round(_safe_div(cagr, mdd_pct / 100), 3) if pd.notna(cagr) else np.nan
        out["return_to_drawdown"]  = round(_safe_div(total_ret, mdd_pct / 100), 3)

        # Jensen alpha / beta vs benchmark
        alpha, beta = self._jensen()
        out["jensen_alpha"] = round(alpha, 4) if pd.notna(alpha) else np.nan
        out["beta"]         = round(beta, 3) if pd.notna(beta) else np.nan

        # equity-curve smoothness (R^2 of equity vs time)
        out["equity_smoothness_r2"] = round(self._smoothness(), 4)
        return out

    def _max_drawdown(self) -> Tuple[float, float]:
        if len(self.eq_daily) >= 1:
            eq = self.eq_daily
            dd = eq / eq.cummax() - 1.0
            ddabs = eq - eq.cummax()
            return abs(float(dd.min())) * 100, abs(float(ddabs.min()))
        if "drawdown_pct" in self.curve:
            mdd = abs(float(self.curve["drawdown_pct"].min()))
            mda = abs(float(self.curve["drawdown"].min())) if "drawdown" in self.curve else np.nan
            return mdd, mda
        return np.nan, np.nan

    def _drawdown_timing(self) -> Tuple[Optional[float], Optional[float], float]:
        """Longest underwater stretch (days), recovery time of deepest (days), ulcer index."""
        if len(self.eq_daily) < 2:
            return None, None, np.nan
        eq = self.eq_daily
        peak = eq.cummax()
        dd = eq / peak - 1.0                     # <= 0
        ulcer = float(np.sqrt(np.mean((dd * 100) ** 2)))

        under = dd < -1e-12
        episodes = []      # (start, trough_t, end_or_None, trough_val)
        in_dd = False
        start = trough_t = None
        trough_v = 0.0
        for t, u in under.items():
            if u and not in_dd:
                in_dd, start, trough_t, trough_v = True, t, t, dd.loc[t]
            elif u and in_dd:
                if dd.loc[t] < trough_v:
                    trough_v, trough_t = dd.loc[t], t
            elif (not u) and in_dd:
                episodes.append((start, trough_t, t, trough_v))
                in_dd = False
        if in_dd:
            episodes.append((start, trough_t, None, trough_v))
        if not episodes:
            return 0.0, 0.0, ulcer

        def _days(a, b):
            return (b - a).total_seconds() / 86400.0
        longest = max(_days(s, (e if e is not None else eq.index[-1])) for s, _, e, _ in episodes)
        deepest = min(episodes, key=lambda ep: ep[3])
        s, tr, e, _ = deepest
        recovery = _days(tr, e) if e is not None else None       # None = still underwater
        return round(longest, 2), (round(recovery, 2) if recovery is not None else None), ulcer

    def _cagr(self) -> float:
        if not self.has_time or len(self.eq_daily) < 2:
            return np.nan
        years = (self.eq_daily.index[-1] - self.eq_daily.index[0]).days / 365.25
        if years <= 0 or self.initial_capital <= 0:
            return np.nan
        # A non-positive final equity (margin call / blown account) has no real
        # growth rate — (negative) ** (1/years) is a *complex* in Python, which
        # then crashes round(). Report the total loss as -100% instead.
        if self.final_equity <= 0:
            return -1.0
        return (self.final_equity / self.initial_capital) ** (1 / years) - 1

    def _jensen(self) -> Tuple[float, float]:
        if self.benchmark is None or not self.has_time or len(self.eq_daily) < 3:
            return np.nan, np.nan
        b = self.benchmark.copy()
        b.index = pd.to_datetime(b.index, errors="coerce")
        b = b[~b.index.isna()].sort_index()
        # treat as prices if it looks like a level series, else as returns
        br = b.resample(self.resample_freq).last().ffill().pct_change() if (b.abs() > 1).mean() > 0.5 \
            else b.resample(self.resample_freq).last()
        join = pd.concat([self.returns.rename("p"), br.rename("b")], axis=1).dropna()
        if len(join) < 3 or join["b"].var() == 0:
            return np.nan, np.nan
        beta = float(np.cov(join["p"], join["b"])[0, 1] / np.var(join["b"], ddof=1))
        alpha_p = (join["p"].mean() - self.rf_period) - beta * (join["b"].mean() - self.rf_period)
        return alpha_p * self.periods_per_year, beta      # annualized alpha

    def _smoothness(self) -> float:
        eq = self.eq_daily if len(self.eq_daily) >= 2 else self.curve["equity"]
        y = np.asarray(eq, dtype=float)
        if len(y) < 2 or np.std(y) == 0:
            return np.nan
        x = np.arange(len(y))
        return float(np.corrcoef(x, y)[0, 1] ** 2)

    # ── 42-44 — streaks ──────────────────────────────────────────────────────

    def _streaks(self) -> Dict:
        signs = np.sign(self.pnl.values)
        win_runs, loss_runs = [], []
        cur_sign, cur_len = 0, 0
        for s in signs:
            if s == cur_sign and s != 0:
                cur_len += 1
            else:
                if cur_sign > 0:
                    win_runs.append(cur_len)
                elif cur_sign < 0:
                    loss_runs.append(cur_len)
                cur_sign, cur_len = s, (1 if s != 0 else 0)
        if cur_sign > 0:
            win_runs.append(cur_len)
        elif cur_sign < 0:
            loss_runs.append(cur_len)
        return {
            "max_win_streak":  int(max(win_runs)) if win_runs else 0,
            "max_loss_streak": int(max(loss_runs)) if loss_runs else 0,
            "avg_win_streak":  round(float(np.mean(win_runs)), 2) if win_runs else 0.0,
            "avg_loss_streak": round(float(np.mean(loss_runs)), 2) if loss_runs else 0.0,
            "current_streak":  int(cur_sign * cur_len),
        }

    # ── 52-54 — timing / delays ──────────────────────────────────────────────

    def _delays(self) -> Dict:
        out: Dict = {}
        if self.has_time and len(self.filled):
            setup = pd.to_datetime(self.filled["setup_time"], errors="coerce")
            entry = pd.to_datetime(self.filled["entry_time"], errors="coerce")
            exit_ = pd.to_datetime(self.filled["exit_time"],  errors="coerce")
            s2e = (entry - setup).dt.total_seconds() / 3600.0      # hours
            hold = (exit_ - entry).dt.total_seconds() / 3600.0
            out["avg_setup_to_entry_hrs"] = round(float(s2e.mean()), 2)
            out["median_setup_to_entry_hrs"] = round(float(s2e.median()), 2)
            out["avg_entry_delay_hrs"] = round(float(s2e.mean()), 2)
            out["avg_exit_delay_hrs"]  = round(float(hold.mean()), 2)
            out["median_hold_hrs"]     = round(float(hold.median()), 2)
        elif "bars_to_entry_from_choch" in self.filled.columns:
            out["avg_entry_delay_bars"] = round(float(self.filled["bars_to_entry_from_choch"].mean()), 2)
            if {"entry_bar", "exit_bar"}.issubset(self.filled.columns):
                out["avg_exit_delay_bars"] = round(float((self.filled["exit_bar"] - self.filled["entry_bar"]).mean()), 2)
        return out

    # ── 36-41, 45 — time-based profit breakdowns (chart-ready) ───────────────

    def _by_period_profit(self) -> Dict[str, pd.Series]:
        frames: Dict[str, pd.Series] = {}
        if not (self.has_time and len(self.filled)):
            return frames
        f = self.filled.copy()
        f["_exit"]  = pd.to_datetime(f["exit_time"],  errors="coerce")
        f["_entry"] = pd.to_datetime(f["entry_time"], errors="coerce")
        pnl = f["net_pnl"].astype(float)

        frames["by_month"] = pnl.groupby(f["_exit"].dt.to_period("M").astype(str)).sum()
        frames["by_week"]  = pnl.groupby(f["_exit"].dt.to_period("W").astype(str)).sum()
        dow = pnl.groupby(f["_exit"].dt.dayofweek).sum()
        dow.index = [_DOW_NAMES[i] for i in dow.index]
        frames["by_dow"]  = dow
        frames["by_hour"] = pnl.groupby(f["_entry"].dt.hour).sum()
        frames["by_session"] = pnl.groupby(f["_entry"].dt.hour.map(self._session_of)).sum()
        return frames

    def _session_of(self, hour) -> str:
        if pd.isna(hour):
            return "unknown"
        for name, start, end in self.session_bins:
            if start <= hour < end:
                return name
        return "other"

    def monthly_returns(self) -> pd.Series:
        if not (self.has_time and len(self.eq_daily) >= 2):
            return pd.Series(dtype=float)
        m = self.eq_daily.resample("ME").last().ffill()
        ret = m.pct_change().dropna()
        ret.index = ret.index.to_period("M").astype(str)
        return ret

    # ── 46-49 — rolling series (chart-ready) ─────────────────────────────────

    def rolling_sharpe(self) -> pd.Series:
        if not (self.returns_annualized and len(self.returns) > self.rolling_window_days):
            return pd.Series(dtype=float)
        w, ann = self.rolling_window_days, self.ann
        return self.returns.rolling(w).apply(
            lambda x: ann * x.mean() / x.std(ddof=1) if x.std(ddof=1) > 0 else np.nan, raw=False)

    def rolling_drawdown(self) -> pd.Series:
        if len(self.eq_daily) < 2:
            return pd.Series(dtype=float)
        eq = self.eq_daily
        return (eq / eq.cummax() - 1.0) * 100.0     # underwater %, indexed by date

    def rolling_win_rate(self) -> pd.Series:
        if not len(self.filled):
            return pd.Series(dtype=float)
        win = (self.pnl > 0).astype(float)
        if self.has_time:
            win.index = pd.to_datetime(self.filled["exit_time"], errors="coerce").values
        return win.rolling(min(self.rolling_trades, len(win))).mean()

    def return_stability(self) -> Dict:
        """Stability of returns across rolling windows (#46)."""
        if not (self.returns_annualized and len(self.eq_daily) > self.rolling_window_days):
            return {"rolling_return_pct_positive": np.nan, "rolling_return_std": np.nan}
        rr = self.eq_daily.pct_change(self.rolling_window_days).dropna()
        return {
            "rolling_window_days": self.rolling_window_days,
            "rolling_return_pct_positive": round(100 * float((rr > 0).mean()), 2),
            "rolling_return_mean": round(float(rr.mean()), 4),
            "rolling_return_std":  round(float(rr.std(ddof=1)), 4),
            "rolling_return_min":  round(float(rr.min()), 4),
            "rolling_return_max":  round(float(rr.max()), 4),
        }

    # ── 2 — exit-reason breakdown (chart-ready pie) ──────────────────────────

    def exit_reason_breakdown(self) -> pd.DataFrame:
        if "exit_reason" not in self.result:
            return pd.DataFrame(columns=["exit_reason", "count", "pct"])
        counts = self.result["exit_reason"].value_counts(dropna=False)
        df = counts.rename_axis("exit_reason").reset_index(name="count")
        df["pct"] = (df["count"] / df["count"].sum() * 100).round(2)
        return df

    # ── assembly ─────────────────────────────────────────────────────────────

    def metrics(self) -> Dict:
        """Flat dict of every scalar KPI."""
        m: Dict = {}
        m.update(self._pnl_stats())          # 3-15
        m.update(self._trade_counts())       # 1, 16-18, 50-55
        m.update(self._risk_stats())         # 19-35
        m.update(self._streaks())            # 42-44
        m.update(self._delays())             # 52-54
        # 45 — % profitable months
        mr = self.monthly_returns()
        m["pct_profitable_months"] = round(100 * float((mr > 0).mean()), 2) if len(mr) else np.nan
        # 36 summary
        m["monthly_return_mean"] = round(float(mr.mean()), 4) if len(mr) else np.nan
        m["monthly_return_std"]  = round(float(mr.std(ddof=1)), 4) if len(mr) > 1 else np.nan
        # 46
        m.update(self.return_stability())
        return m

    def report(self) -> Dict:
        """Everything: scalar metrics + chart-ready frames/series."""
        out: Dict = {"metrics": self.metrics(),
                     "exit_reasons": self.exit_reason_breakdown(),
                     "monthly_returns": self.monthly_returns(),
                     "rolling_sharpe": self.rolling_sharpe(),
                     "rolling_drawdown": self.rolling_drawdown(),
                     "rolling_win_rate": self.rolling_win_rate(),
                     "equity_curve": self.curve}
        out.update(self._by_period_profit())   # by_month/week/dow/hour/session
        return out

    def to_frame(self) -> pd.DataFrame:
        """Scalar metrics as a tidy 2-column DataFrame (nice for display)."""
        return pd.DataFrame(self.metrics().items(), columns=["metric", "value"])


# ─────────────────────────────────────────────────────────────────────────────
# demo — full chain: synthetic trades → simulator → analytics
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    from libs.cfd_cost import CFDCostModel
    from libs.account import CFDAccountSimulator

    rng = np.random.default_rng(7)
    rows, t = [], pd.Timestamp("2024-01-02 08:00")
    for k in range(70):
        t = t + pd.Timedelta(hours=float(rng.integers(6, 60)))
        side = rng.choice(["long", "short"])
        entry = 18000 + rng.normal(0, 200)
        sl_dist = rng.uniform(30, 90)
        roll = rng.random()
        if roll < 0.12:                                   # invalidated setup (no fill)
            rows.append({"trade_id": f"T{k:05d}", "side": side, "setup_time": t,
                         "entry_time": None, "entry_price": None,
                         "exit_time": t + pd.Timedelta(hours=2), "exit_price": None,
                         "sl_price": None, "exit_reason": "Invalidation"})
            continue
        sl = entry - sl_dist if side == "long" else entry + sl_dist
        if roll < 0.55:                                   # win (TP ~ +2R)
            move = sl_dist * rng.uniform(1.5, 2.5); reason = "TP"
        elif roll < 0.85:                                 # loss (SL)
            move = -sl_dist; reason = "SL"
        else:                                             # timeout (small)
            move = sl_dist * rng.uniform(-0.5, 0.6); reason = "timeout"
        exit_p = entry + move if side == "long" else entry - move
        hold = pd.Timedelta(hours=float(rng.integers(2, 40)))
        rows.append({"trade_id": f"T{k:05d}", "side": side,
                     "setup_time": t - pd.Timedelta(hours=float(rng.integers(1, 6))),
                     "entry_time": t, "entry_price": round(entry, 2),
                     "exit_time": t + hold, "exit_price": round(exit_p, 2),
                     "sl_price": round(sl, 2), "exit_reason": reason,
                     "entry_bar": k, "exit_bar": k + 1, "bars_to_entry_from_choch": int(rng.integers(1, 5))})
    trades = pd.DataFrame(rows)

    sim = CFDAccountSimulator(symbol="NAS100", initial_capital=10_000,
                              use_risk_sizing=True, risk_mode="percent",
                              risk_per_trade=0.01, leverage=20.0)
    result, curve = sim.simulate(trades)

    perf = PerformanceAnalytics(result, curve, risk_free_rate=0.04, rolling_trades=10)
    rep = perf.report()
    print("=== METRICS ===")
    for kk, vv in rep["metrics"].items():
        print(f"{kk:30s} {vv}")
    print("\n=== EXIT REASONS (pie data) ===")
    print(rep["exit_reasons"].to_string(index=False))
    print("\n=== PROFIT BY MONTH ===")
    print(rep["by_month"].round(2).to_string())
    print("\n=== PROFIT BY SESSION ===")
    print(rep["by_session"].round(2).to_string())

    # consistency check: net profit must equal final − initial equity
    np.testing.assert_allclose(rep["metrics"]["net_profit"],
                               perf.final_equity - perf.initial_capital, atol=0.02)
    print("\n[check] net_profit == final − initial equity  ✓")