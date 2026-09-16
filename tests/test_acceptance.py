import dataclasses

from crawler import store
from crawler.config import load_settings
from scripts import acceptance


def test_acceptance_reports_checks(tmp_path):
    settings = dataclasses.replace(load_settings(), db_path=tmp_path / "t.db")
    conn = store.connect(settings.db_path)
    store.init_db(conn)
    item = {"url": "https://e.com/1", "title": "磷矿政策", "summary": "",
            "source_key": "mnr", "published_at": ""}
    cls = {"board": "policy", "minerals": ["磷矿"], "regions": [], "types": []}
    store.insert_article(conn, item, cls, "u1", "t1")
    store.upsert_source(conn, "mnr", "自然资源部", "policy", "https://www.mnr.gov.cn/", True)
    run = store.start_crawl_run(conn, "mnr")
    store.finish_crawl_run(conn, run, "ok", 1, 1)
    conn.commit()
    conn.close()
    checks = acceptance.run_checks(settings)
    names = [c[0] for c in checks]
    assert "今日文章数 ≥ 1" in names
    assert "最近一轮源成功率 ≥ 80%" in names
    assert any(name.startswith("搜索响应") for name in names)
