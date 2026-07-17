"""MySQL backtest store, strategy-reports API, saved reports, band study."""
import importlib
import os
import sys
from datetime import date
from unittest import mock

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient


def _reload_server(tmp_path):
    os.environ["MARKET_PREP_DB_URL"] = f"sqlite:///{tmp_path}/test.db"
    for mod in [m for m in list(sys.modules) if m.startswith("server")]:
        del sys.modules[mod]


def _run_backtest(tmp_path, run_id="storetest"):
    from libs.pipeline import PipelineConfig, run_pipeline
    from strategies.session_sigma_strategy import SessionSigmaStrategy
    rng = np.random.default_rng(9)
    idx = pd.date_range("2026-05-01", periods=30 * 96, freq="15min")
    c = 1.10 * np.exp(np.cumsum(rng.normal(0, 0.0004, len(idx))))
    o = np.concatenate([[c[0]], c[:-1]])
    folder = tmp_path / "FX:EURUSD"
    folder.mkdir(exist_ok=True)
    pd.DataFrame({"Open time": idx.strftime("%Y-%m-%d %H:%M:%S"), "open": o,
                  "high": np.maximum(o, c) * 1.0002,
                  "low": np.minimum(o, c) * 0.9998, "close": c}) \
        .to_csv(folder / "15m.csv", index=False)
    return run_pipeline(PipelineConfig(
        asset="EURUSD", asset_class="FX", timeframe="15m", run_id=run_id,
        cost_symbol="EURUSD", strategy_cls=SessionSigmaStrategy,
        marketdata_path=str(tmp_path) + "/", db_path=str(tmp_path) + "/"))


def test_pipeline_persists_to_app_db_and_api_serves_it(tmp_path):
    _reload_server(tmp_path)
    res = _run_backtest(tmp_path)
    assert res.cost_summary["trades"] > 0

    from server.backtest_store import BacktestStore
    summary = BacktestStore().summary_table()
    assert list(summary["run_id"]) == ["storetest"]
    assert summary["net_profit"].iloc[0] is not None

    main = importlib.import_module("server.main")
    with TestClient(main.app) as c:
        runs = c.get("/api/strategy-reports").json()
        assert runs[0]["run_id"] == "storetest"
        assert runs[0]["n_trades"] > 0
        rep = c.get("/api/strategy-reports/storetest").json()
        assert len(rep["metrics"]) > 40
        assert len(rep["equity"]) > 1
        assert "exit_reasons" in rep["frames"]
        assert "costed" in rep["frames"]
        # pipeline metadata (class name) overrides the strategy's own label
        assert rep["metadata"]["strategy"] == "SessionSigmaStrategy"
        tr = c.get("/api/strategy-reports/storetest/trades?limit=5").json()
        assert tr["total"] > 0 and len(tr["rows"]) == 5
        assert "setup" in tr["rows"][0]["extra"]
        assert c.get("/api/strategy-reports/nope").status_code == 404
        # overwrite: re-running the same run_id replaces, not duplicates
    _run_backtest(tmp_path)
    assert len(BacktestStore().summary_table()) == 1


def test_legacy_resultstore_backend_still_works(tmp_path):
    _reload_server(tmp_path)
    from libs.pipeline import PipelineConfig, run_pipeline
    from strategies.session_sigma_strategy import SessionSigmaStrategy
    rng = np.random.default_rng(9)
    idx = pd.date_range("2026-05-01", periods=20 * 96, freq="15min")
    c = 1.10 * np.exp(np.cumsum(rng.normal(0, 0.0004, len(idx))))
    o = np.concatenate([[c[0]], c[:-1]])
    folder = tmp_path / "FX:LEG"
    folder.mkdir()
    pd.DataFrame({"Open time": idx.strftime("%Y-%m-%d %H:%M:%S"), "open": o,
                  "high": np.maximum(o, c) * 1.0002,
                  "low": np.minimum(o, c) * 0.9998, "close": c}) \
        .to_csv(folder / "15m.csv", index=False)
    res = run_pipeline(PipelineConfig(
        asset="LEG", asset_class="FX", timeframe="15m", cost_symbol="EURUSD",
        strategy_cls=SessionSigmaStrategy, store_backend="legacy",
        marketdata_path=str(tmp_path) + "/", db_path=str(tmp_path) + "/"))
    assert "net_profit" in res.metrics
    assert (tmp_path / "all_backtests.db").exists()   # old sqlite store


def test_saved_reports_roundtrip(tmp_path):
    _reload_server(tmp_path)
    main = importlib.import_module("server.main")
    with TestClient(main.app) as c:
        created = c.post("/api/saved-reports", json={
            "kind": "band_study", "title": "demo",
            "params": {"asset": "X"}, "payload": {"pairs": [1, 2]},
        })
        assert created.status_code == 201
        rid = created.json()["id"]
        lst = c.get("/api/saved-reports?kind=band_study").json()
        assert [r["id"] for r in lst] == [rid]
        got = c.get(f"/api/saved-reports/{rid}").json()
        assert got["payload"] == {"pairs": [1, 2]}
        assert c.delete(f"/api/saved-reports/{rid}").status_code == 204
        assert c.get(f"/api/saved-reports/{rid}").status_code == 404


def _synthetic_bars(days=120, seed=1):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2025-01-01", periods=days * 96, freq="15min")
    c = 1.1 * np.exp(np.cumsum(rng.normal(0, 0.0004, len(idx))))
    return pd.DataFrame({"Datetime": idx, "Open": c, "High": c * 1.0002,
                         "Low": c * 0.9998, "Close": c})


def test_band_study_structure():
    from server import band_behavior
    with mock.patch.object(band_behavior, "load_bars",
                           return_value=_synthetic_bars()):
        r = band_behavior.analyze_bands("T", "15m")
    assert len(r["band_labels"]) == 34
    assert len(r["pairs"]) == 4
    p = r["pairs"][0]
    assert abs(sum(p["A"]["probs"]) - 1) < 1e-6
    assert abs(sum(p["A"]["expected_probs"]) - 1) < 1e-6
    assert len(p["B_C"]) == 34 and len(p["D"]["matrix"]) == 34
    # survival curves are monotone non-increasing and start at ≥ touch info
    s = p["B_C"][17]["survival"]
    assert all(a >= b - 1e-12 for a, b in zip(s, s[1:]))
    # transition rows are probability vectors (or all zero); cells are
    # rounded to 4dp in the payload so allow that much slack
    for row in p["D"]["matrix"]:
        t = sum(row)
        assert t == pytest.approx(1.0, abs=0.005) or t == 0.0
    names = {t["name"] for t in p["F"]}
    assert any("Kolmogorov" in n for n in names)
    assert any("Anderson" in n for n in names)
    assert p["G"]["verdict"] in ("structured", "mixed", "noise-like")


def test_band_study_date_filter():
    from server import band_behavior
    df = _synthetic_bars(days=120)
    with mock.patch.object(band_behavior, "load_bars", return_value=df):
        r = band_behavior.analyze_bands("T", "15m",
                                        start=date(2025, 2, 1),
                                        end=date(2025, 3, 15))
    assert r["date_range"][0] >= "2025-02-01"
    assert r["date_range"][1] <= "2025-03-15"
