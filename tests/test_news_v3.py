"""Tests for the news v3 system: sources, roles, relationships, threads,
fuzzy search, story groups, and the to_watch → status migration."""
import importlib
import os
import sys

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


def _mk(client, title, **kw):
    payload = {"title": title, **kw}
    res = client.post("/api/news", json=payload)
    assert res.status_code == 201, res.text
    return res.json()


def test_sources_seeded_and_news_carries_source(client):
    sources = client.get("/api/sources").json()
    assert "Bloomberg" in {s["name"] for s in sources}
    bb = next(s for s in sources if s["name"] == "Bloomberg")
    n = _mk(client, "Fed cuts", source_id=bb["id"], role="primary")
    assert n["source"]["name"] == "Bloomberg"
    assert n["role"] == "primary"
    assert n["status"] == "close"          # default
    assert n["publish_time"] is not None


def test_relationship_chain_and_thread(client):
    a = _mk(client, "Original story", status="open")
    b = _mk(client, "Follow-up", role="update", parent_ids=[a["id"]])
    c = _mk(client, "Counterpoint", role="contradicting", parent_ids=[b["id"]])

    thread = client.get(f"/api/news/{c['id']}/thread").json()
    assert [x["title"] for x in thread["ancestors"]] == ["Original story", "Follow-up"]
    assert thread["parent_ids"] == [b["id"]]

    root = client.get(f"/api/news/{a['id']}/thread").json()
    assert root["tree"]["children"][0]["title"] == "Follow-up"
    assert root["tree"]["children"][0]["children"][0]["title"] == "Counterpoint"


def test_cycle_rejected(client):
    a = _mk(client, "A")
    b = _mk(client, "B", parent_ids=[a["id"]])
    res = client.patch(f"/api/news/{a['id']}", json={"parent_ids": [b["id"]]})
    assert res.status_code == 422
    self_ref = client.patch(f"/api/news/{a['id']}", json={"parent_ids": [a["id"]]})
    assert self_ref.status_code == 200      # self is silently dropped
    assert client.get(f"/api/news/{a['id']}/thread").json()["parent_ids"] == []


def test_watch_threads_fold_open_descendants(client):
    a = _mk(client, "Open root", status="open")
    b = _mk(client, "Closed middle", parent_ids=[a["id"]])
    c = _mk(client, "Open leaf", status="open", parent_ids=[b["id"]])

    watch = client.get("/api/news/watch").json()
    assert [w["title"] for w in watch] == ["Open root"]
    middle = watch[0]["children"][0]
    assert middle["title"] == "Closed middle"
    assert middle["children"][0]["title"] == "Open leaf"

    # closing the root promotes the still-open leaf to top level
    client.patch(f"/api/news/{a['id']}", json={"status": "close"})
    watch = client.get("/api/news/watch").json()
    assert [w["title"] for w in watch] == ["Open leaf"]
    assert c["id"] == watch[0]["id"]


def test_fuzzy_search_not_strict(client):
    _mk(client, "Powell speaks on inflation outlook")
    _mk(client, "ECB raises rates")
    hits = client.get("/api/news/search?q=powel inflation").json()
    assert hits and hits[0]["title"].startswith("Powell")
    hits = client.get("/api/news/search?q=ecb").json()
    assert hits and hits[0]["title"] == "ECB raises rates"


def test_groups_expand_recursively(client):
    a = _mk(client, "Root", role="primary")
    b = _mk(client, "Child", parent_ids=[a["id"]])
    _mk(client, "Lone story")

    from datetime import date
    today = date.today().isoformat()
    groups = client.get(f"/api/news/groups?start={today}&end={today}").json()
    assert len(groups) == 2
    linked = next(g for g in groups if len(g["news"]) == 2)
    assert linked["name"] == "Root"
    assert linked["edges"] == [[a["id"], b["id"]]]


def test_patch_edits_fields_and_relationships(client):
    a = _mk(client, "Parent one")
    b = _mk(client, "Parent two")
    n = _mk(client, "Story", parent_ids=[a["id"]])

    patched = client.patch(f"/api/news/{n['id']}", json={
        "title": "Story v2", "role": "supporting", "parent_ids": [b["id"]],
    }).json()
    assert patched["title"] == "Story v2"
    assert patched["role"] == "supporting"
    thread = client.get(f"/api/news/{n['id']}/thread").json()
    assert thread["parent_ids"] == [b["id"]]


def test_delete_removes_story_and_links_but_keeps_relatives(client):
    a = _mk(client, "Root", status="open")
    b = _mk(client, "Middle", parent_ids=[a["id"]])
    c = _mk(client, "Leaf", status="open", parent_ids=[b["id"]])

    assert client.delete(f"/api/news/{b['id']}").status_code == 204
    assert client.delete(f"/api/news/{b['id']}").status_code == 404

    # relatives survive; the broken chain just unlinks them
    root = client.get(f"/api/news/{a['id']}/thread").json()
    assert root["tree"]["children"] == []
    leaf = client.get(f"/api/news/{c['id']}/thread").json()
    assert leaf["ancestors"] == [] and leaf["parent_ids"] == []
    watch = {w["title"] for w in client.get("/api/news/watch").json()}
    assert watch == {"Root", "Leaf"}


def test_migration_backfills_status_from_to_watch(tmp_path):
    url = f"sqlite:///{tmp_path}/old.db"
    engine = create_engine(url)
    with engine.begin() as conn:   # v2-era news table with to_watch
        conn.execute(text(
            "CREATE TABLE news (id INTEGER PRIMARY KEY, title VARCHAR(300), "
            "body TEXT, to_watch BOOLEAN NOT NULL, created_at DATETIME)"))
        conn.execute(text(
            "INSERT INTO news (title, body, to_watch, created_at) VALUES "
            "('watched', '', 1, '2026-07-01 10:00:00'), "
            "('ignored', '', 0, '2026-07-01 11:00:00')"))

    os.environ["MARKET_PREP_DB_URL"] = url
    for mod in [m for m in list(sys.modules) if m.startswith("server")]:
        del sys.modules[mod]
    migrate_mod = importlib.import_module("server.migrate")
    db_mod = importlib.import_module("server.db")
    migrate_mod.migrate(db_mod.engine)

    cols = {c["name"] for c in inspect(db_mod.engine).get_columns("news")}
    assert {"status", "role", "publish_time", "source_id"} <= cols
    # the retired to_watch column is dropped so strict-mode INSERTs
    # (which no longer supply it) cannot fail with error 1364
    assert "to_watch" not in cols
    with db_mod.engine.connect() as conn:
        rows = dict(conn.execute(
            text("SELECT title, status FROM news")).fetchall())
        assert rows == {"watched": "open", "ignored": "close"}
        pt = conn.execute(text(
            "SELECT publish_time FROM news WHERE title='watched'")).scalar()
        assert pt is not None
    assert "news_relationships" in inspect(db_mod.engine).get_table_names()
    assert "sources" in inspect(db_mod.engine).get_table_names()
