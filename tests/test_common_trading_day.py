"""Multi-asset charts must all show the same trading day, even when one
asset's data ends earlier (stale download, market holiday)."""
from datetime import date

import numpy as np
import pandas as pd
import pytest

from server import marketdata


def _write(root, asset, start, periods):
    idx = pd.date_range(start, periods=periods, freq="1h")
    close = 100 + np.arange(periods) * 0.5
    df = pd.DataFrame({
        "Open time": idx.strftime("%Y-%m-%d %H:%M:%S"),
        "open": close - 0.2, "high": close + 1.0,
        "low": close - 1.0, "close": close,
    })
    (root / asset).mkdir()
    df.to_csv(root / asset / "1h.csv", index=False)


@pytest.fixture
def store(tmp_path, monkeypatch):
    """FX runs through Friday 2026-07-10; IDX data ends Thursday 07-09."""
    monkeypatch.setattr(marketdata, "MARKET_DATA_DIR", tmp_path)
    marketdata._load.cache_clear()
    _write(tmp_path, "FX", "2026-07-08", 72)    # Wed..Fri
    _write(tmp_path, "IDX", "2026-07-08", 48)   # Wed..Thu
    return tmp_path


def test_common_day_is_min_across_assets(store):
    # Monday 07-13: FX alone would say Friday, IDX says Thursday
    day = marketdata.common_trading_day(["FX", "IDX"], "1h",
                                        as_of=date(2026, 7, 13))
    assert day == date(2026, 7, 9)
    # missing assets don't break the computation
    assert marketdata.common_trading_day(["FX", "IDX", "NOPE"], "1h",
                                         as_of=date(2026, 7, 13)) == date(2026, 7, 9)
    assert marketdata.common_trading_day(["NOPE"], "1h") is None


def test_charts_pin_all_assets_to_common_day(store):
    day = marketdata.common_trading_day(["FX", "IDX"], "1h",
                                        as_of=date(2026, 7, 13))
    for asset in ("FX", "IDX"):
        chart = marketdata.yesterday_chart(asset, "1h", day=day)
        assert chart["day"] == "2026-07-09"


def test_returns_share_one_day(store):
    out = marketdata.yesterday_log_returns(["FX", "IDX"], "1h",
                                           as_of=date(2026, 7, 13))
    assert out["day"] == "2026-07-09"
    assert {s["day"] for s in out["series"]} == {"2026-07-09"}
    assert {s["asset"] for s in out["series"]} == {"FX", "IDX"}


def test_pinned_day_without_bars_raises(store):
    with pytest.raises(ValueError):
        marketdata.yesterday_chart("IDX", "1h", day=date(2026, 7, 10))
