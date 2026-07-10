"""Key-level and log-return computation on a synthetic two-day CSV store."""
from datetime import date

import numpy as np
import pandas as pd
import pytest

from server import marketdata


@pytest.fixture
def store(tmp_path, monkeypatch):
    """Two days of 1h bars for one asset under a temp MARKET_DATA_DIR."""
    monkeypatch.setattr(marketdata, "MARKET_DATA_DIR", tmp_path)
    marketdata._load.cache_clear()

    idx = pd.date_range("2026-07-08", periods=48, freq="1h")
    close = 100 + np.arange(48) * 0.5
    df = pd.DataFrame({
        "Open time": idx.strftime("%Y-%m-%d %H:%M:%S"),
        "open": close - 0.2,
        "high": close + 1.0,
        "low": close - 1.0,
        "close": close,
    })
    folder = tmp_path / "TEST"
    folder.mkdir()
    df.to_csv(folder / "1h.csv", index=False)
    return tmp_path


def test_last_trading_day_skips_today(store):
    df = marketdata.load_bars("TEST", "1h")
    assert marketdata.last_trading_day(df, today=date(2026, 7, 10)) == date(2026, 7, 9)
    # On a later date with no newer data, still resolves to the last data day
    assert marketdata.last_trading_day(df, today=date(2026, 7, 13)) == date(2026, 7, 9)


def test_key_levels_include_preday_and_sessions(store):
    df = marketdata.load_bars("TEST", "1h")
    levels = marketdata.key_levels(df, date(2026, 7, 9))
    by_label = {l["label"]: l["value"] for l in levels}

    # Pre-day = 2026-07-08: closes 100..111.5, high = close+1, low = close-1
    assert by_label["Pre-day High"] == pytest.approx(112.5)
    assert by_label["Pre-day Low"] == pytest.approx(99.0)

    # London session (07:00-16:00 UTC) on 07-09: bars 31..39 → high = close+1
    assert by_label["London High"] == pytest.approx(100 + 39 * 0.5 + 1)
    assert by_label["London Low"] == pytest.approx(100 + 31 * 0.5 - 1)

    # Sydney wraps midnight (21:00 → 06:00 next day); with only 2 days of
    # data it still produces a level from the 21:00-23:00 bars of day 2.
    assert "Sydney High" in by_label


def test_yesterday_chart_shape(store):
    chart = marketdata.yesterday_chart("TEST", "1h")
    assert chart["day"] == "2026-07-09"
    assert len(chart["bars"]) == 24
    assert {"time", "open", "high", "low", "close"} <= set(chart["bars"][0])
    assert any(l["kind"] == "preday" for l in chart["levels"])


def test_log_returns_cumulative(store):
    out = marketdata.yesterday_log_returns(["TEST", "MISSING"], "1h")
    assert len(out["series"]) == 1
    pts = out["series"][0]["points"]
    assert pts[0]["value"] == 0.0
    expected = float(np.log((100 + 47 * 0.5) / (100 + 24 * 0.5)) * 100)
    assert pts[-1]["value"] == pytest.approx(expected, abs=1e-3)
