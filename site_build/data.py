import json
from datetime import datetime, timedelta

from crawler import store

SUMMARY_CHARS = 60
SERIES_DAYS = 90


def _decode(value, fallback):
    if not value:
        return list(fallback)
    try:
        data = json.loads(value)
    except (TypeError, ValueError):
        return list(fallback)
    return data if isinstance(data, list) else list(fallback)


def load_articles(conn) -> list:
    rows = conn.execute(
        "SELECT a.title, a.url, a.summary, a.published_at, a.fetched_at, a.board, a.minerals, a.regions, a.types, "
        "(SELECT s.name FROM sources s WHERE s.key=a.source_key) AS source_name, "
        "(SELECT c.member_count FROM article_clusters c WHERE c.id=a.cluster_id) AS member_count "
        "FROM articles a WHERE a.is_primary=1 "
        "ORDER BY CASE WHEN a.published_at='' THEN substr(a.fetched_at,1,10) "
        "ELSE a.published_at END DESC, a.id DESC").fetchall()
    items = []
    for row in rows:
        published = (row["published_at"] or "").strip() or (row["fetched_at"] or "")[:16]
        items.append({
            "title": row["title"],
            "url": row["url"],
            "published_at": published,
            "summary": (row["summary"] or "").strip(),
            "source_name": row["source_name"] or "",
            "board": row["board"],
            "minerals": _decode(row["minerals"], []),
            "regions": _decode(row["regions"], []),
            "types": _decode(row["types"], []),
            "member_count": int(row["member_count"] or 1),
        })
    return items


def search_items(articles) -> list:
    items = []
    for a in articles:
        summary = a["summary"]
        if len(summary) > SUMMARY_CHARS:
            summary = summary[:SUMMARY_CHARS]
        item = {
            "title": a["title"],
            "url": a["url"],
            "published_at": a["published_at"],
            "source_name": a["source_name"],
            "board": a["board"],
        }
        if summary:
            item["summary"] = summary
        if a["minerals"]:
            item["minerals"] = a["minerals"]
        if a["types"]:
            item["types"] = a["types"]
        if a["regions"]:
            item["regions"] = a["regions"]
        if a["member_count"] > 1:
            item["member_count"] = a["member_count"]
        items.append(item)
    return items


def load_marketing_copies(conn) -> list:
    rows = conn.execute(
        "SELECT short_uri, author, description, transcript, published_at, cover_url, link, fetched_at "
        "FROM marketing_copy ORDER BY published_at DESC, id DESC").fetchall()
    items = []
    for row in rows:
        short_uri = (row["short_uri"] or "").strip()
        link = (row["link"] or "").strip()
        if not link and short_uri and not short_uri.startswith("file:"):
            link = "https://weixin.qq.com/sph/" + short_uri
        items.append({
            "short_uri": short_uri,
            "author": (row["author"] or "").strip(),
            "description": (row["description"] or "").strip(),
            "transcript": (row["transcript"] or "").strip(),
            "published_at": (row["published_at"] or "").strip(),
            "cover_url": (row["cover_url"] or "").strip(),
            "link": link,
        })
    return items


def marketing_stats(conn) -> dict:
    day = datetime.now().strftime("%Y-%m-%d")
    total = conn.execute("SELECT COUNT(*) c FROM marketing_copy").fetchone()["c"]
    today = conn.execute(
        "SELECT COUNT(*) c FROM marketing_copy WHERE fetched_at LIKE ?", (day + "%",)).fetchone()["c"]
    return {"today": int(today), "total": int(total)}


def today_stats(conn) -> dict:
    day = datetime.now().strftime("%Y-%m-%d")
    rows = conn.execute(
        "SELECT board, COUNT(*) c FROM articles WHERE fetched_at LIKE ? AND is_primary=1 GROUP BY board",
        (day + "%",)).fetchall()
    by_board = {r["board"]: r["c"] for r in rows}
    return {"total": sum(by_board.values()), "by_board": by_board}


def source_health(conn) -> tuple:
    rows = conn.execute(
        "SELECT s.key, r.status FROM sources s LEFT JOIN crawl_runs r ON r.id = "
        "(SELECT MAX(id) FROM crawl_runs WHERE source_key=s.key)").fetchall()
    ok = sum(1 for r in rows if r["status"] == "ok")
    return ok, len(rows)


def last_fetch_time(conn) -> str:
    row = conn.execute(
        "SELECT MAX(finished_at) t FROM crawl_runs WHERE id IN "
        "(SELECT MAX(id) FROM crawl_runs GROUP BY source_key)").fetchone()
    return (row["t"] or "") if row else ""


def policy_meta(articles) -> dict:
    names = set()
    regions = set()
    for a in articles:
        if a["board"] != "policy":
            continue
        if a["source_name"]:
            names.add(a["source_name"])
        for region in a["regions"]:
            regions.add(region)
    return {"sources": sorted(names), "regions": sorted(regions)}


def _carry_forward(rows, today):
    # 休市/上游未发布日（周末、节假日）把最后报价带到今天：价不变、日期跟到今天，
    # 与指数类源"抓取日盖戳"口径一致。数据层不造假，告警仍按真实报价日判陈旧。
    if rows and rows[-1][0] < today:
        rows = rows + [[today, rows[-1][1], rows[-1][2]]]
    return rows


def _change_pct(row) -> float:
    if row["change_pct"] is not None:
        return float(row["change_pct"])
    change = row["change"]
    value = row["value"]
    if change is not None and value is not None and (value - change) > 0:
        return round(change / (value - change) * 100, 2)
    return None


# 主市场优先顺序：同品种多市场时，"全国/主市场"那条线才是默认展示的代表
MAIN_MARKET_ORDER = ("长江现货", "长江综合", "长江有色", "无锡现货", "上海地区",
                     "佛山现货", "广东现货", "国内市场", "全国")


def _market_rank(market: str) -> int:
    try:
        return MAIN_MARKET_ORDER.index(market)
    except ValueError:
        return len(MAIN_MARKET_ORDER)


SPREAD_MAX_RATIO = 1.5


def _safe_spread(lo, hi, spec):
    """市场价差只在"同一品种同一规格"可信时给出。

    1) 规格没写或不详（`-`）：不同市场可能报的根本不是同一个东西（废铜普料 vs 光亮铜线），
       不给价差；
    2) 价差超过最低价的 50%：说明源站把不同口径（品位/单位/计价基准）混在一个品名下
       （实测钼酸铵 99% 同规格从 2.3 万到 39 万），也不能当地区价差。
    """
    spec = (spec or "").strip()
    if not spec or spec == "-":
        return None
    if lo is None or hi is None or lo <= 0 or hi < lo:
        return None
    if hi / lo > SPREAD_MAX_RATIO:
        return None
    return round(hi - lo, 2)


def _series(conn, cutoff) -> dict:
    """按 (品种, 类型, 市场, 规格) 分组出曲线。

    绝不把不同口径拼成一条线：过去"全部类型"是按日期取最后写入的那条，
    会出现同一天在期货价和现货价之间来回跳的假曲线。
    """
    rows = conn.execute(
        "SELECT commodity, price_type, market, spec, price_date, value, unit, "
        "ROW_NUMBER() OVER (PARTITION BY commodity, price_type, market, spec, price_date "
        "ORDER BY fetched_at DESC, id DESC) rn "
        "FROM prices WHERE price_date>=?", (cutoff,)).fetchall()
    groups: dict = {}
    for r in rows:
        if r["rn"] != 1:
            continue
        key = (r["commodity"], r["price_type"], r["market"], r["spec"])
        groups.setdefault(key, []).append([r["price_date"], r["value"], r["unit"]])
    for key in groups:
        groups[key].sort(key=lambda p: p[0])
    return groups


def prices_payload(conn, days=SERIES_DAYS) -> dict:
    today = datetime.now().strftime("%Y-%m-%d")
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    groups = _series(conn, cutoff)

    type_map: dict = {}
    market_map: dict = {}
    series: dict = {}
    for (commodity, price_type, market, spec), points in sorted(groups.items()):
        type_map.setdefault(commodity, [])
        if price_type not in type_map[commodity]:
            type_map[commodity].append(price_type)
        if market:
            market_map.setdefault(commodity, {}).setdefault(price_type, [])
            if market not in market_map[commodity][price_type]:
                market_map[commodity][price_type].append(market)
        label = price_type + (f"·{market}" if market else "")
        series.setdefault(commodity, []).append({
            "key": f"{price_type}|{market}|{spec}",
            "price_type": price_type,
            "market": market,
            "spec": spec,
            "label": label + (f" {spec}" if spec else ""),
            "points": _carry_forward([list(p) for p in points], today),
        })

    # 每种口径挑一条主线（主市场优先），供"全部类型"视图使用
    for commodity, entries in series.items():
        by_type: dict = {}
        for entry in entries:
            current = by_type.get(entry["price_type"])
            rank = (_market_rank(entry["market"]), -len(entry["points"]))
            if current is None or rank < current[0]:
                by_type[entry["price_type"]] = (rank, entry)
        mains = {t: e[1]["key"] for t, e in by_type.items()}
        for entry in entries:
            entry["main"] = mains.get(entry["price_type"]) == entry["key"]

    latest = []
    rows = conn.execute(
        "SELECT p.*, (SELECT s.name FROM sources s WHERE s.key=p.source_key) AS source_name "
        "FROM prices p JOIN "
        "(SELECT id, ROW_NUMBER() OVER (PARTITION BY commodity, price_type, market, spec "
        "ORDER BY price_date DESC, fetched_at DESC, id DESC) rn FROM prices) r "
        "ON r.id=p.id WHERE r.rn=1 "
        "ORDER BY p.price_date DESC, p.commodity, p.market").fetchall()
    for row in rows:
        quote_date = row["price_date"]
        carried = bool(quote_date and quote_date < today)
        price_date = today if carried else quote_date
        latest.append({
            "commodity": row["commodity"],
            "price_type": row["price_type"],
            "market": row["market"],
            "origin": row["origin"],
            "spec": row["spec"],
            "basis": row["basis"],
            "contract": row["contract"],
            "value": row["value"],
            "unit": row["unit"],
            "change": row["change"],
            "change_pct": row["change_pct"],
            "pct": _change_pct(row),
            "price_date": price_date,
            "quote_date": quote_date,
            "carried": carried,
            "source": row["source_name"] or row["source_key"] or "",
        })

    # 同品种同口径同规格下各市场的价差：只比"同一天真实报过价"的市场，
    # 沿用昨收的点不参与，否则一个没更新的市场会把价差拉大。
    spread: dict = {}
    fresh_date: dict = {}
    for item in latest:
        key = (item["commodity"], item["price_type"], item["spec"])
        if not item["carried"]:
            fresh_date[key] = max(fresh_date.get(key, ""), item["quote_date"])
    for item in latest:
        key = (item["commodity"], item["price_type"], item["spec"])
        if item["carried"]:
            continue
        lo, hi = spread.get(key, (None, None))
        value = item["value"]
        spread[key] = (value if lo is None else min(lo, value),
                        value if hi is None else max(hi, value))
    for item in latest:
        key = (item["commodity"], item["price_type"], item["spec"])
        lo, hi = spread.get(key, (None, None))
        item["market_low"] = lo
        item["market_high"] = hi
        item["market_spread"] = _safe_spread(lo, hi, item["spec"])
        item["market_fresh_date"] = fresh_date.get(key, "")
        spec = (item["spec"] or "").strip()
        origin = (item["origin"] or "").strip()
        # 产地/牌号只在"短、像地名或品牌"时才拼进规格：1# 葫芦岛、A00 抚铝
        short_origin = bool(origin) and len(origin) <= 4 and not any(ch.isdigit() for ch in origin)
        if spec and spec != "-":
            show_origin = short_origin and len(spec) <= 12 and origin != spec
            item["spec_label"] = f"{spec} {origin}" if show_origin else spec
        else:
            item["spec_label"] = origin
        item["brief_spec"] = item["spec_label"]

    markets = sorted({m for by_type in market_map.values()
                      for lst in by_type.values() for m in lst if m})
    return {
        "generated_at": store.now_iso(),
        "days": int(days),
        "commodities": sorted(type_map.keys()),
        "type_map": type_map,
        "market_map": market_map,
        "markets": markets,
        "series": series,
        "latest": latest,
    }
