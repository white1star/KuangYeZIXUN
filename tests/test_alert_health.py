"""scripts/alert_health.py 的行为测试（每日数据健康告警邮件）。

覆盖三类问题（抓取失败 / 疑似静默 / 报价陈旧）、24 小时去重状态、邮件内容与 CLI。
"""
import dataclasses
import json
from datetime import datetime, timedelta

import pytest

from crawler import store
from crawler.config import load_settings
from scripts import alert_health

# 固定"现在"，让 age_days / 静默窗口 / 24 小时窗口都可复现
NOW = datetime(2026, 9, 30, 8, 0, 0)
NAMES = {
    "good": "正常源",
    "broken": "改版源",
    "flaky": "间歇失败源",
    "dead": "静默源",
    "never_run": "从未抓过的源",
    "stopped": "已停用源",
}


def make_settings(tmp_path):
    logs = tmp_path / "logs"
    logs.mkdir()
    config = tmp_path / "config"
    (config / "sources").mkdir(parents=True)
    return dataclasses.replace(load_settings(), db_path=tmp_path / "news.db", data_dir=tmp_path,
                               logs_dir=logs, config_dir=config)


def open_db(settings):
    conn = store.connect(settings.db_path)
    store.init_db(conn)
    return conn


def add_source(conn, key, name=None, enabled=True, board="news"):
    store.upsert_source(conn, key, name or NAMES.get(key, key), board, f"https://{key}.example/", enabled)


def add_run(conn, key, when, status="ok", found=0, error=""):
    """直接插轮次：store.start_crawl_run 只能写"现在"，测不了 3 天前/第二轮。"""
    ts = when.strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        "INSERT INTO crawl_runs(source_key,started_at,finished_at,status,items_found,items_new,error)"
        " VALUES(?,?,?,?,?,0,?)", (key, ts, ts, status, found, error))
    conn.commit()


def add_prices(conn, rows):
    store.upsert_prices(conn, rows)


def price(commodity, price_type, source_key, price_date, value=100.0):
    return {"commodity": commodity, "price_type": price_type, "value": value, "unit": "元/吨",
            "price_date": price_date, "source_key": source_key, "raw_label": "",
            "fetched_at": NOW.strftime("%Y-%m-%d %H:%M:%S")}


def patch_sources(monkeypatch, *enabled, disabled=()):
    """受控的源配置：位置参数为启用源，disabled 为已停用源。"""
    def _load(*args, **kwargs):
        return ([{"key": k, "name": NAMES.get(k, k), "enabled": True} for k in enabled]
                + [{"key": k, "name": NAMES.get(k, k), "enabled": False} for k in disabled])
    monkeypatch.setattr(alert_health, "load_sources", _load)


# ---------------------------------------------------------------- 抓取失败

def test_failed_reports_latest_round_error(tmp_path, monkeypatch):
    settings = make_settings(tmp_path)
    patch_sources(monkeypatch, "good", "broken")
    conn = open_db(settings)
    add_source(conn, "good")
    add_source(conn, "broken")
    add_run(conn, "good", NOW - timedelta(hours=2), status="ok", found=5)
    add_run(conn, "broken", NOW - timedelta(hours=2), status="error", error="HTTP 403 解析失败")
    issues = alert_health.collect_issues(conn, settings=settings, now=NOW)
    conn.close()

    assert issues["failed"] == [
        {"key": "broken", "name": NAMES["broken"], "error": "HTTP 403 解析失败"}]
    assert issues["silent"] == []


def test_failed_ignores_source_recovered_by_later_ok_run(tmp_path, monkeypatch):
    """历史失败过、但最新一轮已正常 → 不报（口径只看 MAX(id) 那一轮）。"""
    settings = make_settings(tmp_path)
    patch_sources(monkeypatch, "flaky")
    conn = open_db(settings)
    add_source(conn, "flaky")
    add_run(conn, "flaky", NOW - timedelta(days=1), status="error", error="timeout")
    add_run(conn, "flaky", NOW - timedelta(hours=1), status="ok", found=3)
    issues = alert_health.collect_issues(conn, settings=settings, now=NOW)
    conn.close()

    assert issues["failed"] == []


def test_failed_ignores_disabled_source(tmp_path, monkeypatch):
    """配置里已停用的源即使最近一轮失败也不报。"""
    settings = make_settings(tmp_path)
    patch_sources(monkeypatch, "good", disabled=("stopped",))
    conn = open_db(settings)
    add_source(conn, "good")
    add_source(conn, "stopped", enabled=False)
    add_run(conn, "good", NOW - timedelta(hours=1), status="ok", found=3)
    add_run(conn, "stopped", NOW - timedelta(hours=1), status="error", error="404")
    issues = alert_health.collect_issues(conn, settings=settings, now=NOW)
    conn.close()

    assert issues["failed"] == []
    assert issues["silent"] == []


def test_failed_and_silent_do_not_double_report(tmp_path, monkeypatch):
    """最新一轮就是 error 的源不算"静默"——两者互补，同一个源只出现一次。"""
    settings = make_settings(tmp_path)
    patch_sources(monkeypatch, "broken")
    conn = open_db(settings)
    add_source(conn, "broken")
    add_run(conn, "broken", NOW - timedelta(days=1), status="ok", found=8)
    add_run(conn, "broken", NOW - timedelta(hours=1), status="error", error="500")
    issues = alert_health.collect_issues(conn, settings=settings, now=NOW)
    conn.close()

    assert [f["key"] for f in issues["failed"]] == ["broken"]
    assert issues["silent"] == []


# ---------------------------------------------------------------- 疑似静默

def test_silent_reports_three_day_zero_output(tmp_path, monkeypatch):
    settings = make_settings(tmp_path)
    patch_sources(monkeypatch, "dead")
    conn = open_db(settings)
    add_source(conn, "dead")
    add_run(conn, "dead", NOW - timedelta(days=2), status="ok", found=0)
    add_run(conn, "dead", NOW - timedelta(days=1), status="ok", found=0)
    issues = alert_health.collect_issues(conn, settings=settings, now=NOW)
    conn.close()

    assert issues["silent"] == [
        {"key": "dead", "name": NAMES["dead"], "reason": "3 天零产出", "last_nonzero": ""}]


def test_silent_maps_names_from_load_sources(tmp_path, monkeypatch):
    settings = make_settings(tmp_path)
    patch_sources(monkeypatch, "never_run")
    conn = open_db(settings)
    add_source(conn, "never_run")
    issues = alert_health.collect_issues(conn, settings=settings, now=NOW)
    conn.close()

    assert issues["silent"][0]["name"] == NAMES["never_run"]
    assert issues["silent"][0]["reason"] == "从未成功抓取"


def test_collect_issues_reuses_ai_check_silent_sources(tmp_path, monkeypatch):
    """静默检测直接复用 ai_check.silent_sources（口径只有一处实现），name 由配置映射。"""
    calls = []
    # 真实的 silent_sources 不返回 name，只给 key/reason/last_nonzero
    def _fake(conn, enabled_keys, days=3, now=None):
        calls.append((list(enabled_keys), days))
        return [{"key": "dead", "reason": "3 天零产出", "last_nonzero": ""}]

    settings = make_settings(tmp_path)
    patch_sources(monkeypatch, "good", "dead")
    monkeypatch.setattr(alert_health, "silent_sources", _fake)
    conn = open_db(settings)
    issues = alert_health.collect_issues(conn, settings=settings, now=NOW)
    conn.close()

    assert calls == [(["good", "dead"], 3)]
    assert issues["silent"] == [
        {"key": "dead", "name": NAMES["dead"], "reason": "3 天零产出", "last_nonzero": ""}]


def broken_config(*args, **kwargs):
    """源配置读坏的典型异常：多行定位 + 回显内容（含 BOM）。"""
    raise ValueError("while parsing a block mapping:\n    \ufeffbad: [unclosed")


def test_failed_still_reported_when_sources_config_broken(tmp_path, monkeypatch):
    """源配置读坏时不能整封邮件哑掉：failed 退化为按 DB 的 enabled 标志判断。"""
    settings = make_settings(tmp_path)
    monkeypatch.setattr(alert_health, "load_sources", broken_config)
    conn = open_db(settings)
    add_source(conn, "broken")
    add_run(conn, "broken", NOW - timedelta(hours=1), status="error", error="500")
    issues = alert_health.collect_issues(conn, settings=settings, now=NOW)
    conn.close()

    assert [f["key"] for f in issues["failed"]] == ["broken"]
    assert issues["silent"] == []
    assert issues["config_error"]  # 供邮件正文说明"本次未做静默检测"


def test_missing_sources_dir_counts_as_config_error(tmp_path):
    """源配置目录不在时 glob 会安静返回空清单 → 必须当配置错误，否则检测被悄悄关掉。"""
    settings = make_settings(tmp_path)
    (settings.config_dir / "sources").rmdir()  # 模拟配置目录丢失
    conn = open_db(settings)
    add_source(conn, "broken")
    add_run(conn, "broken", NOW - timedelta(hours=1), status="error", error="500")
    issues = alert_health.collect_issues(conn, settings=settings, now=NOW)
    conn.close()

    assert "源配置目录不存在" in issues["config_error"]
    assert [f["key"] for f in issues["failed"]] == ["broken"]
    assert alert_health.has_issues(issues) is True


def test_config_error_alone_still_triggers_alert(tmp_path, monkeypatch):
    """只有配置问题、三类清单都空 → 也要发邮件：否则"检测没跑"被当成"一切正常"。"""
    settings = make_settings(tmp_path)
    monkeypatch.setattr(alert_health, "load_sources", broken_config)
    conn = open_db(settings)
    issues = alert_health.collect_issues(conn, settings=settings, now=NOW)
    conn.close()

    assert alert_health.has_issues(issues) is True
    subject, body = alert_health.build_email(issues, "rv-abc1234567")
    assert subject == "【矿业资讯站】数据异常提醒：检测受限 1 项"
    assert "静默检测" in body


# ---------------------------------------------------------------- 报价陈旧

def test_stale_reports_price_older_than_threshold(tmp_path, monkeypatch):
    settings = make_settings(tmp_path)
    patch_sources(monkeypatch)
    conn = open_db(settings)
    add_prices(conn, [
        price("锡", "现货", "ccmn_sn", "2026-09-27"),          # 3 天前
        price("铜", "现货", "ccmn", "2026-09-30"),             # 今天
    ])
    issues = alert_health.collect_issues(conn, settings=settings, now=NOW)
    conn.close()

    assert issues["stale"] == [
        {"commodity": "锡", "price_type": "现货", "latest": "2026-09-27",
         "age_days": 3, "source": "ccmn_sn"}]


def test_stale_includes_age_exactly_at_threshold(tmp_path, monkeypatch):
    """age_days 恰好等于阈值必须报（上游当天没出价属正常，连续 2 天没更新才算异常）。"""
    settings = make_settings(tmp_path)
    patch_sources(monkeypatch)
    conn = open_db(settings)
    add_prices(conn, [price("锡", "现货", "ccmn_sn", "2026-09-28")])  # 2 天前 = 阈值
    issues = alert_health.collect_issues(conn, settings=settings, now=NOW)
    conn.close()

    assert [(s["commodity"], s["age_days"]) for s in issues["stale"]] == [("锡", 2)]


def test_stale_ignores_one_day_old_price(tmp_path, monkeypatch):
    """1#锡 那种"昨天还更新过"的情况不算陈旧。"""
    settings = make_settings(tmp_path)
    patch_sources(monkeypatch)
    conn = open_db(settings)
    add_prices(conn, [price("锡", "现货", "ccmn_sn", "2026-09-29")])  # 1 天前
    issues = alert_health.collect_issues(conn, settings=settings, now=NOW)
    conn.close()

    assert issues["stale"] == []


def test_stale_measured_per_commodity_not_per_source(tmp_path, monkeypatch):
    """低频备用源自身日期旧，但品种层面是新的 → 不报（否则每天都会误报期货备用源）。"""
    settings = make_settings(tmp_path)
    patch_sources(monkeypatch)
    conn = open_db(settings)
    add_prices(conn, [
        price("铁矿", "期货", "eastmoney_futures", "2026-09-18"),   # 备用源低频
        price("铁矿", "期货", "sina_futures", "2026-09-30"),        # 主源今天
    ])
    issues = alert_health.collect_issues(conn, settings=settings, now=NOW)
    conn.close()

    assert issues["stale"] == []


def test_stale_reports_source_of_latest_price_date(tmp_path, monkeypatch):
    """同品种多源时，source 报的是"提供最新那条价"的源（管理员要据此去修那个源）。"""
    settings = make_settings(tmp_path)
    patch_sources(monkeypatch)
    conn = open_db(settings)
    add_prices(conn, [
        price("铜", "现货", "ccmn", "2026-09-20"),
        price("铜", "现货", "smm", "2026-09-25"),
    ])
    issues = alert_health.collect_issues(conn, settings=settings, now=NOW)
    conn.close()

    assert issues["stale"] == [
        {"commodity": "铜", "price_type": "现货", "latest": "2026-09-25",
         "age_days": 5, "source": "smm"}]


def test_stale_reports_never_updated_commodity(tmp_path, monkeypatch):
    """整条时间线停在几天前的品种（1#锡 事故形态）要报出来。"""
    settings = make_settings(tmp_path)
    patch_sources(monkeypatch)
    conn = open_db(settings)
    add_prices(conn, [
        price("锡", "现货", "ccmn_sn", "2026-09-21"),
        price("锡", "现货", "smm", "2026-09-21"),
    ])
    issues = alert_health.collect_issues(conn, settings=settings, now=NOW)
    conn.close()

    assert [(s["commodity"], s["age_days"]) for s in issues["stale"]] == [("锡", 9)]


def test_stale_custom_threshold(tmp_path, monkeypatch):
    settings = make_settings(tmp_path)
    patch_sources(monkeypatch)
    conn = open_db(settings)
    add_prices(conn, [price("锡", "现货", "ccmn_sn", "2026-09-29")])  # 1 天前
    assert alert_health.collect_issues(conn, settings=settings, now=NOW)["stale"] == []
    assert alert_health.collect_issues(conn, settings=settings, stale_days=1,
                                        now=NOW)["stale"][0]["age_days"] == 1
    conn.close()


def test_stale_skips_unparsable_price_date(tmp_path, monkeypatch):
    """脏数据（日期不是 ISO）不能让整封告警炸掉：跳过该行继续判。"""
    settings = make_settings(tmp_path)
    patch_sources(monkeypatch)
    conn = open_db(settings)
    add_prices(conn, [
        price("锡", "现货", "ccmn_sn", "9/21"),
        price("铜", "现货", "ccmn", "2026-09-30"),
    ])
    issues = alert_health.collect_issues(conn, settings=settings, now=NOW)
    conn.close()

    assert issues["stale"] == []


def test_stale_sorted_worst_first(tmp_path, monkeypatch):
    settings = make_settings(tmp_path)
    patch_sources(monkeypatch)
    conn = open_db(settings)
    add_prices(conn, [
        price("锡", "现货", "ccmn_sn", "2026-09-28"),   # 2 天
        price("铜", "现货", "ccmn", "2026-09-25"),      # 5 天，更严重
    ])
    issues = alert_health.collect_issues(conn, settings=settings, now=NOW)
    conn.close()

    assert [(s["commodity"], s["age_days"]) for s in issues["stale"]] == [("铜", 5), ("锡", 2)]


# ---------------------------------------------------------------- 全正常

def test_collect_issues_all_clean(tmp_path, monkeypatch):
    settings = make_settings(tmp_path)
    patch_sources(monkeypatch, "good")
    conn = open_db(settings)
    add_source(conn, "good")
    add_run(conn, "good", NOW - timedelta(hours=1), status="ok", found=12)
    add_prices(conn, [price("铜", "现货", "ccmn", "2026-09-30")])
    issues = alert_health.collect_issues(conn, settings=settings, now=NOW)
    conn.close()

    assert issues["failed"] == []
    assert issues["silent"] == []
    assert issues["stale"] == []
    assert alert_health.has_issues(issues) is False


# ---------------------------------------------------------------- 去重状态

def test_should_send_first_time(tmp_path):
    assert alert_health.should_send(tmp_path / ".alert_state.json", "sig-a") is True


def test_should_send_dedup_within_24h(tmp_path):
    state = tmp_path / ".alert_state.json"
    alert_health.mark_sent(state, "sig-a")
    assert alert_health.should_send(state, "sig-a") is False
    assert alert_health.should_send(state, "sig-a", now=datetime.now() + timedelta(hours=23)) is False


def test_should_send_again_after_24h(tmp_path):
    state = tmp_path / ".alert_state.json"
    alert_health.mark_sent(state, "sig-a", now=datetime.now() - timedelta(hours=25))
    assert alert_health.should_send(state, "sig-a") is True


def test_should_send_new_signature_right_away(tmp_path):
    state = tmp_path / ".alert_state.json"
    alert_health.mark_sent(state, "sig-a")
    assert alert_health.should_send(state, "sig-b") is True


def test_should_send_true_when_state_corrupt(tmp_path):
    """状态文件坏掉时当没发过：宁可多发一次，也不要因为状态坏了永久静默。"""
    state = tmp_path / ".alert_state.json"
    state.write_text("{not json", encoding="utf-8")
    assert alert_health.should_send(state, "sig-a") is True


def test_should_send_true_when_state_timestamps_garbage(tmp_path):
    state = tmp_path / ".alert_state.json"
    state.write_text(json.dumps({"last_signature": "sig-a", "last_sent_at": "上周三"}),
                     encoding="utf-8")
    assert alert_health.should_send(state, "sig-a") is True


def test_should_send_true_when_state_empty_object(tmp_path):
    state = tmp_path / ".alert_state.json"
    state.write_text("{}", encoding="utf-8")
    assert alert_health.should_send(state, "sig-a") is True


def test_mark_sent_writes_expected_shape(tmp_path):
    state = tmp_path / ".alert_state.json"
    when = datetime(2026, 9, 30, 8, 0, 0)
    alert_health.mark_sent(state, "sig-a", now=when)
    assert json.loads(state.read_text(encoding="utf-8")) == {
        "last_signature": "sig-a", "last_sent_at": "2026-09-30T08:00:00"}


def test_mark_sent_reads_state_written_by_hand(tmp_path):
    """兼容手工/旧版本写的状态文件：只要有 signature+时间就能判去重。"""
    state = tmp_path / ".alert_state.json"
    state.write_text(json.dumps(
        {"last_signature": "sig-a", "last_sent_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}),
        encoding="utf-8")
    assert alert_health.should_send(state, "sig-a") is False


# ---------------------------------------------------------------- 指纹

def test_signature_stable_for_same_issues():
    issues = {"failed": [{"key": "a", "name": "A", "error": "x"}],
              "silent": [{"key": "s", "name": "S", "reason": "r", "last_nonzero": ""}],
              "stale": [{"commodity": "锡", "price_type": "现货", "latest": "2026-09-27",
                         "age_days": 3, "source": "ccmn_sn"}]}
    other = {"failed": [{"key": "a", "name": "换个名", "error": "换个错"}],
             "silent": [{"key": "s", "name": "S", "reason": "别的", "last_nonzero": "x"}],
             "stale": [{"commodity": "锡", "price_type": "现货", "latest": "2026-09-27",
                        "age_days": 99, "source": "别人"}]}
    assert alert_health.signature_of(issues) == alert_health.signature_of(other)
    assert "a" in alert_health.signature_of(issues)


def test_signature_differs_when_issue_set_differs():
    base = {"failed": [], "silent": [], "stale": []}
    with_stale = {"failed": [], "silent": [],
                  "stale": [{"commodity": "锡", "price_type": "现货", "latest": "2026-09-27",
                             "age_days": 3, "source": "ccmn_sn"}]}
    assert alert_health.signature_of(base) != alert_health.signature_of(with_stale)


def test_signature_ignores_ordering():
    a = {"failed": [{"key": "a"}, {"key": "b"}], "silent": [], "stale": []}
    b = {"failed": [{"key": "b"}, {"key": "a"}], "silent": [], "stale": []}
    assert alert_health.signature_of(a) == alert_health.signature_of(b)


# ---------------------------------------------------------------- 邮件内容

def _issues_all_three():
    return {
        "failed": [{"key": "broken", "name": "改版源", "error": "HTTP 403 解析失败"}],
        "silent": [{"key": "dead", "name": "静默源", "reason": "3 天零产出", "last_nonzero": ""}],
        "stale": [{"commodity": "锡", "price_type": "现货", "latest": "2026-09-28",
                   "age_days": 2, "source": "ccmn_sn"}],
    }


def test_build_email_subject_lists_present_categories():
    subject, _ = alert_health.build_email(_issues_all_three(), "rv-abc1234567")
    assert subject == "【矿业资讯站】数据异常提醒：失败 1 个 / 静默 1 个 / 报价陈旧 1 个"


def test_build_email_subject_omits_absent_categories():
    subject, _ = alert_health.build_email(
        {"failed": [], "silent": [], "stale": [{"commodity": "锡", "price_type": "现货",
                                                "latest": "2026-09-28", "age_days": 2,
                                                "source": "ccmn_sn"}]}, "rv-abc1234567")
    assert subject == "【矿业资讯站】数据异常提醒：报价陈旧 1 个"


def test_build_email_body_sections():
    _, body = alert_health.build_email(_issues_all_three(), "rv-abc1234567")
    assert "## 抓取失败" in body
    assert "改版源（broken）：HTTP 403 解析失败" in body
    assert "## 疑似静默（3 天零产出）" in body
    assert "静默源（dead）：3 天零产出" in body
    assert "## 报价陈旧（≥2 天未更新）" in body
    assert "锡 现货 停在 2026-09-28（2 天） 来源 ccmn_sn" in body
    assert body.strip().endswith("本邮件由服务器每日抓取后自动发送，规则版本 rv-abc1234567")


def test_build_email_body_skips_empty_sections():
    _, body = alert_health.build_email(
        {"failed": [{"key": "broken", "name": "改版源", "error": "500"}],
         "silent": [], "stale": []}, "rv-abc1234567")
    assert "## 抓取失败" in body
    assert "疑似静默" not in body
    assert "报价陈旧" not in body


def test_build_email_shows_last_nonzero_when_known():
    _, body = alert_health.build_email(
        {"failed": [], "silent": [{"key": "dead", "name": "静默源", "reason": "3 天零产出",
                                   "last_nonzero": "2026-09-20 07:30:00"}], "stale": []},
        "rv-abc1234567")
    assert "最后有产出：2026-09-20 07:30:00" in body


def test_build_email_reports_config_error(tmp_path, monkeypatch):
    _, body = alert_health.build_email(
        {"failed": [{"key": "b", "name": "B", "error": "500"}], "silent": [],
         "stale": [], "config_error": "bad: [unclosed"}, "rv-abc1234567")
    assert "静默检测" in body and "bad: [unclosed" in body


def test_build_email_never_leaks_secrets():
    """邮件里只放问题清单，绝不回显 SMTP 密码/配置内容。"""
    cfg = {"enabled": True, "smtp_host": "smtp.qq.com", "smtp_port": 465,
           "sender": "sender@qq.com", "password": "SUPER-SECRET-PWD",
           "recipient": "boss@qq.com"}
    subject, body = alert_health.build_email(_issues_all_three(), "rv-abc1234567")
    assert "SUPER-SECRET-PWD" not in body
    assert "SUPER-SECRET-PWD" not in subject
    assert cfg["password"] not in subject + body


def test_build_email_uses_compute_rules_version(tmp_path):
    from crawler.rules_version import compute_rules_version
    settings = make_settings(tmp_path)
    (settings.config_dir / "settings.yaml").write_text("port: 8080\n", encoding="utf-8")
    rv = compute_rules_version(settings.config_dir)
    _, body = alert_health.build_email(_issues_all_three(), alert_health.rules_version(settings))
    assert f"规则版本 {rv}" in body


def test_rules_version_degrades_to_unknown(tmp_path):
    """配置目录读不了时降级为"未知"，不能让告警邮件本身炸掉。"""
    class Broken:
        @property
        def config_dir(self):
            raise OSError("config 目录不可读")

    assert alert_health.rules_version(Broken()) == "未知"


# ---------------------------------------------------------------- CLI

class FakeSender:
    def __init__(self, ok=True):
        self.calls = []
        self.ok = ok

    def __call__(self, subject, body, config=None):
        self.calls.append((subject, body))
        return self.ok


def seed_broken(settings, monkeypatch=None):
    patch_sources(monkeypatch, "broken") if monkeypatch else None
    conn = open_db(settings)
    add_source(conn, "broken")
    add_run(conn, "broken", NOW - timedelta(hours=1), status="error", error="HTTP 403")
    conn.close()


def test_run_dry_run_all_clean(tmp_path, monkeypatch, capsys):
    """无问题时 --dry-run 也要明确说"一切正常"，方便人工排查（真的没发信）。"""
    settings = make_settings(tmp_path)
    patch_sources(monkeypatch, "good")
    conn = open_db(settings)
    add_source(conn, "good")
    add_run(conn, "good", NOW - timedelta(hours=1), status="ok", found=9)
    conn.close()
    sender = FakeSender()

    code = alert_health.run(["--dry-run"], settings=settings, sender=sender,
                            config_loader=lambda: {"enabled": True})
    out = capsys.readouterr().out
    assert code == 0
    assert "一切正常，无需告警" in out
    assert sender.calls == []
    assert not alert_health.state_path(settings).exists()


def test_run_dry_run_with_issues_prints_but_sends_nothing(tmp_path, monkeypatch, capsys):
    settings = make_settings(tmp_path)
    seed_broken(settings, monkeypatch)
    sender = FakeSender()

    code = alert_health.run(["--dry-run"], settings=settings, sender=sender,
                            config_loader=lambda: {"enabled": True})
    out = capsys.readouterr().out
    assert code == 0
    assert "数据异常提醒" in out
    assert "改版源" in out
    assert sender.calls == []
    assert not alert_health.state_path(settings).exists()  # 不写状态


def test_run_all_clean_sends_nothing(tmp_path, monkeypatch):
    settings = make_settings(tmp_path)
    patch_sources(monkeypatch, "good")
    conn = open_db(settings)
    add_source(conn, "good")
    add_run(conn, "good", NOW - timedelta(hours=1), status="ok", found=9)
    conn.close()
    sender = FakeSender()

    assert alert_health.run([], settings=settings, sender=sender,
                            config_loader=lambda: {"enabled": True}) == 0
    assert sender.calls == []
    assert not alert_health.state_path(settings).exists()


def test_run_sends_and_marks_state(tmp_path, monkeypatch):
    settings = make_settings(tmp_path)
    seed_broken(settings, monkeypatch)
    sender = FakeSender()

    assert alert_health.run([], settings=settings, sender=sender,
                            config_loader=lambda: {"enabled": True}) == 0
    assert len(sender.calls) == 1
    assert "改版源" in sender.calls[0][1]
    state = json.loads(alert_health.state_path(settings).read_text(encoding="utf-8"))
    assert state["last_signature"] == alert_health.signature_of(
        {"failed": [{"key": "broken", "name": "改版源", "error": "HTTP 403"}],
         "silent": [], "stale": []})


def test_run_skips_when_same_alert_sent_within_24h(tmp_path, monkeypatch, capsys):
    """一天 3 次 cron，同一 signature 只发一次。"""
    settings = make_settings(tmp_path)
    seed_broken(settings, monkeypatch)
    sender = FakeSender()

    assert alert_health.run([], settings=settings, sender=sender,
                            config_loader=lambda: {"enabled": True}) == 0
    assert alert_health.run([], settings=settings, sender=sender,
                            config_loader=lambda: {"enabled": True}) == 0
    out = capsys.readouterr().out
    assert len(sender.calls) == 1
    assert "24" in out


def test_run_force_ignores_dedup(tmp_path, monkeypatch):
    settings = make_settings(tmp_path)
    seed_broken(settings, monkeypatch)
    sender = FakeSender()

    alert_health.run([], settings=settings, sender=sender, config_loader=lambda: {})
    assert alert_health.run(["--force"], settings=settings, sender=sender,
                            config_loader=lambda: {}) == 0
    assert len(sender.calls) == 2


def test_run_does_not_mark_state_when_send_fails(tmp_path, monkeypatch):
    """发信失败不能记成"已发"：否则这一轮的问题会被 24 小时去重吃掉。"""
    settings = make_settings(tmp_path)
    seed_broken(settings, monkeypatch)
    sender = FakeSender(ok=False)

    assert alert_health.run([], settings=settings, sender=sender,
                            config_loader=lambda: {}) == 1
    assert not alert_health.state_path(settings).exists()
    assert alert_health.run([], settings=settings, sender=sender,
                            config_loader=lambda: {}) == 1
    assert len(sender.calls) == 2


def test_run_uses_web_notify_send_mail_and_config(tmp_path, monkeypatch):
    """走 web.notify 的 send_mail/config（不另写 SMTP），密码不会进正文。"""
    import web.notify as notify

    sent = {}

    class FakeSMTP:
        def __init__(self, host, port, timeout=None):
            sent["host"] = host

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def login(self, user, password):
            sent["login"] = (user, password)

        def send_message(self, msg):
            sent["msg"] = msg

    settings = make_settings(tmp_path)
    seed_broken(settings, monkeypatch)
    cfg = {"enabled": True, "smtp_host": "smtp.qq.com", "smtp_port": 465,
           "sender": "sender@qq.com", "password": "SUPER-SECRET-PWD", "recipient": "boss@qq.com"}
    monkeypatch.setattr(notify.smtplib, "SMTP_SSL", FakeSMTP)
    monkeypatch.setattr(notify, "log", lambda message, name="crawler": None)
    loaded = []
    monkeypatch.setattr(alert_health, "load_notify_config",
                        lambda *a, **k: loaded.append(True) or cfg)

    assert alert_health.run([], settings=settings) == 0
    assert loaded == [True]
    assert sent["host"] == "smtp.qq.com"
    assert sent["login"] == ("sender@qq.com", "SUPER-SECRET-PWD")
    assert sent["msg"]["To"] == "boss@qq.com"
    assert "SUPER-SECRET-PWD" not in sent["msg"].get_content()
    assert "数据异常提醒" in str(sent["msg"]["Subject"])


def test_run_reports_db_failure(tmp_path, monkeypatch, capsys):
    """DB 读不了要报错退出，不能静默当"一切正常"（那就是这个任务要消灭的假阴性）。"""
    settings = make_settings(tmp_path)
    patch_sources(monkeypatch, "good")
    (tmp_path / "news.db").mkdir()  # 目录占位，sqlite 打不开
    sender = FakeSender()

    assert alert_health.run([], settings=settings, sender=sender) == 1
    assert "数据库" in capsys.readouterr().out
    assert sender.calls == []


def test_state_path_under_data_dir(tmp_path):
    settings = make_settings(tmp_path)
    assert alert_health.state_path(settings) == tmp_path / ".alert_state.json"
