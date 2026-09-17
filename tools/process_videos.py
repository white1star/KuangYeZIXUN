import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from crawler import store
from crawler.config import load_marketing_settings
from crawler.transcribe import transcribe_media

INBOX_DIR = ROOT / "video_inbox"
DONE_DIR_NAME = "已处理"
MEDIA_EXTS = {".mp4", ".mov", ".mkv", ".m4v", ".avi", ".wmv", ".wav", ".mp3"}
STABLE_SECONDS = 5.0
PREVIEW_CHARS = 40
LIST_PREVIEW_CHARS = 60
EMPTY_SCAN_LIMIT = 1000


def _fmt_time(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M")


def is_stable(path: Path, wait=STABLE_SECONDS, sleeper=time.sleep) -> bool:
    try:
        first = path.stat().st_size
        sleeper(wait)
        second = path.stat().st_size
    except OSError:
        return False
    return first > 0 and first == second


def scan_inbox(inbox: Path, wait=STABLE_SECONDS, sleeper=time.sleep) -> list:
    inbox.mkdir(parents=True, exist_ok=True)
    files = []
    for path in sorted(inbox.iterdir()):
        if path.is_file() and path.suffix.lower() in MEDIA_EXTS and is_stable(path, wait, sleeper):
            files.append(path)
    return files


def process_file(path: Path, conn, author: str, transcriber) -> tuple:
    published_at = _fmt_time(path)
    text = (transcriber(path) or "").strip()
    if not text:
        raise RuntimeError("转录结果为空")
    store.upsert_marketing_copy(conn, {
        "short_uri": f"file:{path.name}",
        "author": author,
        "description": "",
        "transcript": text,
        "published_at": published_at,
        "cover_url": "",
        "link": "",
        "fetched_at": store.now_iso(),
    })
    done_dir = path.parent / DONE_DIR_NAME
    done_dir.mkdir(exist_ok=True)
    target = done_dir / path.name
    if target.exists():
        target = done_dir / f"{path.stem}_{int(time.time())}{path.suffix}"
    path.replace(target)
    return published_at, text


def run(inbox=None, db_path=None, transcriber=None, sleeper=None,
        wait=STABLE_SECONDS, author=None, show=print) -> int:
    inbox = Path(inbox) if inbox else INBOX_DIR
    db = Path(db_path) if db_path else ROOT / "data" / "news.db"
    transcriber = transcriber or transcribe_media
    sleeper = sleeper or time.sleep
    if author is None:
        author = str(load_marketing_settings().get("author") or "")
    files = scan_inbox(inbox, wait=wait, sleeper=sleeper)
    if not files:
        show("收件箱没有新的媒体文件")
        return 0
    conn = store.connect(db)
    store.init_db(conn)
    failures = 0
    try:
        for path in files:
            try:
                published_at, text = process_file(path, conn, author, transcriber)
            except Exception as exc:
                failures += 1
                show(f"[失败] {path.name} | {exc}")
                continue
            preview = text.replace("\n", " ")[:PREVIEW_CHARS]
            show(f"[OK] {path.name} | {published_at} | {preview}")
    finally:
        conn.close()
    return 1 if failures else 0


def cmd_list(conn, limit, show=print) -> int:
    rows = store.list_marketing_copy(conn, limit)
    if not rows:
        show("文案库为空")
        return 0
    for row in rows:
        text = (row["transcript"] or row["description"] or "").replace("\n", " ")
        show(f"{row['id']} | {row['short_uri']} | {row['published_at']} | {text[:LIST_PREVIEW_CHARS]}")
    return 0


def cmd_fix(conn, copy_id, text, show=print) -> int:
    cleaned = (text or "").strip()
    if not cleaned:
        show("新文案不能为空")
        return 1
    if not store.update_marketing_transcript(conn, copy_id, cleaned):
        show(f"未找到 id={copy_id} 的文案条目")
        return 1
    show(f"已更新 id={copy_id} 的转录文案（{len(cleaned)} 字）")
    return 0


def cmd_empty(conn, show=print) -> int:
    rows = store.list_marketing_copy(conn, EMPTY_SCAN_LIMIT)
    empties = [row for row in rows if not (row["transcript"] or "").strip()]
    if not empties:
        show("没有缺少转录文案的条目")
        return 0
    for row in empties:
        desc = (row["description"] or "").replace("\n", " ")
        show(f"{row['id']} | {row['short_uri']} | {row['published_at']} | {desc[:LIST_PREVIEW_CHARS]}")
    show(f"共 {len(empties)} 条缺少转录文案，可用 --fix <id> <新文案> 补上")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="把收件箱里的视频文件转录成文案并入库")
    parser.add_argument("--inbox", default=str(INBOX_DIR), help="收件箱目录（默认 video_inbox）")
    parser.add_argument("--db", default=str(ROOT / "data" / "news.db"), help="SQLite 数据库路径")
    parser.add_argument("--list", dest="list_limit", type=int, metavar="N", help="列出最近 N 条文案")
    parser.add_argument("--fix", nargs=2, metavar=("ID", "新文案"), help="按 id 更新转录文案（AI 校对）")
    parser.add_argument("--empty", action="store_true", help="显示缺少转录文案的条目")
    args = parser.parse_args(argv)
    if args.fix or args.list_limit is not None or args.empty:
        conn = store.connect(args.db)
        try:
            store.init_db(conn)
            if args.fix:
                return cmd_fix(conn, int(args.fix[0]), args.fix[1])
            if args.list_limit is not None:
                return cmd_list(conn, args.list_limit)
            return cmd_empty(conn)
        finally:
            conn.close()
    return run(inbox=args.inbox, db_path=args.db)


if __name__ == "__main__":
    raise SystemExit(main())
