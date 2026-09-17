import dataclasses
from datetime import datetime, timedelta
from pathlib import Path

from crawler import main, store
from crawler.config import load_settings
from crawler.fetch import FetchResult

LIST_HTML = """
<ul class="list">
  <li><a href="/a/1.html">河北开展磷矿安全生产整治</a><span>2026-09-15</span></li>
  <li><a href="/a/2.html">云南铜矿项目投产</a><span>2026-09-15</span></li>
  <li><a href="/a/3.html">普通新闻一条</a><span>2026-09-15</span></li>
</ul>
"""

PRICE_TEXT = "秦皇岛5500K动力煤现货价 650 元/吨"


def _write_sources(d: Path):
    (d / "news_a.yaml").write_text(
        "name: 测试新闻站\nboard: news\nurl: https://news.example.com/list\n"
        "list:\n  item: ul.list li\n  title: a\n  date: span\n",
        encoding="utf-8")
    (d / "price_a.yaml").write_text(
        "name: 测试价格源\nboard: price\nparser: regex\nurl: https://price.example.com/\n"
        "price_type: 现货\nunit: 元/吨\nregex:\n"
        "  pattern: \"(?P<name>秦皇岛(?:5500|5000))(?:K)(?:动力煤现货价)[^0-9]{0,6}(?P<price>\\\\d{3,4})\"\n"
        "commodity_map:\n  动力煤: [5500, 5000]\n",
        encoding="utf-8")
    (d / "bad.yaml").write_text(
        "name: 坏掉的源\nboard: news\nurl: https://bad.example.com/\n"
        "list:\n  item: ul li\n  title: a\n",
        encoding="utf-8")


def _fetcher(url, **kwargs):
    if "bad" in url:
        return FetchResult(ok=False, status=500, error="HTTP 500", text="<html>错误页</html>")
    if "price" in url:
        return FetchResult(ok=True, status=200, text=PRICE_TEXT, final_url=url)
    return FetchResult(ok=True, status=200, text=LIST_HTML, final_url=url)


def test_run_once_end_to_end(tmp_path, monkeypatch):
    sources_dir = tmp_path / "sources"
    sources_dir.mkdir()
    _write_sources(sources_dir)
    settings = dataclasses.replace(
        load_settings(), request_interval=0.0, db_path=tmp_path / "t.db")
    monkeypatch.setattr(main.report, "snapshots_dir", lambda: tmp_path / "snaps")
    monkeypatch.setattr(main.report, "logs_dir", lambda: tmp_path / "logs")
    (tmp_path / "logs").mkdir()
    summary = main.run_once(settings=settings, fetcher=_fetcher, sources_dir=sources_dir)

    assert summary["sources_total"] == 3
    assert summary["sources_ok"] == 2
    assert summary["sources_error"] == 1
    assert summary["articles_new"] == 3
    assert summary["prices"] == 1

    conn = store.connect(settings.db_path)
    runs = conn.execute("SELECT source_key,status FROM crawl_runs ORDER BY id").fetchall()
    assert [(r["source_key"], r["status"]) for r in runs] == [
        ("bad", "error"), ("news_a", "ok"), ("price_a", "ok")]
    titles = [r["title"] for r in conn.execute("SELECT title FROM articles").fetchall()]
    assert "河北开展磷矿安全生产整治" in titles
    assert len(list((tmp_path / "snaps").glob("bad_*.html"))) == 1


def test_run_once_bad_yaml_isolation(tmp_path, monkeypatch):
    sources_dir = tmp_path / "sources"
    sources_dir.mkdir()
    (sources_dir / "broken.yaml").write_text(
        "name: 缺url的源\nboard: news\n", encoding="utf-8")
    (sources_dir / "news_a.yaml").write_text(
        "name: 测试新闻站\nboard: news\nurl: https://news.example.com/list\n"
        "list:\n  item: ul.list li\n  title: a\n  date: span\n",
        encoding="utf-8")
    settings = dataclasses.replace(
        load_settings(), request_interval=0.0, db_path=tmp_path / "t.db")
    monkeypatch.setattr(main.report, "snapshots_dir", lambda: tmp_path / "snaps")
    monkeypatch.setattr(main.report, "logs_dir", lambda: tmp_path / "logs")
    (tmp_path / "logs").mkdir()
    summary = main.run_once(settings=settings, fetcher=_fetcher, sources_dir=sources_dir)

    assert summary["sources_total"] == 2
    assert summary["sources_ok"] == 1
    assert summary["sources_error"] == 1
    assert summary["articles_new"] == 3
    assert any(e.startswith("broken:") for e in summary["errors"])

    conn = store.connect(settings.db_path)
    runs = conn.execute("SELECT source_key,status FROM crawl_runs ORDER BY id").fetchall()
    assert [(r["source_key"], r["status"]) for r in runs] == [("news_a", "ok")]


def test_run_once_max_age_days_drops_old_items(tmp_path, monkeypatch):
    sources_dir = tmp_path / "sources"
    sources_dir.mkdir()
    (sources_dir / "news_fresh.yaml").write_text(
        "name: 时效过滤源\nboard: news\nurl: https://news.example.com/list\n"
        "list:\n  item: ul.list li\n  title: a\n  date: span\n  max_age_days: 3\n",
        encoding="utf-8")
    today = datetime.now().strftime("%Y-%m-%d")
    old = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    html = (f'<ul class="list">'
            f'<li><a href="/a/new.html">新鲜新闻</a><span>{today}</span></li>'
            f'<li><a href="/a/old.html">过期新闻</a><span>{old}</span></li>'
            f'<li><a href="/a/nodate.html">无日期新闻</a><span>暂无</span></li></ul>')
    fetcher = lambda url, **kw: FetchResult(ok=True, status=200, text=html, final_url=url)
    settings = dataclasses.replace(
        load_settings(), request_interval=0.0, db_path=tmp_path / "t.db")
    monkeypatch.setattr(main.report, "snapshots_dir", lambda: tmp_path / "snaps")
    monkeypatch.setattr(main.report, "logs_dir", lambda: tmp_path / "logs")
    (tmp_path / "logs").mkdir()
    main.run_once(settings=settings, fetcher=fetcher, sources_dir=sources_dir)

    conn = store.connect(settings.db_path)
    titles = [r["title"] for r in conn.execute("SELECT title FROM articles ORDER BY id")]
    assert titles == ["新鲜新闻", "无日期新闻"]


def test_run_once_multi_url_partial_failure_keeps_counts(tmp_path, monkeypatch):
    sources_dir = tmp_path / "sources"
    sources_dir.mkdir()
    (sources_dir / "price_multi.yaml").write_text(
        "name: 多URL价格源\nboard: price\nparser: regex\n"
        "urls: [https://price.example.com/a, https://bad.example.com/b]\n"
        "price_type: 现货\nunit: 元/吨\nregex:\n"
        "  pattern: \"(?P<name>秦皇岛(?:5500|5000))(?:K)(?:动力煤现货价)[^0-9]{0,6}(?P<price>\\\\d{3,4})\"\n"
        "commodity_map:\n  动力煤: [5500, 5000]\n",
        encoding="utf-8")
    settings = dataclasses.replace(
        load_settings(), request_interval=0.0, db_path=tmp_path / "t.db")
    monkeypatch.setattr(main.report, "snapshots_dir", lambda: tmp_path / "snaps")
    monkeypatch.setattr(main.report, "logs_dir", lambda: tmp_path / "logs")
    (tmp_path / "logs").mkdir()
    summary = main.run_once(settings=settings, fetcher=_fetcher, sources_dir=sources_dir)

    assert summary["sources_ok"] == 0
    assert summary["sources_error"] == 1
    assert summary["prices"] == 1

    conn = store.connect(settings.db_path)
    row = conn.execute(
        "SELECT status,items_found,items_new,error FROM crawl_runs").fetchone()
    assert row["status"] == "error"
    assert row["items_found"] == 1
    assert row["items_new"] == 1
    assert "HTTP 500" in row["error"]
