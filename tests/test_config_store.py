from crawler import config, store


def test_load_settings_overrides(tmp_path):
    p = tmp_path / "settings.yaml"
    p.write_text("port: 9000\nsummary_max_chars: 150\n", encoding="utf-8")
    s = config.load_settings(p)
    assert s.port == 9000
    assert s.summary_max_chars == 150
    assert s.dedup_threshold == 0.85
    assert s.db_path.name == "news.db"


def test_load_tags_has_minerals():
    tags = config.load_tags()
    assert "磷矿" in tags["minerals"]
    assert "政策" in tags["types"]
    assert "河北" in tags["regions"]


def test_load_sources_defaults(tmp_path):
    d = tmp_path / "sources"
    d.mkdir()
    (d / "a.yaml").write_text("name: 甲\nboard: news\nurl: http://e.com\n", encoding="utf-8")
    srcs = config.load_sources(d)
    assert len(srcs) == 1
    assert srcs[0]["key"] == "a"
    assert srcs[0]["enabled"] is True


def test_runs_and_articles(tmp_path):
    conn = store.connect(tmp_path / "t.db")
    store.init_db(conn)
    store.upsert_source(conn, "a", "甲", "news", "http://e.com", True)
    run_id = store.start_crawl_run(conn, "a")
    store.finish_crawl_run(conn, run_id, "ok", 10, 3)
    row = conn.execute("SELECT * FROM crawl_runs").fetchone()
    assert row["status"] == "ok"
    assert row["items_found"] == 10

    item = {"url": "http://e.com/1", "title": "标题一", "summary": "", "source_key": "a", "published_at": ""}
    cls = {"board": "news", "minerals": ["铜"], "regions": [], "types": []}
    aid = store.insert_article(conn, item, cls, "uh1", "th1")
    art = conn.execute("SELECT * FROM articles WHERE id=?", (aid,)).fetchone()
    assert art["cluster_id"] is not None
    assert art["is_primary"] == 1
    assert store.url_exists(conn, "uh1") is True
    assert len(store.find_recent_titles(conn, days=3)) == 1


def test_upsert_prices_dedups(tmp_path):
    conn = store.connect(tmp_path / "t.db")
    store.init_db(conn)
    row = {"commodity": "铜", "price_type": "期货", "value": 70000.0, "unit": "元/吨",
           "price_date": "2026-09-15", "source_key": "sina", "raw_label": "cu2610",
           "change": 100.0, "change_pct": 0.14, "fetched_at": store.now_iso()}
    assert store.upsert_prices(conn, [row]) == 1
    row["value"] = 70100.0
    assert store.upsert_prices(conn, [row]) == 1
    assert conn.execute("SELECT COUNT(*) c FROM prices").fetchone()["c"] == 1
    assert conn.execute("SELECT value FROM prices").fetchone()["value"] == 70100.0
