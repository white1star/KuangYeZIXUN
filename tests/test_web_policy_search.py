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
        ("智能矿山无人驾驶试点", "news", ["煤炭"], [], ["技术"]),
        ("矿区安全应急演练完成", "news", ["磷矿"], [], ["安全"]),
        ("内蒙古新发现大型萤石矿", "news", ["萤石"], ["内蒙古"], ["新矿"]),
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
    assert "智能矿山无人驾驶试点" in resp.text
    assert "矿区安全应急演练完成" in resp.text
    assert "内蒙古新发现大型萤石矿" in resp.text
    assert "河北开展磷矿安全生产整治" not in resp.text
    assert 'href="/news?type=新矿山"' in resp.text
    assert 'href="/news?type=行情"' in resp.text
    assert 'href="/news?type=技术"' in resp.text
    assert 'class="pill active" href="/news">全部</a>' in resp.text
    order = [resp.text.index(f'href="/news?type={t}"') for t in ("新矿山", "行情", "技术", "企业", "安全")]
    assert order == sorted(order)


def test_news_page_filters_new_mine(tmp_path):
    db = tmp_path / "t.db"
    seed(db)
    client = TestClient(create_app(db))
    resp = client.get("/news?type=新矿山")
    assert resp.status_code == 200
    assert "内蒙古新发现大型萤石矿" in resp.text
    assert "云南铜矿项目投产" not in resp.text
    assert "今日铜价小幅上涨" not in resp.text
    assert "铁矿石港口库存下降" not in resp.text
    assert "智能矿山无人驾驶试点" not in resp.text
    assert "矿区安全应急演练完成" not in resp.text
    assert "河北开展磷矿安全生产整治" not in resp.text
    assert 'class="pill active" href="/news?type=新矿山">新矿山</a>' in resp.text


def test_news_page_filters_type(tmp_path):
    db = tmp_path / "t.db"
    seed(db)
    client = TestClient(create_app(db))
    resp = client.get("/news?type=技术")
    assert "智能矿山无人驾驶试点" in resp.text
    assert "矿区安全应急演练完成" not in resp.text
    assert "今日铜价小幅上涨" not in resp.text
    assert "河北开展磷矿安全生产整治" not in resp.text
    assert 'class="pill active" href="/news?type=技术">技术</a>' in resp.text
    resp2 = client.get("/news?type=行情")
    assert "今日铜价小幅上涨" in resp2.text
    assert "铁矿石港口库存下降" in resp2.text
    assert "智能矿山无人驾驶试点" not in resp2.text
    assert "云南铜矿项目投产" not in resp2.text
    resp3 = client.get("/news?type=安全")
    assert "矿区安全应急演练完成" in resp3.text
    assert "智能矿山无人驾驶试点" not in resp3.text
