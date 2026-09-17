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


SIBLING_HTML = """
<html><body><div id="list">
<h4><a href="/a/1.html">带兄弟日期的标题</a></h4>
<div class="info"><span class="time">2026/9/16 7:51:00</span></div>
<h4><a href="/a/2.html">没有日期的标题</a></h4>
</div></body></html>
"""


def test_parse_list_date_sibling():
    cfg = {"list": {"item": "div#list h4", "title": "a", "date": "span.time", "date_sibling": True}}
    items = parse_list(SIBLING_HTML, cfg, "https://e.com/")
    assert items[0].published_at == "2026-09-16"
    assert items[1].published_at == ""


def test_parse_list_date_without_sibling_flag():
    cfg = {"list": {"item": "div#list h4", "title": "a", "date": "span.time"}}
    items = parse_list(SIBLING_HTML, cfg, "https://e.com/")
    assert items[0].published_at == ""


LIST_JSON = """
{"datasource": [
  {"title": "关于煤矿产能置换的通知", "publishUrl": "../20260911/abc/c.html",
   "publishTime": "2026-09-11 12:04:01", "summary": "摘要一"},
  {"title": "能源政策发布", "publishUrl": "https://x.com/y/z.html",
   "publishTime": "2026-08-01 09:00:00", "summary": ""},
  {"title": "无链接的条目", "publishUrl": "", "publishTime": "2026-07-01 09:00:00"},
  {"title": "", "publishUrl": "../20260701/dead/c.html", "publishTime": "2026-06-01 09:00:00"},
  {"showTitle": "标题字段缺失的条目", "publishUrl": "../20260501/beef/c.html",
   "publishTime": "2026-05-01 09:00:00", "summary": ""}
]}
"""

JSON_CFG = {
    "list": {"format": "json", "items": "datasource", "title": "title",
             "link": "publishUrl", "date": "publishTime", "summary": "summary"},
}


def test_parse_json_list_basic():
    items = parse_list(LIST_JSON, JSON_CFG, "https://www.nea.gov.cn/xwzx/ds_x.json")
    assert [i.title for i in items] == ["关于煤矿产能置换的通知", "能源政策发布"]
    assert items[0].url == "https://www.nea.gov.cn/20260911/abc/c.html"
    assert items[1].url == "https://x.com/y/z.html"
    assert items[0].published_at == "2026-09-11"
    assert items[0].summary == "摘要一"
    assert items[1].summary == ""


def test_parse_json_list_filter_keywords():
    cfg = {**JSON_CFG, "filter_keywords": ["煤矿"]}
    items = parse_list(LIST_JSON, cfg, "https://www.nea.gov.cn/xwzx/ds_x.json")
    assert [i.title for i in items] == ["关于煤矿产能置换的通知"]


def test_parse_json_list_bad_json_returns_empty():
    assert parse_list("not json", JSON_CFG, "https://e.com/") == []
    assert parse_list('{"other": []}', JSON_CFG, "https://e.com/") == []


def test_parse_json_list_tolerates_bom():
    items = parse_list("\ufeff" + LIST_JSON, JSON_CFG, "https://www.nea.gov.cn/xwzx/ds_x.json")
    assert len(items) == 2
