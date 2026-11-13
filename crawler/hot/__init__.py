"""选矿热榜抓取入口：python -m crawler.hot --once"""
import argparse
import time

from crawler import report
from crawler import store as news_store
from crawler.config import load_settings
from crawler.hot import sources
from crawler.hot import store as hot_store
from crawler.hot.config import load_hot_config, source_conf
from crawler.hot.keywords import compute_heat


def run_once(settings=None, cfg=None, only=None, fetcher=None) -> dict:
    settings = settings or load_settings()
    cfg = cfg or load_hot_config()
    summary = {"sources_total": 0, "sources_ok": 0, "sources_error": 0,
               "items_found": 0, "items_new": 0, "errors": []}
    if not cfg.enabled:
        return summary
    only = set(only or [])
    conn = news_store.connect(settings.db_path)
    try:
        news_store.init_db(conn)
        sess = sources._session()
        for key, func in sources.FETCHERS.items():
            conf = source_conf(cfg, key)
            if not conf.get("enabled", True) or (only and key not in only):
                continue
            summary["sources_total"] += 1
            run_id = hot_store.start_run(conn, key)
            try:
                items = func(sess, cfg)
                weight = float(conf.get("weight", 0.85))
                for item in items:
                    item["heat_score"] = compute_heat(item, cfg, source_weight=weight)
                new, updated = hot_store.upsert_items(conn, items)
                hot_store.finish_run(conn, run_id, "ok", len(items), new)
                summary["sources_ok"] += 1
                summary["items_found"] += len(items)
                summary["items_new"] += new
                report.log(f"[hot:{key}] {len(items)} 条（新增 {new}，更新 {updated}）")
            except Exception as exc:  # noqa: BLE001 - 单源失败不影响其他源
                hot_store.finish_run(conn, run_id, "error", 0, 0, str(exc))
                summary["sources_error"] += 1
                summary["errors"].append(f"{key}: {exc}")
                report.log(f"[hot:{key}] 失败: {exc}")
            time.sleep(cfg.request_interval)
        removed = hot_store.cleanup(conn, cfg.cleanup_days)
        if removed:
            report.log(f"[hot] 清理过期条目 {removed} 条")
        blocked = hot_store.purge_blocked(conn, cfg.block_terms)
        if blocked:
            report.log(f"[hot] 清除招聘/广告类条目 {blocked} 条")
        noise = hot_store.purge_noise(conn)
        if noise:
            report.log(f"[hot] 清除与矿业无关的噪音 {noise} 条")
        cleaned = hot_store.clean_titles(conn)
        if cleaned:
            report.log(f"[hot] 标题清洗 {cleaned} 条")
        cleaned = hot_store.clean_summaries(conn)
        if cleaned:
            report.log(f"[hot] 摘要清洗 {cleaned} 条")
    finally:
        conn.close()
    report.log("热榜完成：源 {}/{} 成功，抓到 {} 条，新增 {} 条".format(
        summary["sources_ok"], summary["sources_total"],
        summary["items_found"], summary["items_new"]))
    return summary


def main():
    parser = argparse.ArgumentParser(description="选矿热榜抓取器")
    parser.add_argument("--once", action="store_true", help="执行一轮后退出")
    parser.add_argument("--only", help="只抓指定源（逗号分隔）")
    args = parser.parse_args()
    only = {x.strip() for x in (args.only or "").split(",") if x.strip()}
    summary = run_once(only=only or None)
    print("热榜抓取完成：源 {}/{} 成功，抓到 {} 条，新增 {} 条".format(
        summary["sources_ok"], summary["sources_total"],
        summary["items_found"], summary["items_new"]))
    for err in summary["errors"]:
        print("  失败:", err)


if __name__ == "__main__":
    main()
