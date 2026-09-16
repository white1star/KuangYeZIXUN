from pathlib import Path

from fastapi.testclient import TestClient

from crawler import store
from web import app as web_app
from web.app import create_app


def _open_admin(monkeypatch):
    monkeypatch.setattr(web_app, "load_admin_config", lambda: None)


def seed(db):
    conn = store.connect(db)
    store.init_db(conn)
    store.upsert_source(conn, "mnr", "自然资源部要闻", "policy", "https://www.mnr.gov.cn/", True)
    run = store.start_crawl_run(conn, "mnr")
    store.finish_crawl_run(conn, run, "ok", 20, 5)
    conn.commit()
    conn.close()


def test_sources_page(tmp_path, monkeypatch):
    _open_admin(monkeypatch)
    db = tmp_path / "t.db"
    seed(db)
    client = TestClient(create_app(db))
    resp = client.get("/sources")
    assert resp.status_code == 200
    assert "自然资源部要闻" in resp.text
    assert "成功" in resp.text
    assert "数据源状态" in resp.text


def test_run_crawl_lock(tmp_path, monkeypatch):
    _open_admin(monkeypatch)
    db = tmp_path / "t.db"
    seed(db)
    started = []
    monkeypatch.setattr("subprocess.Popen", lambda *a, **k: started.append(a) or None)
    client = TestClient(create_app(db))
    resp = client.post("/admin/run_crawl")
    assert resp.status_code == 200
    assert started, "应启动抓取子进程"
    assert (db.parent / "crawl.lock").exists()
    resp2 = client.post("/admin/run_crawl")
    assert resp2.status_code == 409
    (db.parent / "crawl.lock").unlink()
