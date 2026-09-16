import threading

import pytest
from fastapi.testclient import TestClient

from crawler import store
from web import notify
from web.app import create_app

FAKE_CONFIG = {
    "enabled": True,
    "smtp_host": "smtp.example.com",
    "smtp_port": 465,
    "sender": "a@example.com",
    "password": "x",
    "recipient": "b@example.com",
}


@pytest.fixture(autouse=True)
def fake_notify(monkeypatch):
    calls = []
    done = threading.Event()

    def fake_load(path=None):
        return FAKE_CONFIG

    def fake_send(content, contact="", page="", config=None):
        calls.append({"content": content, "contact": contact, "page": page, "config": config})
        done.set()
        return True

    monkeypatch.setattr(notify, "load_notify_config", fake_load)
    monkeypatch.setattr(notify, "send_feedback_email", fake_send)
    return calls, done


def make_client(tmp_path):
    db = tmp_path / "t.db"
    conn = store.connect(db)
    store.init_db(conn)
    store.upsert_source(conn, "mnr", "自然资源部要闻", "policy", "https://www.mnr.gov.cn/", True)
    run = store.start_crawl_run(conn, "mnr")
    store.finish_crawl_run(conn, run, "ok", 20, 5)
    conn.commit()
    conn.close()
    return db, TestClient(create_app(db))


def test_feedback_saved_and_shown(tmp_path):
    db, client = make_client(tmp_path)
    resp = client.post("/feedback", json={
        "content": "希望增加铜价走势图", "contact": "老王", "page": "/prices"})
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    conn = store.connect(db)
    row = conn.execute("SELECT content, contact, page, created_at FROM feedback").fetchone()
    conn.close()
    assert row["content"] == "希望增加铜价走势图"
    assert row["contact"] == "老王"
    assert row["page"] == "/prices"
    assert row["created_at"]
    page = client.get("/sources")
    assert page.status_code == 200
    assert "用户反馈" in page.text
    assert "希望增加铜价走势图" in page.text
    assert "老王" in page.text


def test_feedback_triggers_notify(tmp_path, fake_notify):
    calls, done = fake_notify
    _, client = make_client(tmp_path)
    resp = client.post("/feedback", json={
        "content": "通知测试", "contact": "小张", "page": "/news"})
    assert resp.status_code == 200
    assert done.wait(5)
    assert calls[0]["content"] == "通知测试"
    assert calls[0]["contact"] == "小张"
    assert calls[0]["page"] == "/news"
    assert calls[0]["config"]["enabled"] is True


def test_feedback_anonymous_shown(tmp_path):
    _, client = make_client(tmp_path)
    resp = client.post("/feedback", json={"content": "匿名反馈内容", "contact": "", "page": "/"})
    assert resp.status_code == 200
    page = client.get("/sources")
    assert "匿名" in page.text
    assert "匿名反馈内容" in page.text


def test_feedback_empty_content(tmp_path):
    _, client = make_client(tmp_path)
    resp = client.post("/feedback", json={"content": "   ", "contact": "", "page": "/"})
    assert resp.status_code == 400
    assert resp.json()["message"] == "内容不能为空"
    assert "暂无反馈" in client.get("/sources").text


def test_feedback_too_long(tmp_path):
    _, client = make_client(tmp_path)
    resp = client.post("/feedback", json={"content": "长" * 501, "contact": "", "page": "/"})
    assert resp.status_code == 400
    assert resp.json()["message"] == "内容太长（最多500字）"
