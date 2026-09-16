import dataclasses
from datetime import datetime

from crawler.config import load_settings
from scripts import ai_check, ai_run


def make_settings(tmp_path):
    logs = tmp_path / "logs"
    logs.mkdir()
    return dataclasses.replace(load_settings(), db_path=tmp_path / "news.db",
                               data_dir=tmp_path, logs_dir=logs)


def test_ai_run_all_ok(tmp_path, monkeypatch, capsys):
    settings = make_settings(tmp_path)
    calls = []

    def fake_runner(s):
        calls.append("run")
        return {"sources_total": 2, "sources_ok": 2, "sources_error": 0,
                "articles_found": 3, "articles_new": 1, "prices": 2, "errors": []}

    def fake_report(s):
        calls.append("report")
        return ("# 假报告", [], 0)

    monkeypatch.setattr(ai_check, "generate_report", fake_report)
    code = ai_run.run(runner=fake_runner, settings=settings)
    out = capsys.readouterr().out
    assert calls == ["run", "report"]
    assert code == 0
    assert "2/2 成功" in out
    assert "下一步建议" in out
    assert "一切正常" in out
    path = settings.logs_dir / ("ai_check_" + datetime.now().strftime("%Y%m%d") + ".md")
    assert path.read_text(encoding="utf-8") == "# 假报告"


def test_ai_run_with_failure(tmp_path, monkeypatch, capsys):
    settings = make_settings(tmp_path)
    calls = []

    def fake_runner(s):
        calls.append("run")
        return {"sources_total": 2, "sources_ok": 1, "sources_error": 1,
                "articles_found": 3, "articles_new": 1, "prices": 2,
                "errors": ["bad: HTTP 403"]}

    def fake_report(s):
        calls.append("report")
        return ("# 假报告", ["源「坏源」(bad) 抓取失败：HTTP 403"], 1)

    monkeypatch.setattr(ai_check, "generate_report", fake_report)
    code = ai_run.run(runner=fake_runner, settings=settings)
    out = capsys.readouterr().out
    assert calls == ["run", "report"]
    assert code == 1
    assert "bad: HTTP 403" in out
    assert "修源四步法" in out
    assert "docs/ai-maintenance.md" in out


def test_ai_run_runner_error_without_report_issue(tmp_path, monkeypatch, capsys):
    settings = make_settings(tmp_path)

    def fake_runner(s):
        return {"sources_total": 1, "sources_ok": 0, "sources_error": 1,
                "articles_found": 0, "articles_new": 0, "prices": 0, "errors": ["bad: 超时"]}

    monkeypatch.setattr(ai_check, "generate_report", lambda s: ("# 假报告", [], 0))
    code = ai_run.run(runner=fake_runner, settings=settings)
    out = capsys.readouterr().out
    assert code == 1
    assert "修源四步法" in out
