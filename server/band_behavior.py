"""Band-behaviour study: how price moves through the previous session's
volatility bands in the next session — and which parts beat noise.

For each consecutive session pair (S_t → S_{t+1}) of the five-part day
partition (Tokyo solo → Tokyo∩London → London solo → London∩NY → NY solo,
DST-correct), per day:

  μ_t, σ_t   mean / std of ALL candle closes inside S_t (price levels)
  z          (close − μ_t) / σ_t for every S_{t+1} candle close
  bands      0.25σ intervals from −4σ to +4σ plus the two open tails
             (34 bands; index 0 = below −4σ, 33 = above +4σ)

Aggregated over the chosen date range:

  A  empirical distribution of S_{t+1} closes across bands (+ the normal-
     model expectation for comparison)
  B  first-touch analysis: per band, touch rate, median first-touch candle,
     and a Kaplan–Meier style survival curve (never-touch days censored at
     session end)
  C  path geometry per band: candles to first touch, max adverse excursion
     (bands) before touch, oscillation (direction-reversal share), candles
     spent in the band afterwards, max depth beyond it
  D  band-to-band transition matrix P_ij (consecutive candles), plus each
     band's probability of moving toward the centre
  E  escape velocity per band: signed and absolute band-change per candle
     on exits, and the share of exits toward the centre
  F  inferential tests: KS + Anderson–Darling on z vs N(0,1), χ² of band
     counts vs the normal model, Wald–Wolfowitz runs tests (above/below μ;
     outer-band hits), Mann–Whitney U (inner vs outer first-touch times and
     escape speeds) — each with its null, statistic, p, and interpretation
  G  synthesis: which findings look like real structure vs noise
"""
from __future__ import annotations

import math
from datetime import date

import numpy as np

from scipy import stats as sps

from .marketdata import load_bars
from libs.market_sessions import SEGMENT_LABEL, segment_windows

K_STEP = 0.25
K_MAX = 4.0
N_EDGE = int(K_MAX / K_STEP) * 2          # 32 interior intervals
N_BANDS = N_EDGE + 2                       # + two open tails
PAIRS = list(zip(["tokyo_solo", "tokyo_london", "london_solo", "london_ny"],
                 ["tokyo_london", "london_solo", "london_ny", "ny_solo"]))
SURV_MAX = 60                              # survival curve horizon (candles)


def band_labels() -> list[str]:
    labels = [f"<-{K_MAX:g}σ"]
    k = -K_MAX
    for _ in range(N_EDGE):
        labels.append(f"{k:+.2f}…{k + K_STEP:+.2f}σ")
        k += K_STEP
    labels.append(f">+{K_MAX:g}σ")
    return labels


def band_index(z: np.ndarray) -> np.ndarray:
    """z-score → band index 0..33 (0/33 are the open tails)."""
    idx = np.floor(z / K_STEP).astype(int) + N_EDGE // 2 + 1
    return np.clip(idx, 0, N_BANDS - 1)


def _center_dist(b: np.ndarray) -> np.ndarray:
    """Distance of a band index from the centre boundary (μ)."""
    return np.abs(b - (N_EDGE // 2 + 0.5))


def _normal_probs() -> np.ndarray:
    edges = np.arange(-K_MAX, K_MAX + 1e-9, K_STEP)
    cdf = sps.norm.cdf(edges)
    return np.concatenate([[cdf[0]], np.diff(cdf), [1 - cdf[-1]]])


def _runs_test(binary: np.ndarray) -> tuple[float, float]:
    """Wald–Wolfowitz runs test → (z, p). NaN when degenerate."""
    x = binary.astype(bool)
    n1, n2 = int(x.sum()), int((~x).sum())
    if n1 < 5 or n2 < 5:
        return float("nan"), float("nan")
    runs = 1 + int(np.sum(x[1:] != x[:-1]))
    n = n1 + n2
    mean = 2 * n1 * n2 / n + 1
    var = 2 * n1 * n2 * (2 * n1 * n2 - n) / (n ** 2 * (n - 1))
    if var <= 0:
        return float("nan"), float("nan")
    z = (runs - mean) / math.sqrt(var)
    return float(z), float(2 * (1 - sps.norm.cdf(abs(z))))


def _fin(x):
    if isinstance(x, dict):
        return {k: _fin(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_fin(v) for v in x]
    if isinstance(x, (np.floating, np.integer)):
        x = x.item()
    if isinstance(x, float) and not math.isfinite(x):
        return None
    return x


# ──────────────────────────────────────────────────────────────────────────
# per-pair study
# ──────────────────────────────────────────────────────────────────────────

def _study_pair(day_zs: list[np.ndarray]) -> dict:
    """day_zs: one z-score array per day (the S_{t+1} closes)."""
    n_days = len(day_zs)
    pooled_z = np.concatenate(day_zs) if day_zs else np.array([])
    pooled_b = band_index(pooled_z) if pooled_z.size else np.array([], int)

    # A ── distribution across bands
    counts = np.bincount(pooled_b, minlength=N_BANDS).astype(float)
    total = counts.sum()
    probs = counts / total if total else counts
    exp_probs = _normal_probs()

    # B/C ── first-touch, survival, path geometry (per band)
    touch_idx: list[list[int]] = [[] for _ in range(N_BANDS)]
    adverse: list[list[float]] = [[] for _ in range(N_BANDS)]
    osc: list[list[float]] = [[] for _ in range(N_BANDS)]
    inside: list[list[int]] = [[] for _ in range(N_BANDS)]
    depth: list[list[float]] = [[] for _ in range(N_BANDS)]
    day_lens = []
    for z in day_zs:
        b = band_index(z)
        day_lens.append(len(z))
        dz = np.diff(z)
        sign_flip = (np.sign(dz[1:]) * np.sign(dz[:-1]) < 0) if len(dz) > 1 else np.array([])
        first = {}
        for i, bi in enumerate(b):
            if bi not in first:
                first[bi] = i
        for bi, i in first.items():
            touch_idx[bi].append(i)
            start_side = 1 if bi > b[0] else -1        # direction toward the band
            pre = z[:i + 1]
            if len(pre) > 1:
                adv = (pre[0] - pre.min()) if start_side > 0 else (pre.max() - pre[0])
                adverse[bi].append(max(adv, 0.0) / K_STEP)   # in bands
                if len(pre) > 2:
                    pdz = np.diff(pre)
                    flips = np.sign(pdz[1:]) * np.sign(pdz[:-1]) < 0
                    osc[bi].append(float(np.mean(flips)))
            inside[bi].append(int(np.sum(b[i:] == bi)))
            if bi >= N_BANDS - 1 or bi <= 0:
                depth[bi].append(float(np.max(np.abs(z)) - K_MAX))
            else:
                lo = -K_MAX + (bi - 1) * K_STEP
                hi = lo + K_STEP
                seg = z[i:][b[i:] == bi]
                if seg.size:
                    depth[bi].append(float(np.max(np.minimum(seg - lo, hi - seg)) / K_STEP))

    horizon = min(max(day_lens) if day_lens else 0, SURV_MAX)
    per_band = []
    for bi in range(N_BANDS):
        touched = np.array(touch_idx[bi])
        n_touch = len(touched)
        # Kaplan–Meier style: S(n) = P(first touch > n); never-touch days
        # are censored at session end and stay in the numerator throughout
        surv = [float((np.sum(touched > n) + (n_days - n_touch)) / n_days)
                if n_days else None for n in range(horizon + 1)]
        per_band.append({
            "band": bi,
            "touch_rate": n_touch / n_days if n_days else None,
            "median_touch": float(np.median(touched)) if n_touch else None,
            "survival": surv,
            "n_touch": n_touch,
            "candles_to_touch_mean": float(np.mean(touched)) if n_touch else None,
            "adverse_bands_mean": float(np.mean(adverse[bi])) if adverse[bi] else None,
            "oscillation_mean": float(np.mean(osc[bi])) if osc[bi] else None,
            "candles_inside_mean": float(np.mean(inside[bi])) if inside[bi] else None,
            "depth_mean": float(np.mean(depth[bi])) if depth[bi] else None,
        })

    # D ── transition matrix
    M = np.zeros((N_BANDS, N_BANDS))
    for z in day_zs:
        b = band_index(z)
        for a, c in zip(b[:-1], b[1:]):
            M[a, c] += 1
    row = M.sum(axis=1, keepdims=True)
    P = np.divide(M, row, out=np.zeros_like(M), where=row > 0)
    toward_center = []
    cd = _center_dist(np.arange(N_BANDS))
    for i in range(N_BANDS):
        if row[i, 0] == 0:
            toward_center.append(None)
            continue
        closer = P[i][cd < cd[i]].sum() if (cd < cd[i]).any() else 0.0
        toward_center.append(float(closer))

    # E ── escape velocity
    esc = [{"n": 0, "d": [], "away": 0} for _ in range(N_BANDS)]
    for z in day_zs:
        b = band_index(z)
        for a, c in zip(b[:-1], b[1:]):
            if a != c:
                esc[a]["n"] += 1
                esc[a]["d"].append(int(c - a))
                if _center_dist(np.array([c]))[0] > _center_dist(np.array([a]))[0]:
                    esc[a]["away"] += 1
    escape = []
    for bi in range(N_BANDS):
        d = np.array(esc[bi]["d"], float)
        escape.append({
            "band": bi, "n_exits": esc[bi]["n"],
            "mean_signed_bands": float(d.mean()) if d.size else None,
            "mean_abs_bands": float(np.abs(d).mean()) if d.size else None,
            "toward_center_share": 1 - esc[bi]["away"] / esc[bi]["n"] if esc[bi]["n"] else None,
        })

    # F ── inferential tests
    tests = []
    if pooled_z.size >= 50:
        ks_stat, ks_p = sps.kstest(pooled_z, "norm")
        tests.append({
            "name": "Kolmogorov–Smirnov (z vs N(0,1))",
            "null": "next-session z-scores are standard normal",
            "statistic": float(ks_stat), "p_value": float(ks_p),
            "interpretation": ("shape differs from the normal model — structure "
                               "beyond Gaussian noise" if ks_p < 0.05 else
                               "consistent with normal noise around μ_t"),
        })
        ad = sps.anderson(pooled_z, "norm")
        crit5 = float(ad.critical_values[list(ad.significance_level).index(5.0)])
        rej = bool(ad.statistic > crit5)
        tests.append({
            "name": "Anderson–Darling (tail-sensitive)",
            "null": "z-scores are normal (tails included)",
            "statistic": float(ad.statistic), "p_value": None,
            "crit_5pct": crit5, "reject_5pct": rej,
            "interpretation": ("tails deviate from normal — outer bands carry "
                               "non-Gaussian behaviour" if rej else
                               "tails consistent with a normal model"),
        })
        exp = exp_probs * total
        mask = exp >= 5
        if mask.sum() >= 3:
            obs_m = np.append(counts[mask], counts[~mask].sum())
            exp_m = np.append(exp[mask], exp[~mask].sum())
            exp_m = exp_m * obs_m.sum() / exp_m.sum()
            chi, chi_p = sps.chisquare(obs_m, exp_m)
            tests.append({
                "name": "χ² band occupancy vs normal model",
                "null": "band visit counts match the normal expectation",
                "statistic": float(chi), "p_value": float(chi_p),
                "interpretation": ("some bands are systematically over/under-"
                                   "visited" if chi_p < 0.05 else
                                   "band occupancy matches the normal model"),
            })
        # runs tests: Stouffer-combined per day
        for label, binfn in (("above/below μ", lambda z: z > 0),
                             ("outer-band hits (|z|>2)", lambda z: np.abs(z) > 2)):
            zs = []
            for z in day_zs:
                rz, _ = _runs_test(binfn(z))
                if np.isfinite(rz):
                    zs.append(rz)
            if len(zs) >= 5:
                zc = float(np.sum(zs) / math.sqrt(len(zs)))
                pc = float(2 * (1 - sps.norm.cdf(abs(zc))))
                tests.append({
                    "name": f"Runs test — {label}",
                    "null": "hits are randomly scattered in time",
                    "statistic": zc, "p_value": pc,
                    "interpretation": (("hits cluster (trending/persistent)"
                                        if zc < 0 else "hits alternate (choppy)")
                                       + " — non-random sequencing"
                                       if pc < 0.05 else
                                       "sequencing consistent with randomness"),
                })
        # Mann–Whitney: inner vs outer first-touch times and escape speeds
        inner_b = [bi for bi in range(N_BANDS)
                   if _center_dist(np.array([bi]))[0] <= 1.0 / K_STEP / 2]
        outer_b = [bi for bi in range(N_BANDS)
                   if _center_dist(np.array([bi]))[0] > 2.0 / K_STEP / 2]
        ft_in = np.concatenate([touch_idx[b] for b in inner_b]) if inner_b else np.array([])
        ft_out = np.concatenate([touch_idx[b] for b in outer_b]) if outer_b else np.array([])
        if ft_in.size >= 10 and ft_out.size >= 10:
            u, p = sps.mannwhitneyu(ft_in, ft_out, alternative="two-sided")
            tests.append({
                "name": "Mann–Whitney U — first-touch, inner vs outer bands",
                "null": "inner and outer bands are reached on the same timescale",
                "statistic": float(u), "p_value": float(p),
                "interpretation": ("touch-time distributions differ by band "
                                   "distance (expected under any diffusion, but "
                                   "the magnitude calibrates the drift)"
                                   if p < 0.05 else
                                   "no detectable timing difference"),
            })
        ev_in = np.concatenate([np.abs(esc[b]["d"]) for b in inner_b if esc[b]["d"]]) \
            if any(esc[b]["d"] for b in inner_b) else np.array([])
        ev_out = np.concatenate([np.abs(esc[b]["d"]) for b in outer_b if esc[b]["d"]]) \
            if any(esc[b]["d"] for b in outer_b) else np.array([])
        if ev_in.size >= 10 and ev_out.size >= 10:
            u, p = sps.mannwhitneyu(ev_in, ev_out, alternative="two-sided")
            tests.append({
                "name": "Mann–Whitney U — escape speed, inner vs outer bands",
                "null": "exits from inner and outer bands move at the same speed",
                "statistic": float(u), "p_value": float(p),
                "interpretation": ("outer-band exits move at a different speed — "
                                   "band position carries momentum information"
                                   if p < 0.05 else
                                   "escape speeds look band-independent"),
            })

    # G ── synthesis
    rejected = [t for t in tests
                if (t.get("p_value") is not None and t["p_value"] < 0.05)
                or t.get("reject_5pct")]
    bullets = [t["name"] + ": " + t["interpretation"] for t in tests]
    verdict = ("structured" if len(rejected) >= 3 else
               "mixed" if len(rejected) >= 1 else "noise-like")

    return {
        "n_days": n_days,
        "n_candles": int(total),
        "A": {"counts": [int(c) for c in counts],
              "probs": [float(p) for p in probs],
              "expected_probs": [float(p) for p in exp_probs]},
        "B_C": per_band,
        "D": {"matrix": [[round(float(x), 4) for x in r] for r in P],
              "toward_center": toward_center},
        "E": escape,
        "F": tests,
        "G": {"bullets": bullets, "verdict": verdict,
              "n_tests": len(tests), "n_rejections": len(rejected)},
    }


# ──────────────────────────────────────────────────────────────────────────
# entry point
# ──────────────────────────────────────────────────────────────────────────

def analyze_bands(asset: str, tf: str, start: date | None = None,
                  end: date | None = None) -> dict:
    df = load_bars(asset, tf).dropna(subset=["Datetime"]).sort_values("Datetime")
    if start is not None:
        df = df[df["Datetime"].dt.date >= start]
    if end is not None:
        df = df[df["Datetime"].dt.date <= end]
    df = df.reset_index(drop=True)
    if len(df) < 100:
        raise ValueError(f"Not enough {tf} bars for {asset} in that range")

    T = df["Datetime"].values.astype("datetime64[ns]")
    C = df["Close"].to_numpy(float)
    days = sorted(set(df["Datetime"].dt.date))

    pair_zs: dict[tuple[str, str], list[np.ndarray]] = {p: [] for p in PAIRS}
    for day in days:
        wins = segment_windows(day)
        for a_key, b_key in PAIRS:
            a0 = np.searchsorted(T, np.datetime64(wins[a_key][0]), "left")
            a1 = np.searchsorted(T, np.datetime64(wins[a_key][1]), "left")
            b0 = np.searchsorted(T, np.datetime64(wins[b_key][0]), "left")
            b1 = np.searchsorted(T, np.datetime64(wins[b_key][1]), "left")
            if a1 - a0 < 5 or b1 - b0 < 3:
                continue
            closesA = C[a0:a1]
            mu = float(np.mean(closesA))
            sd = float(np.std(closesA, ddof=1))
            if not np.isfinite(sd) or sd <= 0:
                continue
            pair_zs[(a_key, b_key)].append((C[b0:b1] - mu) / sd)

    pairs_out = []
    for (a_key, b_key), zs in pair_zs.items():
        entry = {"analyze": SEGMENT_LABEL[a_key], "trigger": SEGMENT_LABEL[b_key]}
        if len(zs) < 20:
            entry["note"] = f"only {len(zs)} usable days — need ≥ 20"
        else:
            entry.update(_study_pair(zs))
        pairs_out.append(entry)

    return _fin({
        "asset": asset, "timeframe": tf,
        "date_range": [days[0].isoformat(), days[-1].isoformat()],
        "band_step": K_STEP, "band_max": K_MAX,
        "band_labels": band_labels(),
        "pairs": pairs_out,
    })
