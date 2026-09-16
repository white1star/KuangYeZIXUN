import dataclasses
from datetime import datetime

from crawler import store
from crawler.config import load_settings
from scripts import ai_check


def make_settings(tmp_path):
    logs = tmp_path / "logs"
    logs.mkdir()
    return dataclasses.replace(load_settings(), db_path=tmp_path / "news.db",
                               data_dir=tmp_path, logs_dir=logs)


def seed(db, with_bad=True, with_article=False):
    conn = store.connect(db)
    store.init_db(conn)
    store.upsert_source(conn, "good", "好源", "news", "https://good.example/", True)
    run = store.start_crawl_run(conn, "good")
    store.finish_crawl_run(conn, run, "ok", 10, 2)
    if with_article:
        store.insert_article(
            conn,
            {"url": "https://good.example/a", "title": "新发现大型铜矿", "summary": "",
             "source_key": "good", "published_at": "", "fetched_at": store.now_iso()},
            {"board": "news", "minerals": ["铜"], "regions": [], "types": ["新矿"]},
            "urlhash1", "titlehash1")
    if with_bad:
        store.upsert_source(conn, "bad", "坏源", "news", "https://bad.example/", True)
        run = store.start_crawl_run(conn, "bad")
        store.finish_crawl_run(conn, run, "error", 0, 0, "HTTP 403")
    conn.commit()
    conn.close()


def test_report_with_failed_source(tmp_path):
    settings = make_settings(tmp_path)
    snap_dir = settings.logs_dir / "snapshots"
    snap_dir.mkdir()
    snap = snap_dir / "bad_20260916_101010.html"
    snap.write_text("<html>403</html>", encoding="utf-8")
    seed(settings.db_path, with_article=True)

    text, issues, code = ai_check.generate_report(settings)
    assert "坏源" in text
    assert snap.name in text
    assert "## 二、失败源与快照" in text
    assert "## 三、数据概览" in text
    assert "今日新增文章：1 条" in text
    assert "「新矿」标签条数：1 条" in text
    assert "## 四、建议动作" in text
    assert "tools.snapshot bad" in text
    assert issues and "bad" in issues[0]
    assert code == 1


def test_report_all_ok(tmp_path):
    settings = make_settings(tmp_path)
    seed(settings.db_path, with_bad=False, with_article=True)

    text, issues, code = ai_check.generate_report(settings)
    assert "全部源最近一轮正常。" in text
    assert issues == []
    assert code == 0
    assert "本轮巡检未发现问题" in text


def test_write_report(tmp_path):
    settings = make_settings(tmp_path)
    seed(settings.db_path, with_bad=False)

    text, issues, code = ai_check.generate_report(settings)
    path = ai_check.write_report(text, settings)
    assert path.exists()
    assert path.name == "ai_check_" + datetime.now().strftime("%Y%m%d") + ".md"
    assert path.read_text(encoding="utf-8") == text
