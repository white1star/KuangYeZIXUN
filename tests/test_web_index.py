from fastapi.testclient import TestClient

from crawler import store
from web.app import create_app


def seed(db):
    conn = store.connect(db)
    store.init_db(conn)
    item = {"url": "https://e.com/1", "title": "河北开展磷矿安全生产整治", "summary": "摘要文字",
            "source_key": "mnr", "published_at": "2026-09-15"}
    cls = {"board": "policy", "minerals": ["磷矿"], "regions": ["河北"], "types": ["政策"]}
    store.insert_article(conn, item, cls, "u1", "t1")
    store.upsert_source(conn, "mnr", "自然资源部", "policy", "https://www.mnr.gov.cn/", True)
    run = store.start_crawl_run(conn, "mnr")
    store.finish_crawl_run(conn, run, "ok", 10, 3)
    conn.commit()
    conn.close()


def test_healthz(tmp_path):
    client = TestClient(create_app(tmp_path / "t.db"))
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


def test_index_renders(tmp_path):
    db = tmp_path / "t.db"
    seed(db)
    client = TestClient(create_app(db))
    resp = client.get("/")
    assert resp.status_code == 200
    assert "今日新增" in resp.text
    assert "搜索" in resp.text
    assert "新闻资讯" in resp.text
    assert "今日行情" not in resp.text
    assert "price-card" not in resp.text


def test_index_search_hits(tmp_path):
    db = tmp_path / "t.db"
    seed(db)
    client = TestClient(create_app(db))
    resp = client.get("/?q=磷矿")
    assert resp.status_code == 200
    assert "河北开展磷矿安全生产整治" in resp.text
    assert "共" in resp.text


def test_index_search_empty(tmp_path):
    db = tmp_path / "t.db"
    seed(db)
    client = TestClient(create_app(db))
    resp = client.get("/?q=不存在词")
    assert resp.status_code == 200
    assert "没有找到匹配内容" in resp.text
