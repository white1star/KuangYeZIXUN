import json
from datetime import datetime, timedelta

from crawler import store
from site_build.builder import build

PAGES = ["index.html", "news.html", "policy.html", "prices.html", "search.html", "copy.html"]
ASSETS = ["style.css", "app.js", "vendor/echarts.min.js"]


def seed(db):
    conn = store.connect(db)
    store.init_db(conn)
    store.upsert_source(conn, "mnr", "自然资源部", "policy", "https://example.com/p", True)
    store.upsert_source(conn, "kyb", "中国矿业报", "news", "https://example.com/n", True)
    store.upsert_source(conn, "sina", "新浪期货行情", "price", "https://example.com/f", True)
    news = {"url": "https://e.com/n1", "title": "内蒙古发现大型萤石矿", "summary": "探矿成果显著" * 20,
            "source_key": "kyb", "published_at": "2026-09-16"}
    store.insert_article(conn, news, {"board": "news", "minerals": ["萤石"], "regions": ["内蒙古"],
                                      "types": ["新矿", "市场"]}, "un1", "tn1")
    policy = {"url": "https://e.com/p1", "title": "河北省自然资源厅发布绿色矿山名录", "summary": "政策摘要",
              "source_key": "mnr", "published_at": "2026-09-15"}
    store.insert_article(conn, policy, {"board": "policy", "minerals": ["铁矿"], "regions": ["河北"],
                                        "types": ["政策"]}, "up1", "tp1")
    days = [(datetime.now() - timedelta(days=delta)).strftime("%Y-%m-%d") for delta in (2, 1, 0)]
    store.upsert_prices(conn, [
        {"commodity": "铜", "price_type": "期货", "value": 71000 + i * 100, "unit": "元/吨",
         "change": None, "change_pct": None, "price_date": day, "source_key": "sina",
         "raw_label": "", "fetched_at": store.now_iso()}
        for i, day in enumerate(days)])
    run = store.start_crawl_run(conn, "mnr")
    store.finish_crawl_run(conn, run, "ok", 2, 2)
    store.upsert_marketing_copy(conn, {
        "short_uri": "AIUEY9XuiH", "author": "老张说矿",
        "description": "磷矿价格回暖，选矿设备更新正当时。\n欢迎咨询像素智能。",
        "published_at": "2026-09-16 10:30", "cover_url": "https://e.com/cover.jpg",
        "link": "https://weixin.qq.com/sph/AIUEY9XuiH", "fetched_at": store.now_iso()})
    conn.close()


def make_site(tmp_path):
    db = tmp_path / "t.db"
    seed(db)
    out = tmp_path / "dist"
    result = build(db_path=db, out_dir=out, feedback_key="")
    return out, result


def test_build_outputs_complete(tmp_path):
    out, result = make_site(tmp_path)
    for name in PAGES + ASSETS + ["search.json", "prices.json"]:
        assert (out / name).exists(), name
    assert result["counts"]["articles"] == 2
    assert result["counts"]["copies"] == 1
    assert result["files"]["search.json"] > 0
    assert result["files"]["prices.json"] > 0
    assert result["files"]["copy.html"] > 0


def test_pages_use_relative_assets(tmp_path):
    out, _ = make_site(tmp_path)
    index = (out / "index.html").read_text(encoding="utf-8")
    prices = (out / "prices.html").read_text(encoding="utf-8")
    for page in PAGES:
        text = (out / page).read_text(encoding="utf-8")
        assert "/static/" not in text
        assert 'href="style.css"' in text
    assert 'action="search.html"' in index
    assert 'href="search.html?q=' in index
    assert 'href="news.html"' in index
    assert 'src="vendor/echarts.min.js"' in prices
    assert 'src="app.js"' in prices


def test_index_contains_stats_and_feedback(tmp_path):
    out, _ = make_site(tmp_path)
    index = (out / "index.html").read_text(encoding="utf-8")
    assert "构建时间" in index
    assert "今日新增" in index
    assert index.count('class="card stat-card"') == 4
    assert index.count('class="card entry-card"') == 4
    assert "营销文案" in index
    assert "1/3" in index
    assert "mailto:" in index
    assert "3103631561@qq.com" not in index


def test_feedback_form_rendered_when_key_configured(tmp_path):
    db = tmp_path / "t.db"
    seed(db)
    out = tmp_path / "dist"
    build(db_path=db, out_dir=out, feedback_key="test-key-123")
    index = (out / "index.html").read_text(encoding="utf-8")
    assert "api.web3forms.com" in index
    assert "test-key-123" in index
    assert 'id="feedback-dialog"' in index
    assert "mailto:" not in index


def test_feedback_mailto_without_key(tmp_path):
    out, _ = make_site(tmp_path)
    index = (out / "index.html").read_text(encoding="utf-8")
    assert "mailto:" in index
    assert "api.web3forms.com" not in index


def test_news_contains_seed_title(tmp_path):
    out, _ = make_site(tmp_path)
    news = (out / "news.html").read_text(encoding="utf-8")
    assert "内蒙古发现大型萤石矿" in news
    for tab in ("全部", "新矿山", "市场", "技术", "企业", "安全"):
        assert f'data-type="{tab}"' in news
    assert 'id="feed"' in news


def test_policy_contains_filters_and_seed(tmp_path):
    out, _ = make_site(tmp_path)
    policy = (out / "policy.html").read_text(encoding="utf-8")
    assert "河北省自然资源厅发布绿色矿山名录" in policy
    assert '<option value="自然资源部">自然资源部</option>' in policy
    assert '<option value="河北">河北</option>' in policy


def test_search_json_items(tmp_path):
    out, result = make_site(tmp_path)
    payload = json.loads((out / "search.json").read_text(encoding="utf-8"))
    assert payload["count"] == 2
    assert len(payload["items"]) == 2
    item = payload["items"][0]
    assert item["title"] == "内蒙古发现大型萤石矿"
    assert item["url"] == "https://e.com/n1"
    assert item["board"] == "news"
    assert item["source_name"] == "中国矿业报"
    assert item["minerals"] == ["萤石"]
    assert "新矿" in item["types"]
    assert len(item["summary"]) <= 60
    assert result["files"]["search.json"] == (out / "search.json").stat().st_size


def test_copy_page_renders_text_and_button(tmp_path):
    out, _ = make_site(tmp_path)
    copy = (out / "copy.html").read_text(encoding="utf-8")
    assert "营销文案" in copy
    assert "每日视频号文案，点复制发朋友圈" in copy
    assert "磷矿价格回暖，选矿设备更新正当时。" in copy
    assert "\n欢迎咨询像素智能。" in copy
    assert "复制文案" in copy
    assert "data-copy" in copy
    assert "2026-09-16 10:30" in copy
    assert "老张说矿" in copy
    assert 'href="https://weixin.qq.com/sph/AIUEY9XuiH"' in copy
    assert "看视频" in copy


def test_nav_contains_copy_link(tmp_path):
    out, _ = make_site(tmp_path)
    for page in ("index.html", "news.html"):
        text = (out / page).read_text(encoding="utf-8")
        assert 'href="copy.html"' in text
    copy = (out / "copy.html").read_text(encoding="utf-8")
    assert 'href="copy.html" class="active"' in copy
    index = (out / "index.html").read_text(encoding="utf-8")
    assert "今日 <b>1</b> 条 · 累计 <b>1</b> 条" in index


def test_copy_page_empty_state(tmp_path):
    db = tmp_path / "t.db"
    seed(db)
    conn = store.connect(db)
    conn.execute("DELETE FROM marketing_copy")
    conn.commit()
    conn.close()
    out = tmp_path / "dist"
    build(db_path=db, out_dir=out, feedback_key="")
    copy = (out / "copy.html").read_text(encoding="utf-8")
    assert "暂无文案" in copy
    assert 'class="card copy-card"' not in copy


def test_search_json_unaffected_by_marketing_copy(tmp_path):
    out, _ = make_site(tmp_path)
    text = (out / "search.json").read_text(encoding="utf-8")
    payload = json.loads(text)
    assert payload["count"] == 2
    assert "磷矿价格回暖" not in text


def test_prices_json_series_and_latest(tmp_path):
    out, _ = make_site(tmp_path)
    payload = json.loads((out / "prices.json").read_text(encoding="utf-8"))
    assert payload["commodities"] == ["铜"]
    assert payload["type_map"]["铜"] == ["期货"]
    futures = payload["series"]["铜"]["期货"]
    assert len(futures) == 3
    assert all(len(point) == 3 for point in futures)
    assert payload["series"]["铜"]["全部"] == futures
    latest = payload["latest"][0]
    assert latest["commodity"] == "铜"
    assert latest["value"] == 71200
    assert latest["unit"] == "元/吨"
