"""把 MediaCrawler 抓到的社媒数据并入选矿热榜 hot_items。

用法：
  python -m tools.hot_from_media_crawler --platform wb --file <jsonl>
  python -m tools.hot_from_media_crawler --platform zhihu --file <jsonl>
  python -m tools.hot_from_media_crawler --platform dy --file <jsonl>
"""
import argparse
import io
import json
from datetime import datetime
from pathlib import Path

from crawler import store
from crawler.hot import store as hot_store
from crawler.hot.config import load_hot_config, source_conf
from crawler.hot.keywords import classify_category, compute_heat, is_noise, mining_hits

ROOT = Path(__file__).resolve().parent.parent

PLATFORM_MAP = {
    "wb": ("weibo", "微博热搜"),
    "weibo": ("weibo", "微博热搜"),
    "zhihu": ("zhihu", "知乎热榜"),
    "dy": ("douyin", "抖音热榜"),
    "douyin": ("douyin", "抖音热榜"),
}

MAX_TITLE = 200


def _first(row, *keys):
    for k in keys:
        v = row.get(k)
        if v not in (None, "", 0):
            return v
    return ""


def _pub(row):
    d = _first(row, "create_date_time", "created_time", "create_time_str")
    if d:
        s = str(d)
        return s[:16] if len(s) >= 16 else s
    ts = _first(row, "create_time", "created_at", "publish_time")
    if ts:
        try:
            n = int(ts)
            if n > 10_000_000_000:
                n //= 1000
            return datetime.fromtimestamp(n).strftime("%Y-%m-%d %H:%M")
        except (ValueError, OSError):
            pass
    return ""


def _mapper_to_item(row, platform, source_name):
    title = (_first(row, "content", "title", "desc", "text", "content_text") or "").strip()
    url = _first(row, "note_url", "content_url", "url", "share_url", "aweme_url",
                 "article_url")
    author = _first(row, "nickname", "user_nickname", "author_name", "author")
    raw_heat = _first(row, "liked_count", "voteup_count", "digg_count",
                      "like_count", "favorite_count")
    return {
        "title": title[:MAX_TITLE],
        # 保留完整原文，用来做垂直判定（标题清洗后话题标签会丢）
        "summary": title[:600],
        "url": str(url),
        "author": str(author),
        "published_at": _pub(row),
        "raw_heat": raw_heat or None,
    }


# 噪音词判断统一放在 crawler.hot.keywords.is_noise


def ingest(platform: str, path: str, db_path: str) -> dict:
    platform_key, source_name = PLATFORM_MAP[platform]
    cfg = load_hot_config()
    weight = float(source_conf(cfg, platform_key).get("weight", 0.9))

    rows = []
    with io.open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))

    mapped = []
    seen = set()
    for row in rows:
        item = _mapper_to_item(row, platform_key, source_name)
        title = item["title"]
        full = f"{title} {item['summary']}"
        if not title or len(title) < 6 or title in seen:
            continue
        # 入库就卡垂直：全文（含话题标签）不含选矿术语的直接不要
        if is_noise(full):
            continue
        if any(w and w in full for w in cfg.block_terms):
            continue
        if cfg.strict_vertical and cfg.vertical_terms:
            if not any(w and w in full for w in cfg.vertical_terms):
                continue
        seen.add(title)
        mapped.append(item)

    # 按原始热度(点赞/赞/播放)排序，给出名次
    def _heat(x):
        try:
            return float(x.get("raw_heat") or 0)
        except (TypeError, ValueError):
            return 0.0
    mapped.sort(key=_heat, reverse=True)

    items = []
    for i, m in enumerate(mapped):
        text = f"{m['title']} {m['summary']}"
        it = {
            "platform": platform_key,
            "source_name": source_name,
            "title": m["title"],
            "url": m["url"],
            "summary": m["summary"],
            "author": m["author"],
            "published_at": m["published_at"] or hot_store.now_iso(),
            "rank": i + 1,
            "rank_total": len(mapped),
            "raw_heat": m["raw_heat"],
        }
        it["category"] = classify_category(it["title"], cfg)
        # 垂直词优先，其次才是通用矿业词
        vhits = [w for w in cfg.vertical_terms if w in text]
        it["keywords"] = list(dict.fromkeys(
            vhits + [w for w, _ in mining_hits(text, cfg)]))
        it["heat_score"] = compute_heat(it, cfg, source_weight=weight)
        items.append(it)

    conn = store.connect(db_path)
    try:
        store.init_db(conn)
        new, updated = hot_store.upsert_items(conn, items)
        hot_store.purge_noise(conn)
        hot_store.clean_titles(conn)
        hot_store.clean_summaries(conn)
    finally:
        conn.close()
    return {"platform": platform_key, "parsed": len(rows), "kept": len(items),
            "new": new, "updated": updated}


def main(argv=None):
    parser = argparse.ArgumentParser(description="MediaCrawler 结果并入选矿热榜")
    parser.add_argument("--platform", required=True, choices=list(PLATFORM_MAP))
    parser.add_argument("--file", required=True)
    parser.add_argument("--db", default=str(ROOT / "data" / "news.db"))
    args = parser.parse_args(argv)
    result = ingest(args.platform, args.file, args.db)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
