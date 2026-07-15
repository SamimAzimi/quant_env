"""Asset behaviour statistics engine (overlap segments, σ-bands, matrix)."""
import importlib
import os
import sys
from datetime import date
from unittest import mock

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from server import asset_stats


def _synthetic(days=300, seed=1, london_drift=0.0):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2024-01-01", periods=days * 96, freq="15min")
    step = rng.normal(0, 0.0006, len(idx))
    if london_drift:
        step += (((idx.hour >= 7) & (idx.hour < 16)).astype(float)) * london_drift
    close = 100 * np.exp(np.cumsum(step))
    op = np.concatenate([[100.0], close[:-1]])
    hi = np.maximum(op, close) * (1 + np.abs(rng.normal(0, 0.0004, len(idx))))
    lo = np.minimum(op, close) * (1 - np.abs(rng.normal(0, 0.0004, len(idx))))
    return pd.DataFrame({"Datetime": idx, "Open": op, "High": hi,
                         "Low": lo, "Close": close})


def _analyze(df, **kw):
    with mock.patch.object(asset_stats, "load_bars", return_value=df):
        return asset_stats.analyze("TEST", "15m", **kw)


def test_bands_and_segments():
    r = _analyze(_synthetic())
    assert r["bands"] == [0.5, 1.0, 1.5, 2.0]
    # all overlap/session segments present
    for label in ["Tokyo", "Tokyo ∩ London", "London ∩ NY",
                  "New York ∖ London (after London)", "Full trading day"]:
        assert label in r["sessions"]
        s = r["sessions"][label]
        assert s["n"] > 0 and s["std"] > 0
        assert set(s["probs"]["up"]) == {"0.5", "1.0", "1.5", "2.0"}


def test_six_references_with_expected_triggers():
    r = _analyze(_synthetic())
    keys = {ref["key"]: ref for ref in r["references"]}
    assert set(keys) == {"tokyo_wo_london", "tokyo_x_london", "london_x_ny",
                         "london_wo_ny", "ov_tokyo_london", "ov_london_ny"}
    # Tokyo∖London fans out to two London triggers
    assert len(keys["tokyo_wo_london"]["triggers"]) == 2
    # the London∩NY overlap reference has an overnight continuation
    ov = keys["ov_london_ny"]["triggers"][0]
    assert ov["overnight"] is True


def test_matrix_is_valid_conditional_probability():
    r = _analyze(_synthetic())
    for ref in r["references"]:
        for trig in ref["triggers"]:
            for side in (trig["up"], trig["down"]):
                m = side["matrix"]
                assert len(m) == 4 and all(len(row) == 4 for row in m)
                for i in range(4):
                    for j in range(4):
                        v = m[i][j]
                        if v is not None:
                            assert 0 <= v <= 1
                        # reaching a nearer-or-equal band given breakout is certain-ish:
                        if j <= i and side["breakout_counts"][i] > 0:
                            assert v is None or v >= 0


def test_clean_segments_are_adjacent_and_bounded():
    r = _analyze(_synthetic())
    trig = r["references"][0]["triggers"][0]
    segs = trig["up"]["clean_segments"]
    assert [(s["from"], s["to"]) for s in segs] == [(0.5, 1.0), (1.0, 1.5), (1.5, 2.0)]
    for s in segs:
        if s["eff_mean"] is not None:
            assert 0 < s["eff_mean"] <= 1
            assert s["adverse_mean"] >= 0


def test_date_range_filter_narrows_sample():
    df = _synthetic(days=300)
    full = _analyze(df)
    sub = _analyze(df, start=date(2024, 3, 1), end=date(2024, 4, 30))
    assert sub["n_days"] < full["n_days"]
    assert sub["date_range"][0] >= "2024-03-01"
    assert sub["date_range"][1] <= "2024-04-30"


def test_available_range():
    with mock.patch.object(asset_stats, "load_bars", return_value=_synthetic(days=100)):
        rng = asset_stats.available_range("TEST", "15m")
    assert rng["n_days"] == 100
    assert rng["start"] == "2024-01-01"


def test_injected_london_drift_shows_in_distribution():
    r = _analyze(_synthetic(london_drift=0.0002, seed=3))
    assert r["sessions"]["London"]["mean"] > r["sessions"]["Tokyo"]["mean"]


@pytest.fixture
def client(tmp_path):
    os.environ["MARKET_PREP_DB_URL"] = f"sqlite:///{tmp_path}/test.db"
    for mod in [m for m in list(sys.modules) if m.startswith("server")]:
        del sys.modules[mod]
    main = importlib.import_module("server.main")
    with TestClient(main.app) as c:
        yield c


def test_endpoint_guards(client):
    assert client.get("/api/asset-stats?asset=FOO&tf=1d").status_code == 422
    assert client.get("/api/asset-stats?asset=NOPE&tf=15m").status_code == 404
    assert client.get("/api/asset-stats/range?asset=NOPE&tf=15m").status_code == 404
