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


def test_index_home_blocks(tmp_path):
    db = tmp_path / "t.db"
    seed(db)
    conn = store.connect(db)
    item = {"url": "https://e.com/2", "title": "内蒙古发现大型萤石矿", "summary": "探矿成果",
            "source_key": "mnr", "published_at": "2026-09-16"}
    cls = {"board": "policy", "minerals": ["萤石"], "regions": ["内蒙古"], "types": ["新矿"]}
    store.insert_article(conn, item, cls, "u2", "t2")
    item2 = {"url": "https://e.com/3", "title": "今日头条普通新闻", "summary": "行业动态",
             "source_key": "mnr", "published_at": "2026-09-16"}
    cls2 = {"board": "news", "minerals": [], "regions": [], "types": ["市场"]}
    store.insert_article(conn, item2, cls2, "u3", "t3")
    conn.commit()
    conn.close()
    client = TestClient(create_app(db))
    resp = client.get("/")
    assert resp.status_code == 200
    assert "新矿山动态" not in resp.text
    assert "今日要闻" not in resp.text
    assert "内蒙古发现大型萤石矿" not in resp.text
    assert "今日头条普通新闻" not in resp.text
    assert 'class="card entry-card"' in resp.text
    assert resp.text.count('class="card entry-card"') == 3
    assert resp.text.count("ec-arrow") == 3
    assert resp.text.count("ec-icon") == 3
    for title in ("新闻资讯", "矿价行情", "政策法规"):
        assert title in resp.text
    assert "每日行业动态与政策早知道" in resp.text
    assert "全品种价格与走势" in resp.text
    assert "国家与地方矿业政策" in resp.text
    assert "今日 <b>1</b> 条" in resp.text
    assert "<b>0</b> 个品种" in resp.text
    assert "热门搜索" in resp.text
    assert "探矿权" in resp.text
    assert "/?q=%E6%8E%A2%E7%9F%BF%E6%9D%83" in resp.text
    assert 'class="card stat-card"' in resp.text
    assert resp.text.count('class="card stat-card"') == 4
    assert "/news?type=%E6%96%B0%E7%9F%BF%E5%B1%B1" not in resp.text
