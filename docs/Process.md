# Statistical & Probabilistic Toolkit for FX / CFD Price Behaviour

A working reference for characterising how price moves, how each session behaves, and how to attach real probabilities to a move. Written for someone building a Python backtesting framework — every item names what it measures, what it actually tells you, and how to compute it.

---

## The one idea to anchor everything

In liquid FX, **direction is close to unpredictable at almost every horizon.** Most "edges" you can find on *next-bar direction* sit within a percent or two of 50/50 and decay once you account for spread and slippage. Finding that out empirically is itself a useful result — it stops you chasing ghosts.

What **is** strongly structured and forecastable:

- **Volatility** — clusters, mean-reverts, and has a repeatable daily/session shape. The single most predictable quantity in markets.
- **Range / activity** — how far price travels and *when*, tied tightly to session and calendar.
- **Conditional behaviour around levels and events** — news, session opens, prior-range breaks.

So the highest-value metrics are about *when* and *how much* price moves, not *which way*. Build your probabilities on volatility, range and timing and you stand on firm ground; build them on "this candle predicts up 60% of the time" and you are mostly fitting noise.

**Robustness tags used below:**
`[Robust]` persistent across pairs and decades · `[Regime]` real but depends on the regime · `[Fragile]` weak, decays, or overfits easily — verify hard before trusting.

---

## Group 1 — Characterising the return distribution (the foundation)

**1. Log returns** `[Robust]` — Use `ln(P_t / P_{t-1})`, not percentage change. They're additive across time and roughly symmetric, which every test below assumes. *Compute:* `np.log(close).diff()`.

**2. Skewness** `[Robust]` — Asymmetry of the return distribution. Equity indices are negatively skewed (crashes are sharper than rallies); FX skew is milder and pair-dependent (carry pairs like AUD/JPY can skew negative from sudden unwinds). Tells you whether your tail risk sits on the long or short side. *Compute:* `scipy.stats.skew`.

**3. Excess kurtosis** `[Robust]` — Fatness of the tails. FX returns are heavily leptokurtic (excess > 0, often 5–20+ on intraday data). This is *the* reason normal-distribution risk models understate blow-ups. *Compute:* `scipy.stats.kurtosis(fisher=True)`.

**4. Jarque–Bera test** `[Robust]` — Formal test of whether returns are normal (combines skew + kurtosis). It will almost always reject normality for FX — confirming you must model fat tails explicitly. *Compute:* `scipy.stats.jarque_bera`.

**5. QQ-plot vs Normal and Student-t** `[Robust]` — Visual diagnostic: plot empirical quantiles against theoretical ones. Points curving away at the ends = fat tails. Compare against a fitted t to see how many degrees of freedom you need. *Compute:* `scipy.stats.probplot`.

**6. Hill tail index** `[Regime]` — Estimates how heavy the extreme tail is (the power-law exponent). Lower index = fatter tail = more frequent extreme moves than a normal allows. Useful for sizing worst-case risk. *Compute:* custom (sort the largest order statistics, fit the slope).

**7. Student-t / generalized-hyperbolic fit** `[Robust]` — Fit a fat-tailed distribution to returns instead of a normal. The fitted degrees-of-freedom parameter quantifies tail heaviness; feeds directly into VaR and Monte Carlo. *Compute:* `scipy.stats.t.fit`.

**8. Empirical CDF / quantiles** `[Robust]` — Skip parametric assumptions entirely: read probabilities straight off the historical sample (e.g. "the 5th percentile daily move is −0.9%"). Honest and robust when you have enough data. *Compute:* `np.quantile`, `np.percentile`.

---

## Group 2 — Volatility (the most predictable thing in markets)

**9. Close-to-close historical volatility** `[Robust]` — Annualised standard deviation of returns (`std × √252` for daily). The baseline vol number everything else is compared to. *Compute:* `returns.std() * np.sqrt(252)`.

**10. Realized volatility** `[Robust]` — Sum of squared intraday returns over a window (e.g. 5-min bars → daily RV). Far more accurate than close-to-close because it uses the whole path. The modern standard. *Compute:* `np.sqrt((intraday_logret**2).resample('1D').sum())`.

**11. Parkinson estimator** `[Robust]` — Uses the high–low range. ~5× more efficient than close-to-close, but assumes no drift and no gaps (underestimates when jumps happen). *Compute:* custom, `(1/(4 ln2)) · ln(H/L)²`.

**12. Garman–Klass estimator** `[Robust]` — Uses full OHLC. More efficient than Parkinson; still assumes no overnight gap. Good for liquid intraday FX. *Compute:* custom OHLC formula.

**13. Rogers–Satchell estimator** `[Robust]` — OHLC estimator that **handles drift** (price trending within the bar). Better than Garman–Klass on trending instruments. *Compute:* custom.

**14. Yang–Zhang estimator** `[Robust]` — The best general-purpose OHLC vol estimator: handles **both** overnight gaps **and** drift, and is the most statistically efficient. Default choice if you have clean OHLC. *Compute:* custom (combines overnight, open-close, and Rogers–Satchell terms).

**15. ATR (Average True Range)** `[Robust]` — Smoothed true range including gaps. Not annualised vol, but the practical workhorse for stop placement and position sizing — you already use it. *Compute:* rolling mean of `max(H−L, |H−prevC|, |L−prevC|)`.

**16. GARCH(1,1)** `[Robust]` — Models and **forecasts** volatility by exploiting clustering (big moves follow big moves). The `α + β` sum measures persistence; near 1.0 means shocks decay slowly. The single most useful vol model. *Compute:* `arch.arch_model(...).fit()`.

**17. EGARCH / GJR-GARCH** `[Regime]` — GARCH variants that capture the **leverage effect**: negative returns raise future vol more than positive ones. Strong in indices, present-but-weaker in FX (varies by pair). *Compute:* `arch_model(..., vol='EGARCH')` or `p,o,q` for GJR.

**18. Volatility cones** `[Robust]` — Plot realized vol across multiple horizons (10d, 20d, 60d…) with historical percentile bands. Shows instantly whether current vol is high or low *for that horizon*. Great for regime context. *Compute:* rolling vol at several windows, then quantiles.

**19. Volatility-of-volatility** `[Regime]` — Variability of the vol series itself. Rising vol-of-vol flags an unstable regime where vol forecasts are less reliable. *Compute:* std of a rolling-vol series.

**20. ARCH-LM / Ljung–Box on squared returns** `[Robust]` — Statistical test for volatility clustering. If squared returns are autocorrelated (they almost always are), GARCH-type models are justified. *Compute:* `statsmodels het_arch` or `acorr_ljungbox` on `returns**2`.

---

## Group 3 — Memory: mean reversion vs trending

**21. Autocorrelation function (ACF) of returns** `[Robust]` — Correlation of returns with their own lags. In liquid FX this is near zero at most lags (efficient market) but can be slightly negative at very short intraday lags (microstructure mean reversion). *Compute:* `statsmodels.tsa.stattools.acf`.

**22. Ljung–Box test (on returns)** `[Robust]` — Joint test of whether *any* of the first k autocorrelations differ from zero. A clean check for exploitable serial dependence in direction. *Compute:* `acorr_ljungbox`.

**23. Variance Ratio test (Lo–MacKinlay)** `[Robust]` — Tests the random-walk hypothesis. `VR(q) > 1` → trending (momentum); `VR(q) < 1` → mean-reverting; `≈ 1` → random walk. One of the cleanest mean-reversion-vs-momentum diagnostics. *Compute:* custom (well-documented formula) or specialised libs.

**24. Hurst exponent** `[Regime]` — Single number for long-run behaviour: `H < 0.5` anti-persistent (mean-reverting), `H = 0.5` random walk, `H > 0.5` persistent (trending). Run it *per pair, per timeframe* — results shift with horizon. *Compute:* `hurst` package or rescaled-range / DFA custom code.

**25. Augmented Dickey–Fuller (ADF) test** `[Robust]` — Tests for a unit root. Rejecting the null implies the series is **stationary / mean-reverting** — central for spread and pairs trading. *Compute:* `statsmodels.tsa.stattools.adfuller`.

**26. Ornstein–Uhlenbeck fit** `[Regime]` — Fit a continuous mean-reverting process to a (stationary) series to estimate the **speed of reversion** θ and long-run mean. Turns "it reverts" into a usable number. *Compute:* OLS regression of `ΔP` on `P` (lagged).

**27. Half-life of mean reversion** `[Regime]` — `ln(2) / θ` from the OU fit: how long, on average, until half the deviation is corrected. Directly sets the holding period for a reversion trade. *Compute:* derived from item 26.

**28. Detrended Fluctuation Analysis (DFA)** `[Regime]` — Robust estimate of long-memory / self-similarity that tolerates non-stationarity better than raw Hurst. Cross-check with item 24. *Compute:* custom or `nolds` / `fathon`.

---

## Group 4 — Session & intraday structure (Tokyo / London / New York)

> Session clock times below are **approximate GMT/UTC** and shift with daylight saving — always recompute from your own timestamps in your own timezone. The *patterns*, not the exact minutes, are what's robust.

**29. Intraday volatility profile (vol by hour)** `[Robust]` — Average absolute return or realized vol bucketed by hour of day. FX shows a repeatable shape: quiet Asia → sharp spike at the London open → a second spike at the NY open → peak in the London–NY overlap → fade into late NY. The most reliable intraday structure that exists. *Compute:* `df.groupby(df.index.hour)['abs_ret'].mean()`.

**30. Session Average Daily Range (ADR per session)** `[Robust]` — Mean high–low range computed separately for the Asian, London and NY windows. Typically Asia < NY < London. Sets realistic profit-target and stop expectations per session. *Compute:* group by session label, then `(H−L).mean()`.

**31. Overlap volatility concentration** `[Robust]` — Fraction of the day's total movement occurring in the **London–NY overlap (~13:00–17:00 GMT)**. This window carries the most liquidity and the largest moves; a disproportionate share of daily range forms here. *Compute:* overlap range ÷ full-day range.

**32. Asian-range → London-breakout probability** `[Regime]` — The Asian session range is usually narrow; estimate `P(London breaks the Asian high or low)` and the follow-through size. A classic, genuinely-tradeable intraday structure — but verify it still holds on *your* pairs and period. *Compute:* define Asian H/L, flag London breaks, tabulate hit rate and continuation.

**33. Session-open volatility spike magnitude** `[Robust]` — Average vol in the first 15–60 min after the London open (~08:00 GMT) and NY open (~13:00 GMT) vs the surrounding baseline. Quantifies the "open burst" you can see on any chart. *Compute:* vol in opening window ÷ session-average vol.

**34. Tick / volume count by session** `[Robust]` — Tick volume (or real volume on CFDs) as a liquidity proxy per hour/session. Liquidity *drives* the vol profile — thin Asia and late-NY periods produce slippage and false breaks. *Compute:* tick count grouped by session.

**35. Spread by hour** `[Robust]` — Average bid–ask spread across the day. Widest in thin hours (late NY, pre-Asia, rollover) — directly erodes any short-horizon edge and must be in your cost model. *Compute:* mean spread grouped by hour.

**36. Daily high/low formation-time distribution** `[Robust]` — Histogram of *when* the day's extreme high and low are set. A large share form during London and the overlap; relatively few form in the Asian session. Informs when a day's direction is likely "decided." *Compute:* `idxmax`/`idxmin` per day → hour histogram.

**37. Inter-session & weekend gap distribution** `[Robust]` — Size and frequency of gaps between Friday close and Monday open (and across daily sessions). Drives overnight risk and stop-gapping; weekend gaps are a real, recurring tail. *Compute:* distribution of `open_t − close_{t−1}`.

**38. Time-of-day conditional volatility (your pair)** `[Robust]` — Same idea as the profile but as a *conditional distribution* you can sample from: "given it's the NY open hour, expected move = X, 90th-percentile move = Y." This is what turns the session story into actual probabilities. *Compute:* per-hour empirical quantiles of absolute returns.

---

## Group 5 — Calendar & seasonality

**39. Day-of-week effect** `[Fragile]` — Average return / range by weekday (the old "Monday effect," etc.). Largely arbitraged away in modern liquid FX and unstable across samples. *Range* differences by weekday are more robust than *return* differences. Treat any return edge here with deep suspicion. *Compute:* group by `dayofweek`.

**40. Turn-of-month effect** `[Fragile]` — Tendency for moves around month-end / month-start (rebalancing, fixings like the WMR 16:00 London fix). Real flow effects exist around fixings, but a tradeable directional edge is weak and crowded. *Compute:* flag last/first N business days, compare.

**41. Month-of-year / seasonal volatility** `[Regime]` — Average vol and range by calendar month. **Volatility** seasonality is fairly real (e.g. August/December liquidity droughts, quiet holiday periods); **directional** seasonality ("Sell in May") is weak in FX. Trust the vol pattern, distrust the direction. *Compute:* group by `month`.

**42. Pre/post economic-release volatility** `[Robust]` — Vol in the windows around scheduled releases — NFP (first Friday, 13:30 GMT), FOMC, CPI, central-bank meetings. Sharp, *predictable spikes in volatility* (direction stays unpredictable). Essential for risk and for deciding when to stand aside. *Compute:* align an economic calendar, measure vol in ±N-minute windows.

**43. Rollover / swap & low-liquidity-window behaviour** `[Robust]` — Behaviour around the daily 21:00–22:00 GMT rollover (spread widening, swap charges) and other thin pockets. Costs and erratic prints, not opportunity. *Compute:* spread/vol in the rollover window.

**44. Holiday & half-day effects** `[Regime]` — Reduced liquidity and compressed ranges around major holidays (US Thanksgiving, year-end, regional bank holidays). Predictably quieter — adjust targets and avoid range-breakout systems. *Compute:* tag holidays, compare range to baseline.

---

## Group 6 — Probability of a move & conditional behaviour

**45. Conditional probability tables** `[Regime]` — `P(next state | current state)`, e.g. `P(up tomorrow | today up & inside London hours)`. The honest way to ask "what's the probability of a move." In liquid FX most of these land near 50/50 — finding the rare cell that doesn't (and survives out-of-sample) is the whole game. *Compute:* `pandas` groupby + value_counts on discretised states.

**46. Markov transition matrix** `[Regime]` — Generalises item 45: discretise price into states (e.g. strong-down / down / flat / up / strong-up) and estimate the full state-to-state transition matrix. Captures short-horizon persistence or reversion compactly and is simulatable. *Compute:* count transitions, row-normalise.

**47. First-passage / barrier-hit ("touch") probability** `[Robust]` — Probability that price *touches* a level before the bar/horizon ends — distinct from closing beyond it. Key fact: for a driftless random walk, the probability of *touching* a level is roughly **twice** the probability of *closing* beyond it (reflection principle). Critical for realistic stop-loss and take-profit hit rates. *Compute:* analytic barrier formula, or empirical from intraday paths.

**48. MFE / MAE distributions** `[Robust]` — Maximum Favourable and Maximum Adverse Excursion: for each historical setup, how far price ran *for* you and *against* you before exit. The most practical tool for setting stops and targets from data rather than guesswork. *Compute:* per-trade max/min excursion from your backtest, then plot distributions.

**49. Expected-move bands (σ·√T)** `[Robust]` — Translate a volatility estimate into a forward move range: a 1-day 1-sigma move ≈ `price × daily_vol`, where `daily_vol ≈ annual_vol / √252`; scale by `√(horizon)` for other windows. Gives instant "how far could it go" bands — but **widen the tails** vs the normal assumption because of item 3. *Compute:* `price * vol * np.sqrt(horizon)`.

**50. Simulation — Monte Carlo & block bootstrap** `[Robust]` — Generate thousands of synthetic forward paths to read off probabilities directly (touch a level, drawdown, terminal range). Use a **fat-tailed** distribution (item 7) or, better, **block bootstrap** from your real returns to preserve volatility clustering and autocorrelation. The most flexible way to put a probability on almost any "what's the chance of…" question, and to get confidence intervals on every metric above. *Compute:* `arch.bootstrap` (e.g. `StationaryBootstrap`) or custom resampling.

---

## Bonus — Regime detection (beyond the 50, high leverage)

- **Hidden Markov Model (HMM)** `[Regime]` — Infers hidden states (e.g. low-vol-trending vs high-vol-choppy) and their transition probabilities. Powerful for switching strategies on/off by regime. *Compute:* `hmmlearn`.
- **Markov regime-switching model** `[Regime]` — Econometric cousin of HMM with regime-dependent mean/vol. *Compute:* `statsmodels MarkovRegression`.
- **Change-point detection** `[Regime]` — Finds structural breaks where the statistical behaviour shifts. Stops you fitting one model across two different worlds. *Compute:* `ruptures`.

---

## What actually works (read this before trusting any of it)

**Lean on these — robust across pairs and decades:**
volatility clustering and GARCH-style forecasting; fat tails (never use a plain normal for risk); the intraday/session volatility profile and the London–NY overlap dominance; volatility seasonality around news and holidays; MFE/MAE and touch-probability for stop/target design; the OHLC vol estimators (Yang–Zhang) over close-to-close.

**Use with regime awareness — real but conditional:**
mean reversion vs momentum (Hurst, variance ratio, ADF) — they flip by pair and horizon, so re-test continuously; the leverage effect; Asian-range breakouts; carry-related skew.

**Distrust by default — fragile, decaying, or data-mined:**
day-of-week and most *directional* calendar effects; any "candle pattern → 60% up" claim; conditional-probability cells that look strong on a single sample. If an edge doesn't survive out-of-sample on data the model never saw, it isn't an edge.

**Two discipline rules that matter more than any single metric:**
1. **Separate volatility from direction.** Almost everything reliable here predicts *magnitude and timing*, not *sign*. Don't let a strong vol result fool you into thinking you can predict direction.
2. **Validate out-of-sample and correct for multiple testing.** If you scan 50 metrics × 20 pairs × 10 timeframes, some will look significant by chance alone. Hold out data, use walk-forward, and apply a multiple-comparison haircut before believing anything.

---

## Suggested order to build this into your framework

1. **Distribution + volatility module first** (items 1–20). It's the most robust and underpins everything — and slots naturally next to your existing `performance.py`.
2. **Session/intraday analytics** (items 29–38) computed from your own tick/OHLC data, with session labels driven by your trading timezone.
3. **Mean-reversion vs momentum diagnostics** (items 21–28) run per pair/timeframe to decide which of your strategies (`choch`, `msb`, `anti_breakout`, `hull_suite`, …) suits each instrument's character.
4. **Probability & simulation layer** (items 45–50) to attach hit-rate and excursion probabilities to each strategy's setups — block bootstrap is the highest-value single addition.
5. **Regime detection** last, as a meta-layer that gates the others.

Python stack you'll want: `numpy`, `pandas`, `scipy.stats`, `statsmodels`, `arch` (GARCH + bootstrap), and optionally `hmmlearn` / `ruptures` for regimes.



## What to do next 
The most useful reframe first: in liquid FX you've already established that point-prediction of direction is a dead end, so don't aim the stats at "predict price." Aim them at *characterizing the distribution of outcomes* and exploiting the parts that are stable — volatility, time-of-day, range, and cost. The character report isn't a signal generator; it's a context and filtering layer that tells you what game each instrument is playing so you can match a strategy to it and size by expectancy after costs.

Given that, the highest-leverage next step isn't a new predictor — it's conditioning the strategies you already have. Take choch, msb, anti_breakout, and hull_suite, and tag every trade with the `market_stats` state at entry: vol regime, session, whether range was expanding or contracting, distance from the session extreme, where in the vol cone you were. Then look at where each strategy actually makes and loses money. Almost always the discovery isn't "this signal is broken," it's "this signal only works in high-vol London and bleeds during quiet Asia." Turning a strategy off 40% of the time can flip its expectancy, and that's an edge you can deploy immediately. This plugs straight into your `performance.py` and is the natural bridge from the stats to real P&L.

The structural edges worth mining, roughly in order of how well they survive contact with live data: volatility and range first — use the Yang-Zhang/GARCH estimates to normalize risk per trade (vol-targeting alone improves most systems before any signal change), then trade structures whose payoff depends on magnitude rather than direction, conditioned on the vol regime. Then session/time structure — Asian-range-into-London breakout, overlap concentration, end-of-session reversion — these persist because they're driven by liquidity and participant structure, not by anyone predicting anything. Then state-conditioning of existing edges. And underneath all of it, cost and execution: in FX the edge is frequently *when and how* you trade (spread by hour, rollover timing, slippage) rather than the entry rule itself.

The workflow that actually turns this into a validated edge:

1. Classify the instrument/timeframe with the report, pick a strategy archetype that fits its measured character.
2. State one specific, falsifiable hypothesis *before* you test — not "EURUSD mean-reverts" but "in the low-vol regime, the London range reverts toward the Asian midpoint by NY close, net of spread."
3. Test it conditional on that state, on one slice of data.
4. Validate hard: out-of-sample / walk-forward, across multiple pairs, with a multiple-testing correction.
5. Cost-and-capacity check before you believe any of it.

The trap to respect: 50 metrics times many pairs is thousands of implicit comparisons, and if you go hunting for what worked historically you'll find beautiful, convincing nonsense. Hypothesis-first plus a real holdout plus deflating for how many things you tried is the whole discipline. Your own toolkit already flagged the calendar and day-of-week effects as the fragile part — that's exactly where this bites hardest.

If you want, I'll build the regime/session trade-tagging module next: feed it your trade log plus OHLC, and it returns each strategy's performance broken down by the `market_stats` state at entry. That's the piece that turns the character report into an actual edge-finding loop.



### Distrubtion 
Practical implication
For trading and risk work, do not model these returns with a normal assumption alone. A better choice is often:

Student-t distribution,

EVT or tail modeling,

regime-based analysis,

Monte Carlo using fat-tailed returns,

VaR/ES instead of just mean and standard deviation.


Use Extreme Value Theory (EVT) for stress testing.

