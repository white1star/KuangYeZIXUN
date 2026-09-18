from datetime import datetime

from crawler import store
from tools import process_videos


def make_inbox(tmp_path):
    inbox = tmp_path / "video_inbox"
    inbox.mkdir()
    return inbox


def no_sleep(_seconds):
    pass


def count_copies(db):
    conn = store.connect(db)
    total = conn.execute("SELECT COUNT(*) c FROM marketing_copy").fetchone()["c"]
    conn.close()
    return total


def test_process_moves_and_saves(tmp_path, capsys):
    inbox = make_inbox(tmp_path)
    video = inbox / "矿山现场.mp4"
    video.write_bytes(b"fake-video-bytes")
    mtime = video.stat().st_mtime
    db = tmp_path / "t.db"
    code = process_videos.run(inbox=inbox, db_path=db, author="计算机选矿",
                              transcriber=lambda path: "大家好，欢迎来到矿山现场。",
                              sleeper=no_sleep, wait=0)
    assert code == 0
    output = capsys.readouterr().out
    assert "[OK] 矿山现场.mp4" in output
    assert "大家好，欢迎来到矿山现场。" in output
    assert not video.exists()
    day = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d")
    moved = inbox / "已处理" / day / "矿山现场.mp4"
    assert moved.exists()
    conn = store.connect(db)
    row = conn.execute("SELECT * FROM marketing_copy").fetchone()
    assert row["short_uri"] == "file:矿山现场.mp4"
    assert row["transcript"] == "大家好，欢迎来到矿山现场。"
    assert row["author"] == "计算机选矿"
    assert row["description"] == ""
    assert row["cover_url"] == ""
    assert row["link"] == ""
    expected = datetime.fromtimestamp(moved.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
    assert row["published_at"] == expected
    conn.close()


def test_ocr_fallback_when_transcript_empty(tmp_path, capsys):
    inbox = make_inbox(tmp_path)
    video = inbox / "无声视频.mp4"
    video.write_bytes(b"fake-video-bytes")
    db = tmp_path / "t.db"
    code = process_videos.run(inbox=inbox, db_path=db, author="作者",
                              transcriber=lambda path: "",
                              ocr=lambda path: "画面文字文案",
                              sleeper=no_sleep, wait=0)
    assert code == 0
    output = capsys.readouterr().out
    assert "[OK-OCR] 无声视频.mp4" in output
    assert not video.exists()
    conn = store.connect(db)
    row = conn.execute("SELECT * FROM marketing_copy").fetchone()
    assert row["transcript"] == "画面文字文案"
    conn.close()


def test_both_transcript_and_ocr_empty_fails(tmp_path, capsys):
    inbox = make_inbox(tmp_path)
    video = inbox / "空白视频.mp4"
    video.write_bytes(b"x")
    code = process_videos.run(inbox=inbox, db_path=tmp_path / "t.db", author="作者",
                              transcriber=lambda path: "",
                              ocr=lambda path: "  ",
                              sleeper=no_sleep, wait=0)
    assert code == 1
    assert "[失败] 空白视频.mp4" in capsys.readouterr().out
    assert video.exists()
    assert count_copies(tmp_path / "t.db") == 0


def test_second_run_is_idempotent(tmp_path):
    inbox = make_inbox(tmp_path)
    (inbox / "第一条.mp4").write_bytes(b"x")
    db = tmp_path / "t.db"
    calls = []

    def transcriber(path):
        calls.append(path.name)
        return "文案一"

    assert process_videos.run(inbox=inbox, db_path=db, author="作者", transcriber=transcriber,
                              sleeper=no_sleep, wait=0) == 0
    assert process_videos.run(inbox=inbox, db_path=db, author="作者", transcriber=transcriber,
                              sleeper=no_sleep, wait=0) == 0
    assert calls == ["第一条.mp4"]
    assert count_copies(db) == 1


def test_failure_does_not_stop_others(tmp_path, capsys):
    inbox = make_inbox(tmp_path)
    bad = inbox / "坏文件.mp4"
    good = inbox / "好文件.mp4"
    bad.write_bytes(b"x")
    good.write_bytes(b"y")
    db = tmp_path / "t.db"

    def transcriber(path):
        if path.name == "坏文件.mp4":
            raise RuntimeError("模型加载失败")
        return "好文件文案"

    code = process_videos.run(inbox=inbox, db_path=db, author="作者", transcriber=transcriber,
                              sleeper=no_sleep, wait=0)
    assert code == 1
    output = capsys.readouterr().out
    assert "[失败] 坏文件.mp4" in output
    assert "模型加载失败" in output
    assert "[OK] 好文件.mp4" in output
    assert bad.exists()
    assert not list((inbox / "已处理").rglob("坏文件.mp4"))
    assert list((inbox / "已处理").rglob("好文件.mp4"))
    assert count_copies(db) == 1


def test_skips_growing_file(tmp_path):
    inbox = make_inbox(tmp_path)
    growing = inbox / "写入中.mp4"
    growing.write_bytes(b"a")

    def sleeper(_seconds):
        growing.write_bytes(b"ab")

    code = process_videos.run(inbox=inbox, db_path=tmp_path / "t.db", author="作者",
                              transcriber=lambda path: "不应被调用",
                              sleeper=sleeper, wait=0)
    assert code == 0
    assert growing.exists()
    assert not list((inbox / "已处理").rglob("写入中.mp4"))
    assert not (tmp_path / "t.db").exists()


def test_scans_subfolders_and_archives_by_date(tmp_path, capsys):
    inbox = make_inbox(tmp_path)
    day_dir = inbox / "2026-09-17"
    day_dir.mkdir()
    video = day_dir / "现场视频.mp4"
    video.write_bytes(b"x")
    mtime = video.stat().st_mtime
    db = tmp_path / "t.db"
    code = process_videos.run(inbox=inbox, db_path=db, author="作者",
                              transcriber=lambda path: "子文件夹里的口播文案",
                              sleeper=no_sleep, wait=0)
    assert code == 0
    assert not video.exists()
    archived = list((inbox / "已处理").rglob("现场视频.mp4"))
    assert len(archived) == 1
    expected_day = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d")
    assert archived[0].parent.name == expected_day
    assert count_copies(db) == 1
    assert "子文件夹里的口播文案" in capsys.readouterr().out


def test_ignores_unsupported_and_subdirs(tmp_path):
    inbox = make_inbox(tmp_path)
    (inbox / "说明.txt").write_text("不是媒体", encoding="utf-8")
    (inbox / "已处理").mkdir()
    (inbox / "已处理" / "旧文件.mp4").write_bytes(b"x")
    db = tmp_path / "t.db"
    code = process_videos.run(inbox=inbox, db_path=db, author="作者",
                              transcriber=lambda path: "文案", sleeper=no_sleep, wait=0)
    assert code == 0
    assert not db.exists()


def seed_copy(db, short_uri="file:测试.mp4", transcript="", description="简介"):
    conn = store.connect(db)
    store.init_db(conn)
    store.upsert_marketing_copy(conn, {
        "short_uri": short_uri, "author": "计算机选矿", "description": description,
        "transcript": transcript, "published_at": "2026-09-17 10:00",
        "cover_url": "", "link": "", "fetched_at": store.now_iso()})
    row_id = conn.execute("SELECT id FROM marketing_copy WHERE short_uri=?", (short_uri,)).fetchone()["id"]
    conn.close()
    return row_id


def test_fix_updates_transcript(tmp_path, capsys):
    db = tmp_path / "t.db"
    row_id = seed_copy(db, transcript="错别字文案")
    code = process_videos.main(["--db", str(db), "--fix", str(row_id), "校对后的文案"])
    assert code == 0
    assert "已更新" in capsys.readouterr().out
    conn = store.connect(db)
    assert conn.execute("SELECT transcript FROM marketing_copy WHERE id=?",
                        (row_id,)).fetchone()["transcript"] == "校对后的文案"
    conn.close()


def test_fix_unknown_id_returns_error(tmp_path, capsys):
    db = tmp_path / "t.db"
    seed_copy(db)
    code = process_videos.main(["--db", str(db), "--fix", "99999", "新文案"])
    assert code == 1
    assert "未找到" in capsys.readouterr().out


def test_list_shows_recent_entries(tmp_path, capsys):
    db = tmp_path / "t.db"
    seed_copy(db, transcript="口播文案正文")
    code = process_videos.main(["--db", str(db), "--list", "5"])
    assert code == 0
    output = capsys.readouterr().out
    assert "file:测试.mp4" in output
    assert "2026-09-17 10:00" in output
    assert "口播文案正文" in output


def test_empty_lists_missing_transcripts(tmp_path, capsys):
    db = tmp_path / "t.db"
    seed_copy(db, short_uri="file:有文案.mp4", transcript="已有转录")
    seed_copy(db, short_uri="file:缺文案.mp4", transcript="")
    code = process_videos.main(["--db", str(db), "--empty"])
    assert code == 0
    output = capsys.readouterr().out
    assert "file:缺文案.mp4" in output
    assert "file:有文案.mp4" not in output
    assert "1 条缺少转录文案" in output


def test_config_author_used_by_default(tmp_path, monkeypatch):
    captured = {}

    def fake_upsert(conn, item):
        captured.update(item)
        return 1

    monkeypatch.setattr(process_videos.store, "upsert_marketing_copy", fake_upsert)
    monkeypatch.setattr(process_videos.store, "connect", lambda db: _FakeConn())
    monkeypatch.setattr(process_videos.store, "init_db", lambda conn: None)
    inbox = make_inbox(tmp_path)
    (inbox / "视频.mp4").write_bytes(b"x")
    code = process_videos.run(inbox=inbox, db_path=tmp_path / "t.db",
                              transcriber=lambda path: "文案", sleeper=no_sleep, wait=0)
    assert code == 0
    assert captured["author"] == process_videos.load_marketing_settings()["author"]


class _FakeConn:
    def close(self):
        pass
