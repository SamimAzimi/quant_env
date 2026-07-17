"""Day-over-day + quant character engine."""
import importlib
import json
import math
import os
import sys
from datetime import date
from unittest import mock

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from server import quant_stats


def _synthetic(days=400, seed=2, drift=0.00002):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2023-01-01", periods=days * 96, freq="15min")
    step = rng.normal(drift, 0.0006, len(idx))
    close = 100 * np.exp(np.cumsum(step))
    op = np.concatenate([[100.0], close[:-1]])
    hi = np.maximum(op, close) * (1 + np.abs(rng.normal(0, 0.0004, len(idx))))
    lo = np.minimum(op, close) * (1 - np.abs(rng.normal(0, 0.0004, len(idx))))
    return pd.DataFrame({"Datetime": idx, "Open": op, "High": hi,
                         "Low": lo, "Close": close})


def _analyze(df, **kw):
    with mock.patch.object(quant_stats, "load_bars", return_value=df):
        return quant_stats.analyze("TEST", "15m", **kw)


def test_daily_distribution_and_continuation():
    r = _analyze(_synthetic())
    dd = r["daily_distribution"]
    assert dd["n"] > 100 and dd["std"] > 0
    ic = r["intraday_continuation"]
    assert ic["n_days"] > 100
    assert len(ic["up"]["matrix"]) == 8


def test_day_to_day_four_buckets():
    r = _analyze(_synthetic())
    keys = {s["key"] for s in r["day_to_day"]}
    assert keys == {"strong_up", "mild_up", "mild_down", "strong_down"}
    for s in r["day_to_day"]:
        if s["n"] > 0:
            assert 0 <= s["p_next_up"] <= 1


def test_gaps_and_streaks():
    r = _analyze(_synthetic())
    g = r["gaps"]
    assert 0 <= g["p_gap_up"] <= 1
    assert 0 <= g["fill_prob_up"] <= 1
    s = r["streaks"]
    assert 0 <= s["p_up"] <= 1
    assert s["longest_up"] >= 1 and s["longest_down"] >= 1


def test_performance_ratios():
    r = _analyze(_synthetic())
    p = r["performance"]
    for k in ("sharpe", "sortino", "calmar", "max_drawdown", "var_95",
              "cvar_95", "profit_factor", "win_rate", "tail_ratio"):
        assert k in p
    assert p["max_drawdown"] <= 0
    assert 0 <= p["win_rate"] <= 1
    # CVaR is at least as extreme as VaR
    assert p["cvar_95"] >= p["var_95"] - 1e-9


def test_character_present_when_scipy_available():
    r = _analyze(_synthetic())
    ch = r["character"]
    if "note" not in ch:
        # the FULL market_metrics dict, the text report, and the desk cards
        mm = ch["market_metrics"]
        for block in ("meta", "distribution", "volatility", "mean_reversion",
                      "sessions", "calendar", "probability", "regimes"):
            assert block in mm
        assert "hurst_rs" in mm["mean_reversion"]
        assert mm["mean_reversion"]["verdict"] is not None
        assert "DISTRIBUTION CARD" in ch["desk_card"]["distribution"]["text"]
        assert "VOLATILITY CARD" in ch["desk_card"]["volatility"]["text"]
        assert isinstance(ch["character_report"], str) and ch["character_report"]


def test_payload_is_strict_json_no_nan():
    r = _analyze(_synthetic())
    # must serialize with allow_nan=False (no NaN/Inf leaked to the client)
    json.dumps(r, allow_nan=False)


def test_date_range_filter():
    df = _synthetic(days=400)
    sub = _analyze(df, start=date(2023, 2, 1), end=date(2023, 3, 31))
    assert sub["date_range"][0] >= "2023-02-01"
    assert sub["date_range"][1] <= "2023-03-31"


def test_finite_helper():
    assert quant_stats._finite(float("nan")) is None
    assert quant_stats._finite({"a": math.inf, "b": [1.0, float("nan")]}) == {"a": None, "b": [1.0, None]}


@pytest.fixture
def client(tmp_path):
    os.environ["MARKET_PREP_DB_URL"] = f"sqlite:///{tmp_path}/test.db"
    for mod in [m for m in list(sys.modules) if m.startswith("server")]:
        del sys.modules[mod]
    main = importlib.import_module("server.main")
    with TestClient(main.app) as c:
        yield c


def test_endpoint_guards(client):
    assert client.get("/api/quant-stats?asset=FOO&tf=1d").status_code == 422
    assert client.get("/api/quant-stats?asset=NOPE&tf=15m").status_code == 404
    assert client.get("/api/quant-stats/range?asset=NOPE&tf=15m").status_code == 404
