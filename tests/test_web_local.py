import pytest
from fastapi.testclient import TestClient

from crawler import store
from web import app as web_app
from web.app import create_app


def seed(db):
    conn = store.connect(db)
    store.init_db(conn)
    conn.commit()
    conn.close()


def make_client(tmp_path):
    db = tmp_path / "t.db"
    seed(db)
    return TestClient(create_app(db))


def test_sources_open_from_localhost(tmp_path):
    client = make_client(tmp_path)
    resp = client.get("/sources")
    assert resp.status_code == 200
    assert "数据源状态" in resp.text


def test_sources_hidden_from_remote(tmp_path, monkeypatch):
    monkeypatch.setattr(web_app, "LOCAL_HOSTS", set())
    client = make_client(tmp_path)
    assert client.get("/sources").status_code == 404
    assert client.post("/admin/run_crawl").status_code == 404
    assert client.get("/admin/backup/now").status_code == 404
    assert client.get("/admin/logs/crawler_19000101.log").status_code == 404


def test_public_pages_unaffected(tmp_path, monkeypatch):
    monkeypatch.setattr(web_app, "LOCAL_HOSTS", set())
    client = make_client(tmp_path)
    assert client.get("/").status_code == 200
    assert client.get("/news").status_code == 200
    assert client.post("/feedback", json={"content": "员工反馈"}).status_code == 200
