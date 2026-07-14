"""Asset behaviour statistics engine + endpoint."""
import importlib
import os
import sys
from unittest import mock

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from server import asset_stats


def _synthetic(days=300, bars_per_day=96, seed=1, london_drift=0.0):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2024-01-01", periods=days * bars_per_day, freq="15min")
    step = rng.normal(0, 0.0006, len(idx))
    if london_drift:
        step += (((idx.hour >= 7) & (idx.hour < 16)).astype(float)) * london_drift
    close = 100 * np.exp(np.cumsum(step))
    op = np.concatenate([[100.0], close[:-1]])
    hi = np.maximum(op, close) * (1 + np.abs(rng.normal(0, 0.0004, len(idx))))
    lo = np.minimum(op, close) * (1 - np.abs(rng.normal(0, 0.0004, len(idx))))
    return pd.DataFrame({"Datetime": idx, "Open": op, "High": hi,
                         "Low": lo, "Close": close})


def _analyze(df):
    with mock.patch.object(asset_stats, "load_bars", return_value=df):
        return asset_stats.analyze("TEST", "15m")


def test_report_structure_and_sessions():
    r = _analyze(_synthetic())
    assert r["n_days"] == 300
    assert set(r["sessions"]) == {"Tokyo", "London", "New York"}
    for s in r["sessions"].values():
        assert s["n"] > 0
        assert "mean" in s and "std" in s and s["std"] > 0
        assert set(s["bands"]) == {"up1", "up2", "dn1", "dn2"}
        assert s["bands"]["up2"] > s["bands"]["up1"] > s["bands"]["dn1"] > s["bands"]["dn2"]
        assert len(s["hist"]["counts"]) + 1 == len(s["hist"]["edges"])


def test_transitions_have_conditional_probabilities():
    r = _analyze(_synthetic())
    pairs = {(t["reference"], t["trigger"]) for t in r["transitions"]}
    assert pairs == {("Tokyo", "London"), ("London", "New York"),
                     ("New York", "London")}
    for t in r["transitions"]:
        for side in (t["up"], t["down"]):
            assert 0 <= side["p_breakout"] <= 1
            # P(target | breakout) is a valid conditional probability
            if side["p_target_given_breakout"] is not None:
                assert 0 <= side["p_target_given_breakout"] <= 1
            # never more targets than breakouts among conditioned days
            assert side["clean"]["n"] <= side["n_breakout"]
            if side["clean"]["eff_mean"] is not None:
                assert 0 < side["clean"]["eff_mean"] <= 1


def test_overnight_transition_pairs_next_day():
    r = _analyze(_synthetic())
    ny_london = next(t for t in r["transitions"]
                     if (t["reference"], t["trigger"]) == ("New York", "London"))
    assert ny_london["overnight"] is True
    # one fewer usable day than same-day pairs (last NY has no next London)
    assert ny_london["up"]["n_days"] <= r["n_days"]


def test_daily_study_bands_and_day_to_day():
    r = _analyze(_synthetic())
    d = r["daily"]
    assert d["n"] == 300
    assert d["bands"]["up1"] < d["bands"]["up2"]
    assert "intraday" in d and "day_to_day" in d
    for cond in d["day_to_day"].values():
        if cond["n"] > 0:
            assert 0 <= cond["p_next_up"] <= 1


def test_injected_london_drift_shows_in_distribution():
    # a strong positive London drift should raise London's mean well above 0
    r = _analyze(_synthetic(london_drift=0.0002, seed=3))
    assert r["sessions"]["London"]["mean"] > r["sessions"]["Tokyo"]["mean"]
    assert r["sessions"]["London"]["probs"]["p_up"] > 0.6


def test_insufficient_data_raises():
    tiny = _synthetic(days=1, bars_per_day=10)
    with pytest.raises(ValueError):
        _analyze(tiny.head(20))


@pytest.fixture
def client(tmp_path):
    os.environ["MARKET_PREP_DB_URL"] = f"sqlite:///{tmp_path}/test.db"
    for mod in [m for m in list(sys.modules) if m.startswith("server")]:
        del sys.modules[mod]
    main = importlib.import_module("server.main")
    with TestClient(main.app) as c:
        yield c


def test_endpoint_validates_timeframe_and_missing_data(client):
    assert client.get("/api/asset-stats?asset=FOO&tf=1d").status_code == 422
    assert client.get("/api/asset-stats?asset=NOPE&tf=15m").status_code == 404
