"""SessionExtremeFadeStrategy: touch ±4σ of the reference session, fade to μ."""
from datetime import date

import numpy as np
import pandas as pd
import pytest

from strategies.session_extreme_fade import SessionExtremeFadeStrategy

DAY = date(2026, 7, 6)   # Monday; summer windows: tokyo_solo 00-07 UTC


def _bars(start, closes, spread=0.0002):
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
    idx = pd.date_range(t0, "2026-07-06 20:45", freq="15min")
    return pd.DataFrame({"Datetime": idx, "Open": price, "High": price,
                         "Low": price, "Close": price})


def _analyze():
    # tokyo_solo closes oscillate 1.0990/1.1010 → μ=1.1, σ≈1.0183e-3
    return _bars("2026-07-06 00:00", [1.0990, 1.1010] * 14)


def test_short_fade_from_plus_4_sigma_targets_mean():
    trig = [1.1010, 1.1030, 1.1041, 1.1020, 1.1005, 1.0999, 1.0999, 1.0999]
    df = pd.concat([_analyze(), _bars("2026-07-06 07:00", trig),
                    _flat_rest_of_day("2026-07-06 09:00", 1.0999)],
                   ignore_index=True)
    strat = SessionExtremeFadeStrategy(sessions="tokyo_solo")
    trades_df, details = strat.backtest(df)
    full = details["trades"]
    assert len(full) == 1
    t = full.iloc[0]
    mu, sd = float(t["mu"]), float(t["sigma"])
    assert mu == pytest.approx(1.1000, abs=1e-6)
    assert t["side"] == "short"
    assert t["entry_price"] == pytest.approx(mu + 4 * sd)     # limit at the band
    assert t["sl_price"] == pytest.approx(t["entry_price"] + sd)   # 1σ above
    assert t["tp_price"] == pytest.approx(mu)                 # target = mean
    assert t["exit_reason"] == "TP"
    assert t["analyze_segment"] == "Tokyo (solo)"


def test_long_fade_from_minus_4_sigma_stops_1_sigma_below():
    trig = [1.0990, 1.0970, 1.0958, 1.0948, 1.0948, 1.0948, 1.0948, 1.0948]
    df = pd.concat([_analyze(), _bars("2026-07-06 07:00", trig),
                    _flat_rest_of_day("2026-07-06 09:00", 1.0948)],
                   ignore_index=True)
    strat = SessionExtremeFadeStrategy(sessions="tokyo_solo")
    _, details = strat.backtest(df)
    full = details["trades"]
    assert len(full) == 1
    t = full.iloc[0]
    mu, sd = float(t["mu"]), float(t["sigma"])
    assert t["side"] == "long"
    assert t["entry_price"] == pytest.approx(mu - 4 * sd)
    assert t["sl_price"] == pytest.approx(t["entry_price"] - sd)   # 1σ below
    assert t["exit_reason"] == "SL"                                # kept falling


def test_validity_hours_expire_the_bands():
    # touch happens at 09:00 — inside an until_next_occurrence window,
    # but AFTER a 1-hour validity has expired
    trig = [1.1000] * 8                                   # 07:00–08:45 quiet
    spike = [1.1041, 1.1020, 1.1005, 1.0999]              # 09:00 touch
    df = pd.concat([_analyze(), _bars("2026-07-06 07:00", trig),
                    _bars("2026-07-06 09:00", spike),
                    _flat_rest_of_day("2026-07-06 10:00", 1.0999)],
                   ignore_index=True)
    hour1 = SessionExtremeFadeStrategy(sessions="tokyo_solo", valid_for=1.0)
    _, d1 = hour1.backtest(df)
    assert len(d1["trades"]) == 0                         # bands already expired
    allday = SessionExtremeFadeStrategy(sessions="tokyo_solo")
    _, d2 = allday.backtest(df)
    assert len(d2["trades"]) == 1                         # still valid → trades


def test_open_trade_flattens_when_bands_expire():
    trig = [1.1041, 1.1041, 1.1041, 1.1041]               # touch, never reverts
    df = pd.concat([_analyze(), _bars("2026-07-06 07:00", trig),
                    _flat_rest_of_day("2026-07-06 08:00", 1.1041)],
                   ignore_index=True)
    strat = SessionExtremeFadeStrategy(sessions="tokyo_solo", valid_for=1.0)
    _, details = strat.backtest(df)
    full = details["trades"]
    assert len(full) == 1
    assert full.iloc[0]["exit_reason"] == "segment_close"
    assert full.iloc[0]["exit_time"] == pd.Timestamp("2026-07-06 07:45")


def test_session_selection_and_validation():
    trig = [1.1010, 1.1041, 1.1005, 1.0999, 1.0999, 1.0999, 1.0999, 1.0999]
    df = pd.concat([_analyze(), _bars("2026-07-06 07:00", trig),
                    _flat_rest_of_day("2026-07-06 09:00", 1.0999)],
                   ignore_index=True)
    # tokyo touched, but only london_solo is selected → nothing trades
    strat = SessionExtremeFadeStrategy(sessions="london_solo")
    _, details = strat.backtest(df)
    assert len(details["trades"]) == 0
    with pytest.raises(ValueError):
        SessionExtremeFadeStrategy(sessions="sydney")
    with pytest.raises(ValueError):
        SessionExtremeFadeStrategy(valid_for="forever")


def test_full_pipeline_run(tmp_path):
    import os
    import sys
    os.environ["MARKET_PREP_DB_URL"] = f"sqlite:///{tmp_path}/app.db"
    for mod in [m for m in list(sys.modules) if m.startswith("server")]:
        del sys.modules[mod]
    from libs.pipeline import PipelineConfig, run_pipeline
    rng = np.random.default_rng(3)
    idx = pd.date_range("2026-05-01", periods=45 * 96, freq="15min")
    c = 1.10 * np.exp(np.cumsum(rng.normal(0, 0.0004, len(idx))))
    o = np.concatenate([[c[0]], c[:-1]])
    folder = tmp_path / "FX:FADETEST"
    folder.mkdir()
    pd.DataFrame({"Open time": idx.strftime("%Y-%m-%d %H:%M:%S"),
                  "open": o, "high": np.maximum(o, c) * 1.0002,
                  "low": np.minimum(o, c) * 0.9998, "close": c}) \
        .to_csv(folder / "15m.csv", index=False)
    res = run_pipeline(PipelineConfig(
        asset="FADETEST", asset_class="FX", timeframe="15m",
        cost_symbol="EURUSD", strategy_cls=SessionExtremeFadeStrategy,
        strategy_params={"touch_k": 2.0},     # 4σ touches are rare on a walk
        marketdata_path=str(tmp_path) + "/", db_path=str(tmp_path) + "/",
    ))
    assert res.cost_summary["trades"] > 0
    assert "net_profit" in res.metrics
