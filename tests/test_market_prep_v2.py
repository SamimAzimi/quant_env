"""Tests for the v2 features: countries, trade asset/prices, date selector,
history endpoints, and the additive schema migration."""
import importlib
import os
import sys
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text


@pytest.fixture
def client(tmp_path):
    os.environ["MARKET_PREP_DB_URL"] = f"sqlite:///{tmp_path}/test.db"
    for mod in [m for m in list(sys.modules) if m.startswith("server")]:
        del sys.modules[mod]
    main = importlib.import_module("server.main")
    with TestClient(main.app) as c:
        yield c


def _asset_id(client, ticker):
    for cat in client.get("/api/effects").json():
        for a in cat["assets"]:
            if a["ticker"] == ticker:
                return a["id"]
    raise AssertionError(f"{ticker} not seeded")


def test_countries_seeded_and_addable(client):
    names = {c["name"] for c in client.get("/api/countries").json()}
    assert {"United States", "Japan", "Eurozone"} <= names
    created = client.post("/api/countries", json={"name": "India"})
    assert created.status_code == 201
    again = client.post("/api/countries", json={"name": "India"}).json()
    assert again["id"] == created.json()["id"]


def test_econ_report_carries_country(client):
    us = next(c for c in client.get("/api/countries").json()
              if c["name"] == "United States")
    r = client.post("/api/econ-reports", json={
        "name": "CPI YoY", "country_id": us["id"],
        "forecast": "2.4%", "previous": "2.3%",
    })
    assert r.status_code == 201
    assert r.json()["country"]["name"] == "United States"


def test_trade_with_asset_and_prices(client):
    aid = _asset_id(client, "XAUUSD")
    t = client.post("/api/trades", json={
        "asset_id": aid, "entry_time": "2026-07-10T08:30:00Z",
        "entry_price": 2410.5, "entry_reason": "breakout",
    })
    assert t.status_code == 201
    body = t.json()
    assert body["asset"]["ticker"] == "XAUUSD"
    assert body["entry_price"] == 2410.5

    patched = client.patch(f"/api/trades/{body['id']}", json={
        "exit_time": "2026-07-10T12:00:00Z", "exit_price": 2422.0,
    }).json()
    assert patched["exit_price"] == 2422.0


def test_trades_date_selector(client):
    client.post("/api/trades", json={
        "entry_time": "2026-01-05T10:00:00Z", "entry_reason": "old trade",
        "exit_time": "2026-01-05T11:00:00Z",
    })
    on_day = client.get("/api/trades?date=2026-01-05").json()
    assert len(on_day) == 1
    off_day = client.get("/api/trades?date=2026-01-06").json()
    assert off_day == []


def test_trades_history_range(client):
    client.post("/api/trades", json={
        "entry_time": "2026-01-05T10:00:00Z", "entry_reason": "x",
    })
    hist = client.get("/api/trades/history?start=2026-01-01&end=2026-01-31").json()
    assert len(hist) == 1
    assert client.get(
        "/api/trades/history?start=2026-02-01&end=2026-02-28").json() == []


def test_news_history_filters(client):
    tag = client.post("/api/tags", json={"name": "OPEC"}).json()
    aid = _asset_id(client, "OIL")
    client.post("/api/news", json={
        "title": "Supply cut", "tag_ids": [tag["id"]], "effect_ids": [aid],
    })
    client.post("/api/news", json={"title": "Unrelated"})

    today = date.today().isoformat()
    base = f"/api/news/history?start={today}&end={today}"
    assert len(client.get(base).json()) == 2
    assert len(client.get(f"{base}&tag_id={tag['id']}").json()) == 1
    assert len(client.get(f"{base}&effect_id={aid}").json()) == 1
    assert client.get(f"{base}&tag_id={tag['id'] + 999}").json() == []


def test_vix_history_and_prev_day_date_param(client):
    client.post("/api/vix", json={"value": 15.0, "ts": "2026-07-08T20:00:00Z"})
    client.post("/api/vix", json={"value": 17.5, "ts": "2026-07-09T20:00:00Z"})
    client.post("/api/vix", json={"value": 19.0, "ts": "2026-07-10T08:00:00Z"})

    hist = client.get("/api/vix/history?start=2026-07-01&end=2026-07-31").json()
    assert [h["value"] for h in hist] == [15.0, 17.5, 19.0]

    # "tomorrow" view covers the previous day AND the selected day itself,
    # newest first — a same-morning recording wins over last evening's
    prev = client.get("/api/vix/previous-day?date=2026-07-09").json()
    assert [p["value"] for p in prev] == [17.5, 15.0]
    prev = client.get("/api/vix/previous-day?date=2026-07-10").json()
    assert [p["value"] for p in prev] == [19.0, 17.5]


def test_rate_probs_history_top_buckets(client):
    t1 = ("| Meeting Date | 325-350 | 350-375 | 375-400 | 400-425 |\n"
          "|---|---|---|---|---|\n"
          "| 29/04/2026 | 1.0% | 90.0% | 8.0% | 1.0% |")
    client.post("/api/rate-probs", json={"table": t1})
    t2 = t1.replace("90.0%", "85.0%").replace("8.0%", "13.0%")
    client.post("/api/rate-probs", json={"table": t2})

    hist = client.get("/api/rate-probs/history?buckets=2").json()
    assert hist["meeting_date"] == "2026-04-29"
    assert set(hist["buckets"]) == {"350-375", "375-400"}
    assert len(hist["series"]) == 2
    assert hist["series"][0]["probs"]["350-375"] == 90.0
    assert hist["series"][1]["probs"]["350-375"] == 85.0


def test_migration_adds_missing_columns(tmp_path):
    url = f"sqlite:///{tmp_path}/old.db"
    engine = create_engine(url)
    with engine.begin() as conn:   # v1-era trades table, no v2 columns
        conn.execute(text(
            "CREATE TABLE trades (id INTEGER PRIMARY KEY, "
            "entry_time DATETIME NOT NULL, entry_reason TEXT)"))

    os.environ["MARKET_PREP_DB_URL"] = url
    for mod in [m for m in list(sys.modules) if m.startswith("server")]:
        del sys.modules[mod]
    migrate_mod = importlib.import_module("server.migrate")
    db_mod = importlib.import_module("server.db")
    migrate_mod.migrate(db_mod.engine)

    cols = {c["name"] for c in inspect(db_mod.engine).get_columns("trades")}
    assert {"asset_id", "entry_price", "exit_price"} <= cols
    assert "countries" in inspect(db_mod.engine).get_table_names()
