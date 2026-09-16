from fastapi.testclient import TestClient

from crawler import store
from web.app import create_app


def seed(db):
    conn = store.connect(db)
    store.init_db(conn)
    rows = [
        ("河北开展磷矿安全生产整治", "policy", ["磷矿"], ["河北"], ["政策"]),
        ("云南铜矿项目投产", "news", ["铜"], ["云南"], ["企业"]),
        ("今日铜价小幅上涨", "news", ["铜"], [], ["价格"]),
        ("铁矿石港口库存下降", "news", ["铁矿石"], [], ["市场"]),
    ]
    for i, (title, board, minerals, regions, types) in enumerate(rows):
        item = {"url": f"https://e.com/{i}", "title": title, "summary": title + "的摘要",
                "source_key": "mnr", "published_at": "2026-09-15"}
        cls = {"board": board, "minerals": minerals, "regions": regions, "types": types}
        store.insert_article(conn, item, cls, f"u{i}", f"t{i}")
    store.upsert_prices(conn, [{"commodity": "黄金", "price_type": "现货", "value": 560.0,
                                "price_date": "2026-09-15", "source_key": "sina"}])
    conn.commit()
    conn.close()


def test_policy_page_filters_region(tmp_path):
    db = tmp_path / "t.db"
    seed(db)
    client = TestClient(create_app(db))
    resp = client.get("/policy?region=河北")
    assert resp.status_code == 200
    assert "河北开展磷矿安全生产整治" in resp.text
    assert "云南铜矿项目投产" not in resp.text


def test_news_page_lists_only_news(tmp_path):
    db = tmp_path / "t.db"
    seed(db)
    client = TestClient(create_app(db))
    resp = client.get("/news")
    assert resp.status_code == 200
    assert "云南铜矿项目投产" in resp.text
    assert "今日铜价小幅上涨" in resp.text
    assert "铁矿石港口库存下降" in resp.text
    assert "河北开展磷矿安全生产整治" not in resp.text
    assert 'href="/news?mineral=煤炭"' in resp.text


def test_news_page_filters_mineral(tmp_path):
    db = tmp_path / "t.db"
    seed(db)
    client = TestClient(create_app(db))
    resp = client.get("/news?mineral=铜")
    assert "云南铜矿项目投产" in resp.text
    assert "今日铜价小幅上涨" in resp.text
    assert "铁矿石港口库存下降" not in resp.text
    assert "河北开展磷矿安全生产整治" not in resp.text
    resp2 = client.get("/news?mineral=铁矿石")
    assert "铁矿石港口库存下降" in resp2.text
    assert "云南铜矿项目投产" not in resp2.text
