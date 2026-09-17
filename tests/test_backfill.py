import dataclasses

from crawler import backfill, store
from crawler.config import load_settings
from crawler.fetch import FetchResult

ITEM = '<li><a href="/a/{i}.html">{title}</a><span>{date}</span></li>'


def page(items_html, next_href=""):
    nxt = f'<a href="{next_href}">下一页</a>' if next_href else ""
    return f"<html><body><ul class='list'>{items_html}</ul>{nxt}</body></html>"


def item(i, title, date):
    return ITEM.format(i=i, title=title, date=date)


def make_fetcher(pages):
    def fetcher(url, **kwargs):
        if url in pages:
            return FetchResult(ok=True, status=200, text=pages[url], final_url=url)
        return FetchResult(ok=False, status=404, error="HTTP 404", final_url=url)

    return fetcher


def make_source():
    return {"key": "t", "name": "测试源", "board": "news", "url": "https://t/",
            "list": {"item": "ul.list li", "title": "a", "date": "span"}}


def run_backfill(tmp_path, pages, max_pages=60, since="2026-01-01"):
    settings = dataclasses.replace(load_settings(), request_interval=0.0, db_path=tmp_path / "t.db")
    return backfill.run(since=since, max_pages=max_pages, settings=settings,
                        sources=[make_source()], fetcher=make_fetcher(pages),
                        sleep=lambda s: None)


def test_date_filter_and_stop_on_old_page(tmp_path):
    pages = {
        "https://t/": page(
            item(1, "2026年的新闻", "2026-03-01") + item(2, "2025年的旧闻", "2025-12-01")
            + item(3, "没日期的新闻", "暂无"),
            next_href="https://t/index_1.html"),
        "https://t/index_1.html": page(item(4, "很老的新闻", "2024-05-01")),
    }
    res = run_backfill(tmp_path, pages)["t"]
    assert res["new"] == 2
    assert res["pages"] == 2
    assert res["stopped"] == "已到日期下限"
    assert res["oldest"] == "2026-03-01"
    conn = store.connect(tmp_path / "t.db")
    titles = [r["title"] for r in conn.execute("SELECT title FROM articles ORDER BY id")]
    assert "2026年的新闻" in titles and "没日期的新闻" in titles
    assert "2025年的旧闻" not in titles and "很老的新闻" not in titles


def test_max_pages_limits(tmp_path):
    html = page(item(9, "新", "2026-06-01"), next_href="https://t/index_1.html")
    pages = {"https://t/": html}
    for n in range(1, 6):
        pages[f"https://t/index_{n}.html"] = page(item(10 + n, f"第{n}页新闻", "2026-06-02"),
                                                  next_href=f"https://t/index_{n + 1}.html")
    res = run_backfill(tmp_path, pages, max_pages=3)["t"]
    assert res["pages"] == 3
    assert res["new"] == 3


def test_stop_when_no_next_page(tmp_path):
    pages = {"https://t/": page(item(1, "就一页", "2026-01-02"))}
    res = run_backfill(tmp_path, pages)["t"]
    assert res["pages"] == 1
    assert res["stopped"] == "无下一页"
    assert res["new"] == 1


def test_stop_when_empty_page(tmp_path):
    pages = {
        "https://t/": page(item(1, "第一页", "2026-01-02"), next_href="https://t/index_1.html"),
        "https://t/index_1.html": page(""),
    }
    res = run_backfill(tmp_path, pages)["t"]
    assert res["pages"] == 1
    assert res["stopped"] == "空页"


def test_find_next_url_by_text():
    html = '<html><body><a href="/list_2.html">下一页</a></body></html>'
    assert backfill.find_next_url(html, "https://t/") == "https://t/list_2.html"


def test_probe_candidates():
    assert backfill.probe_candidates("https://t/kqsc/", 1)[0] == "https://t/kqsc/index_1.html"
    assert backfill.probe_candidates("https://t/kqsc/index.html", 2)[0] == "https://t/kqsc/index_2.html"


def test_template_pagination(tmp_path):
    src = make_source()
    src["pages"] = {"template": "https://t/p{n}.html", "max_pages": 3}
    pages = {
        "https://t/": page(item(1, "新1", "2026-06-01")),
        "https://t/p1.html": page(item(2, "新2", "2026-06-02")),
        "https://t/p2.html": page(item(3, "新3", "2026-06-03")),
    }
    settings = dataclasses.replace(load_settings(), request_interval=0.0, db_path=tmp_path / "t.db")
    res = backfill.run(max_pages=0, settings=settings, sources=[src],
                       fetcher=make_fetcher(pages), sleep=lambda s: None)["t"]
    assert res["pages"] == 3
    assert res["new"] == 3


def test_template_offset_start(tmp_path):
    src = make_source()
    src["pages"] = {"template": "https://t/p{n}.html", "offset": 1, "max_pages": 2}
    pages = {
        "https://t/": page(item(1, "新1", "2026-06-01")),
        "https://t/p1.html": page(item(2, "新2", "2026-06-02")),
    }
    settings = dataclasses.replace(load_settings(), request_interval=0.0, db_path=tmp_path / "t.db")
    res = backfill.run(max_pages=0, settings=settings, sources=[src],
                       fetcher=make_fetcher(pages), sleep=lambda s: None)["t"]
    assert res["pages"] == 2
    assert res["new"] == 2


def test_iter_entries_single_url():
    assert backfill.iter_entries(make_source()) == [{"url": "https://t/", "pages": {}}]


def test_iter_entries_multi_url_shared_pages():
    src = make_source()
    src.pop("url")
    src["urls"] = ["https://t/a/", "https://t/b/"]
    src["pages"] = {"template": "{url}index_{n}.html"}
    entries = backfill.iter_entries(src)
    assert [e["url"] for e in entries] == ["https://t/a/", "https://t/b/"]
    assert entries[0]["pages"]["template"] == "{url}index_{n}.html"
    assert entries[1]["pages"] == src["pages"]


def test_iter_entries_url_pages_override():
    src = make_source()
    src["urls"] = [{"url": "https://t/a/", "pages": {"max_pages": 3}}, "https://t/b/"]
    src["pages"] = {"template": "{url}index_{n}.html", "max_pages": 9}
    entries = backfill.iter_entries(src)
    assert entries[0]["pages"]["max_pages"] == 3
    assert entries[0]["pages"]["template"] == "{url}index_{n}.html"
    assert entries[1]["pages"]["max_pages"] == 9


def test_page_base():
    assert backfill.page_base("https://t/a/") == "https://t/a/"
    assert backfill.page_base("https://t/a") == "https://t/a/"
    assert backfill.page_base("https://t/a/index.html") == "https://t/a/"
    assert backfill.page_base("https://t/a/index.htm?x=1") == "https://t/a/"


def test_probe_candidates_skips_data_urls():
    assert backfill.probe_candidates("https://t/ds_1.json", 1) == []


def test_multi_url_template_pagination(tmp_path):
    src = make_source()
    src.pop("url")
    src["urls"] = ["https://t/a/", "https://t/b/"]
    src["pages"] = {"template": "{url}index_{n}.html", "max_pages": 5}
    pages = {
        "https://t/a/": page(item(1, "A1", "2026-06-01")),
        "https://t/a/index_1.html": page(item(2, "A2", "2025-12-01")),
        "https://t/b/": page(item(3, "B1", "2026-05-01")),
        "https://t/b/index_1.html": page(""),
    }
    settings = dataclasses.replace(load_settings(), request_interval=0.0, db_path=tmp_path / "t.db")
    res = backfill.run(max_pages=0, settings=settings, sources=[src],
                       fetcher=make_fetcher(pages), sleep=lambda s: None)["t"]
    assert res["pages"] == 3
    assert res["new"] == 2
    assert "已到日期下限" in res["stopped"]
    assert "空页" in res["stopped"]
    conn = store.connect(tmp_path / "t.db")
    titles = [r["title"] for r in conn.execute("SELECT title FROM articles ORDER BY id")]
    assert titles == ["A1", "B1"]


def test_multi_url_sleeps_between_entries(tmp_path):
    src = make_source()
    src.pop("url")
    src["urls"] = ["https://t/a/", "https://t/b/"]
    pages = {
        "https://t/a/": page(item(1, "A", "2026-06-01")),
        "https://t/b/": page(item(2, "B", "2026-06-01")),
    }
    settings = dataclasses.replace(load_settings(), request_interval=1.0, db_path=tmp_path / "t.db")
    slept = []
    backfill.run(max_pages=0, settings=settings, sources=[src],
                 fetcher=make_fetcher(pages), sleep=slept.append)
    assert slept == [1.0]


def test_multi_url_one_entry_failure_keeps_others(tmp_path):
    src = make_source()
    src.pop("url")
    src["urls"] = ["https://t/a/", "https://t/broken/"]
    pages = {"https://t/a/": page(item(1, "A1", "2026-06-01"))}
    settings = dataclasses.replace(load_settings(), request_interval=0.0, db_path=tmp_path / "t.db")
    res = backfill.run(max_pages=0, settings=settings, sources=[src],
                       fetcher=make_fetcher(pages), sleep=lambda s: None)["t"]
    assert res["new"] == 1
    assert res["pages"] == 1
    assert "broken" in res["error"]
