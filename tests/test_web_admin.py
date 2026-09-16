import base64

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


def make_client(tmp_path, monkeypatch, config):
    db = tmp_path / "t.db"
    seed(db)
    monkeypatch.setattr(web_app, "load_admin_config", lambda: config)
    return TestClient(create_app(db))


def _auth(user, pwd):
    token = base64.b64encode(f"{user}:{pwd}".encode("utf-8")).decode("ascii")
    return {"Authorization": f"Basic {token}"}


def test_sources_requires_password(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch, {"username": "admin", "password": "secret"})
    assert client.get("/sources").status_code == 401
    assert client.get("/sources", headers=_auth("admin", "wrong")).status_code == 401
    resp = client.get("/sources", headers=_auth("admin", "secret"))
    assert resp.status_code == 200
    assert "数据源状态" in resp.text


def test_admin_endpoints_require_password(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch, {"username": "admin", "password": "secret"})
    assert client.post("/admin/run_crawl").status_code == 401
    assert client.get("/admin/backup/now").status_code == 401
    assert client.get("/admin/logs/crawler_20260916.log").status_code == 401
    assert client.get("/admin/logs/crawler_19000101.log",
                      headers=_auth("admin", "secret")).status_code == 404


def test_feedback_is_public(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch, {"username": "admin", "password": "secret"})
    resp = client.post("/feedback", json={"content": "普通员工也能提交"})
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


def test_open_mode_without_config(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch, None)
    assert client.get("/sources").status_code == 200
