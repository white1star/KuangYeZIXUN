import json

from crawler import store
from scripts.apply_marketing import apply, export


def seed(db, short_uri="AIUEY9XuiH", transcript="文案正文", author="计算机选矿"):
    conn = store.connect(db)
    store.init_db(conn)
    store.upsert_marketing_copy(conn, {
        "short_uri": short_uri, "author": author, "description": "简介",
        "transcript": transcript, "published_at": "2026-09-18 12:48",
        "cover_url": "https://e.com/c.jpg", "link": "https://weixin.qq.com/sph/" + short_uri,
        "fetched_at": store.now_iso()})
    conn.close()


def test_export_apply_roundtrip(tmp_path):
    src = tmp_path / "src.db"
    seed(src)
    out = tmp_path / "marketing.json"
    assert export(src, out) == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert len(data) == 1
    assert data[0]["short_uri"] == "AIUEY9XuiH"
    assert data[0]["link"] == "https://weixin.qq.com/sph/AIUEY9XuiH"

    dst = tmp_path / "dst.db"
    seed(dst, short_uri="file:旧数据.mp4", transcript="旧文案")
    assert apply(out, dst) == 0

    conn = store.connect(dst)
    rows = conn.execute("SELECT short_uri, transcript, link FROM marketing_copy").fetchall()
    conn.close()
    assert len(rows) == 1
    assert rows[0]["short_uri"] == "AIUEY9XuiH"
    assert rows[0]["transcript"] == "文案正文"


def test_apply_replaces_existing_rows(tmp_path):
    src = tmp_path / "src.db"
    seed(src, short_uri="file:视频.mp4", transcript="画面文字文案")
    out = tmp_path / "marketing.json"
    export(src, out)

    dst = tmp_path / "dst.db"
    seed(dst, short_uri="file:更旧的.mp4", transcript="更旧文案")
    apply(out, dst)
    apply(out, dst)

    conn = store.connect(dst)
    total = conn.execute("SELECT COUNT(*) c FROM marketing_copy").fetchone()["c"]
    conn.close()
    assert total == 1
