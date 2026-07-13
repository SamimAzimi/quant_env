"""DST alignment of sessions (via libs/market_sessions.py) and the macro
selected-date filter."""
import importlib
import os
import sys
from datetime import date

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from server import marketdata


def _spans(day):
    return {(s["name"], pd.Timestamp(s["start"], unit="s"),
             pd.Timestamp(s["end"], unit="s"))
            for s in marketdata.session_spans(day)}


def test_summer_sessions_utc_footprint():
    # 2026-07-09: BST (UTC+1), EDT (UTC-4), AEST (UTC+10), JST (UTC+9)
    day = date(2026, 7, 9)
    start, end = marketdata.day_window(day)
    assert start == pd.Timestamp("2026-07-09 00:00")   # Tokyo 09:00 JST
    assert end == pd.Timestamp("2026-07-09 21:00")     # NY 17:00 EDT
    spans = _spans(day)
    assert ("London", pd.Timestamp("2026-07-09 07:00"),
            pd.Timestamp("2026-07-09 16:00")) in spans
    assert ("New York", pd.Timestamp("2026-07-09 12:00"),
            pd.Timestamp("2026-07-09 21:00")) in spans


def test_winter_sessions_shift_with_dst():
    # 2026-01-08: GMT (UTC+0), EST (UTC-5), AEDT (UTC+11)
    day = date(2026, 1, 8)
    start, end = marketdata.day_window(day)
    assert start == pd.Timestamp("2026-01-08 00:00")   # JST never shifts
    assert end == pd.Timestamp("2026-01-08 22:00")     # NY close moved 1h
    spans = _spans(day)
    assert ("London", pd.Timestamp("2026-01-08 08:00"),
            pd.Timestamp("2026-01-08 17:00")) in spans
    assert ("New York", pd.Timestamp("2026-01-08 13:00"),
            pd.Timestamp("2026-01-08 22:00")) in spans
    # Sydney on AEDT (+11): the evening session start enters the window
    assert ("Sydney", pd.Timestamp("2026-01-08 20:00"),
            pd.Timestamp("2026-01-08 22:00")) in spans


def test_weekend_anchors_are_skipped():
    # 2026-07-13 is a Monday: no Sunday-anchored sessions leak in
    for span in marketdata.session_spans(date(2026, 7, 13)):
        start = pd.Timestamp(span["start"], unit="s")
        assert start >= pd.Timestamp("2026-07-13 00:00")


@pytest.fixture
def winter_store(tmp_path, monkeypatch):
    """Two winter days of 1h bars, to exercise the DST-shifted window."""
    monkeypatch.setattr(marketdata, "MARKET_DATA_DIR", tmp_path)
    marketdata._load.cache_clear()
    idx = pd.date_range("2026-01-07", periods=48, freq="1h")
    close = 100 + np.arange(48) * 0.5
    df = pd.DataFrame({
        "Open time": idx.strftime("%Y-%m-%d %H:%M:%S"),
        "open": close - 0.2, "high": close + 1.0,
        "low": close - 1.0, "close": close,
    })
    (tmp_path / "WTEST").mkdir()
    df.to_csv(tmp_path / "WTEST" / "1h.csv", index=False)
    return tmp_path


def test_winter_chart_uses_22h_window_and_gmt_levels(winter_store):
    chart = marketdata.yesterday_chart("WTEST", "1h", as_of=date(2026, 1, 9))
    assert chart["day"] == "2026-01-08"
    assert len(chart["bars"]) == 22            # 00:00-22:00 UTC in winter
    by_label = {l["label"]: l["value"] for l in chart["levels"]}
    # London on GMT: bars 32..40 (08:00-17:00 UTC of 01-08)
    assert by_label["London High"] == pytest.approx(100 + 40 * 0.5 + 1)
    assert by_label["London Low"] == pytest.approx(100 + 32 * 0.5 - 1)
    assert {s["name"] for s in chart["sessions"]} == {
        "Sydney", "Tokyo", "London", "New York"}


@pytest.fixture
def client(tmp_path):
    os.environ["MARKET_PREP_DB_URL"] = f"sqlite:///{tmp_path}/test.db"
    for mod in [m for m in list(sys.modules) if m.startswith("server")]:
        del sys.modules[mod]
    main = importlib.import_module("server.main")
    with TestClient(main.app) as c:
        yield c


def test_econ_reports_selected_day_plus_pending(client):
    today = date.today().isoformat()
    client.post("/api/econ-reports", json={"name": "Today CPI"})
    done = client.post("/api/econ-reports", json={
        "name": "Old done NFP", "actual": "200k", "outcome": "beat"}).json()
    pending = client.post("/api/econ-reports", json={"name": "Old pending PMI"}).json()
    # backdate the two "old" reports via direct DB access
    import server.db as db_mod
    from server.models import EconReport
    from datetime import datetime
    with db_mod.SessionLocal() as s:
        for rid in (done["id"], pending["id"]):
            s.get(EconReport, rid).created_at = datetime(2026, 1, 5, 9, 0)
        s.commit()

    names = {r["name"] for r in client.get("/api/econ-reports").json()}
    assert names == {"Today CPI", "Old pending PMI"}   # pending survives, done doesn't

    old_day = {r["name"] for r in
               client.get("/api/econ-reports?date=2026-01-05").json()}
    assert old_day == {"Old done NFP", "Old pending PMI"}

    assert {r["name"] for r in client.get(f"/api/econ-reports?date={today}").json()} \
        == {"Today CPI", "Old pending PMI"}
