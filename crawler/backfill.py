import argparse
import time
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from crawler import classify, dedup, parse, report, store
from crawler.config import load_settings, load_sources, load_tags
from crawler.fetch import fetch

NEXT_TEXTS = {"下一页", "下页", "后一页", "Next", "next", "»", "›"}


def find_next_url(html, current_url):
    soup = BeautifulSoup(html, "lxml")
    for a in soup.find_all("a"):
        text = a.get_text(strip=True)
        if text in NEXT_TEXTS:
            href = (a.get("href") or "").strip()
            if href and not href.lower().startswith(("javascript:", "#")):
                return urljoin(current_url, href)
    for a in soup.find_all("a"):
        rel = " ".join(a.get("rel") or []).lower()
        if "next" in rel:
            href = (a.get("href") or "").strip()
            if href:
                return urljoin(current_url, href)
    return ""


def probe_candidates(base_url, n):
    b = base_url.rstrip("/")
    for tail in ("/index.html", "/index.htm", "/index.shtml"):
        if b.lower().endswith(tail):
            b = b[: -len(tail)]
            break
    if b.lower().endswith((".html", ".htm", ".shtml", ".aspx")):
        return []
    return [f"{b}/index_{n}.html", f"{b}/index_{n}.htm", f"{b}/index_{n}.shtml"]


def keep_item(item, since):
    if not item.published_at:
        return True
    return item.published_at >= since


def page_all_older(items, since):
    dated = [i for i in items if i.published_at]
    if not dated:
        return False
    return all(i.published_at < since for i in dated)


def crawl_source(conn, src, settings, tags, fetcher, since, max_pages, sleep=time.sleep):
    run_id = store.start_crawl_run(conn, src["key"])
    pages_cfg = src.get("pages") or {}
    tpl = pages_cfg.get("template")
    total_max = int(pages_cfg.get("max_pages") or max_pages or 80)
    if max_pages:
        total_max = min(total_max, max_pages)
    start_n = int(pages_cfg.get("offset") or 1)
    stats = {"pages": 0, "found": 0, "new": 0, "merged": 0, "skipped": 0,
             "oldest": "", "stopped": "", "error": ""}
    seen_urls = set()
    current_url = src["url"]
    html = ""
    zero_streak = 0
    try:
        result = fetcher(current_url, referer=src.get("referer", ""), encoding=src.get("encoding"),
                         timeout=settings.request_timeout, retries=settings.request_retries)
        if not result.ok:
            raise RuntimeError(result.error or f"HTTP {result.status}")
        html = result.text
        current_url = result.final_url or current_url
        for page_no in range(1, total_max + 1):
            if current_url in seen_urls:
                stats["stopped"] = "循环翻页"
                break
            seen_urls.add(current_url)
            items = parse.parse_list(html, src, current_url)
            if not items:
                stats["stopped"] = "空页"
                break
            stats["pages"] += 1
            page_new = 0
            for item in items:
                stats["found"] += 1
                if not keep_item(item, since):
                    continue
                if item.published_at and (not stats["oldest"] or item.published_at < stats["oldest"]):
                    stats["oldest"] = item.published_at
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
                    stats["new"] += 1
                    page_new += 1
                elif status == "merged":
                    stats["merged"] += 1
                else:
                    stats["skipped"] += 1
            if page_all_older(items, since):
                stats["stopped"] = "已到日期下限"
                break
            zero_streak = zero_streak + 1 if page_new == 0 else 0
            if not any(i.published_at for i in items) and page_new == 0:
                stats["stopped"] = "无新内容"
                break
            if zero_streak >= 2:
                stats["stopped"] = "连续无新增"
                break
            next_url = ""
            next_text = ""
            if page_no < total_max:
                if tpl:
                    next_url = tpl.format(n=start_n + page_no - 1)
                else:
                    next_url = find_next_url(html, current_url)
                    if not next_url:
                        for cand in probe_candidates(src["url"], page_no):
                            probe = fetcher(cand, referer=src.get("referer", ""), encoding=src.get("encoding"),
                                            timeout=settings.request_timeout, retries=0)
                            if probe.ok:
                                next_url = probe.final_url or cand
                                next_text = probe.text
                                break
            if not next_url:
                if not stats["stopped"]:
                    stats["stopped"] = "达到页数上限" if page_no >= total_max else "无下一页"
                break
            if next_text:
                html = next_text
                current_url = next_url
                continue
            sleep(settings.request_interval)
            nxt = fetcher(next_url, referer=src.get("referer", ""), encoding=src.get("encoding"),
                          timeout=settings.request_timeout, retries=settings.request_retries)
            if not nxt.ok:
                stats["stopped"] = "下一页抓取失败"
                break
            html = nxt.text
            current_url = nxt.final_url or next_url
        store.finish_crawl_run(conn, run_id, "ok", stats["found"], stats["new"])
    except Exception as e:
        store.finish_crawl_run(conn, run_id, "error", stats["found"], stats["new"], str(e))
        stats["error"] = str(e)
    return stats


def run(since="2026-01-01", key=None, max_pages=0, settings=None, tags=None,
        fetcher=None, sleep=time.sleep, sources=None):
    settings = settings or load_settings()
    tags = tags or load_tags()
    fetcher = fetcher or fetch
    all_sources = sources if sources is not None else load_sources()
    todo = [s for s in all_sources if s.get("enabled", True) and s["board"] != "price"]
    if key:
        todo = [s for s in todo if s["key"] == key]
    conn = store.connect(settings.db_path)
    store.init_db(conn)
    results = {}
    for src in todo:
        stats = crawl_source(conn, src, settings, tags, fetcher, since, max_pages, sleep)
        results[src["key"]] = stats
        report.log(
            f"[回填][{src['key']}] 页数 {stats['pages']} 抓到 {stats['found']} 新增 {stats['new']} "
            f"合并 {stats['merged']} 跳过 {stats['skipped']} 最老 {stats['oldest'] or '-'} "
            f"停止[{stats['stopped'] or '完成'}]"
            + (f" 失败 {stats['error']}" if stats["error"] else ""))
    total_new = sum(s["new"] for s in results.values())
    total_pages = sum(s["pages"] for s in results.values())
    report.log(f"[回填] 完成：{len(results)} 个源，{total_pages} 页，新增 {total_new} 条")
    conn.close()
    return results


def main():
    parser = argparse.ArgumentParser(description="矿news 历史回填")
    parser.add_argument("--since", default="2026-01-01", help="日期下限（YYYY-MM-DD）")
    parser.add_argument("--key", default="", help="只回填指定源")
    parser.add_argument("--max-pages", type=int, default=0, help="每源最多页数（0=用源配置或80）")
    args = parser.parse_args()
    run(since=args.since, key=args.key or None, max_pages=args.max_pages)


if __name__ == "__main__":
    main()
