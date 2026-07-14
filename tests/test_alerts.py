"""Scheduled alerts: CRUD, UTC storage, and the send-then-delete dispatch."""
import asyncio
import importlib
import os
import sys

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def server_mods(tmp_path):
    os.environ["MARKET_PREP_DB_URL"] = f"sqlite:///{tmp_path}/test.db"
    for mod in [m for m in list(sys.modules) if m.startswith("server")]:
        del sys.modules[mod]
    main = importlib.import_module("server.main")
    scheduler = importlib.import_module("server.scheduler")
    return main, scheduler


@pytest.fixture
def client(server_mods):
    main, _ = server_mods
    with TestClient(main.app) as c:
        yield c


def test_alert_crud_and_utc_conversion(client):
    created = client.post("/api/alerts", json={
        "due_time": "2026-07-14T09:30:00+02:00",   # local offset → UTC
        "message": "CPI in 15 minutes",
    })
    assert created.status_code == 201
    alert = created.json()
    assert alert["due_time"].startswith("2026-07-14T07:30")

    patched = client.patch(f"/api/alerts/{alert['id']}", json={
        "message": "CPI in 10 minutes",
    }).json()
    assert patched["message"] == "CPI in 10 minutes"

    assert len(client.get("/api/alerts").json()) == 1
    assert client.delete(f"/api/alerts/{alert['id']}").status_code == 204
    assert client.get("/api/alerts").json() == []


def test_dispatch_sends_due_and_deletes_only_on_success(server_mods, client):
    _, scheduler = server_mods
    client.post("/api/alerts", json={
        "due_time": "2020-01-01T00:00:00Z", "message": "overdue one"})
    client.post("/api/alerts", json={
        "due_time": "2099-01-01T00:00:00Z", "message": "far future"})

    sent = []

    async def fake_send(text):
        sent.append(text)
        return True

    scheduler.send_alert = fake_send
    asyncio.run(scheduler.dispatch_due_alerts())
    assert len(sent) == 1 and "overdue one" in sent[0]
    remaining = client.get("/api/alerts").json()
    assert [a["message"] for a in remaining] == ["far future"]

    # unconfigured/failed send keeps the alert queued for retry
    client.post("/api/alerts", json={
        "due_time": "2020-01-01T00:00:00Z", "message": "retry me"})

    async def fake_send_fail(text):
        return False

    scheduler.send_alert = fake_send_fail
    asyncio.run(scheduler.dispatch_due_alerts())
    assert {a["message"] for a in client.get("/api/alerts").json()} \
        == {"far future", "retry me"}
