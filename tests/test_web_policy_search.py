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
    ]
    for i, (title, board, minerals, regions, types) in enumerate(rows):
        item = {"url": f"https://e.com/{i}", "title": title, "summary": title + "的摘要",
                "source_key": "mnr", "published_at": "2026-09-15"}
        cls = {"board": board, "minerals": minerals, "regions": regions, "types": types}
        store.insert_article(conn, item, cls, f"u{i}", f"t{i}")
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


def test_search_fts_and_like(tmp_path):
    db = tmp_path / "t.db"
    seed(db)
    client = TestClient(create_app(db))
    r1 = client.get("/search?q=磷矿")
    assert "河北开展磷矿安全生产整治" in r1.text
    assert "云南铜矿项目投产" not in r1.text
    r2 = client.get("/search?q=铜价")
    assert "今日铜价小幅上涨" in r2.text
    r4 = client.get("/search?q=磷矿安全")
    assert "河北开展磷矿安全生产整治" in r4.text
    r3 = client.get("/search?mineral=铜")
    assert "云南铜矿项目投产" in r3.text
    assert "河北开展磷矿安全生产整治" not in r3.text
