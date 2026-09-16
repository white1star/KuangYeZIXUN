from datetime import datetime

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
    conn.execute(
        "INSERT INTO prices(commodity,price_type,value,unit,change,change_pct,price_date,source_key,raw_label,fetched_at) "
        "VALUES('铜','期货',71000,'元/吨',100,0.14,?,?,'cu',?)",
        (datetime.now().strftime("%Y-%m-%d"), "sina", store.now_iso()))
    store.upsert_source(conn, "mnr", "自然资源部", "policy", "https://www.mnr.gov.cn/", True)
    run = store.start_crawl_run(conn, "mnr")
    store.finish_crawl_run(conn, run, "ok", 10, 3)
    conn.commit()
    conn.close()


def seed_multi_source_price(db):
    conn = store.connect(db)
    store.init_db(conn)
    day = datetime.now().strftime("%Y-%m-%d")
    for source_key, value in (("sina", 71000), ("ccmn", 71100)):
        conn.execute(
            "INSERT INTO prices(commodity,price_type,value,unit,change,change_pct,price_date,source_key,raw_label,fetched_at) "
            "VALUES('铜','期货',?,'元/吨',100,0.14,?,?,'cu',?)",
            (value, day, source_key, store.now_iso()))
    conn.commit()
    conn.close()


def seed_refreshed_price(db):
    conn = store.connect(db)
    store.init_db(conn)
    day = datetime.now().strftime("%Y-%m-%d")
    for source_key, value, fetched in (("sina", 71000, " 09:00:00"), ("ccmn", 71100, " 09:05:00")):
        conn.execute(
            "INSERT INTO prices(commodity,price_type,value,unit,change,change_pct,price_date,source_key,raw_label,fetched_at) "
            "VALUES('铜','期货',?,'元/吨',100,0.14,?,?,'cu',?)",
            (value, day, source_key, day + fetched))
    store.upsert_prices(conn, [{
        "commodity": "铜", "price_type": "期货", "value": 71050, "unit": "元/吨",
        "change": 100, "change_pct": 0.14, "price_date": day, "source_key": "sina",
        "raw_label": "cu", "fetched_at": day + " 09:10:00"}])
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
    assert "河北开展磷矿安全生产整治" in resp.text
    assert "矿价速览" in resp.text
    assert "铜" in resp.text


def test_index_price_multi_source_dedup(tmp_path):
    db = tmp_path / "t.db"
    seed_multi_source_price(db)
    client = TestClient(create_app(db))
    resp = client.get("/")
    assert resp.status_code == 200
    assert resp.text.count('class="num"') == 1
    assert "71100.0" in resp.text
    assert "71000.0" not in resp.text
    assert ">ccmn<" in resp.text
    assert ">sina<" not in resp.text


def test_index_price_refetched_wins(tmp_path):
    db = tmp_path / "t.db"
    seed_refreshed_price(db)
    client = TestClient(create_app(db))
    resp = client.get("/")
    assert resp.status_code == 200
    assert resp.text.count('class="num"') == 1
    assert "71050.0" in resp.text
    assert "71100.0" not in resp.text
    assert ">sina<" in resp.text
    assert ">ccmn<" not in resp.text
