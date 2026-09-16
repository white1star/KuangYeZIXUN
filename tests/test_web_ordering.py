from fastapi.testclient import TestClient

from crawler import store
from web.app import create_app


def seed(db):
    conn = store.connect(db)
    store.init_db(conn)
    rows = [
        ("较老的新闻", "2026-01-05", "news"),
        ("较老的政策", "2026-02-10", "policy"),
        ("新的政策", "2026-08-20", "policy"),
        ("最新的新闻", "2026-09-10", "news"),
    ]
    for i, (title, pub, board) in enumerate(rows):
        item = {"url": f"https://e.com/o{i}", "title": title, "summary": "",
                "source_key": "x", "published_at": pub}
        cls = {"board": board, "minerals": [], "regions": [], "types": []}
        store.insert_article(conn, item, cls, f"ou{i}", f"ot{i}")
    conn.commit()
    conn.close()


def test_news_sorted_by_published_date_desc(tmp_path):
    db = tmp_path / "t.db"
    seed(db)
    client = TestClient(create_app(db))
    text = client.get("/news").text
    assert text.find("最新的新闻") != -1
    assert text.find("最新的新闻") < text.find("较老的新闻")


def test_policy_sorted_by_published_date_desc(tmp_path):
    db = tmp_path / "t.db"
    seed(db)
    client = TestClient(create_app(db))
    text = client.get("/policy").text
    assert text.find("新的政策") != -1
    assert text.find("新的政策") < text.find("较老的政策")


def test_search_results_sorted_by_published_date_desc(tmp_path):
    db = tmp_path / "t.db"
    seed(db)
    client = TestClient(create_app(db))
    text = client.get("/?q=新闻").text
    assert text.find("最新的新闻") < text.find("较老的新闻")
