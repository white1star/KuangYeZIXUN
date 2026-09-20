"""把 video_inbox 里「从视频号链接下载」的视频本地转录，回填到对应链接条目。

场景：先用 `python -m tools.fetch_sph <链接>` 建了简介条目，再用
`python -m tools.wxvideo_download <链接> --download` 下载了同一视频——
本工具转录后把完整口播写回该链接条目（按短链幂等，不产生重复记录）。

用法：
  python -m tools.transcribe_inbox              # 处理收件箱全部（需 .json 旁车且含 link）
  python -m tools.transcribe_inbox --dry-run    # 只列出将要处理的文件
  python -m tools.transcribe_inbox --keep-files # 保留文件（默认移入 已处理/日期/）

说明：缺少旁车 link 或库里没有对应链接条目的文件会被跳过并提示，不新建条目。
"""

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from crawler import store
from crawler.transcribe import transcribe_media

INBOX_DIR = ROOT / "video_inbox"
DONE_DIR_NAME = "已处理"
MEDIA_EXTS = {".mp4", ".mov", ".mkv", ".m4v", ".avi", ".wmv", ".wav", ".mp3"}
STABLE_SECONDS = 5.0
PREVIEW_CHARS = 60
MIN_SPEECH_CHARS = 4


def default_ocr():
    from tools.video_ocr import ocr_video

    def run_ocr(path) -> str:
        return " ".join(ocr_video(path))

    return run_ocr


def short_uri_from_link(link: str) -> str:
    link = (link or "").strip()
    if not link:
        return ""
    return link.rstrip("/").split("/")[-1].split("?")[0]


def load_sidecar(path: Path) -> dict:
    sidecar = path.with_name(path.name + ".json")
    if not sidecar.is_file():
        return {}
    try:
        data = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def is_stable(path: Path, wait=STABLE_SECONDS, sleeper=time.sleep) -> bool:
    try:
        first = path.stat().st_size
        sleeper(wait)
        second = path.stat().st_size
    except OSError:
        return False
    return first > 0 and first == second


def scan_inbox(inbox: Path) -> list:
    inbox.mkdir(parents=True, exist_ok=True)
    done_root = inbox / DONE_DIR_NAME
    files = []
    for path in sorted(inbox.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in MEDIA_EXTS:
            continue
        if done_root in path.parents:
            continue
        if not load_sidecar(path):
            continue
        if is_stable(path):
            files.append(path)
    return files


def run(inbox=INBOX_DIR, db_path=None, dry_run=False, keep_files=False, show=print, ocr=None) -> int:
    db_path = Path(db_path) if db_path else ROOT / "data" / "news.db"
    files = scan_inbox(Path(inbox))
    if not files:
        show("收件箱没有带来源信息的视频文件")
        return 0

    conn = store.connect(db_path)
    failures = 0
    ocr_runner = ocr
    try:
        store.init_db(conn)
        rows = {row["short_uri"]: row for row in store.list_marketing_copy(conn, 1000)}
        for path in files:
            meta = load_sidecar(path)
            short_uri = short_uri_from_link(meta.get("link", ""))
            label = short_uri or path.name
            if dry_run:
                hit = "命中" if short_uri in rows else "无对应条目"
                show(f"[预览] {label} | {hit}")
                continue
            if not short_uri:
                failures += 1
                show(f"[跳过] {path.name} | 旁车缺少 link，无法匹配条目")
                continue
            row = rows.get(short_uri)
            if not row:
                failures += 1
                show(f"[跳过] {label} | 库中没有对应链接条目（先跑 fetch_sph）")
                continue
            try:
                text = (transcribe_media(path) or "").strip()
            except Exception as exc:  # noqa: BLE001 - 单条失败不中断
                failures += 1
                show(f"[失败] {label} | {exc}")
                continue
            source = "口播"
            if len(text) < MIN_SPEECH_CHARS:
                if ocr_runner is None:
                    ocr_runner = default_ocr()
                try:
                    ocr_text = (ocr_runner(path) or "").strip()
                except Exception as exc:  # noqa: BLE001 - OCR 失败不中断
                    ocr_text = ""
                    show(f"[提示] {label} | 画面文字识别失败：{exc}")
                if len(ocr_text) > len(text):
                    text = ocr_text
                    source = "画面文字"
            if not text:
                failures += 1
                show(f"[失败] {label} | 转录与画面文字均为空")
                continue
            store.update_marketing_transcript(conn, row["id"], text)
            rows[short_uri] = dict(row, transcript=text)
            show(f"[OK·{source}] {label} | id={row['id']} | {len(text)} 字 | {text.replace(chr(10), ' ')[:PREVIEW_CHARS]}")
            if not keep_files:
                day = datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d")
                done_dir = Path(inbox) / DONE_DIR_NAME / day
                done_dir.mkdir(parents=True, exist_ok=True)
                sidecar = path.with_name(path.name + ".json")
                path.replace(done_dir / path.name)
                if sidecar.is_file():
                    sidecar.replace(done_dir / sidecar.name)
    finally:
        conn.close()
    return 1 if failures else 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="把收件箱里链接下载的视频转录并回填到对应链接条目")
    parser.add_argument("--inbox", default=str(INBOX_DIR), help="收件箱目录（默认 video_inbox）")
    parser.add_argument("--db", default=str(ROOT / "data" / "news.db"), help="SQLite 数据库路径")
    parser.add_argument("--dry-run", action="store_true", help="只列出将要处理的文件")
    parser.add_argument("--keep-files", action="store_true", help="处理后不移动文件")
    args = parser.parse_args(argv)
    return run(inbox=Path(args.inbox), db_path=args.db, dry_run=args.dry_run, keep_files=args.keep_files)


if __name__ == "__main__":
    raise SystemExit(main())
