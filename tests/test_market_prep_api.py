"""API tests for the Market Preparation backend, on a temp SQLite DB."""
import importlib
import os
import sys

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path):
    os.environ["MARKET_PREP_DB_URL"] = f"sqlite:///{tmp_path}/test.db"
    # server.db reads the env at import time — reload the chain for isolation
    for mod in [m for m in list(sys.modules) if m.startswith("server")]:
        del sys.modules[mod]
    main = importlib.import_module("server.main")
    with TestClient(main.app) as c:
        yield c


def test_seeded_tags_and_effects(client):
    tags = {t["name"] for t in client.get("/api/tags").json()}
    assert {"AI", "Tariffs", "Geopolitics"} <= tags

    cats = client.get("/api/effects").json()
    by_name = {c["name"]: c for c in cats}
    assert by_name["Commodities"]["kind"] == "hard"
    assert by_name["Forex"]["kind"] == "soft"
    forex = {a["ticker"] for a in by_name["Forex"]["assets"]}
    assert "USDJPY" in forex
    crypto = {a["ticker"] for a in by_name["Crypto"]["assets"]}
    assert "BTCUSDT" in crypto


def test_news_roundtrip_with_tags_effects_and_watch(client):
    tag = client.post("/api/tags", json={"name": "China"}).json()
    forex = next(c for c in client.get("/api/effects").json() if c["name"] == "Forex")
    asset_id = forex["assets"][0]["id"]

    created = client.post("/api/news", json={
        "title": "Tariff shock", "body": "details",
        "tag_ids": [tag["id"]], "effect_ids": [asset_id], "status": "open",
    })
    assert created.status_code == 201
    news = created.json()
    assert [t["name"] for t in news["tags"]] == ["China"]
    assert len(news["effects"]) == 1
    assert news["status"] == "open"

    assert len(client.get("/api/news/today").json()) == 1
    assert len(client.get("/api/news/watch").json()) == 1

    # closing removes it from the watch list but keeps the news
    client.patch(f"/api/news/{news['id']}", json={"status": "close"})
    assert client.get("/api/news/watch").json() == []
    assert len(client.get("/api/news/today").json()) == 1


def test_duplicate_tag_is_idempotent(client):
    a = client.post("/api/tags", json={"name": "Energy"}).json()
    b = client.post("/api/tags", json={"name": "Energy"}).json()
    assert a["id"] == b["id"]


def test_trade_entry_then_exit_edit(client):
    created = client.post("/api/trades", json={
        "entry_time": "2026-07-10T08:30:00Z",
        "entry_reason": "ORB breakout", "tp": 1.25, "sl": 1.10,
    })
    assert created.status_code == 201
    trade = created.json()
    assert trade["exit_time"] is None
    # open trades are always listed
    assert any(t["id"] == trade["id"] for t in client.get("/api/trades").json())

    patched = client.patch(f"/api/trades/{trade['id']}", json={
        "exit_time": "2026-07-10T11:00:00Z", "exit_reason": "TP hit",
    }).json()
    assert patched["exit_time"].startswith("2026-07-10T11:00")
    assert patched["exit_reason"] == "TP hit"


def test_fear_greed_validation(client):
    assert client.post("/api/fear-greed", json={"value": 130}).status_code == 422
    assert client.post("/api/fear-greed", json={"value": 55}).status_code == 201


def test_econ_report_outcome_edit(client):
    r = client.post("/api/econ-reports", json={
        "name": "NFP", "forecast": "180k", "previous": "175k",
    }).json()
    assert r["outcome"] is None
    assert len(client.get("/api/econ-reports?pending=true").json()) == 1

    patched = client.patch(f"/api/econ-reports/{r['id']}",
                           json={"actual": "210k", "outcome": "beat"}).json()
    assert patched["outcome"] == "beat"
    assert client.get("/api/econ-reports?pending=true").json() == []


def test_rate_probs_snapshot_and_latest(client):
    table = ("| Meeting Date | 350-375 | 375-400 |\n"
             "|---|---|---|\n"
             "| 29/04/2026 | 93.8% | 6.2% |")
    snap = client.post("/api/rate-probs", json={"table": table})
    assert snap.status_code == 201
    assert len(snap.json()["probs"]) == 2

    latest = client.get("/api/rate-probs/latest").json()
    assert latest["probs"][0]["bucket"] == "350-375"

    bad = client.post("/api/rate-probs", json={"table": "| nope |"})
    assert bad.status_code == 422


def test_stats_endpoints_respond(client):
    meta = client.get("/api/stats/assets").json()
    assert meta["default_charts"] == ["NDX", "XAUUSD", "XAGUSD", "USDJPY", "EURUSD"]
    assert client.get("/api/stats/charts?tf=15m").status_code == 200
    assert client.get("/api/stats/charts?tf=7m").status_code == 422
