import time

from crawler import store
from crawler.config import load_settings
from web import queries


def run_checks(settings=None) -> list:
    settings = settings or load_settings()
    conn = store.connect(settings.db_path)
    try:
        checks = []
        stats = queries.today_stats(conn)
        checks.append(("今日文章数 ≥ 1", stats["total"] >= 1, str(stats["total"])))
        health = queries.source_health(conn)
        ok = [h for h in health if h["status"] == "ok"]
        ratio = (len(ok) / len(health)) if health else 0.0
        checks.append(("最近一轮源成功率 ≥ 80%", ratio >= 0.8, f"{len(ok)}/{len(health)}"))
        commodities = queries.distinct_commodities(conn)
        checks.append(("价格品种 ≥ 12", len(commodities) >= 12, str(len(commodities))))
        start = time.time()
        queries.search_articles(conn, q="磷矿", limit=10)
        cost_ms = (time.time() - start) * 1000
        checks.append(("搜索响应 < 1000ms", cost_ms < 1000, f"{cost_ms:.0f}ms"))
    finally:
        conn.close()
    return checks


def main():
    checks = run_checks()
    failed = 0
    for name, ok, detail in checks:
        print(f"[{'通过' if ok else '未通过'}] {name}：{detail}")
        failed += 0 if ok else 1
    print(f"结论：{'全部通过' if failed == 0 else f'{failed} 项未通过'}")
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
