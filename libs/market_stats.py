"""
market_stats.py
===============
Per-pair, per-timeframe statistical *character* reports for FX / CFD price data.

Implements the six metric groups from the Statistical & Probabilistic Toolkit,
plus a regime-detection layer:

    1. Return distribution      fat tails, skew, normality, tail index, t-fit
    2. Volatility               OHLC estimators, GARCH/GJR, vol cones, clustering
    3. Mean reversion vs trend  ACF, Ljung-Box, variance ratio, Hurst, ADF,
                                OU half-life, DFA
    4. Session / intraday       Tokyo / London / New York profiles, ranges,
                                overlap concentration, breakout, extreme timing
    5. Calendar / seasonality   day-of-week, month, turn-of-month, news, rollover
    6. Probability of a move    conditional tables, Markov matrix, touch
                                probability, MFE/MAE, expected-move bands,
                                Monte-Carlo / stationary block bootstrap
    +  Regime detection         volatility-regime clustering + switch points

Dependencies
------------
Hard:   numpy, pandas, scipy, scikit-learn   (all standard)
None of statsmodels / arch / hmmlearn / ruptures are required — every method
those libraries would normally supply (GARCH MLE, ADF test, HMM, change points)
is implemented here from scratch. If you later install `arch` / `statsmodels`
you can swap in their validated estimators, but nothing here depends on them.

Input contract
--------------
df : pandas.DataFrame
    columns          : open, high, low, close   (case-insensitive; o/h/l/c ok)
    optional columns : volume / tick_volume, spread
    index            : pandas.DatetimeIndex — required for groups 4 & 5
                       (sessions / calendar). Other groups work on any index.

Quick start
-----------
    import pandas as pd
    from market_stats import MarketStats, character_report, analyze

    df = pd.read_csv("EURUSD_H1.csv", parse_dates=["time"], index_col="time")

    ms = MarketStats(df, tz="UTC")     # configure once
    print(ms.report())                  # readable character report (str)
    metrics = ms.to_dict()              # everything, nested dict

    # individual groups (each returns a dict):
    ms.distribution(); ms.volatility(); ms.mean_reversion()
    ms.sessions();     ms.calendar();   ms.probability(); ms.regimes()

    # convenience one-liners matching a (df) -> metrics convention:
    print(character_report(df))
    ms = analyze(df)

See the __main__ block at the bottom for a runnable demo on synthetic data.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy import stats
from scipy.optimize import minimize

try:
    from sklearn.mixture import GaussianMixture
    _HAS_SKLEARN = True
except Exception:                                       # pragma: no cover
    _HAS_SKLEARN = False


# ======================================================================
# Configuration
# ======================================================================

# FX session windows as (start_hour, end_hour) in the working timezone (UTC by
# default). A window with start > end wraps midnight (e.g. Sydney). These are
# conventional GMT/UTC boundaries and shift ~1h with daylight saving — override
# them to match your data's timezone if you need exact alignment.
DEFAULT_SESSIONS = {
    "sydney":  (21, 6),
    "tokyo":   (0, 9),     # "Asian" session
    "london":  (7, 16),
    "newyork": (12, 21),
}
# The window where London and New York are both open — the high-liquidity core.
DEFAULT_OVERLAP = (12, 16)

TRADING_DAYS = 252         # used only to turn bars-per-year into bars-per-day


# ======================================================================
# Low-level helpers
# ======================================================================

def _normalize_ohlc(df: pd.DataFrame) -> pd.DataFrame:
    """Lower-case and map common OHLCV/spread column aliases to canonical names."""
    alias = {
        "open": "open", "o": "open",
        "high": "high", "h": "high",
        "low": "low", "l": "low",
        "close": "close", "c": "close", "price": "close", "last": "close",
        "adj close": "close", "adj_close": "close",
        "volume": "volume", "vol": "volume",
        "tick_volume": "volume", "tickvol": "volume", "tickvolume": "volume",
        "spread": "spread",
    }
    rename = {}
    for col in df.columns:
        key = str(col).lower().strip()
        if key in alias:
            rename[col] = alias[key]
    out = df.rename(columns=rename).copy()
    if not isinstance(out.index, pd.DatetimeIndex):
        # leave as-is; session/calendar groups will report that they need a
        # DatetimeIndex, everything else still works.
        pass
    else:
        out = out[~out.index.duplicated(keep="first")].sort_index()
    return out


def _log_returns(close: pd.Series) -> pd.Series:
    return np.log(close / close.shift(1))


def _periods_per_year(index) -> float:
    """Bars per year, estimated empirically from the data span (accounts for
    weekends/holidays/gaps). Falls back to 252 for non-datetime indices."""
    if not isinstance(index, pd.DatetimeIndex) or len(index) < 3:
        return float(TRADING_DAYS)
    span_seconds = (index[-1] - index[0]).total_seconds()
    if span_seconds <= 0:
        return float(TRADING_DAYS)
    span_years = span_seconds / (365.25 * 24 * 3600)
    if span_years <= 0:
        return float(TRADING_DAYS)
    return max(len(index) / span_years, 1.0)


def _hours(index, tz):
    idx = index
    if getattr(idx, "tz", None) is not None and tz is not None:
        idx = idx.tz_convert(tz)
    return idx.hour


def _in_session(hours, start, end):
    if start <= end:
        return (hours >= start) & (hours < end)
    return (hours >= start) | (hours < end)


def _f(x):
    """Cast numpy scalar / None to plain float (NaN-safe) for clean dicts."""
    try:
        if x is None:
            return float("nan")
        return float(x)
    except (TypeError, ValueError):
        return x


# ----------------------------------------------------------------------
# Group 2 volatility estimators (annualised)
# ----------------------------------------------------------------------

def _vol_close_to_close(ret: np.ndarray, ppy: float) -> float:
    r = ret[np.isfinite(ret)]
    if r.size < 5:
        return np.nan
    return float(np.std(r, ddof=1) * np.sqrt(ppy))


def _vol_parkinson(h, l, ppy):
    with np.errstate(divide="ignore", invalid="ignore"):
        r = np.log(h / l)
    r = r[np.isfinite(r)]
    if r.size < 5:
        return np.nan
    var = np.mean(r ** 2) / (4 * np.log(2))
    return float(np.sqrt(max(var, 0) * ppy))


def _vol_garman_klass(o, h, l, c, ppy):
    with np.errstate(divide="ignore", invalid="ignore"):
        log_hl = np.log(h / l)
        log_co = np.log(c / o)
    m = np.isfinite(log_hl) & np.isfinite(log_co)
    if m.sum() < 5:
        return np.nan
    var = np.mean(0.5 * log_hl[m] ** 2 - (2 * np.log(2) - 1) * log_co[m] ** 2)
    return float(np.sqrt(max(var, 0) * ppy))


def _vol_rogers_satchell(o, h, l, c, ppy):
    with np.errstate(divide="ignore", invalid="ignore"):
        term = np.log(h / c) * np.log(h / o) + np.log(l / c) * np.log(l / o)
    term = term[np.isfinite(term)]
    if term.size < 5:
        return np.nan
    return float(np.sqrt(max(np.mean(term), 0) * ppy))


def _vol_yang_zhang(o, h, l, c, ppy):
    o, h, l, c = map(lambda a: np.asarray(a, float), (o, h, l, c))
    if c.size < 5:
        return np.nan
    prev_c = np.roll(c, 1)
    prev_c[0] = np.nan
    with np.errstate(divide="ignore", invalid="ignore"):
        log_oc = np.log(o / prev_c)      # overnight (open vs prev close)
        log_co = np.log(c / o)           # open-to-close
        rs = np.log(h / c) * np.log(h / o) + np.log(l / c) * np.log(l / o)
    m = np.isfinite(log_oc) & np.isfinite(log_co) & np.isfinite(rs)
    nn = int(m.sum())
    if nn < 5:
        return np.nan
    var_o = np.var(log_oc[m], ddof=1)
    var_c = np.var(log_co[m], ddof=1)
    var_rs = np.mean(rs[m])
    k = 0.34 / (1.34 + (nn + 1) / (nn - 1))
    var_yz = var_o + k * var_c + (1 - k) * var_rs
    return float(np.sqrt(max(var_yz, 0) * ppy))


def _atr(high, low, close, n=14):
    h, l, c = map(lambda s: pd.Series(np.asarray(s, float)), (high, low, close))
    prev_c = c.shift(1)
    tr = pd.concat([(h - l), (h - prev_c).abs(), (l - prev_c).abs()], axis=1).max(axis=1)
    # Wilder smoothing
    atr = tr.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    return float(atr.iloc[-1]) if atr.notna().any() else np.nan


# ----------------------------------------------------------------------
# Group 1 / 2: distribution helpers, GARCH MLE, clustering test
# ----------------------------------------------------------------------

def _hill_tail_index(ret, tail_frac=0.05, min_tail=15):
    x = np.abs(ret[np.isfinite(ret)])
    x = np.sort(x[x > 0])[::-1]
    n = x.size
    k = max(int(n * tail_frac), min_tail)
    if n <= k + 1:
        return np.nan
    xk = x[k]
    if xk <= 0:
        return np.nan
    gamma = np.mean(np.log(x[:k]) - np.log(xk))
    return float(1.0 / gamma) if gamma > 0 else np.nan


def _robust_t_dof(ret):
    """Stable estimate of Student-t degrees of freedom. MLE (location fixed at 0)
    is used when it returns a sane value; otherwise we fall back to the
    method-of-moments estimate from excess kurtosis (df = 4 + 6/excess_kurt,
    valid for df>4). Result is clamped to [2, 250]."""
    r = ret[np.isfinite(ret)]
    if r.size < 30:
        return np.nan
    ek = stats.kurtosis(r, fisher=True)
    moment = 4.0 + 6.0 / ek if ek > 1e-6 else np.nan
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            df_mle, _, _ = stats.t.fit(r, floc=0.0)
    except Exception:
        df_mle = np.nan
    cand = df_mle if (np.isfinite(df_mle) and 1.5 < df_mle < 300) else moment
    if not np.isfinite(cand):
        return np.nan
    return float(min(max(cand, 2.0), 250.0))


def _ljung_box(x, lags=10):
    """Manual Ljung-Box Q-test. Returns (Q, p-value, autocorrelations)."""
    x = np.asarray(x, float)
    x = x[np.isfinite(x)]
    x = x - x.mean()
    n = x.size
    if n < lags + 5:
        return np.nan, np.nan, []
    denom = np.sum(x * x)
    acfs = []
    for k in range(1, lags + 1):
        acfs.append(np.sum(x[k:] * x[:-k]) / denom)
    q = n * (n + 2) * sum((a ** 2) / (n - k) for k, a in enumerate(acfs, start=1))
    p = float(1 - stats.chi2.cdf(q, lags))
    return float(q), p, [float(a) for a in acfs]


def _garch_fit(ret, asymmetric=False, max_obs=4000):
    """GARCH(1,1) or GJR-GARCH(1,1,1) by maximum likelihood (Gaussian).
    Returns dict with omega/alpha/(gamma)/beta, persistence, and an indication
    of whether a leverage effect was found. Returns under percent-scaled returns."""
    r = np.asarray(pd.Series(ret).dropna(), float)
    r = r[np.isfinite(r)]
    if r.size < 250:
        return None
    if r.size > max_obs:                 # keep the sequential loop fast
        r = r[-max_obs:]
    r = r * 100.0                        # scale to percent for stability
    eps = r - r.mean()
    n = eps.size
    var0 = float(np.var(eps))
    neg = (eps < 0).astype(float)

    def nll(params):
        if asymmetric:
            omega, alpha, gamma, beta = params
            if omega <= 0 or alpha < 0 or beta < 0 or (alpha + gamma) < 0:
                return 1e12
            if alpha + beta + 0.5 * gamma >= 0.9999:
                return 1e12
        else:
            omega, alpha, beta = params
            gamma = 0.0
            if omega <= 0 or alpha < 0 or beta < 0 or alpha + beta >= 0.9999:
                return 1e12
        sig2 = np.empty(n)
        sig2[0] = var0
        e2 = eps ** 2
        for t in range(1, n):
            sig2[t] = omega + (alpha + gamma * neg[t - 1]) * e2[t - 1] + beta * sig2[t - 1]
        sig2 = np.maximum(sig2, 1e-10)
        return 0.5 * np.sum(np.log(2 * np.pi) + np.log(sig2) + e2 / sig2)

    if asymmetric:
        x0 = [0.1 * var0, 0.03, 0.04, 0.90]
        bounds = [(1e-10, None), (0, 0.999), (-0.5, 0.999), (0, 0.999)]
        cons = [{"type": "ineq", "fun": lambda p: 0.999 - p[1] - p[3] - 0.5 * p[2]}]
    else:
        x0 = [0.1 * var0, 0.05, 0.90]
        bounds = [(1e-10, None), (0, 0.999), (0, 0.999)]
        cons = [{"type": "ineq", "fun": lambda p: 0.999 - p[1] - p[2]}]

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            res = minimize(nll, x0, method="SLSQP", bounds=bounds,
                           constraints=cons, options={"maxiter": 400, "ftol": 1e-9})
        except Exception:
            return None
    if not np.all(np.isfinite(res.x)):
        return None

    if asymmetric:
        omega, alpha, gamma, beta = res.x
        persistence = alpha + beta + 0.5 * gamma
        out = {"model": "GJR-GARCH(1,1,1)", "omega": _f(omega), "alpha": _f(alpha),
               "gamma": _f(gamma), "beta": _f(beta), "persistence": _f(persistence),
               "leverage_effect": bool(gamma > 1e-3), "converged": bool(res.success),
               "n_obs": int(n)}
    else:
        omega, alpha, beta = res.x
        persistence = alpha + beta
        uncond = omega / (1 - persistence) if persistence < 1 else np.nan
        out = {"model": "GARCH(1,1)", "omega": _f(omega), "alpha": _f(alpha),
               "beta": _f(beta), "persistence": _f(persistence),
               "uncond_sigma_pct_per_bar": _f(np.sqrt(uncond)) if np.isfinite(uncond) else np.nan,
               "converged": bool(res.success), "n_obs": int(n)}
    return out


# ----------------------------------------------------------------------
# Group 3: memory / mean-reversion helpers
# ----------------------------------------------------------------------

def _acf(x, lags=10):
    x = np.asarray(x, float)
    x = x[np.isfinite(x)]
    x = x - x.mean()
    denom = np.sum(x * x)
    if denom == 0 or x.size < lags + 5:
        return [np.nan] * lags
    return [float(np.sum(x[k:] * x[:-k]) / denom) for k in range(1, lags + 1)]


def _variance_ratio(logp, q):
    """Lo-MacKinlay variance ratio for holding period q with homoskedastic
    z-statistic. VR>1 trending, VR<1 mean-reverting, ~1 random walk."""
    logp = np.asarray(logp, float)
    logp = logp[np.isfinite(logp)]
    n = logp.size - 1
    if n < 4 * q:
        return np.nan, np.nan, np.nan
    r = np.diff(logp)
    mu = r.mean()
    var1 = np.sum((r - mu) ** 2) / (n - 1)
    rq = logp[q:] - logp[:-q]
    m = q * (n - q + 1) * (1 - q / n)
    if m <= 0 or var1 == 0:
        return np.nan, np.nan, np.nan
    varq = np.sum((rq - q * mu) ** 2) / m
    vr = varq / var1
    phi = (2 * (2 * q - 1) * (q - 1)) / (3 * q * n)
    z = (vr - 1) / np.sqrt(phi) if phi > 0 else np.nan
    p = float(2 * (1 - stats.norm.cdf(abs(z)))) if np.isfinite(z) else np.nan
    return float(vr), float(z), p


def _hurst_rs(x, min_n=8):
    """Rescaled-range (R/S) Hurst exponent on an increment series (e.g. returns).
    ~0.5 random walk, <0.5 mean-reverting, >0.5 trending."""
    x = np.asarray(x, float)
    x = x[np.isfinite(x)]
    N = x.size
    if N < 2 * min_n:
        return np.nan
    max_n = N // 2
    ns = np.unique(np.floor(np.logspace(np.log10(min_n), np.log10(max_n), 20)).astype(int))
    rs_vals, used = [], []
    for n in ns:
        if n < min_n or n > N // 2:
            continue
        k = N // n
        chunk = []
        for i in range(k):
            seg = x[i * n:(i + 1) * n]
            dev = np.cumsum(seg - seg.mean())
            R = dev.max() - dev.min()
            S = seg.std(ddof=1)
            if S > 0:
                chunk.append(R / S)
        if chunk:
            rs_vals.append(np.mean(chunk))
            used.append(n)
    if len(used) < 3:
        return np.nan
    return float(np.polyfit(np.log(used), np.log(rs_vals), 1)[0])


def _dfa(x, min_n=8):
    """Detrended fluctuation analysis exponent (long-memory, tolerant of
    non-stationarity). ~0.5 uncorrelated, >0.5 persistent, <0.5 anti-persistent."""
    x = np.asarray(x, float)
    x = x[np.isfinite(x)]
    N = x.size
    if N < 4 * min_n:
        return np.nan
    y = np.cumsum(x - x.mean())
    max_n = N // 4
    ns = np.unique(np.floor(np.logspace(np.log10(min_n), np.log10(max_n), 20)).astype(int))
    F, used = [], []
    for n in ns:
        if n < min_n or n > N // 2:
            continue
        k = N // n
        rms = []
        t = np.arange(n)
        for i in range(k):
            seg = y[i * n:(i + 1) * n]
            coef = np.polyfit(t, seg, 1)
            rms.append(np.sqrt(np.mean((seg - np.polyval(coef, t)) ** 2)))
        if rms:
            F.append(np.sqrt(np.mean(np.array(rms) ** 2)))
            used.append(n)
    if len(used) < 3:
        return np.nan
    return float(np.polyfit(np.log(used), np.log(F), 1)[0])


def _half_life(series):
    """OU half-life of mean reversion on the level series. NaN if not
    mean-reverting (positive regression coefficient)."""
    s = pd.Series(series).dropna()
    if s.size < 30:
        return np.nan
    lag = s.shift(1)
    delta = s - lag
    d = pd.concat([delta, lag], axis=1).dropna()
    d.columns = ["delta", "lag"]
    X = np.column_stack([np.ones(len(d)), d["lag"].values])
    beta, *_ = np.linalg.lstsq(X, d["delta"].values, rcond=None)
    lam = beta[1]
    if lam >= 0:
        return np.nan
    return float(-np.log(2) / lam)


def _ols(y, X):
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta
    n, k = X.shape
    dof = max(n - k, 1)
    sigma2 = (resid @ resid) / dof
    XtX_inv = np.linalg.pinv(X.T @ X)
    se = np.sqrt(np.maximum(np.diag(sigma2 * XtX_inv), 0))
    with np.errstate(divide="ignore", invalid="ignore"):
        t = beta / se
    rss = resid @ resid
    llf = -0.5 * n * (np.log(2 * np.pi) + np.log(rss / n + 1e-300) + 1)
    aic = -2 * llf + 2 * k
    return beta, t, resid, aic


def _adf(series):
    """Augmented Dickey-Fuller test (constant, no trend) with AIC lag selection.
    Critical values are the standard asymptotic ones, so treat the verdict as
    indicative rather than exact for short samples."""
    y = np.asarray(pd.Series(series).astype(float).dropna())
    n = y.size
    if n < 30:
        return {"stat": np.nan, "lag": None, "stationary_5pct": None,
                "crit_5pct": -2.86}
    dy = np.diff(y)
    lev = y[:-1]
    L = dy.size
    maxlag = max(0, min(int(12 * ((n / 100.0) ** 0.25)), n // 3))
    best_aic, best = np.inf, None
    for p in range(0, maxlag + 1):
        T = L - p
        if T < 15:
            break
        yv = dy[p:L]
        cols = [np.ones(T), lev[p:L]]
        for i in range(1, p + 1):
            cols.append(dy[p - i:L - i])
        X = np.column_stack(cols)
        try:
            _, tstat, _, aic = _ols(yv, X)
        except Exception:
            continue
        if np.isfinite(aic) and aic < best_aic:
            best_aic, best = aic, (p, float(tstat[1]))
    if best is None:
        return {"stat": np.nan, "lag": None, "stationary_5pct": None,
                "crit_5pct": -2.86}
    lag, adf_stat = best
    crit = {"1%": -3.43, "5%": -2.86, "10%": -2.57}
    return {"stat": adf_stat, "lag": int(lag),
            "stationary_5pct": bool(adf_stat < crit["5%"]),
            "crit_5pct": crit["5%"], "crit": crit}


# ----------------------------------------------------------------------
# Group 6: probability / simulation helpers
# ----------------------------------------------------------------------

def _touch_prob_analytic(k):
    """Reflection principle (driftless): P(price touches +/- k*sigma over the
    horizon) for one barrier = 2*(1-Phi(k))."""
    return float(2 * (1 - stats.norm.cdf(k)))


def _bs_put_frac(vol, t_years, moneyness):
    """Black-Scholes put value as a fraction of spot (r=0, S=1, K=moneyness).
    Used for a rough crash-insurance (protective-put) cost estimate."""
    if vol <= 0 or t_years <= 0:
        return float(max(0.0, moneyness - 1.0))
    srt = vol * np.sqrt(t_years)
    d1 = (-np.log(moneyness) + 0.5 * srt * srt) / srt
    d2 = d1 - srt
    return float(moneyness * stats.norm.cdf(-d2) - stats.norm.cdf(-d1))


def _stationary_bootstrap(returns, horizon, n_sims, mean_block=20, seed=0):
    r = np.asarray(pd.Series(returns).dropna(), float)
    r = r[np.isfinite(r)]
    N = r.size
    if N < 30:
        return None
    rng = np.random.default_rng(seed)
    p = 1.0 / max(mean_block, 1)
    paths = np.empty((n_sims, horizon))
    for s in range(n_sims):
        idx = rng.integers(0, N)
        for t in range(horizon):
            paths[s, t] = r[idx]
            if rng.random() < p:
                idx = rng.integers(0, N)
            else:
                idx = (idx + 1) % N
    return paths


# ======================================================================
# Main engine
# ======================================================================

@dataclass
class MarketStats:
    """Compute statistical character metrics for one OHLC series.

    Parameters
    ----------
    df : DataFrame with open/high/low/close (+ optional volume, spread).
    tz : timezone name for session/calendar grouping (default 'UTC'). If the
         index is tz-aware it is converted; if tz-naive it is assumed already
         in this timezone.
    sessions : dict of {name: (start_hour, end_hour)} in `tz`. Defaults to the
         conventional FX windows in DEFAULT_SESSIONS.
    overlap : (start_hour, end_hour) of the London/NY overlap window.
    periods_per_year : override the inferred bars-per-year (annualisation).
    name : label used in the report header (e.g. the pair / timeframe).
    """
    df: pd.DataFrame
    tz: str = "UTC"
    session_windows: dict = field(default_factory=lambda: dict(DEFAULT_SESSIONS))
    overlap: tuple = DEFAULT_OVERLAP
    periods_per_year: float | None = None
    name: str = "instrument"

    def __post_init__(self):
        self._df = _normalize_ohlc(self.df)
        required = {"open", "high", "low", "close"}
        missing = required - set(self._df.columns)
        if missing:
            raise ValueError(f"missing required column(s): {sorted(missing)}")
        self._close = self._df["close"].astype(float)
        self._ret = _log_returns(self._close).dropna()
        self._ret_np = self._ret.to_numpy()
        self._has_dt = isinstance(self._df.index, pd.DatetimeIndex)
        self.ppy = float(self.periods_per_year) if self.periods_per_year \
            else _periods_per_year(self._df.index)
        self.bars_per_day = max(self.ppy / TRADING_DAYS, 1e-9)
        self._cache: dict = {}

    # ---- Group 1 -----------------------------------------------------
    def distribution(self) -> dict:
        if "distribution" in self._cache:
            return self._cache["distribution"]
        r = self._ret_np
        out = {}
        if r.size < 20:
            out = {"note": "insufficient data"}
        else:
            jb_stat, jb_p = stats.jarque_bera(r)
            tdof = _robust_t_dof(r)
            qs = [0.01, 0.05, 0.25, 0.5, 0.75, 0.95, 0.99]
            out = {
                "n_returns": int(r.size),
                "mean": _f(r.mean()),
                "std": _f(r.std(ddof=1)),
                "skewness": _f(stats.skew(r)),
                "excess_kurtosis": _f(stats.kurtosis(r, fisher=True)),
                "jarque_bera_stat": _f(jb_stat),
                "jarque_bera_p": _f(jb_p),
                "is_normal_5pct": bool(jb_p > 0.05),
                "hill_tail_index": _f(_hill_tail_index(r)),
                "student_t_dof": _f(tdof),
                "empirical_quantiles": {str(q): _f(np.quantile(r, q)) for q in qs},
            }
        self._cache["distribution"] = out
        return out

    # ---- Desk walkthrough (distribution-derived) --------------------
    def desk_distribution(self, book: float = 1_000_000.0,
                          target_vol: float = 0.10,
                          confidence_levels=(0.90, 0.95, 0.975, 0.99, 0.995),
                          kelly_fraction: float = 0.25,
                          hedge_tenor_months: float = 1.0,
                          hedge_strikes=(0.95, 0.90)) -> dict:
        """Translate the return distribution into a trading-desk walkthrough.

        Steps mirror how a desk reads the block:
          1. annualise vol / drift / Sharpe
          2. size the position to a volatility target
          4. daily loss limit (VaR) across confidence levels
          5. expected shortfall (CVaR) across confidence levels
          6. cap leverage with Kelly (+ a tail-index ceiling)
          7. crash-insurance (protective-put) cost

        Parameters are *desk choices*, not properties of the data:
            book               account / book equity (currency units)
            target_vol         annualised vol budget for this sleeve
            confidence_levels  VaR / ES levels to tabulate
            kelly_fraction     fraction of full-Kelly actually run
            hedge_tenor_months protective-put tenor for the cost estimate
            hedge_strikes      put strikes as moneyness K/S (0.95 = 5% OTM)

        Returns a nested dict (JSON-friendly). NB illustrative desk mechanics,
        not advice; the VaR/ES tails assume a *long* position (lower tail) — for
        a short book use the upper tail instead.
        """
        d = self.distribution()
        if "note" in d:
            return {"note": d["note"]}
        r = self._ret_np
        n = int(r.size)
        ppy = self.ppy
        mu = float(r.mean())
        sd = float(r.std(ddof=1))
        skew = float(stats.skew(r))
        hill = _hill_tail_index(r)
        sqppy = np.sqrt(ppy)

        # 1. annualise
        ann_vol = sd * sqppy
        ann_drift = mu * ppy
        per_bar_sharpe = mu / sd if sd else 0.0
        t_stat = per_bar_sharpe * np.sqrt(n)
        ann_sharpe = ann_drift / ann_vol if ann_vol else 0.0
        if abs(t_stat) < 1:
            bias = "no directional edge (drift ~ noise)"
        elif abs(t_stat) < 2:
            bias = "weak drift (tilt only)"
        else:
            bias = "real drift -> long bias" if mu > 0 else "real drift -> short/avoid"

        # 2. size the position to the vol target
        weight = target_vol / ann_vol if ann_vol else 0.0
        notional = weight * book
        daily_pl_sd = notional * sd
        annual_pl_sd = daily_pl_sd * sqppy

        # 4. daily loss limit (VaR) + 5. expected shortfall, per confidence level
        loss_limits, es_rows = [], []
        for c in confidence_levels:
            tail = 1.0 - c
            qret = float(np.quantile(r, tail))              # negative = loss
            var_d = notional * abs(qret)
            zc = float(stats.norm.ppf(tail))                # negative
            var_g = notional * abs(zc) * sd
            gap = (var_d / var_g - 1.0) if var_g else None
            loss_limits.append({
                "confidence": _f(c), "tail_prob": _f(tail),
                "quantile_return": _f(qret),
                "var_dollar": _f(var_d), "var_pct_book": _f(var_d / book),
                "once_per_bars": _f(1.0 / tail) if tail else None,
                "expected_per_year": _f(tail * ppy),
                "chance_worse_day": _f(tail),
                "gaussian_var_dollar": _f(var_g), "gaussian_gap": _f(gap),
            })
            tail_losses = r[r <= qret]
            es_ret = float(tail_losses.mean()) if tail_losses.size else qret
            es_d = notional * abs(es_ret)
            es_rows.append({
                "confidence": _f(c), "tail_prob": _f(tail),
                "es_return": _f(es_ret),
                "es_dollar": _f(es_d), "es_pct_book": _f(es_d / book),
                "es_over_var": _f(es_d / var_d) if var_d else None,
            })

        # 6. cap leverage with Kelly (+ tail-index ceiling)
        full_kelly = mu / (sd * sd) if sd else 0.0
        capped = full_kelly * kelly_fraction
        if hill is None or not np.isfinite(hill):
            tail_cap = 1.0
        elif hill > 4:
            tail_cap = 2.0
        elif hill > 3:
            tail_cap = 1.0
        elif hill > 2:
            tail_cap = 0.5
        else:
            tail_cap = 0.25
        suggested = min(capped, tail_cap) if capped > 0 else tail_cap
        q01 = float(np.quantile(r, 0.01))
        leverage = {
            "full_kelly": _f(full_kelly), "kelly_fraction": _f(kelly_fraction),
            "capped_kelly": _f(capped), "tail_index": _f(hill),
            "tail_cap": _f(tail_cap), "suggested_max": _f(suggested),
            "loss_at_full_kelly_1pct": _f(full_kelly * q01),
        }

        # 7. crash insurance (protective put; skew-bumped IV for OTM strikes)
        T = hedge_tenor_months / 12.0
        skew_prem = max(0.0, -skew)
        strikes = sorted(set((1.0,) + tuple(hedge_strikes)), reverse=True)
        crash = []
        for m in strikes:
            otm = 1.0 - m
            iv = ann_vol + skew_prem * 0.06 * (otm / 0.05 if otm > 0 else 0.0)
            frac = _bs_put_frac(iv, T, m)
            crash.append({
                "strike_moneyness": _f(m), "otm_pct": _f(otm),
                "tenor_months": _f(hedge_tenor_months), "iv_used": _f(iv),
                "cost_pct_notional": _f(frac), "cost_dollar": _f(notional * frac),
            })

        return {
            "params": {"book": _f(book), "target_vol": _f(target_vol),
                       "kelly_fraction": _f(kelly_fraction),
                       "hedge_tenor_months": _f(hedge_tenor_months),
                       "bars_per_year": _f(ppy), "n_returns": n},
            "annualized": {"vol": _f(ann_vol), "drift": _f(ann_drift),
                           "sharpe": _f(ann_sharpe),
                           "per_bar_sharpe": _f(per_bar_sharpe),
                           "t_stat": _f(t_stat), "bias": bias},
            "sizing": {"weight": _f(weight), "notional": _f(notional),
                       "daily_pl_sd": _f(daily_pl_sd),
                       "annual_pl_sd": _f(annual_pl_sd)},
            "loss_limits": loss_limits,
            "expected_shortfall": es_rows,
            "leverage": leverage,
            "crash_insurance": crash,
        }

    # ---- Group 2 -----------------------------------------------------
    def volatility(self) -> dict:
        if "volatility" in self._cache:
            return self._cache["volatility"]
        d, ppy = self._df, self.ppy
        o, h, l, c = (d["open"].to_numpy(), d["high"].to_numpy(),
                      d["low"].to_numpy(), d["close"].to_numpy())
        r = self._ret_np

        # vol cones: rolling annualised vol at several windows + current percentile
        cones = {}
        ret_s = self._ret
        for w in (10, 20, 60, 120):
            if ret_s.size > w + 5:
                rv = ret_s.rolling(w).std(ddof=1) * np.sqrt(ppy)
                cur = rv.iloc[-1]
                pct = float((rv.dropna() < cur).mean()) if rv.notna().sum() > 5 else np.nan
                cones[f"{w}bar"] = {
                    "current": _f(cur), "median": _f(rv.median()),
                    "p10": _f(rv.quantile(0.10)), "p90": _f(rv.quantile(0.90)),
                    "current_percentile": _f(pct),
                }

        lb_q, lb_p, _ = _ljung_box(r ** 2, lags=10)   # ARCH effect / clustering
        vov = np.nan
        if ret_s.size > 30:
            rolling_vol = ret_s.rolling(20).std(ddof=1)
            vov = _f(rolling_vol.std())

        out = {
            "annualised": {
                "close_to_close": _f(_vol_close_to_close(r, ppy)),
                "parkinson": _f(_vol_parkinson(h, l, ppy)),
                "garman_klass": _f(_vol_garman_klass(o, h, l, c, ppy)),
                "rogers_satchell": _f(_vol_rogers_satchell(o, h, l, c, ppy)),
                "yang_zhang": _f(_vol_yang_zhang(o, h, l, c, ppy)),
            },
            "atr_14": _f(_atr(h, l, c, 14)),
            "vol_of_vol": vov,
            "volatility_cones": cones,
            "clustering_test": {
                "ljung_box_sq_returns_stat": _f(lb_q),
                "ljung_box_sq_returns_p": _f(lb_p),
                "clustering_present_5pct": bool(np.isfinite(lb_p) and lb_p < 0.05),
            },
            "garch": _garch_fit(r, asymmetric=False),
            "gjr_garch": _garch_fit(r, asymmetric=True),
            "bars_per_year_used": _f(ppy),
        }
        self._cache["volatility"] = out
        return out

    # ---- Group 3 -----------------------------------------------------
    def mean_reversion(self) -> dict:
        if "mean_reversion" in self._cache:
            return self._cache["mean_reversion"]
        r = self._ret_np
        logp = np.log(self._close.dropna().to_numpy())
        acfs = _acf(r, lags=10)
        lb_q, lb_p, _ = _ljung_box(r, lags=10)
        vr = {f"q{q}": dict(zip(("vr", "z", "p"), _variance_ratio(logp, q)))
              for q in (2, 4, 8, 16)}
        hurst = _hurst_rs(r)
        adf = _adf(self._close)

        # verdict
        verdict, signals = "random walk (no exploitable memory)", []
        if np.isfinite(hurst):
            if hurst < 0.45:
                signals.append("mean-reverting")
            elif hurst > 0.55:
                signals.append("trending")
        vr2 = vr["q2"]["vr"]
        if np.isfinite(vr2):
            if vr2 < 0.9:
                signals.append("mean-reverting")
            elif vr2 > 1.1:
                signals.append("trending")
        if signals:
            mr = signals.count("mean-reverting")
            tr = signals.count("trending")
            if mr > tr:
                verdict = "mean-reverting"
            elif tr > mr:
                verdict = "trending / momentum"
            else:
                verdict = "mixed / regime-dependent"

        out = {
            "acf_returns": {f"lag{i+1}": v for i, v in enumerate(acfs)},
            "ljung_box_returns_stat": _f(lb_q),
            "ljung_box_returns_p": _f(lb_p),
            "serial_dependence_5pct": bool(np.isfinite(lb_p) and lb_p < 0.05),
            "variance_ratio": vr,
            "hurst_rs": _f(hurst),
            "dfa_exponent": _f(_dfa(r)),
            "adf": adf,
            "half_life_bars": _f(_half_life(self._close)),
            "verdict": verdict,
        }
        self._cache["mean_reversion"] = out
        return out

    # ---- Group 4 -----------------------------------------------------
    def sessions(self) -> dict:
        if "sessions" in self._cache:
            return self._cache["sessions"]
        if not self._has_dt:
            out = {"note": "DatetimeIndex required for session metrics"}
            self._cache["sessions"] = out
            return out
        if self.bars_per_day < 2:
            out = {"note": "session metrics need intraday (sub-daily) bars; "
                           "this data looks daily or coarser"}
            self._cache["sessions"] = out
            return out

        d = self._df.copy()
        hours = _hours(d.index, self.tz)
        d = d.assign(_hour=np.asarray(hours))
        abs_ret = self._ret.abs()

        # intraday vol profile: mean |return| by hour
        prof = abs_ret.groupby(_hours(abs_ret.index, self.tz)).mean()
        profile = {int(hh): _f(v) for hh, v in prof.items()}
        peak_hour = int(prof.idxmax()) if prof.notna().any() else None
        trough_hour = int(prof.idxmin()) if prof.notna().any() else None

        # per-session average range (group by a session-anchored date so windows
        # that wrap midnight are handled by shifting the timestamp by start hour)
        idx = d.index
        if getattr(idx, "tz", None) is not None and self.tz is not None:
            idx = idx.tz_convert(self.tz)
        session_adr = {}
        session_share = {}
        full_day_range = None
        # full-day range per calendar date (denominator for overlap share)
        day_grp = d.groupby(idx.normalize())
        day_range = (day_grp["high"].max() - day_grp["low"].min())
        full_day_range = _f(day_range.mean())

        for sname, (start, end) in self.session_windows.items():
            mask = _in_session(d["_hour"].to_numpy(), start, end)
            sub = d[mask]
            if sub.empty:
                session_adr[sname] = np.nan
                continue
            sidx = sub.index
            if getattr(sidx, "tz", None) is not None and self.tz is not None:
                sidx = sidx.tz_convert(self.tz)
            anchor = (sidx - pd.Timedelta(hours=start)).normalize()
            g = sub.groupby(anchor)
            rng = (g["high"].max() - g["low"].min())
            session_adr[sname] = _f(rng.mean())

        # London/NY overlap concentration: overlap range / full-day range
        ostart, oend = self.overlap
        omask = _in_session(d["_hour"].to_numpy(), ostart, oend)
        osub = d[omask]
        overlap_share = np.nan
        if not osub.empty and day_range.notna().any():
            oidx = osub.index
            if getattr(oidx, "tz", None) is not None and self.tz is not None:
                oidx = oidx.tz_convert(self.tz)
            og = osub.groupby(oidx.normalize())
            orange = (og["high"].max() - og["low"].min())
            aligned = pd.concat([orange.rename("o"), day_range.rename("d")], axis=1).dropna()
            if not aligned.empty:
                overlap_share = _f((aligned["o"] / aligned["d"].replace(0, np.nan)).mean())

        # Asian (tokyo) range -> London breakout probability
        breakout = self._asian_breakout(d, idx)

        # daily high / low formation-hour distribution
        hi_hour = day_grp.apply(lambda x: x["high"].idxmax(), include_groups=False)
        lo_hour = day_grp.apply(lambda x: x["low"].idxmin(), include_groups=False)
        def _hour_hist(ts_series):
            hh = pd.DatetimeIndex(pd.to_datetime(ts_series.values))
            if getattr(hh, "tz", None) is not None and self.tz is not None:
                hh = hh.tz_convert(self.tz)
            vc = pd.Series(hh.hour).value_counts(normalize=True).sort_index()
            return {int(k): _f(v) for k, v in vc.items()}

        # weekend / inter-session gaps
        gaps = (d["open"] - d["close"].shift(1)) / d["close"].shift(1)
        gaps = gaps.dropna()

        # volume & spread by hour, if present
        vol_by_hour = {}
        if "volume" in d.columns:
            vbh = d.groupby("_hour")["volume"].mean()
            vol_by_hour = {int(k): _f(v) for k, v in vbh.items()}
        spread_by_hour = {}
        if "spread" in d.columns:
            sbh = d.groupby("_hour")["spread"].mean()
            spread_by_hour = {int(k): _f(v) for k, v in sbh.items()}

        out = {
            "intraday_vol_profile_abs_ret": profile,
            "peak_vol_hour": peak_hour,
            "trough_vol_hour": trough_hour,
            "session_avg_range": session_adr,
            "full_day_avg_range": full_day_range,
            "overlap_range_share_of_day": overlap_share,
            "asian_range_breakout": breakout,
            "daily_high_formation_hour_dist": _hour_hist(hi_hour),
            "daily_low_formation_hour_dist": _hour_hist(lo_hour),
            "gap_stats": {
                "mean_abs_gap": _f(gaps.abs().mean()),
                "p95_abs_gap": _f(gaps.abs().quantile(0.95)),
                "max_abs_gap": _f(gaps.abs().max()),
            },
            "volume_by_hour": vol_by_hour,
            "spread_by_hour": spread_by_hour,
        }
        self._cache["sessions"] = out
        return out

    def _asian_breakout(self, d, idx):
        try:
            a_start, a_end = self.session_windows.get("tokyo", (0, 9))
            l_start, l_end = self.session_windows.get("london", (7, 16))
            hour = d["_hour"].to_numpy()
            a_mask = _in_session(hour, a_start, a_end)
            l_mask = _in_session(hour, l_start, l_end)
            date = pd.Series(idx.normalize(), index=d.index)
            asian = d[a_mask]
            london = d[l_mask]
            if asian.empty or london.empty:
                return {"note": "insufficient session data"}
            a_hi = asian.groupby(date[a_mask])["high"].max()
            a_lo = asian.groupby(date[a_mask])["low"].min()
            l_hi = london.groupby(date[l_mask])["high"].max()
            l_lo = london.groupby(date[l_mask])["low"].min()
            common = a_hi.index.intersection(l_hi.index)
            if len(common) < 10:
                return {"note": "too few overlapping days"}
            broke_up = (l_hi[common] > a_hi[common])
            broke_dn = (l_lo[common] < a_lo[common])
            broke_any = (broke_up | broke_dn)
            return {
                "days": int(len(common)),
                "p_break_either_side": _f(broke_any.mean()),
                "p_break_up": _f(broke_up.mean()),
                "p_break_down": _f(broke_dn.mean()),
            }
        except Exception as e:                       # pragma: no cover
            return {"note": f"breakout calc failed: {e}"}

    # ---- Group 5 -----------------------------------------------------
    def calendar(self, news_times=None, holidays=None, rollover_hour=21) -> dict:
        if not self._has_dt:
            return {"note": "DatetimeIndex required for calendar metrics"}
        ret = self._ret
        idx = ret.index
        if getattr(idx, "tz", None) is not None and self.tz is not None:
            idx = idx.tz_convert(self.tz)

        # day-of-week effect (0=Mon)
        dow = pd.DataFrame({"ret": ret.values, "abs": ret.abs().values}, index=idx)
        dow_g = dow.groupby(dow.index.dayofweek)
        names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        dow_eff = {names[k]: {"mean_ret": _f(v["ret"].mean()),
                              "mean_abs_ret": _f(v["abs"].mean())}
                   for k, v in dow_g}

        # month-of-year effect (volatility seasonality is the robust part)
        moy_g = dow.groupby(dow.index.month)
        months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        moy_eff = {months[m - 1]: {"mean_ret": _f(v["ret"].mean()),
                                   "ann_vol": _f(v["ret"].std(ddof=1) * np.sqrt(self.ppy))}
                   for m, v in moy_g}

        # turn-of-month: first/last 2 unique dates of each month vs rest
        dates = pd.Series(idx.normalize(), index=idx)
        naive = dates.dt.tz_localize(None) if dates.dt.tz is not None else dates
        ym = naive.dt.to_period("M")
        is_tom = pd.Series(False, index=idx)
        for _, grp in dates.groupby(ym):
            uniq = np.sort(grp.unique())
            edge = set(list(uniq[:2]) + list(uniq[-2:]))
            is_tom.loc[grp.index] = grp.isin(edge).values
        tom_ret = dow["ret"][is_tom.values]
        rest_ret = dow["ret"][~is_tom.values]
        tom = {
            "turn_of_month_mean_ret": _f(tom_ret.mean()),
            "rest_of_month_mean_ret": _f(rest_ret.mean()),
            "turn_of_month_mean_abs": _f(tom_ret.abs().mean()),
            "rest_of_month_mean_abs": _f(rest_ret.abs().mean()),
        }

        # rollover-window volatility (thin-liquidity hour)
        roll_mask = dow.index.hour == int(rollover_hour)
        rollover = {
            "rollover_hour": int(rollover_hour),
            "mean_abs_ret_in_window": _f(dow["abs"][roll_mask].mean()),
            "mean_abs_ret_overall": _f(dow["abs"].mean()),
        }

        out = {"day_of_week": dow_eff, "month_of_year": moy_eff,
               "turn_of_month": tom, "rollover_window": rollover}

        # optional: volatility around scheduled news timestamps
        if news_times is not None:
            out["news_window"] = self._news_window(ret, news_times)
        else:
            out["news_window"] = {"note": "pass news_times=[Timestamp,...] to measure"}

        # optional: holiday effect
        if holidays is not None:
            hol = pd.DatetimeIndex(holidays).normalize()
            on_hol = dates.isin(hol)
            out["holiday_effect"] = {
                "holiday_mean_abs_ret": _f(dow["abs"][on_hol.values].mean()),
                "normal_mean_abs_ret": _f(dow["abs"][~on_hol.values].mean()),
            }
        else:
            out["holiday_effect"] = {"note": "pass holidays=[date,...] to measure"}
        return out

    def _news_window(self, ret, news_times, window_bars=3):
        try:
            news = pd.DatetimeIndex(pd.to_datetime(news_times))
            in_win = pd.Series(False, index=ret.index)
            for t in news:
                lo = t - pd.Timedelta(minutes=1)
                # mark the nearest bar at/after the event and a few following
                pos = ret.index.searchsorted(t)
                for j in range(pos, min(pos + window_bars, len(ret))):
                    in_win.iloc[j] = True
            a = ret.abs()
            return {
                "n_events": int(len(news)),
                "mean_abs_ret_in_window": _f(a[in_win.values].mean()),
                "mean_abs_ret_baseline": _f(a[~in_win.values].mean()),
                "vol_multiple": _f(a[in_win.values].mean() / a[~in_win.values].mean())
                if a[~in_win.values].mean() else np.nan,
            }
        except Exception as e:                       # pragma: no cover
            return {"note": f"news window calc failed: {e}"}

    # ---- Group 6 -----------------------------------------------------
    def probability(self, horizon=None, n_sims=4000, mfe_horizon=None) -> dict:
        r = self._ret
        rn = self._ret_np
        sigma_bar = float(np.nanstd(rn, ddof=1))
        sigma_daily = sigma_bar * np.sqrt(self.bars_per_day)
        last = float(self._close.iloc[-1])
        if horizon is None:
            horizon = int(round(self.bars_per_day)) or 1   # ~one day ahead
        if mfe_horizon is None:
            mfe_horizon = horizon

        # conditional direction probabilities (sign persistence)
        sign = np.sign(rn)
        cond = {}
        if sign.size > 20:
            up_today = sign[:-1] > 0
            nxt_up = sign[1:] > 0
            cond = {
                "P(up)": _f((sign > 0).mean()),
                "P(up_next | up_today)": _f(nxt_up[up_today].mean()) if up_today.any() else np.nan,
                "P(up_next | down_today)": _f(nxt_up[~up_today].mean()) if (~up_today).any() else np.nan,
            }

        # Markov transition matrix over 3 return-quantile states (down/flat/up)
        markov = self._markov(rn)

        # expected-move bands
        bands = {
            "sigma_per_bar": _f(sigma_bar),
            "sigma_per_day": _f(sigma_daily),
            "last_close": _f(last),
            "1bar_1sigma_move": _f(last * sigma_bar),
            "daily_1sigma_band": [_f(last * (1 - sigma_daily)), _f(last * (1 + sigma_daily))],
            "daily_2sigma_band": [_f(last * (1 - 2 * sigma_daily)), _f(last * (1 + 2 * sigma_daily))],
        }

        # touch (first-passage) probabilities: analytic vs empirical
        touch = {"analytic_reflection": {f"{k}sigma": _touch_prob_analytic(k)
                                         for k in (1, 2, 3)}}
        touch["empirical"] = self._empirical_touch(rn, horizon)

        # MFE / MAE forward-excursion distributions over the horizon
        mfe = self._mfe_mae(mfe_horizon)

        # Monte-Carlo / stationary block bootstrap
        sim = self._bootstrap_summary(rn, horizon, n_sims, sigma_bar)

        out = {
            "horizon_bars": int(horizon),
            "conditional_direction": cond,
            "markov_transition": markov,
            "expected_move_bands": bands,
            "touch_probability": touch,
            "mfe_mae": mfe,
            "bootstrap": sim,
        }
        return out

    @staticmethod
    def _markov(rn, n_states=3):
        if rn.size < 50:
            return {"note": "insufficient data"}
        qs = np.quantile(rn, [1 / 3, 2 / 3])
        state = np.digitize(rn, qs)        # 0=down, 1=flat, 2=up
        labels = ["down", "flat", "up"][:n_states]
        M = np.zeros((n_states, n_states))
        for a, b in zip(state[:-1], state[1:]):
            M[a, b] += 1
        row = M.sum(axis=1, keepdims=True)
        with np.errstate(invalid="ignore", divide="ignore"):
            P = np.divide(M, row, out=np.zeros_like(M), where=row > 0)
        return {labels[i]: {labels[j]: _f(P[i, j]) for j in range(n_states)}
                for i in range(n_states)}

    def _empirical_touch(self, rn, horizon):
        if rn.size < horizon + 20:
            return {"note": "insufficient data"}
        sig_h = np.nanstd(rn, ddof=1) * np.sqrt(horizon)
        # rolling cumulative path over each window of length `horizon`
        cum = np.cumsum(rn)
        res = {}
        for k in (1, 2, 3):
            level = k * sig_h
            hits = 0
            count = 0
            # windowed running max abs deviation from window start
            for start in range(0, rn.size - horizon, max(1, horizon // 2)):
                seg = rn[start:start + horizon]
                path = np.cumsum(seg)
                count += 1
                if path.max() >= level or path.min() <= -level:
                    hits += 1
            res[f"{k}sigma"] = _f(hits / count) if count else np.nan
        return res

    def _mfe_mae(self, horizon):
        c = self._close.to_numpy()
        h = self._df["high"].to_numpy()
        l = self._df["low"].to_numpy()
        n = c.size
        if n < horizon + 20:
            return {"note": "insufficient data"}
        step = max(1, horizon // 2)
        mfe_long, mae_long = [], []
        for t in range(0, n - horizon, step):
            entry = c[t]
            fwd_hi = h[t + 1:t + 1 + horizon].max()
            fwd_lo = l[t + 1:t + 1 + horizon].min()
            mfe_long.append((fwd_hi - entry) / entry)   # best case for a long
            mae_long.append((fwd_lo - entry) / entry)   # worst case for a long
        mfe_long = np.array(mfe_long)
        mae_long = np.array(mae_long)
        return {
            "note": "per-bar forward excursion over horizon, as fraction of price (long perspective)",
            "mfe_median": _f(np.median(mfe_long)),
            "mfe_p90": _f(np.quantile(mfe_long, 0.90)),
            "mae_median": _f(np.median(mae_long)),
            "mae_p10": _f(np.quantile(mae_long, 0.10)),
        }

    def _bootstrap_summary(self, rn, horizon, n_sims, sigma_bar):
        paths = _stationary_bootstrap(rn, horizon, n_sims, mean_block=20)
        if paths is None:
            return {"note": "insufficient data"}
        cum = np.cumsum(paths, axis=1)
        terminal = cum[:, -1]
        run_max = np.maximum.accumulate(cum, axis=1)
        drawdown = (cum - run_max).min(axis=1)         # most negative dip per path
        sig_h = sigma_bar * np.sqrt(horizon)
        touch = {}
        for k in (1, 2):
            lvl = k * sig_h
            touched = (cum.max(axis=1) >= lvl) | (cum.min(axis=1) <= -lvl)
            touch[f"{k}sigma"] = _f(touched.mean())
        return {
            "method": "stationary block bootstrap (preserves clustering)",
            "n_sims": int(n_sims),
            "terminal_return_median": _f(np.median(terminal)),
            "terminal_return_p05": _f(np.quantile(terminal, 0.05)),
            "terminal_return_p95": _f(np.quantile(terminal, 0.95)),
            "P_terminal_up": _f((terminal > 0).mean()),
            "max_drawdown_median": _f(np.median(drawdown)),
            "max_drawdown_p05": _f(np.quantile(drawdown, 0.05)),
            "touch_prob_empirical_sim": touch,
        }

    # ---- Bonus: regimes ---------------------------------------------
    def regimes(self, n_states=2) -> dict:
        if not _HAS_SKLEARN:
            return {"note": "scikit-learn unavailable"}
        r = self._ret
        if r.size < 200:
            return {"note": "insufficient data for regime clustering"}
        # Cluster on a smoothed volatility feature (~1 day rolling) so regimes
        # reflect sustained vol level rather than single-bar noise. Without a
        # transition prior (a true HMM) per-bar clustering flip-flops; smoothing
        # the feature is the pragmatic fix.
        w = max(int(round(self.bars_per_day)), 10)
        roll_vol = r.rolling(w, min_periods=max(w // 3, 5)).std(ddof=1)
        roll_abs = r.abs().rolling(w, min_periods=max(w // 3, 5)).mean()
        feat = np.column_stack([roll_vol.to_numpy(), roll_abs.to_numpy()])
        m = np.isfinite(feat).all(axis=1)
        feat = feat[m]
        idx = r.index[m]
        mu = feat.mean(axis=0)
        sd = feat.std(axis=0) + 1e-12
        z = (feat - mu) / sd
        try:
            gm = GaussianMixture(n_components=n_states, covariance_type="full",
                                 random_state=0, n_init=3)
            raw_states = gm.fit_predict(z)
        except Exception as e:                       # pragma: no cover
            return {"note": f"regime fit failed: {e}"}
        # order states low->high volatility by mean |return| feature
        order = np.argsort([feat[raw_states == s, 0].mean() if (raw_states == s).any() else np.inf
                            for s in range(n_states)])
        remap = {old: new for new, old in enumerate(order)}
        states = np.array([remap[s] for s in raw_states])

        # transition matrix + average durations
        M = np.zeros((n_states, n_states))
        for a, b in zip(states[:-1], states[1:]):
            M[a, b] += 1
        rowsum = M.sum(axis=1, keepdims=True)
        with np.errstate(invalid="ignore", divide="ignore"):
            P = np.divide(M, rowsum, out=np.zeros_like(M), where=rowsum > 0)

        labels = (["low_vol", "high_vol"] if n_states == 2
                  else [f"regime_{i}" for i in range(n_states)])
        rvals = r.to_numpy()[m]
        per_state = {}
        for s in range(n_states):
            sel = states == s
            seg_ret = rvals[sel]
            per_state[labels[s]] = {
                "share_of_time": _f(sel.mean()),
                "ann_vol": _f(np.std(seg_ret, ddof=1) * np.sqrt(self.ppy)) if seg_ret.size > 1 else np.nan,
                "mean_ret": _f(np.mean(seg_ret)) if seg_ret.size else np.nan,
            }
        # switch points (change points) where the regime label changes
        switches = idx[1:][states[1:] != states[:-1]]
        out = {
            "method": "Gaussian-mixture volatility-regime clustering (HMM-style)"
                      if _HAS_SKLEARN else "n/a",
            "n_states": int(n_states),
            "current_regime": labels[int(states[-1])],
            "per_state": per_state,
            "transition_matrix": {labels[i]: {labels[j]: _f(P[i, j])
                                              for j in range(n_states)}
                                  for i in range(n_states)},
            "n_switch_points": int(len(switches)),
            "last_switch": str(switches[-1]) if len(switches) else None,
        }
        return out

    # ---- Aggregators -------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "meta": {"name": self.name, "n_bars": int(len(self._df)),
                     "bars_per_year": _f(self.ppy),
                     "start": str(self._df.index[0]) if self._has_dt else None,
                     "end": str(self._df.index[-1]) if self._has_dt else None},
            "distribution": self.distribution(),
            "desk": self.desk_distribution(),
            "volatility": self.volatility(),
            "mean_reversion": self.mean_reversion(),
            "sessions": self.sessions(),
            "calendar": self.calendar(),
            "probability": self.probability(),
            "regimes": self.regimes(),
        }

    def report(self) -> str:
        """Human-readable character report — the recommended entry point."""
        D = self.distribution()
        V = self.volatility()
        MR = self.mean_reversion()
        S = self.sessions()
        C = self.calendar()
        P = self.probability()
        R = self.regimes()

        def pct(x, d=1):
            return "n/a" if x is None or (isinstance(x, float) and np.isnan(x)) \
                else f"{x*100:.{d}f}%"

        def num(x, d=4):
            return "n/a" if x is None or (isinstance(x, float) and np.isnan(x)) \
                else f"{x:.{d}f}"

        L = []
        L.append("=" * 70)
        L.append(f"  MARKET CHARACTER REPORT — {self.name}")
        L.append(f"  bars: {len(self._df)}   bars/year: {self.ppy:,.0f}"
                 f"   ~bars/day: {self.bars_per_day:.1f}")
        if self._has_dt:
            L.append(f"  span: {self._df.index[0]}  ->  {self._df.index[-1]}")
        L.append("=" * 70)

        # 1. Distribution
        L.append("\n[1] RETURN DISTRIBUTION")
        if "note" in D:
            L.append("    " + D["note"])
        else:
            tail = ("fat-tailed" if D["excess_kurtosis"] > 1 else "near-normal tails")
            sk = ("negative (downside-heavy)" if D["skewness"] < -0.1
                  else "positive (upside-heavy)" if D["skewness"] > 0.1 else "~symmetric")
            L.append(f"    skew {num(D['skewness'],3)} ({sk}); "
                     f"excess kurtosis {num(D['excess_kurtosis'],2)} -> {tail}")
            L.append(f"    normality (Jarque-Bera): "
                     f"{'normal' if D['is_normal_5pct'] else 'NOT normal'} "
                     f"(p={num(D['jarque_bera_p'],4)}); Student-t dof {num(D['student_t_dof'],1)}")
            L.append(f"    per-bar return quantiles: 5%={pct(D['empirical_quantiles']['0.05'],2)}  "
                     f"95%={pct(D['empirical_quantiles']['0.95'],2)}")

        # 2. Volatility
        L.append("\n[2] VOLATILITY")
        ann = V["annualised"]
        L.append(f"    annualised (Yang-Zhang) {pct(ann['yang_zhang'])}  | "
                 f"close-to-close {pct(ann['close_to_close'])}  | "
                 f"Parkinson {pct(ann['parkinson'])}")
        L.append(f"    ATR(14): {num(V['atr_14'],5)}   vol-of-vol: {num(V['vol_of_vol'],5)}")
        cl = V["clustering_test"]
        L.append(f"    volatility clustering: "
                 f"{'PRESENT' if cl['clustering_present_5pct'] else 'not detected'} "
                 f"(Ljung-Box p={num(cl['ljung_box_sq_returns_p'],4)})")
        g = V["garch"]
        if g:
            L.append(f"    GARCH(1,1): alpha={num(g['alpha'],3)} beta={num(g['beta'],3)} "
                     f"persistence={num(g['persistence'],3)} "
                     f"{'(shocks decay slowly)' if g['persistence']>0.9 else ''}")
        gj = V["gjr_garch"]
        if gj:
            L.append(f"    GJR-GARCH leverage effect: "
                     f"{'YES (down moves raise vol more)' if gj.get('leverage_effect') else 'no'} "
                     f"(gamma={num(gj.get('gamma'),3)})")
        if V["volatility_cones"]:
            w = "20bar"
            if w in V["volatility_cones"]:
                cn = V["volatility_cones"][w]
                L.append(f"    current 20-bar vol sits at the "
                         f"{pct(cn['current_percentile'],0)} percentile of its history")

        # 3. Mean reversion vs trend
        L.append("\n[3] MEAN REVERSION vs TREND")
        L.append(f"    VERDICT: {MR['verdict'].upper()}")
        L.append(f"    Hurst(R/S) {num(MR['hurst_rs'],3)} (0.5=random)  | "
                 f"DFA {num(MR['dfa_exponent'],3)}")
        vr2 = MR["variance_ratio"]["q2"]
        L.append(f"    variance ratio q=2: {num(vr2['vr'],3)} "
                 f"(z={num(vr2['z'],2)}, p={num(vr2['p'],3)})")
        adf = MR["adf"]
        L.append(f"    ADF stat {num(adf['stat'],2)} (5% crit {adf['crit_5pct']}): "
                 f"{'stationary/mean-reverting' if adf['stationary_5pct'] else 'unit root / not stationary'}")
        L.append(f"    serial dependence in returns: "
                 f"{'yes' if MR['serial_dependence_5pct'] else 'no'} "
                 f"(Ljung-Box p={num(MR['ljung_box_returns_p'],4)})")
        if np.isfinite(MR["half_life_bars"]):
            L.append(f"    mean-reversion half-life: {num(MR['half_life_bars'],1)} bars")

        # 4. Sessions
        L.append("\n[4] SESSION / INTRADAY STRUCTURE")
        if "note" in S:
            L.append("    " + S["note"])
        else:
            L.append(f"    peak-volatility hour: {S['peak_vol_hour']}:00 {self.tz}   "
                     f"quietest hour: {S['trough_vol_hour']}:00")
            sr = S["session_avg_range"]
            parts = "  ".join(f"{k}={num(v,5)}" for k, v in sr.items())
            L.append(f"    avg range by session: {parts}")
            L.append(f"    London/NY overlap holds "
                     f"{pct(S['overlap_range_share_of_day'],0)} of the daily range")
            bo = S["asian_range_breakout"]
            if "p_break_either_side" in bo:
                L.append(f"    London breaks the Asian range "
                         f"{pct(bo['p_break_either_side'],0)} of days "
                         f"(up {pct(bo['p_break_up'],0)} / down {pct(bo['p_break_down'],0)})")
            g = S["gap_stats"]
            L.append(f"    gaps: mean |gap| {pct(g['mean_abs_gap'],3)}, "
                     f"95th pct {pct(g['p95_abs_gap'],3)}")

        # 5. Calendar
        L.append("\n[5] CALENDAR / SEASONALITY")
        if "note" in C:
            L.append("    " + C["note"])
        else:
            dow = C["day_of_week"]
            busiest = max(dow, key=lambda k: dow[k]["mean_abs_ret"]
                          if not np.isnan(dow[k]["mean_abs_ret"]) else -1)
            L.append(f"    most active weekday (by range): {busiest}")
            tom = C["turn_of_month"]
            L.append(f"    turn-of-month |move| {pct(tom['turn_of_month_mean_abs'],3)} "
                     f"vs rest {pct(tom['rest_of_month_mean_abs'],3)}")
            L.append("    (treat directional weekday/month effects with suspicion; "
                     "vol seasonality is the robust part)")

        # 6. Probability
        L.append("\n[6] PROBABILITY OF A MOVE")
        b = P["expected_move_bands"]
        L.append(f"    horizon: {P['horizon_bars']} bars (~1 day)")
        L.append(f"    daily 1-sigma band: [{num(b['daily_1sigma_band'][0],5)}, "
                 f"{num(b['daily_1sigma_band'][1],5)}]  (last close {num(b['last_close'],5)})")
        cd = P["conditional_direction"]
        if cd:
            L.append(f"    P(up next | up today) = {pct(cd.get('P(up_next | up_today)'),1)}  "
                     f"vs P(up next | down today) = {pct(cd.get('P(up_next | down_today)'),1)}  "
                     f"[near 50% = no directional edge]")
        ta = P["touch_probability"]["analytic_reflection"]
        te = P["touch_probability"]["empirical"]
        L.append(f"    P(touch +/-1 sigma): analytic {pct(ta['1sigma'],0)}  "
                 f"empirical {pct(te.get('1sigma'),0) if isinstance(te,dict) and '1sigma' in te else 'n/a'}")
        bs = P["bootstrap"]
        if "P_terminal_up" in bs:
            L.append(f"    bootstrap P(up over horizon) = {pct(bs['P_terminal_up'],1)}; "
                     f"median max-drawdown over horizon = {pct(bs['max_drawdown_median'],2)}")

        # Bonus: regimes
        L.append("\n[+] VOLATILITY REGIMES")
        if "note" in R:
            L.append("    " + R["note"])
        else:
            L.append(f"    current regime: {R['current_regime']}  "
                     f"({R['n_switch_points']} switches in sample)")
            for k, v in R["per_state"].items():
                L.append(f"      {k}: {pct(v['share_of_time'],0)} of time, "
                         f"ann vol {pct(v['ann_vol'])}")

        # Bottom-line synthesis
        L.append("\n" + "-" * 70)
        L.append("  BOTTOM LINE")
        verdict = MR["verdict"]
        clustering = V["clustering_test"]["clustering_present_5pct"]
        L.append(f"    - Character: {verdict}.")
        L.append(f"    - Volatility is {'clustered and forecastable' if clustering else 'weakly structured'}; "
                 f"size/timing of moves is far more predictable than direction.")
        if not S.get("note"):
            L.append(f"    - Trade the active window: peak vol around "
                     f"{S['peak_vol_hour']}:00 {self.tz}, overlap carries "
                     f"{pct(S['overlap_range_share_of_day'],0)} of daily range.")
        L.append("    - Reminder: validate any edge out-of-sample; most single-sample "
                 "conditional/calendar edges do not survive.")
        L.append("-" * 70)
        return "\n".join(L)


# ======================================================================
# Convenience wrappers (match a (df) -> metrics convention)
# ======================================================================

def analyze(df: pd.DataFrame, **kwargs) -> MarketStats:
    """Return a configured MarketStats object: analyze(df).report() / .to_dict()."""
    return MarketStats(df, **kwargs)


def character_report(df: pd.DataFrame, **kwargs) -> str:
    """One-liner: return the text character report for an OHLC frame."""
    return MarketStats(df, **kwargs).report()


def market_metrics(df: pd.DataFrame, **kwargs) -> dict:
    """One-liner: return the full nested metrics dict for an OHLC frame."""
    return MarketStats(df, **kwargs).to_dict()


# ======================================================================
# Demo on synthetic data
# ======================================================================

if __name__ == "__main__":
    # Build ~120 trading days of hourly FX-like bars with: volatility clustering,
    # a London/NY intraday vol bump, fat tails, and mild mean reversion — so the
    # report has something real to find.
    rng = np.random.default_rng(7)
    n_days = 180
    hours = pd.date_range("2024-01-01", periods=n_days * 24, freq="h", tz="UTC")
    hours = hours[hours.dayofweek < 5]      # FX doesn't trade weekends
    n = len(hours)

    # clustered return engine (GARCH recursion). Normal innovations + GARCH give
    # realistic, moderately fat tails without absurd kurtosis.
    z = rng.standard_normal(n)
    var = np.empty(n)
    ret = np.empty(n)
    var[0] = 1.0
    omega, alpha, beta = 0.02, 0.08, 0.90
    for t in range(n):
        if t > 0:
            var[t] = omega + alpha * ret[t - 1] ** 2 + beta * var[t - 1]
        ret[t] = np.sqrt(var[t]) * z[t]

    # scale to FX-hourly size, add an intraday vol bump (London/NY), mild reversion
    hour_of_day = hours.hour.to_numpy()
    bump = np.where((hour_of_day >= 7) & (hour_of_day < 21), 1.4, 0.6)
    ret = ret / np.std(ret) * 6e-4 * bump
    for t in range(1, n):
        ret[t] -= 0.05 * ret[t - 1]

    close = 1.10 * np.exp(np.cumsum(ret))
    open_ = np.concatenate([[close[0]], close[:-1]])
    wick = np.abs(rng.normal(0, 1, n)) * 6e-4 * bump
    high = np.maximum(open_, close) + wick
    low = np.minimum(open_, close) - wick
    volume = (1000 * bump * (1 + np.abs(z))).round()

    df = pd.DataFrame({"open": open_, "high": high, "low": low,
                       "close": close, "volume": volume}, index=hours)

    print(character_report(df, name="SYNTH/USD H1"))

    # show that the structured dict is available too
    import json
    metrics = market_metrics(df, name="SYNTH/USD H1")
    print("\n--- sample of structured output (volatility.garch) ---")
    print(json.dumps(metrics["volatility"]["garch"], indent=2))