"""SessionSigmaStrategy: segment windows, both setups, ledger, pipeline run.

The strategy is the evidence-based redesign from the band study: breakout
continuation on every pair, mean-cross momentum only on the calibrated
pairs, per-pair stops — and no fade-to-the-mean setup anywhere.
"""
from datetime import date

import numpy as np
import pandas as pd
import pytest

from strategies.session_sigma_strategy import (
    PAIR_PARAMS, SEGMENT_CHAIN, SessionSigmaStrategy, segment_windows,
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


def test_pair_params_reflect_band_study():
    # fade is gone entirely, and the two under-scaled rulers (8% / 35% of
    # closes beyond ±4σ in the study) never run mean-cross
    assert not hasattr(SessionSigmaStrategy, "_fade")
    assert PAIR_PARAMS[("tokyo_london", "london_solo")]["mean_cross"] is False
    assert PAIR_PARAMS[("london_solo", "london_ny")]["mean_cross"] is False
    assert PAIR_PARAMS[("tokyo_solo", "tokyo_london")]["mean_cross"] is True
    assert PAIR_PARAMS[("london_ny", "ny_solo")]["mean_cross"] is True
    # stops cover the measured adverse excursion per pair (0.26/0.7/1.0/0.37σ)
    assert PAIR_PARAMS[("tokyo_solo", "tokyo_london")]["sl_k"] >= 0.30
    assert PAIR_PARAMS[("tokyo_london", "london_solo")]["sl_k"] >= 0.75
    assert PAIR_PARAMS[("london_solo", "london_ny")]["sl_k"] >= 1.00
    assert PAIR_PARAMS[("london_ny", "ny_solo")]["sl_k"] >= 0.40
    # breakout targets sit further out where the tails reach further
    assert (PAIR_PARAMS[("london_solo", "london_ny")]["breakout_tp_ks"]
            > PAIR_PARAMS[("tokyo_solo", "tokyo_london")]["breakout_tp_ks"])


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

    strat = SessionSigmaStrategy(enable_breakout=False)
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
    # initial stop was the pair's sl_k (0.5σ) against the trade for lot 1
    lot1 = mc[mc["lot"] == 1].iloc[0]
    assert lot1["sl_price"] == pytest.approx(entry + 0.5 * sd, rel=1e-6)


def test_mean_cross_never_runs_on_uncalibrated_pair():
    # london_solo → london_ny: KS 0.293, ~35% of closes beyond ±4σ in the
    # study — the σ ruler is decorative, so mean-cross must not fire even
    # when the analyze close sits within ±0.5σ and the trigger crosses μ
    analyze = [1.0990, 1.1010] * 5 + [1.0990, 1.1002]   # 12 bars, dev≈+0.27
    a = _bars("2026-07-06 09:00", analyze)
    b = _bars("2026-07-06 12:00", [1.0990] * 16)        # running mean < μ
    df = pd.concat([a, b], ignore_index=True)
    _, details = SessionSigmaStrategy().backtest(df)
    assert len(details["trades"]) == 0


def test_breakout_long_scales_out_three_lots():
    # analyze (tokyo_solo): μ=1.1, σ≈1.02e-3.  trigger: staircase up through
    # +2σ (entry with the break) then on through 3σ, 3.5σ, 4σ (the pair's
    # targets) — continuation, exactly what the band study measured
    analyze = [1.0990, 1.1010] * 14
    a = _bars("2026-07-06 00:00", analyze)
    trig = [1.1005, 1.1015, 1.1022, 1.1028, 1.1033, 1.1038, 1.1043, 1.1043]
    b = _bars("2026-07-06 07:00", trig)
    df = pd.concat([a, b, _flat_rest_of_day("2026-07-06 09:00", 1.1043)],
                   ignore_index=True)

    strat = SessionSigmaStrategy(enable_mean_cross=False)
    _, details = strat.backtest(df)
    full = details["trades"]
    bo = full[(full["setup"] == "breakout")
              & (full["analyze_segment"] == "Tokyo (solo)")]
    assert len(bo) == 3
    assert set(bo["side"]) == {"long"}
    mu, sd = float(bo["mu"].iloc[0]), float(bo["sigma"].iloc[0])
    entry = float(bo["entry_price"].iloc[0])
    assert entry == pytest.approx(1.1022)     # first close beyond μ+2σ
    assert entry > mu + 2 * sd
    tps = sorted(bo["tp_price"])
    assert tps == pytest.approx([mu + 3 * sd, mu + 3.5 * sd, mu + 4 * sd])
    assert set(bo["exit_reason"]) == {"TP"}   # staircase carried to all three
    # pair stop: sl_k=0.5σ below entry for lot 1; lot 3 at breakeven after
    # lot 2's target filled
    lot1 = bo[bo["lot"] == 1].iloc[0]
    assert lot1["sl_price"] == pytest.approx(entry - 0.5 * sd, rel=1e-6)
    lot3 = bo[bo["lot"] == 3].iloc[0]
    assert lot3["sl_price"] == pytest.approx(entry)


def test_breakout_only_once_per_direction():
    # first break enters (hits cluster → first hit marks the episode);
    # a second push through the same level must not open a second position
    analyze = [1.0990, 1.1010] * 14
    a = _bars("2026-07-06 00:00", analyze)
    trig = [1.1022, 1.1005, 1.1010, 1.1022, 1.1005, 1.1005, 1.1005, 1.1005]
    b = _bars("2026-07-06 07:00", trig)
    df = pd.concat([a, b, _flat_rest_of_day("2026-07-06 09:00", 1.1005)],
                   ignore_index=True)
    strat = SessionSigmaStrategy(enable_mean_cross=False)
    _, details = strat.backtest(df)
    full = details["trades"]
    bo = full[(full["setup"] == "breakout")
              & (full["analyze_segment"] == "Tokyo (solo)")]
    assert len(bo) == 3                       # one entry, three lots
    assert bo["entry_time"].nunique() == 1
    assert set(bo["exit_reason"]) == {"SL"}   # the pullback stopped them out


def test_breakout_beyond_top_target_is_skipped():
    # entry ≈ +12σ: every pair target already passed → nothing left to aim
    # at → no trade (and no re-arm later in the segment)
    analyze = [1.0990, 1.1010] * 14
    a = _bars("2026-07-06 00:00", analyze)
    b = _bars("2026-07-06 07:00", [1.1120] * 8)
    df = pd.concat([a, b, _flat_rest_of_day("2026-07-06 09:00", 1.1120)],
                   ignore_index=True)
    strat = SessionSigmaStrategy(enable_mean_cross=False)
    _, details = strat.backtest(df)
    full = details["trades"]
    if len(full):
        assert not ((full["setup"] == "breakout")
                    & (full["analyze_segment"] == "Tokyo (solo)")).any()


def test_reference_mode_trades_only_that_session_across_the_day():
    # reference = Tokyo (solo): its μ/σ are the only ruler, and its trading
    # window spans until the next Tokyo occurrence — so a breakout that
    # happens hours later (here in the London∩NY window) still trades off
    # Tokyo's levels, and no other analyze segment produces trades.
    analyze = [1.0990, 1.1010] * 14                       # tokyo_solo, μ=1.1
    a = _bars("2026-07-06 00:00", analyze)
    flat1 = _bars("2026-07-06 07:00", [1.1000] * 20)      # quiet until 12:00
    trig = [1.1005, 1.1015, 1.1022, 1.1028, 1.1033, 1.1038, 1.1043, 1.1043]
    b = _bars("2026-07-06 12:00", trig)                   # breakout in Ldn∩NY
    flat2 = _bars("2026-07-06 14:00", [1.1043] * 40)      # rest of day 1
    day2 = _bars("2026-07-07 00:00", [1.1043] * 28)       # next occurrence
    df = pd.concat([a, flat1, b, flat2, day2], ignore_index=True)

    strat = SessionSigmaStrategy(reference="tokyo_solo", enable_mean_cross=False)
    _, details = strat.backtest(df)
    full = details["trades"]
    assert len(full) > 0
    assert set(full["analyze_segment"]) == {"Tokyo (solo)"}
    assert set(full["trigger_segment"]) == {"until next Tokyo (solo)"}
    bo = full[full["setup"] == "breakout"]
    day1 = bo[bo["day"] == DAY]
    assert len(day1) == 3
    mu, sd = float(day1["mu"].iloc[0]), float(day1["sigma"].iloc[0])
    assert mu == pytest.approx(1.1000, abs=1e-4)          # Tokyo's ruler
    # entry happened long after the adjacent segment, inside London∩NY
    assert day1["entry_time"].iloc[0] == pd.Timestamp("2026-07-06 12:30")
    tps = sorted(day1["tp_price"])
    assert tps == pytest.approx([mu + 3 * sd, mu + 3.5 * sd, mu + 4 * sd])
    assert set(day1["exit_reason"]) == {"TP"}


def test_reference_mode_flattens_before_next_occurrence():
    # a breakout that never reaches a target stays open until the last bar
    # before the next reference occurrence, then closes as segment_close
    analyze = [1.0990, 1.1010] * 14
    a = _bars("2026-07-06 00:00", analyze)
    hold = _bars("2026-07-06 07:00", [1.1022] * 68)       # 07:00 → 23:45
    day2 = _bars("2026-07-07 00:00", [1.1022] * 28)
    df = pd.concat([a, hold, day2], ignore_index=True)

    strat = SessionSigmaStrategy(reference="tokyo_solo", enable_mean_cross=False)
    _, details = strat.backtest(df)
    full = details["trades"]
    day1 = full[(full["setup"] == "breakout") & (full["day"] == DAY)]
    assert len(day1) == 3
    assert set(day1["exit_reason"]) == {"segment_close"}
    # held to the final bar of day 1 — well past every session boundary —
    # and closed before day 2's Tokyo occurrence began
    assert set(day1["exit_time"]) == {pd.Timestamp("2026-07-06 23:45")}


def test_reference_mode_rejects_unknown_segment():
    with pytest.raises(ValueError):
        SessionSigmaStrategy(reference="sydney")


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
        assert set(full["setup"]) <= {"mean_cross", "breakout"}
        assert full["entry_price"].notna().all()
        assert full["exit_price"].notna().all()   # everything closed
    assert "segments" in details and "metadata" in details
    assert details["metadata"]["strategy"] == "SessionSigma"
    assert "pair_params" in details["metadata"]


def test_full_pipeline_run(tmp_path):
    # the default store backend persists into the app DB → point it at sqlite
    import os
    import sys
    os.environ["MARKET_PREP_DB_URL"] = f"sqlite:///{tmp_path}/app.db"
    for mod in [m for m in list(sys.modules) if m.startswith("server")]:
        del sys.modules[mod]
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
