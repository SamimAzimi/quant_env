"""SessionSigmaStrategy: segment windows, both setups, ledger, pipeline run."""
from datetime import date

import numpy as np
import pandas as pd
import pytest

from strategies.session_sigma_strategy import (
    SEGMENT_CHAIN, SessionSigmaStrategy, segment_windows,
)

# 2026-07-06 is a Monday; summer windows (UTC): tokyo_solo 00-07,
# tokyo∩london 07-09, london_solo 09-12, london∩ny 12-16, ny_solo 16-21.
DAY = date(2026, 7, 6)


def test_segment_windows_partition_summer_day():
    w = segment_windows(DAY)
    assert [k for k in w] == SEGMENT_CHAIN
    assert w["tokyo_solo"] == (pd.Timestamp("2026-07-06 00:00"), pd.Timestamp("2026-07-06 07:00"))
    assert w["tokyo_london"] == (pd.Timestamp("2026-07-06 07:00"), pd.Timestamp("2026-07-06 09:00"))
    assert w["london_solo"] == (pd.Timestamp("2026-07-06 09:00"), pd.Timestamp("2026-07-06 12:00"))
    assert w["london_ny"] == (pd.Timestamp("2026-07-06 12:00"), pd.Timestamp("2026-07-06 16:00"))
    assert w["ny_solo"] == (pd.Timestamp("2026-07-06 16:00"), pd.Timestamp("2026-07-06 21:00"))
    # consecutive segments tile the trading day
    for a, b in zip(SEGMENT_CHAIN[:-1], SEGMENT_CHAIN[1:]):
        assert w[a][1] == w[b][0]


def _bars(start, closes, spread=0.0002):
    """15m bars with tight highs/lows around the close path."""
    idx = pd.date_range(start, periods=len(closes), freq="15min")
    c = np.asarray(closes, float)
    o = np.concatenate([[c[0]], c[:-1]])
    return pd.DataFrame({
        "Datetime": idx, "Open": o,
        "High": np.maximum(o, c) + spread,
        "Low": np.minimum(o, c) - spread,
        "Close": c,
    })


def _flat_rest_of_day(t0, price):
    """Filler bars so later segments exist but do nothing (constant price)."""
    idx = pd.date_range(t0, "2026-07-06 20:45", freq="15min")
    return pd.DataFrame({"Datetime": idx, "Open": price, "High": price,
                         "Low": price, "Close": price})


def test_mean_cross_short_scales_out_three_lots():
    # analyze (tokyo_solo): closes oscillate 1.0990/1.1010 → μ=1.1, σ≈1e-3;
    # last close 1.1002 → dev≈+0.2 (within 0.5σ) → watch for mean-cross short
    analyze = ([1.0990, 1.1010] * 14)[:27] + [1.1002]
    a = _bars("2026-07-06 00:00", analyze)
    # trigger (tokyo∩london): first close 1.0999 → running mean < μ → short.
    # then a staircase down through μ−1σ, μ−2σ, μ−3σ
    trig = [1.0999, 1.0993, 1.0989, 1.0983, 1.0979, 1.0973, 1.0969, 1.0965]
    b = _bars("2026-07-06 07:00", trig)
    df = pd.concat([a, b, _flat_rest_of_day("2026-07-06 09:00", 1.0965)],
                   ignore_index=True)

    strat = SessionSigmaStrategy(enable_fade=False)
    trades_df, details = strat.backtest(df)
    full = details["trades"]
    mc = full[(full["setup"] == "mean_cross")
              & (full["analyze_segment"] == "Tokyo (solo)")]
    assert len(mc) == 3                       # three lots
    assert set(mc["side"]) == {"short"}
    assert mc["entry_price"].nunique() == 1
    entry = float(mc["entry_price"].iloc[0])
    assert entry == pytest.approx(1.0999, abs=1e-9)

    mu, sd = float(mc["mu"].iloc[0]), float(mc["sigma"].iloc[0])
    assert mu == pytest.approx(1.1000, abs=1e-4)
    tps = sorted(mc["tp_price"])              # μ−3σ < μ−2σ < μ−1σ
    assert tps == pytest.approx([mu - 3 * sd, mu - 2 * sd, mu - 1 * sd])
    assert set(mc["exit_reason"]) == {"TP"}   # staircase hit all three
    # after lot 2's TP, lot 3's stop moved to entry (breakeven)
    lot3 = mc[mc["lot"] == 3].iloc[0]
    assert lot3["sl_price"] == pytest.approx(entry)
    # initial stop was 0.5σ against the trade for lot 1
    lot1 = mc[mc["lot"] == 1].iloc[0]
    assert lot1["sl_price"] == pytest.approx(entry + 0.5 * sd, rel=1e-6)


def test_fade_short_fills_and_targets_mean():
    # analyze: μ=1.1, σ≈1e-3, last close 1.1012 → dev≈+1.19 → k=1.0
    analyze = ([1.0990, 1.1010] * 14)[:27] + [1.1012]
    a = _bars("2026-07-06 00:00", analyze)
    # trigger: pushes up through μ+1.5σ (≈1.10152) then falls to the mean
    trig = [1.1013, 1.1016, 1.1010, 1.1004, 1.0999, 1.0999, 1.0999, 1.0999]
    b = _bars("2026-07-06 07:00", trig)
    df = pd.concat([a, b, _flat_rest_of_day("2026-07-06 09:00", 1.0999)],
                   ignore_index=True)

    strat = SessionSigmaStrategy(enable_mean_cross=False)
    _, details = strat.backtest(df)
    full = details["trades"]
    fd = full[(full["setup"] == "fade")
              & (full["analyze_segment"] == "Tokyo (solo)")
              & (full["lot"] > 0)]
    assert len(fd) == 3
    mu, sd = float(fd["mu"].iloc[0]), float(fd["sigma"].iloc[0])
    entry = float(fd["entry_price"].iloc[0])
    assert entry == pytest.approx(mu + 1.5 * sd, rel=1e-6)   # one level further
    assert set(fd["side"]) == {"short"}
    assert fd["tp_price"].iloc[0] == pytest.approx(mu)       # target = analyze mean
    assert fd["sl_price"].iloc[0] == pytest.approx(entry + 0.5 * sd, rel=1e-6)
    assert set(fd["exit_reason"]) == {"TP"}


def test_fade_no_fill_recorded():
    analyze = ([1.0990, 1.1010] * 14)[:27] + [1.1012]
    a = _bars("2026-07-06 00:00", analyze)
    trig = [1.1005] * 8                        # never reaches μ+1.5σ
    b = _bars("2026-07-06 07:00", trig)
    df = pd.concat([a, b, _flat_rest_of_day("2026-07-06 09:00", 1.1005)],
                   ignore_index=True)
    strat = SessionSigmaStrategy(enable_mean_cross=False)
    _, details = strat.backtest(df)
    full = details["trades"]
    nf = full[(full["setup"] == "fade")
              & (full["analyze_segment"] == "Tokyo (solo)")]
    assert len(nf) == 1
    assert nf["exit_reason"].iloc[0] == "no_fill"
    assert pd.isna(nf["entry_price"].iloc[0])


def test_extreme_extension_beyond_top_level_is_skipped():
    # last close ≈ +12σ → k capped at 3.0 → no level above → no fade trade
    analyze = ([1.0990, 1.1010] * 14)[:27] + [1.1120]
    a = _bars("2026-07-06 00:00", analyze)
    b = _bars("2026-07-06 07:00", [1.1120] * 8)
    df = pd.concat([a, b, _flat_rest_of_day("2026-07-06 09:00", 1.1120)],
                   ignore_index=True)
    strat = SessionSigmaStrategy(enable_mean_cross=False)
    _, details = strat.backtest(df)
    full = details["trades"]
    if len(full):
        assert not ((full["setup"] == "fade")
                    & (full["analyze_segment"] == "Tokyo (solo)")).any()


def test_ledger_has_pipeline_columns_and_details():
    rng = np.random.default_rng(5)
    idx = pd.date_range("2026-07-06", periods=10 * 96, freq="15min")
    c = 1.10 * np.exp(np.cumsum(rng.normal(0, 0.0004, len(idx))))
    o = np.concatenate([[c[0]], c[:-1]])
    df = pd.DataFrame({"Datetime": idx, "Open": o,
                       "High": np.maximum(o, c) * 1.0002,
                       "Low": np.minimum(o, c) * 0.9998, "Close": c})
    trades_df, details = SessionSigmaStrategy().backtest(df)
    assert list(trades_df.columns) == SessionSigmaStrategy.TRADE_COLUMNS
    full = details["trades"]
    if len(full):
        assert {"sl_price", "tp_price", "setup", "lot", "mu", "sigma"} <= set(full.columns)
        filled = full[full["entry_price"].notna()]
        assert filled["exit_price"].notna().all()   # everything closed
    assert "segments" in details and "metadata" in details
    assert details["metadata"]["strategy"] == "SessionSigma"


def test_full_pipeline_run(tmp_path):
    from libs.pipeline import PipelineConfig, run_pipeline
    rng = np.random.default_rng(11)
    idx = pd.date_range("2026-05-01", periods=45 * 96, freq="15min")
    c = 1.10 * np.exp(np.cumsum(rng.normal(0, 0.0004, len(idx))))
    o = np.concatenate([[c[0]], c[:-1]])
    folder = tmp_path / "FX:SIGTEST"
    folder.mkdir()
    pd.DataFrame({"Open time": idx.strftime("%Y-%m-%d %H:%M:%S"),
                  "open": o, "high": np.maximum(o, c) * 1.0002,
                  "low": np.minimum(o, c) * 0.9998, "close": c}) \
        .to_csv(folder / "15m.csv", index=False)

    res = run_pipeline(PipelineConfig(
        asset="SIGTEST", asset_class="FX", timeframe="15m",
        cost_symbol="EURUSD", strategy_cls=SessionSigmaStrategy,
        marketdata_path=str(tmp_path) + "/", db_path=str(tmp_path) + "/",
    ))
    m = res.metrics
    assert "net_profit" in m and "sharpe" in m and "win_rate" in m
    assert res.cost_summary["trades"] > 0
    assert not res.equity_curve.empty
