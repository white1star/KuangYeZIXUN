from crawler import config, dedup, store
from crawler.classify import classify


def _tags():
    return config.load_tags()


def test_classify_example_from_spec():
    cls = classify("河北开展磷矿安全生产整治", "部署开展专项整治工作", "policy", _tags())
    assert cls["board"] == "policy"
    assert "磷矿" in cls["minerals"]
    assert "河北" in cls["regions"]
    assert "政策" in cls["types"]


def test_classify_tech_news():
    cls = classify("XRT 智能分选机在钨矿投用", "", "news", _tags())
    assert "钨" in cls["minerals"]
    assert "技术" in cls["types"]


def test_classify_keyword_and_combo():
    tags = {"minerals": {}, "regions": [], "types": {"技术": ["无人机+矿", "智能分选"]}}
    assert "技术" not in classify("全国无人机应用挑战赛落幕", "", "news", tags)["types"]
    assert "技术" in classify("矿区无人机巡检系统正式上线", "", "news", tags)["types"]


def test_normalize_url_strips_tracking():
    a = dedup.normalize_url("https://e.com/a?utm_source=x&id=1#frag")
    assert a == "https://e.com/a?id=1"


def test_core_title_strips_decoration():
    assert dedup.core_title("【转载】铜价上涨（附全文）") == "铜价上涨"
    assert dedup.normalize_title("河北：磷矿，2026！") == "河北磷矿2026"


def test_similarity_edges():
    assert dedup.similarity("河北开展磷矿安全生产整治", "河北开展磷矿安全生产整治") == 1.0
    assert dedup.similarity("河北开展磷矿安全生产整治", "河北开展磷矿安全生产整治（附全文）") >= 0.85
    assert dedup.similarity("河北开展磷矿安全生产整治", "云南铜矿项目投产") < 0.2


def test_core_title_whitelist_decoration():
    assert dedup.core_title("（转载）河北开展磷矿安全生产整治") == "河北开展磷矿安全生产整治"
    assert dedup.core_title("转载：河北开展磷矿安全生产整治") == "河北开展磷矿安全生产整治"
    assert dedup.core_title("铜价破位（来源：上海有色网）") == "铜价破位"
    assert dedup.core_title("铜价上涨（2026年展望上篇）") == "铜价上涨（2026年展望上篇）"


def test_similarity_reprint_prefix():
    assert dedup.similarity("（转载）河北开展磷矿安全生产整治", "河北开展磷矿安全生产整治") >= 0.85
    assert dedup.similarity("转载：河北开展磷矿安全生产整治", "河北开展磷矿安全生产整治") >= 0.85


def test_similarity_part_titles_not_merged():
    assert dedup.similarity("铜价上涨（2026年展望上篇）", "铜价上涨（2026年展望下篇）") < 0.85


def _article(url, title):
    return {"url": url, "title": title, "summary": "", "source_key": "a",
            "published_at": "", "classification": {"board": "news", "minerals": [], "regions": [], "types": []}}


def test_submit_item_three_outcomes(tmp_path):
    conn = store.connect(tmp_path / "t.db")
    store.init_db(conn)
    assert dedup.submit_item(conn, _article("https://e.com/1?utm_source=x", "河北开展磷矿安全生产整治")) == "new"
    assert dedup.submit_item(conn, _article("https://e.com/1", "完全一样标题不应重复")) == "skipped"
    assert dedup.submit_item(conn, _article("https://e.com/2", "河北开展磷矿安全生产整治（附全文）")) == "merged"
    row = conn.execute("SELECT member_count FROM article_clusters").fetchone()
    assert row["member_count"] == 2
    assert conn.execute("SELECT COUNT(*) c FROM articles").fetchone()["c"] == 2
    assert dedup.submit_item(conn, _article("https://e.com/3", "云南铜矿项目投产")) == "new"
