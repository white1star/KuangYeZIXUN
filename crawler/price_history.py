import argparse
import json
import re
import time
from datetime import datetime, timedelta

from crawler import store
from crawler.config import load_settings, load_sources
from crawler.fetch import fetch
from crawler.report import log

KLINE_URL = ("https://stock2.finance.sina.com.cn/futures/api/jsonp.php/"
             "var%20_X=/InnerFuturesNewService.getDailyKLine?symbol={code}")
REFERER = "https://finance.sina.com.cn"
VAR_RE = re.compile(r"var\s+_X=\((\[.*\])\)\s*;?", re.S)
REQUEST_INTERVAL = 1.0


def parse_kline(text: str) -> list:
    m = VAR_RE.search(text or "")
    if not m:
        raise ValueError("新浪日K线返回格式异常")
    try:
        data = json.loads(m.group(1))
    except ValueError:
        raise ValueError("新浪日K线 JSON 解析失败")
    if not isinstance(data, list):
        raise ValueError("新浪日K线数据不是数组")
    return data


def _to_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def unit_for(cfg: dict, commodity: str) -> str:
    return (cfg.get("unit_map") or {}).get(commodity) or cfg.get("unit", "")


def build_rows(points: list, cfg: dict, code: str, days: int, now=None) -> list:
    now = now or datetime.now()
    cutoff = (now - timedelta(days=days)).strftime("%Y-%m-%d")
    commodity = (cfg.get("commodity_map") or {}).get(code)
    if not commodity:
        raise ValueError(f"未配置品种: {code}")
    unit = unit_for(cfg, commodity)
    series = []
    for item in points or []:
        date = str(item.get("d") or "").strip()
        close = _to_float(item.get("c"))
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", date) or close is None or close <= 0:
            continue
        series.append((date, close))
    series.sort(key=lambda x: x[0])
    rows = []
    prev = None
    for date, close in series:
        change = round(close - prev, 4) if prev is not None else None
        change_pct = round(change / prev * 100, 2) if change is not None and prev else None
        if date >= cutoff:
            rows.append({
                "commodity": commodity,
                "price_type": "期货",
                "value": close,
                "unit": unit,
                "change": change,
                "change_pct": change_pct,
                "price_date": date,
                "source_key": cfg["key"],
                "raw_label": code,
            })
        prev = close
    return rows


def fetch_symbol(code, cfg, days, settings, fetcher, now=None) -> list:
    url = KLINE_URL.format(code=code)
    result = fetcher(url, referer=cfg.get("referer") or REFERER,
                     timeout=settings.request_timeout, retries=settings.request_retries)
    if not result.ok:
        raise RuntimeError(result.error or f"HTTP {result.status}")
    return build_rows(parse_kline(result.text), cfg, code, days, now=now)


def run(days=90, fetcher=None, sleep=time.sleep, settings=None, sources=None, now=None) -> dict:
    settings = settings or load_settings()
    fetcher = fetcher or fetch
    all_sources = sources if sources is not None else load_sources()
    cfg = next((s for s in all_sources if s.get("key") == "sina_futures"), None)
    if cfg is None:
        raise RuntimeError("未找到 sina_futures 源配置")
    conn = store.connect(settings.db_path)
    store.init_db(conn)
    stats = {}
    codes = list((cfg.get("commodity_map") or {}).keys())
    try:
        for idx, code in enumerate(codes):
            if idx:
                sleep(REQUEST_INTERVAL)
            name = cfg["commodity_map"][code]
            try:
                rows = fetch_symbol(code, cfg, days, settings, fetcher, now=now)
                store.upsert_prices(conn, rows)
                latest = max((r["price_date"] for r in rows), default="-")
                stats[code] = {"commodity": name, "days": len(rows), "latest": latest, "error": ""}
                log(f"[期货回填] {name}({code}) 写入 {len(rows)} 天，最新 {latest}")
            except Exception as e:
                stats[code] = {"commodity": name, "days": 0, "latest": "", "error": str(e)}
                log(f"[期货回填] {name}({code}) 失败：{e}")
    finally:
        conn.close()
    total = sum(s["days"] for s in stats.values())
    failed = [k for k, s in stats.items() if s["error"]]
    log(f"[期货回填] 完成：{len(stats)} 个品种，写入 {total} 行"
        + (f"，失败 {len(failed)} 个：{','.join(failed)}" if failed else ""))
    return stats


def main():
    parser = argparse.ArgumentParser(description="矿news 期货历史回填（新浪日K线）")
    parser.add_argument("--days", type=int, default=90, help="回填最近 N 个自然日")
    args = parser.parse_args()
    run(days=args.days)


if __name__ == "__main__":
    main()
