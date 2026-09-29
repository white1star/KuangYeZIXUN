import sqlite3

import pytest

from scripts.backup import run_backup, verify_backup


def _mkdb(path, rows=3):
    conn = sqlite3.connect(path)
    conn.executescript("CREATE TABLE articles(id INTEGER PRIMARY KEY, title TEXT);")
    conn.executemany("INSERT INTO articles(title) VALUES(?)", [("t%d" % i,) for i in range(rows)])
    conn.commit()
    conn.close()
    return path


def test_verify_ok(tmp_path):
    src = _mkdb(tmp_path / "news.db", rows=5)
    target = run_backup(src, tmp_path / "backup")
    ok, why = verify_backup(src, target)
    assert ok, why


def test_verify_detects_row_mismatch(tmp_path):
    src = _mkdb(tmp_path / "news.db", rows=5)
    target = run_backup(src, tmp_path / "backup")
    conn = sqlite3.connect(target)
    conn.execute("DELETE FROM articles WHERE id > 2")   # 模拟备份不完整
    conn.commit()
    conn.close()
    ok, why = verify_backup(src, target)
    assert not ok and "条数" in why


def test_backup_deleted_when_verify_fails(tmp_path, monkeypatch):
    src = _mkdb(tmp_path / "news.db", rows=5)
    monkeypatch.setattr("scripts.backup.verify_backup", lambda s, b: (False, "模拟校验失败"))
    with pytest.raises(RuntimeError, match="备份校验失败"):
        run_backup(src, tmp_path / "backup")
    assert list((tmp_path / "backup").glob("news_*.db")) == []   # 坏备份必须删掉
