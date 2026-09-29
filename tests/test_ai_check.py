import dataclasses
from datetime import datetime, timedelta

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


def _add_run(conn, key, started_at, status="ok", items_found=0):
    """直接插轮次记录：既有 store.start_crawl_run 只能写"现在"，测不了 3 天前。"""
    conn.execute(
        "INSERT INTO crawl_runs(source_key,started_at,finished_at,status,items_found,items_new)"
        " VALUES(?,?,?,?,?,0)", (key, started_at, started_at, status, items_found))
    conn.commit()


def _run_days_ago(conn, key, days_ago, **kw):
    ts = (datetime.now() - timedelta(days=days_ago)).strftime("%Y-%m-%d %H:%M:%S")
    _add_run(conn, key, ts, **kw)


def test_silent_sources_flags_three_day_zero(tmp_path):
    """近 3 天有成功轮次但一条都没抓到 → 疑似静默。"""
    settings = make_settings(tmp_path)
    conn = store.connect(settings.db_path)
    store.init_db(conn)
    _run_days_ago(conn, "dead_source", 2, items_found=0)
    _run_days_ago(conn, "dead_source", 1, items_found=0)
    rows = ai_check.silent_sources(conn, ["dead_source"], days=3)
    assert [r["key"] for r in rows] == ["dead_source"]
    assert rows[0]["reason"] == "3 天零产出"
    conn.close()


def test_silent_sources_ignores_sources_with_recent_output(tmp_path):
    settings = make_settings(tmp_path)
    conn = store.connect(settings.db_path)
    store.init_db(conn)
    _run_days_ago(conn, "ok_source", 2, items_found=0)
    _run_days_ago(conn, "ok_source", 1, items_found=7)
    assert ai_check.silent_sources(conn, ["ok_source"], days=3) == []
    conn.close()


def test_silent_sources_separates_never_run(tmp_path):
    """从未成功抓过的启用源单独表述，不和'零产出'混为一谈。"""
    settings = make_settings(tmp_path)
    conn = store.connect(settings.db_path)
    store.init_db(conn)
    rows = ai_check.silent_sources(conn, ["never_run"], days=3)
    assert rows[0]["reason"] == "从未成功抓取"
    conn.close()


def test_silent_sources_ignores_disabled_sources(tmp_path):
    """传入的 enabled_keys 之外（已停用/已删除）的源不报。"""
    settings = make_settings(tmp_path)
    conn = store.connect(settings.db_path)
    store.init_db(conn)
    _run_days_ago(conn, "old_source", 1, items_found=0)
    assert ai_check.silent_sources(conn, [], days=3) == []
    conn.close()


def test_silent_sources_ignores_failed_runs(tmp_path):
    """失败轮次不算'零产出'（那种由既有的失败源段落负责报）。"""
    settings = make_settings(tmp_path)
    conn = store.connect(settings.db_path)
    store.init_db(conn)
    _run_days_ago(conn, "err_source", 1, status="error", items_found=0)
    assert ai_check.silent_sources(conn, ["err_source"], days=3) == []
    conn.close()


def test_silent_sources_ignores_running_only_runs(tmp_path):
    """窗口内只有 running 轮次：瞬时状态，不能当'从未成功抓取'报进静默列表。"""
    settings = make_settings(tmp_path)
    conn = store.connect(settings.db_path)
    store.init_db(conn)
    _run_days_ago(conn, "running_source", 1, status="running", items_found=0)
    assert ai_check.silent_sources(conn, ["running_source"], days=3) == []
    conn.close()


def _boom(*args, **kwargs):
    raise ValueError("while parsing a block mapping:\n    \ufeffbroken: [unclosed")


def test_report_survives_sources_config_error(tmp_path, monkeypatch):
    """源配置读坏只跳过静默检测：DB 的 ## 一/二/三 与退出码照常（回归：曾被 DB 的 except 吞掉）。"""
    settings = make_settings(tmp_path)
    seed(settings.db_path, with_bad=False)
    monkeypatch.setattr(ai_check, "load_sources", _boom)

    text, issues, code = ai_check.generate_report(settings)
    assert "## 一、各源最近一轮" in text
    assert "## 二、失败源与快照" in text
    assert "## 三、数据概览" in text
    assert "静默源检查已跳过" in text
    assert "配置读取失败" in text
    assert "数据库读取失败" not in text
    assert "\ufeff" not in text  # 异常回显里的 BOM 等不可打印字符必须滤掉
    assert issues == []
    assert code == 0


def test_report_rules_version_unknown_on_config_error(tmp_path, monkeypatch):
    """规则版本计算失败降级为'未知'，不影响 DB 段落。"""
    settings = make_settings(tmp_path)
    seed(settings.db_path, with_bad=False)
    monkeypatch.setattr(ai_check, "compute_rules_version", _boom)

    text, issues, code = ai_check.generate_report(settings)
    assert "规则版本：未知" in text
    assert "## 一、各源最近一轮" in text
    assert issues == []
    assert code == 0


def test_report_renders_three_day_zero_source(tmp_path, monkeypatch):
    """报告渲染'3 天零产出'分支：受控源近 3 天成功跑过但一条没抓到。"""
    settings = make_settings(tmp_path)
    monkeypatch.setattr(ai_check, "load_sources",
                        lambda: [{"key": "dead", "name": "死源", "enabled": True}])
    conn = store.connect(settings.db_path)
    store.init_db(conn)
    store.upsert_source(conn, "dead", "死源", "news", "https://dead.example/", True)
    _run_days_ago(conn, "dead", 2, items_found=0)
    _run_days_ago(conn, "dead", 1, items_found=0)
    conn.commit()
    conn.close()

    text, issues, code = ai_check.generate_report(settings)
    assert f"### 疑似静默源（近 {ai_check.SILENT_DAYS} 天零产出）" in text
    assert "- 死源（窗口内无产出记录）" in text
    assert "3 天零产出" in text
    assert issues == []
    assert code == 0


def test_report_silent_section_none(tmp_path, monkeypatch):
    """报告渲染'（无）'分支：受控源近期有产出时静默段落为空。"""
    settings = make_settings(tmp_path)
    monkeypatch.setattr(ai_check, "load_sources",
                        lambda: [{"key": "alive", "name": "活跃源", "enabled": True}])
    conn = store.connect(settings.db_path)
    store.init_db(conn)
    store.upsert_source(conn, "alive", "活跃源", "news", "https://alive.example/", True)
    _run_days_ago(conn, "alive", 1, items_found=5)
    conn.commit()
    conn.close()

    text, issues, code = ai_check.generate_report(settings)
    assert "### 疑似静默源" in text
    assert "（无）" in text
    assert "窗口内无产出记录" not in text
    assert issues == []
    assert code == 0
