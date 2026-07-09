"""
desk_card.py
============
Turn the `distribution` and `volatility` blocks produced by
`market_stats.MarketStats(...).to_dict()` into the kind of "desk card" a
trading / risk desk would read off them: directional bias, position size,
VaR / expected-shortfall, a leverage cap, an option-hedge estimate, the
overnight-gap split, the current-vs-historical vol regime, a GARCH
mean-reversion glide path, and ATR-based unit sizing.

Pure standard library (only `math`). Drop it next to market_stats.py.

    from market_stats import MarketStats
    from desk_card import desk_card

    rep = MarketStats(df, name="US500 D1").to_dict()
    desk_card(rep, equity=1_000_000, vol_target=0.10, point_value=1.0)

Every function also *returns* a dict of the raw computed numbers (under the
same keys shown on the card) so you can use them programmatically; the
formatted card is under the "text" key.

NOTE: illustrative desk mechanics, not financial advice. Validate on your
own data, and set point_value / contract specifics for your instrument.
"""

from __future__ import annotations
import math

# ----------------------------------------------------------------------
# small helpers (no numpy/scipy needed)
# ----------------------------------------------------------------------

_SQRT2 = math.sqrt(2.0)


def _ncdf(x: float) -> float:
    """Standard normal CDF."""
    return 0.5 * (1.0 + math.erf(x / _SQRT2))


def _z(p: float) -> float:
    """Inverse normal CDF (Acklam approximation) for VaR z-scores."""
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00]
    plow, phigh = 0.02425, 1 - 0.02425
    if p < plow:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
               ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    if p > phigh:
        q = math.sqrt(-2 * math.log(1 - p))
        return -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
                ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    q = p - 0.5
    r = q * q
    return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q / \
           (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)


def _bs_put_pct(vol: float, t_years: float, moneyness: float) -> float:
    """Black-Scholes put value as a fraction of spot (r=0, S=1, K=moneyness)."""
    if vol <= 0 or t_years <= 0:
        return max(0.0, moneyness - 1.0)
    srt = vol * math.sqrt(t_years)
    d1 = (-math.log(moneyness) + 0.5 * srt * srt) / srt
    d2 = d1 - srt
    return moneyness * _ncdf(-d2) - _ncdf(-d1)


def _money(x) -> str:
    return f"${x:,.0f}" if x is not None else "n/a"


def _pct(x, dp=2) -> str:
    return f"{x*100:.{dp}f}%" if x is not None else "n/a"


def _bar(width=64, ch="-") -> str:
    return ch * width


# ----------------------------------------------------------------------
# distribution card
# ----------------------------------------------------------------------

def distribution_card(dist: dict, *, equity=1_000_000.0, vol_target=0.10,
                      bars_per_year=252.0, hedge_tenor_months=1.0,
                      name="instrument") -> dict:
    """Desk card from a `to_dict()['distribution']` block."""
    n    = dist.get("n_returns")
    mu   = dist.get("mean")
    sd   = dist.get("std")
    skew = dist.get("skewness")
    hill = dist.get("hill_tail_index")
    dof  = dist.get("student_t_dof")
    q    = dist.get("empirical_quantiles", {}) or {}

    def qv(k):  # quantiles use string keys like "0.01"
        return q.get(k, q.get(str(k)))

    q01, q05, q50, q95, q99 = (qv("0.01"), qv("0.05"), qv("0.5"),
                               qv("0.95"), qv("0.99"))

    ann_vol   = sd * math.sqrt(bars_per_year)
    ann_drift = mu * bars_per_year
    sharpe_b  = mu / sd if sd else 0.0
    t_mean    = sharpe_b * math.sqrt(n) if n else 0.0
    ann_sharpe = ann_drift / ann_vol if ann_vol else 0.0

    # directional bias verdict
    if abs(t_mean) < 1:
        bias = "no directional edge (drift indistinguishable from noise)"
    elif abs(t_mean) < 2:
        bias = "weak drift (tilt at most; discount heavily out-of-sample)"
    else:
        d = "long" if mu > 0 else "short/avoid"
        bias = f"real drift -> {d} bias (discount in-sample t out-of-sample)"

    # sizing
    weight   = vol_target / ann_vol if ann_vol else 0.0
    notional = weight * equity
    daily_sd = notional * sd

    # VaR / ES on that position
    var95 = notional * abs(q05) if q05 is not None else None
    var99 = notional * abs(q01) if q01 is not None else None
    var99_g = notional * abs(_z(0.01)) * sd
    gauss_gap = (var99 / var99_g - 1) if (var99 and var99_g) else None
    es_mult = hill / (hill - 1) if (hill and hill > 1) else None
    es99 = var99 * es_mult if (var99 and es_mult) else None

    # leverage: full/quarter Kelly vs a tail-index cap, take the min
    kelly = mu / (sd * sd) if sd else 0.0
    quarter_k = kelly / 4
    if hill is None:
        alpha_cap = 1.0
    elif hill > 4:
        alpha_cap = 2.0
    elif hill > 3:
        alpha_cap = 1.0
    elif hill > 2:
        alpha_cap = 0.5
    else:
        alpha_cap = 0.25
    lev_cap = min(quarter_k, alpha_cap) if quarter_k > 0 else alpha_cap
    loss_at_kelly = kelly * q01 if q01 is not None else None

    # option hedge (put) as % of notional; skew fattens OTM-put IV
    T = hedge_tenor_months / 12.0
    skew_prem = max(0.0, -(skew or 0.0))
    iv_atm = ann_vol
    iv_5   = ann_vol + skew_prem * 0.06
    iv_10  = ann_vol + skew_prem * 0.125
    put_atm = _bs_put_pct(iv_atm, T, 1.00)
    put_5   = _bs_put_pct(iv_5,   T, 0.95)
    put_10  = _bs_put_pct(iv_10,  T, 0.90)

    out = dict(
        name=name, equity=equity, vol_target=vol_target, bars_per_year=bars_per_year,
        ann_vol=ann_vol, ann_drift=ann_drift, ann_sharpe=ann_sharpe,
        t_mean=t_mean, bias=bias, weight=weight, notional=notional,
        daily_pl_sd=daily_sd, var95=var95, var99=var99, var99_gauss=var99_g,
        gauss_understate=gauss_gap, es99=es99, es_mult=es_mult,
        kelly=kelly, quarter_kelly=quarter_k, alpha_cap=alpha_cap, lev_cap=lev_cap,
        loss_at_full_kelly=loss_at_kelly, hill=hill, student_t_dof=dof, skew=skew,
        put_atm_pct=put_atm, put_5_pct=put_5, put_10_pct=put_10,
        hedge_tenor_months=hedge_tenor_months,
    )
    out["text"] = _render_distribution(out)
    return out


def _render_distribution(o: dict) -> str:
    L = []
    L.append(_bar())
    L.append(f" DISTRIBUTION CARD  |  {o['name']}")
    L.append(f" book {_money(o['equity'])}   vol target {_pct(o['vol_target'],0)}"
             f"   {o['bars_per_year']:.0f} bars/yr")
    L.append(_bar())
    L.append(f" character   ann vol {_pct(o['ann_vol'])}   ann drift {_pct(o['ann_drift'])}"
             f"   ann Sharpe {o['ann_sharpe']:.2f}")
    L.append(f" drift test  t(mean) = {o['t_mean']:.2f}")
    L.append(f" bias        {o['bias']}")
    L.append(f" tails       hill a={o['hill']:.2f}  student-t dof={o['student_t_dof']:.2f}"
             f"  skew={o['skew']:+.2f}")
    L.append(_bar())
    L.append(f" SIZE        weight {o['weight']:.3f}  ->  notional {_money(o['notional'])}")
    L.append(f"             daily P&L sd {_money(o['daily_pl_sd'])}")
    L.append(f" RISK        95% VaR {_money(o['var95'])}   99% VaR {_money(o['var99'])}")
    if o['gauss_understate'] is not None:
        g = o['gauss_understate']
        _gtail = (f"  -> gaussian understates by {_pct(g,0)}" if g >= 0
                  else f"  -> gaussian overstates 99% by {_pct(abs(g),0)} (tail risk sits further out)")
    else:
        _gtail = ""
    L.append(f"             99% VaR (gaussian) {_money(o['var99_gauss'])}{_gtail}")
    if o['es99'] is not None:
        L.append(f"             99% ExpShortfall {_money(o['es99'])}"
                 f"   (a/(a-1) = {o['es_mult']:.2f}x VaR)")
    L.append(_bar())
    L.append(f" LEVERAGE    full-Kelly {o['kelly']:.2f}x   quarter-Kelly {o['quarter_kelly']:.2f}x")
    L.append(f"             tail cap {o['alpha_cap']:.2f}x   ->  suggested max {o['lev_cap']:.2f}x")
    if o['loss_at_full_kelly'] is not None:
        L.append(f"             (a 1%-day at full Kelly = {_pct(o['loss_at_full_kelly'],1)} of equity)")
    L.append(_bar())
    m = o['hedge_tenor_months']
    L.append(f" HEDGE       {m:.0f}M put, % of notional:")
    L.append(f"             ATM {_pct(o['put_atm_pct'])}   5% OTM {_pct(o['put_5_pct'])}"
             f"   10% OTM {_pct(o['put_10_pct'])}   (skew-adjusted)")
    L.append(_bar())
    return "\n".join(L)


# ----------------------------------------------------------------------
# volatility card
# ----------------------------------------------------------------------

def volatility_card(vol: dict, *, equity=1_000_000.0, vol_target=0.10,
                    size_window="20bar", point_value=1.0, trade_risk=None,
                    glide_horizons=(1, 5, 20, 60), name="instrument") -> dict:
    """Desk card from a `to_dict()['volatility']` block."""
    ann = vol.get("annualised", {}) or {}
    bpy = vol.get("bars_per_year_used", 252.0)
    if trade_risk is None:
        trade_risk = 0.01 * equity

    ctc = ann.get("close_to_close")
    yz  = ann.get("yang_zhang")
    park = ann.get("parkinson")
    gk  = ann.get("garman_klass")
    rs  = ann.get("rogers_satchell")
    best = yz or ctc  # best all-in estimate

    # overnight-gap decomposition (uses a range estimator as intraday proxy)
    intraday = min([v for v in (gk, park, rs) if v is not None], default=None)
    onight_vol = onight_share = None
    if ctc and intraday and ctc > intraday:
        onight_var = ctc**2 - intraday**2
        onight_vol = math.sqrt(onight_var)
        onight_share = onight_var / ctc**2

    # baseline size off the long-run estimate
    base_w = vol_target / best if best else None
    base_notional = base_w * equity if base_w else None

    # cones -> current regime & today's size
    cones = vol.get("volatility_cones", {}) or {}
    cone_rows = []
    for k, c in cones.items():
        cur, pc = c.get("current"), c.get("current_percentile")
        cone_rows.append((k, cur, c.get("median"), c.get("p10"), c.get("p90"), pc))
    sc = cones.get(size_window) or (next(iter(cones.values())) if cones else None)
    cur_vol = sc.get("current") if sc else None
    cur_pct = sc.get("current_percentile") if sc else None
    if cur_pct is None:
        regime = "unknown"
    elif cur_pct < 0.25:
        regime = "calm  (size up within limits; vol cheap to buy)"
    elif cur_pct <= 0.75:
        regime = "normal  (baseline size)"
    elif cur_pct <= 0.90:
        regime = "elevated  (trim size)"
    else:
        regime = "STORM  (cut size hard; expect persistence)"
    today_w = vol_target / cur_vol if cur_vol else None
    today_notional = today_w * equity if today_w else None

    # GARCH mean-reversion glide
    garch = vol.get("garch") or {}
    pers = garch.get("persistence")
    unc_bar = garch.get("uncond_sigma_pct_per_bar")
    unc_ann = (unc_bar / 100.0) * math.sqrt(bpy) if unc_bar else None
    half_life = math.log(0.5) / math.log(pers) if (pers and 0 < pers < 1) else None
    glide = []
    if pers and cur_vol and unc_ann:
        cur_bar_var = (cur_vol / math.sqrt(bpy))**2
        unc_bar_var = (unc_ann / math.sqrt(bpy))**2
        for h in glide_horizons:
            v = unc_bar_var + (pers**h) * (cur_bar_var - unc_bar_var)
            ann_h = math.sqrt(max(v, 0.0)) * math.sqrt(bpy)
            w_h = vol_target / ann_h if ann_h else None
            glide.append((h, ann_h, w_h * equity if w_h else None))

    # asymmetry / clustering / vov
    gjr = vol.get("gjr_garch") or {}
    gamma = gjr.get("gamma")
    lever = gjr.get("leverage_effect")
    clus = vol.get("clustering_test", {}) or {}
    clustering = clus.get("clustering_present_5pct")
    vov = vol.get("vol_of_vol")

    # ATR unit sizing
    atr = vol.get("atr_14")
    atr_rows = []
    if atr:
        for k in (1.5, 2.0, 3.0):
            stop = k * atr
            units = trade_risk / (stop * point_value)
            atr_rows.append((k, stop, units))

    out = dict(
        name=name, equity=equity, vol_target=vol_target, bars_per_year=bpy,
        est_ctc=ctc, est_yz=yz, est_park=park, est_gk=gk, est_rs=rs, best=best,
        onight_vol=onight_vol, onight_share=onight_share,
        base_weight=base_w, base_notional=base_notional,
        size_window=size_window, cur_vol=cur_vol, cur_pct=cur_pct, regime=regime,
        today_weight=today_w, today_notional=today_notional, cone_rows=cone_rows,
        persistence=pers, half_life=half_life, uncond_ann=unc_ann, glide=glide,
        gjr_gamma=gamma, leverage_effect=lever, clustering=clustering, vol_of_vol=vov,
        atr=atr, trade_risk=trade_risk, point_value=point_value, atr_rows=atr_rows,
    )
    out["text"] = _render_volatility(out)
    return out


def _render_volatility(o: dict) -> str:
    L = []
    L.append(_bar())
    L.append(f" VOLATILITY CARD  |  {o['name']}")
    L.append(f" book {_money(o['equity'])}   vol target {_pct(o['vol_target'],0)}"
             f"   {o['bars_per_year']:.0f} bars/yr")
    L.append(_bar())
    L.append(f" ESTIMATES   best all-in {_pct(o['best'])}"
             f"   (CtC {_pct(o['est_ctc'])}  YZ {_pct(o['est_yz'])})")
    L.append(f"             intraday-only  Park {_pct(o['est_park'])}"
             f"  GK {_pct(o['est_gk'])}  RS {_pct(o['est_rs'])}")
    if o['onight_vol'] is not None:
        L.append(f" OVERNIGHT   gap vol ~{_pct(o['onight_vol'])}"
                 f"  =  {_pct(o['onight_share'],0)} of variance"
                 f"  -> trim overnight / stops won't span the close")
    L.append(_bar())
    if o['cone_rows']:
        L.append(" CONES       window  current   median    [p10..p90]   pctile")
        for k, cur, med, p10, p90, pc in o['cone_rows']:
            L.append(f"             {k:>6}  {_pct(cur,1):>7}  {_pct(med,1):>7}"
                     f"   [{_pct(p10,1)}..{_pct(p90,1)}]  {_pct(pc,0):>5}")
    L.append(f" REGIME      {o['regime']}  (from {o['size_window']}, "
             f"current {_pct(o['cur_vol'],1)})")
    L.append(_bar())
    L.append(f" SIZE now    weight {o['today_weight']:.3f}  ->  {_money(o['today_notional'])}"
             if o['today_weight'] else " SIZE now    n/a")
    L.append(f" SIZE base   weight {o['base_weight']:.3f}  ->  {_money(o['base_notional'])}"
             f"   (at long-run vol)" if o['base_weight'] else " SIZE base   n/a")
    L.append(_bar())
    if o['persistence']:
        L.append(f" GARCH       persistence {o['persistence']:.4f}"
                 f"   shock half-life {o['half_life']:.0f} bars"
                 f"   uncond {_pct(o['uncond_ann'])}")
    if o['glide']:
        L.append("  glide path (size back up as vol reverts):")
        for h, ann_h, notl in o['glide']:
            L.append(f"             +{h:>2}d  {_pct(ann_h,1):>6} ann  ->  {_money(notl)}")
    L.append(_bar())
    if o['leverage_effect'] is not None:
        note = ("down-days spike vol -> cut size after selloffs, buy put skew"
                if o['leverage_effect'] else
                "no reliable down-day vol asymmetry -> treat shocks symmetrically")
        L.append(f" ASYMMETRY   GJR gamma {o['gjr_gamma']:+.4f}  ({note})")
    if o['clustering'] is not None:
        L.append(f" CLUSTERING  {'present -> dynamic vol-targeting adds value' if o['clustering'] else 'absent -> a constant long-run vol is fine'}")
    if o['vol_of_vol'] is not None:
        L.append(f" VOL-OF-VOL  {o['vol_of_vol']:.4f}  (higher -> resize more often, more option convexity risk)")
    L.append(_bar())
    if o['atr_rows']:
        L.append(f" ATR SIZING  atr14 {o['atr']:.1f} pts   risk {_money(o['trade_risk'])}"
                 f"/trade   pt value {_money(o['point_value'])}")
        for k, stop, units in o['atr_rows']:
            L.append(f"             {k:>3}x ATR = {stop:7.1f} pts  ->  {units:6.1f} units")
        L.append("             (ATR is intraday range; won't protect the overnight gap)")
        L.append(_bar())
    return "\n".join(L)


# ----------------------------------------------------------------------
# combined entry point
# ----------------------------------------------------------------------

def desk_card(report: dict, *, equity=1_000_000.0, vol_target=0.10,
              point_value=1.0, trade_risk=None, size_window="20bar",
              hedge_tenor_months=1.0, print_out=True) -> dict:
    """
    Accepts a full MarketStats.to_dict() (or any dict containing
    'distribution' and/or 'volatility') and builds both cards.
    bars/year is pulled from meta/volatility when available.
    """
    meta = report.get("meta", {}) or {}
    name = meta.get("name", "instrument")
    vol_block = report.get("volatility")
    dist_block = report.get("distribution")
    bpy = (meta.get("bars_per_year")
           or (vol_block or {}).get("bars_per_year_used")
           or 252.0)

    result = {}
    if dist_block:
        result["distribution"] = distribution_card(
            dist_block, equity=equity, vol_target=vol_target,
            bars_per_year=bpy, hedge_tenor_months=hedge_tenor_months, name=name)
    if vol_block:
        result["volatility"] = volatility_card(
            vol_block, equity=equity, vol_target=vol_target,
            size_window=size_window, point_value=point_value,
            trade_risk=trade_risk, name=name)

    if print_out:
        if "distribution" in result:
            print(result["distribution"]["text"])
        if "volatility" in result:
            print(result["volatility"]["text"])
    return result


# ----------------------------------------------------------------------
# demo with the two blocks from our discussion
# ----------------------------------------------------------------------

if __name__ == "__main__":
    dist = {'n_returns': 6481, 'mean': 0.00041318557624228625,
            'std': 0.011261606555328292, 'skewness': -0.48369990350469355,
            'excess_kurtosis': 6.790984741342109, 'hill_tail_index': 3.2118756770097434,
            'student_t_dof': 3.567827879795554,
            'empirical_quantiles': {'0.01': -0.03168622975944998,
             '0.05': -0.017843559227287458, '0.25': -0.0048554767151210805,
             '0.5': 0.0004920349595730881, '0.75': 0.006352787968514301,
             '0.95': 0.017229703502251552, '0.99': 0.02836015654528773}}

    volb = {'annualised': {'close_to_close': 0.17838404593464302,
             'parkinson': 0.12969393492500947, 'garman_klass': 0.12191508023247288,
             'rogers_satchell': 0.1246685982498311, 'yang_zhang': 0.1637102938339562},
            'atr_14': 88.7791324335978, 'vol_of_vol': 0.004521697692417467,
            'volatility_cones': {
              '10bar': {'current': 0.2532183096842404, 'median': 0.14222463155528006,
                        'p10': 0.08750579469398047, 'p90': 0.2533296498270256,
                        'current_percentile': 0.8994128553770087},
              '20bar': {'current': 0.2982816603234596, 'median': 0.14644169578834104,
                        'p10': 0.09906996705324464, 'p90': 0.24492351901677298,
                        'current_percentile': 0.9418136799752399},
              '60bar': {'current': 0.2338717511986585, 'median': 0.15161167763502492,
                        'p10': 0.10793199709199035, 'p90': 0.2480463978638663,
                        'current_percentile': 0.8777639364683899},
              '120bar': {'current': 0.3444906111363122, 'median': 0.1547189128219659,
                         'p10': 0.11170683111045904, 'p90': 0.24466594549446616,
                         'current_percentile': 0.9819239232945615}},
            'clustering_test': {'clustering_present_5pct': True},
            'garch': {'alpha': 0.05621291384006461, 'beta': 0.9269545713904003,
                      'persistence': 0.9831674852304649,
                      'uncond_sigma_pct_per_bar': 1.1085873324780853},
            'gjr_garch': {'gamma': -0.03079979147944595, 'leverage_effect': False},
            'bars_per_year_used': 250.90615727002967}

    report = {"meta": {"name": "US500 D1 (demo)", "bars_per_year": 250.90615727002967},
              "distribution": dist, "volatility": volb}
    desk_card(report, equity=1_000_000, vol_target=0.10, point_value=1.0)