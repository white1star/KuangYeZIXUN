from datetime import datetime

from crawler.parse import ParsedItem, absolutize, extract_summary, parse_date, parse_list

LIST_HTML = """
<html><body>
<ul class="list">
  <li><a href="/x/202609/t20260915_1.html">河北开展磷矿安全生产整治</a><span class="date">2026-09-15</span></li>
  <li><a href="http://e.com/x/2.html">关于开展矿山安全监察的通知</a><span class="date">2026年9月14日</span></li>
  <li><a href="/x/3.html">铜价近日震荡上行</a><span class="date">[20260913]</span></li>
  <li><a href="/x/4.html">萤石市场周报</a><span class="date">09-12</span></li>
  <li><a href="/x/5.html">无日期的普通新闻</a><span class="date">暂无</span></li>
</ul>
</body></html>
"""

CFG = {"list": {"item": "ul.list li", "title": "a", "date": "span.date"}}


def test_parse_list_basic():
    items = parse_list(LIST_HTML, CFG, "https://www.mnr.gov.cn/dt/ywbb/")
    assert len(items) == 5
    assert isinstance(items[0], ParsedItem)
    assert items[0].title == "河北开展磷矿安全生产整治"
    assert items[0].url == "https://www.mnr.gov.cn/x/202609/t20260915_1.html"
    assert items[1].url == "http://e.com/x/2.html"


def test_parse_list_dates():
    items = parse_list(LIST_HTML, CFG, "https://www.mnr.gov.cn/")
    assert items[0].published_at == "2026-09-15"
    assert items[1].published_at == "2026-09-14"
    assert items[2].published_at == "2026-09-13"
    assert items[3].published_at.endswith("-09-12")
    assert items[4].published_at == ""


def test_parse_list_filter_keywords_keeps_hits():
    cfg = {"list": CFG["list"], "filter_keywords": ["矿", "地热"]}
    items = parse_list(LIST_HTML, cfg, "https://www.mnr.gov.cn/")
    assert [i.title for i in items] == [
        "河北开展磷矿安全生产整治",
        "关于开展矿山安全监察的通知",
    ]


def test_parse_list_filter_keywords_no_hit_returns_empty():
    cfg = {"list": CFG["list"], "filter_keywords": ["石油"]}
    assert parse_list(LIST_HTML, cfg, "https://www.mnr.gov.cn/") == []


def test_parse_list_without_filter_keywords_unchanged():
    items = parse_list(LIST_HTML, dict(CFG), "https://www.mnr.gov.cn/")
    assert len(items) == 5


def test_parse_date_variants():
    assert parse_date("2026/09/15") == "2026-09-15"
    assert parse_date("2026年9月5日") == "2026-09-05"
    assert parse_date("t20260915_16.html") == "2026-09-15"
    assert parse_date("12345.67") == ""
    assert parse_date("") == ""


def test_parse_date_mmdd_rolls_back_across_year():
    assert parse_date("12-31", today=datetime(2026, 1, 5)) == "2025-12-31"
    assert parse_date("01-05", today=datetime(2026, 1, 5)) == "2026-01-05"


def test_absolutize():
    assert absolutize("https://a.com/b/", "/c/d.html") == "https://a.com/c/d.html"
    assert absolutize("https://a.com/b/", "https://x.com/y") == "https://x.com/y"
    assert absolutize("https://a.com/b/", "javascript:void(0)") == ""


DETAIL_HTML = """
<html><body><div class="nav">导航</div>
<div class="article"><script>bad()</script>
  近日，河北省自然资源厅印发通知，部署开展磷矿安全生产专项整治工作，
  对全省磷矿开采企业开展全覆盖检查，重点排查边坡、尾矿库等风险隐患。
</div></body></html>
"""


def test_extract_summary_truncates_and_collapses():
    cfg = {"detail": {"content": "div.article"}}
    s = extract_summary(DETAIL_HTML, cfg, max_chars=40)
    assert "河北省自然资源厅" in s
    assert "bad()" not in s
    assert s.endswith("…")
    assert len(s) <= 40


def test_extract_summary_without_selector():
    s = extract_summary("<html><body><p>正文一句话</p></body></html>", {}, max_chars=200)
    assert s == "正文一句话"
