import argparse
import time

from crawler import classify, dedup, parse, price_sources, report, store
from crawler.config import load_settings, load_sources, load_tags
from crawler.fetch import fetch


def _iter_urls(src: dict) -> list:
    return src.get("urls") or [src["url"]]


def _process_articles(conn, src, html, base_url, settings, tags, fetcher):
    items = parse.parse_list(html, src, base_url)
    detail = src.get("detail") or {}
    if detail.get("enabled"):
        limit = int(detail.get("limit", 10))
        fetched = 0
        for item in items:
            if fetched >= limit:
                break
            if item.summary:
                continue
            result = fetcher(item.url, referer=src.get("referer", ""), encoding=src.get("encoding"),
                             timeout=settings.request_timeout, retries=settings.request_retries)
            if result.ok:
                item.summary = parse.extract_summary(result.text, src, settings.summary_max_chars)
            fetched += 1
            time.sleep(settings.request_interval)
    new = merged = skipped = 0
    for item in items:
        article = {
            "url": item.url,
            "title": item.title,
            "summary": item.summary,
            "source_key": src["key"],
            "published_at": item.published_at,
            "classification": classify.classify(item.title, item.summary, src["board"], tags),
        }
        status = dedup.submit_item(conn, article, threshold=settings.dedup_threshold)
        if status == "new":
            new += 1
        elif status == "merged":
            merged += 1
        else:
            skipped += 1
    report.log(f"[{src['key']}] 解析 {len(items)} 条（新增 {new}，转载合并 {merged}，重复 {skipped}）")
    return len(items), new


def _process_prices(conn, src, text):
    rows = price_sources.parse(src["parser"], text, src)
    return store.upsert_prices(conn, rows)


def run_once(settings=None, fetcher=None, sources_dir=None, tags=None) -> dict:
    settings = settings or load_settings()
    tags = tags or load_tags()
    sources = [s for s in load_sources(sources_dir) if s.get("enabled", True)]
    fetcher = fetcher or fetch
    conn = store.connect(settings.db_path)
    store.init_db(conn)
    summary = {"sources_total": len(sources), "sources_ok": 0, "sources_error": 0,
               "articles_found": 0, "articles_new": 0, "prices": 0, "errors": []}
    try:
        for src in sources:
            run_id = None
            found = new = 0
            last_result = None
            try:
                store.upsert_source(conn, src["key"], src.get("name", src["key"]),
                                    src["board"], _iter_urls(src)[0], True)
                run_id = store.start_crawl_run(conn, src["key"])
                for url in _iter_urls(src):
                    result = fetcher(url, referer=src.get("referer", ""), encoding=src.get("encoding"),
                                     timeout=settings.request_timeout, retries=settings.request_retries)
                    last_result = result
                    if not result.ok:
                        raise RuntimeError(result.error or f"HTTP {result.status}")
                    if src["board"] == "price":
                        price_count = _process_prices(conn, src, result.text)
                        found += price_count
                        new += price_count
                        summary["prices"] += price_count
                    else:
                        item_count, new_count = _process_articles(
                            conn, src, result.text, result.final_url or url, settings, tags, fetcher)
                        found += item_count
                        new += new_count
                        summary["articles_found"] += item_count
                        summary["articles_new"] += new_count
                    time.sleep(settings.request_interval)
                store.finish_crawl_run(conn, run_id, "ok", found, new)
                summary["sources_ok"] += 1
                report.log(f"[{src['key']}] 完成：抓到 {found} 条，新增 {new} 条")
            except Exception as e:
                if last_result is not None and last_result.text:
                    snap = report.save_snapshot(src["key"], last_result.text)
                    report.prune_snapshots(src["key"], keep=3)
                    report.log(f"[{src['key']}] 原始响应已存快照 {snap.name}")
                if run_id is not None:
                    store.finish_crawl_run(conn, run_id, "error", found, new, str(e))
                summary["sources_error"] += 1
                summary["errors"].append(f"{src['key']}: {e}")
                report.log(f"[{src['key']}] 失败: {e}")
    finally:
        conn.close()
    report.log("本轮完成：源 {}/{} 成功，新增文章 {}，价格 {} 条".format(
        summary["sources_ok"], summary["sources_total"],
        summary["articles_new"], summary["prices"]))
    return summary


def main():
    parser = argparse.ArgumentParser(description="矿news 抓取器")
    parser.add_argument("--once", action="store_true", help="执行一轮抓取后退出")
    parser.parse_args()
    run_once()


if __name__ == "__main__":
    main()
