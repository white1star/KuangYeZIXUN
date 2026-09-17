import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from crawler import store

SHARE_PREFIX = "https://weixin.qq.com/sph/"
PREVIEW_URL = "https://channels.weixin.qq.com/finder-preview/pages/sph?id={}"
FEED_API_KEY = "get_feed_info"
WAIT_INTERVAL_MS = 500
DEFAULT_TIMEOUT_MS = 30000
PREVIEW_CHARS = 40


def normalize_short_uri(value) -> str:
    text = (value or "").strip()
    if not text:
        return ""
    parsed = urlparse(text if "://" in text else "https://" + text)
    query = parse_qs(parsed.query)
    if query.get("id"):
        return query["id"][0].strip()
    path = parsed.path.strip("/")
    if path.startswith("sph/"):
        return path.split("/", 1)[1].split("/")[0]
    if "://" not in text and "/" not in text and " " not in text:
        return text
    return ""


def parse_feed_payload(payload) -> dict:
    if not isinstance(payload, dict):
        return {"author": "", "description": "", "published_at": "", "cover_url": ""}
    data = payload.get("data")
    if not isinstance(data, dict):
        data = payload
    feed = data.get("feedInfo")
    feed = feed if isinstance(feed, dict) else {}
    author = data.get("authorInfo")
    author = author if isinstance(author, dict) else {}
    published_at = ""
    raw_time = feed.get("createtime")
    if raw_time:
        try:
            published_at = datetime.fromtimestamp(int(raw_time)).strftime("%Y-%m-%d %H:%M")
        except (TypeError, ValueError, OSError):
            published_at = ""
    return {
        "author": str(author.get("nickname") or "").strip(),
        "description": str(feed.get("description") or "").strip(),
        "published_at": published_at,
        "cover_url": str(feed.get("coverUrl") or "").strip(),
    }


def fetch_feed(short_uri, timeout_ms=DEFAULT_TIMEOUT_MS) -> dict:
    from playwright.sync_api import sync_playwright

    captured = {}

    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page()

        def on_response(response):
            if FEED_API_KEY in response.url and "payload" not in captured:
                try:
                    captured["payload"] = response.json()
                except Exception:
                    try:
                        captured["payload"] = json.loads(response.text())
                    except Exception:
                        pass

        page.on("response", on_response)
        try:
            page.goto(PREVIEW_URL.format(short_uri), wait_until="domcontentloaded", timeout=timeout_ms)
            waited = 0
            while "payload" not in captured and waited < timeout_ms:
                page.wait_for_timeout(WAIT_INTERVAL_MS)
                waited += WAIT_INTERVAL_MS
        finally:
            browser.close()

    if "payload" not in captured:
        raise RuntimeError("未捕获到 get_feed_info 响应（页面结构可能已变化）")
    info = parse_feed_payload(captured["payload"])
    if not info["description"]:
        raise RuntimeError("接口响应中没有文案内容（可能已删除或需登录）")
    info["short_uri"] = short_uri
    info["link"] = SHARE_PREFIX + short_uri
    return info


def run(links, db_path=None) -> int:
    db = Path(db_path) if db_path else ROOT / "data" / "news.db"
    conn = store.connect(db)
    store.init_db(conn)
    failures = 0
    try:
        for raw in links:
            short_uri = normalize_short_uri(raw)
            if not short_uri:
                print(f"失败 | {raw} | 无法识别的链接，支持分享链接或 shortUri")
                failures += 1
                continue
            try:
                info = fetch_feed(short_uri)
            except Exception as exc:
                print(f"失败 | {short_uri} | {exc}")
                failures += 1
                continue
            store.upsert_marketing_copy(conn, info)
            preview = info["description"].replace("\n", " ")[:PREVIEW_CHARS]
            print(f"{info['published_at'] or '未知时间'} | {info['author'] or '未知作者'} | {preview}")
    finally:
        conn.close()
    return 1 if failures else 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="抓取微信视频号分享链接的文案并入库")
    parser.add_argument("links", nargs="+", help="视频号分享链接或 shortUri")
    parser.add_argument("--db", default=str(ROOT / "data" / "news.db"), help="SQLite 数据库路径")
    args = parser.parse_args(argv)
    return run(args.links, db_path=args.db)


if __name__ == "__main__":
    raise SystemExit(main())
