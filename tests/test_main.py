import dataclasses
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
