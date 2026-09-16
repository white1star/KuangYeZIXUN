import json

from crawler import config, store
from crawler.retag import retag


def seed(db):
    conn = store.connect(db)
    store.init_db(conn)
    rows = [
        ("某地铁矿探矿权出让公告", "news"),
        ("今日铜价小幅上涨", "news"),
    ]
    for i, (title, board) in enumerate(rows):
        item = {"url": f"https://e.com/{i}", "title": title, "summary": title + "的摘要",
                "source_key": "mnr", "published_at": "2026-09-15"}
        cls = {"board": board, "minerals": [], "regions": [], "types": []}
        store.insert_article(conn, item, cls, f"u{i}", f"t{i}")
    conn.commit()
    conn.close()


def test_retag_refreshes_types(tmp_path):
    db = tmp_path / "t.db"
    seed(db)
    conn = store.connect(db)
    try:
        count = retag(conn, config.load_tags())
        assert count == 2
        hit = conn.execute("SELECT types FROM articles WHERE title LIKE '%探矿权%'").fetchone()
        assert "新矿" in json.loads(hit["types"])
        other = conn.execute("SELECT types FROM articles WHERE title LIKE '%铜价%'").fetchone()
        assert "新矿" not in json.loads(other["types"])
    finally:
        conn.close()
