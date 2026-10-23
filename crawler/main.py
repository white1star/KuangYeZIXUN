import argparse
import time
from datetime import datetime, timedelta

from crawler import classify, dedup, parse, price_sources, report, store
from crawler.config import load_settings, load_sources, load_tags
from crawler.fetch import fetch
from crawler.rules_version import compute_rules_version


def _iter_urls(src: dict) -> list:
    return [spec["url"] for spec in _url_specs(src)]


def _url_specs(src: dict) -> list:
    """urls 既可以是字符串，也可以是 {url, commodity_map, ...} 这样的字典。

    字典里的键会在解析时覆盖源级配置：生意社一个品类页对应一个品种，
    用页面级 commodity_map 就不会把钼精矿/钼铁/钼酸铵混成一个"钼"。
    """
    items = src.get("urls") or [src["url"]]
    specs = []
    for item in items:
        if isinstance(item, dict):
            spec = dict(item)
            spec.setdefault("url", src.get("url", ""))
        else:
            spec = {"url": item}
        specs.append(spec)
    return specs


def _drop_stale(items, src):
    days = int((src.get("list") or {}).get("max_age_days") or 0)
    if not days:
        return items
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    return [i for i in items if not i.published_at or i.published_at >= cutoff]


def _process_articles(conn, src, html, base_url, settings, tags, fetcher):
    items = _drop_stale(parse.parse_list(html, src, base_url), src)
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
    return store.upsert_prices(conn, rows), rows


def run_once(settings=None, fetcher=None, sources_dir=None, tags=None) -> dict:
    settings = settings or load_settings()
    tags = tags or load_tags()
    sources = [s for s in load_sources(sources_dir) if s.get("enabled", True)]
    fetcher = fetcher or fetch
    rv = compute_rules_version(settings.config_dir)
    report.log(f"[规则版本] {rv}")
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
                run_id = store.start_crawl_run(conn, src["key"], rv)
                price_rows = []
                for spec in _url_specs(src):
                    url = spec["url"]
                    result = fetcher(url, referer=src.get("referer", ""), encoding=src.get("encoding"),
                                     timeout=settings.request_timeout, retries=settings.request_retries,
                                     method=src.get("method", "GET"), data=src.get("post_data"),
                                     extra_headers=src.get("headers"))
                    last_result = result
                    if not result.ok:
                        raise RuntimeError(result.error or f"HTTP {result.status}")
                    if src["board"] == "price":
                        parse_cfg = {k: v for k, v in {**src, **spec}.items() if k != "url"}
                        price_count, rows = _process_prices(conn, parse_cfg, result.text)
                        price_rows.extend(rows)
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
                if src["board"] == "price" and price_rows:
                    # 整源抓完再对账：源今天没再出的报价要清掉
                    store.sync_price_source_day(conn, src["key"], price_rows)
                    covered = price_sources.covered_commodities(src)
                    if src.get("covered_commodities"):
                        purged = store.purge_uncovered_prices(conn, src["key"], covered)
                        if purged:
                            report.log(f"[{src['key']}] 清理已下架品种的历史报价 {purged} 条")
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
    (settings.data_dir / "crawl.lock").unlink(missing_ok=True)
    return summary


def main():
    parser = argparse.ArgumentParser(description="矿news 抓取器")
    parser.add_argument("--once", action="store_true", help="执行一轮抓取后退出")
    parser.parse_args()
    run_once()


if __name__ == "__main__":
    main()
