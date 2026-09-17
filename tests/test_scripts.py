import sqlite3
from datetime import datetime
from pathlib import Path

from scripts import backup, install, watchdog


def test_ps_task_script_contents():
    script = install.ps_task_script("矿news抓取07", r"C:\py\python.exe", "-m scripts.crawl_publish",
                                    r"E:\矿_news", daily_at="07:30")
    assert "Register-ScheduledTask" in script
    assert "矿news抓取07" in script
    assert "-m scripts.crawl_publish" in script
    assert "07:30" in script
    assert "StartWhenAvailable" in script


def test_crawl_tasks_use_crawl_publish():
    assert len(install.CRAWL_TASKS) == 3
    assert install.CRAWL_CMD == "-m scripts.crawl_publish"
    for name, when in install.CRAWL_TASKS:
        script = install.ps_task_script(name, "py.exe", install.CRAWL_CMD, "d", daily_at=when)
        assert "-m scripts.crawl_publish" in script


def test_ps_task_script_logon_and_repeat():
    s1 = install.ps_task_script("矿news网站", "py.exe", "-m web.app", "d", at_logon=True)
    assert "-AtLogOn" in s1
    s2 = install.ps_task_script("矿news看门狗", "py.exe", "-m scripts.watchdog", "d", repeat_minutes=5)
    assert "RepetitionInterval" in s2


def test_netsh_and_powercfg():
    assert install.firewall_rule(8080)[:4] == ["netsh", "advfirewall", "firewall", "add"]
    assert "localport=8080" in install.firewall_rule(8080)
    assert install.disable_sleep() == ["powercfg", "/change", "standby-timeout-ac", "0"]


def test_backup_creates_and_prunes(tmp_path):
    db = tmp_path / "news.db"
    src = sqlite3.connect(str(db))
    src.execute("CREATE TABLE t(x INTEGER)")
    src.execute("INSERT INTO t VALUES (1)")
    src.commit()
    bdir = tmp_path / "backup"
    bdir.mkdir()
    old = bdir / "news_20200101.db"
    old.write_text("old", encoding="utf-8")
    target = backup.run_backup(db, bdir, keep_days=30)
    assert target.exists()
    assert target.name == f"news_{datetime.now().strftime('%Y%m%d')}.db"
    dst = sqlite3.connect(str(target))
    try:
        assert dst.execute("SELECT x FROM t").fetchone()[0] == 1
    finally:
        dst.close()
        src.close()
    assert not old.exists()


def test_watchdog_ok_and_restart(tmp_path, monkeypatch):
    pid_file = tmp_path / "web.pid"
    pid_file.write_text("12345", encoding="utf-8")
    monkeypatch.setattr(watchdog, "http_ok", lambda url, timeout=3: True)
    assert watchdog.check_and_restart("http://x", pid_file) == "ok"

    monkeypatch.setattr(watchdog, "http_ok", lambda url, timeout=3: False)
    killed, started = [], []
    monkeypatch.setattr(watchdog, "kill_pid", lambda pid: killed.append(pid))
    monkeypatch.setattr(watchdog, "start_web", lambda py, wd: started.append((py, wd)))
    assert watchdog.check_and_restart("http://x", pid_file) == "restarted"
    assert killed == [12345]
    assert started
