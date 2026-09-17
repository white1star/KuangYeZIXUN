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


def _series(conn, commodity, price_type, cutoff) -> list:
    sql = ("SELECT price_date, value, unit FROM ("
           "SELECT price_date, value, unit, ROW_NUMBER() OVER "
           "(PARTITION BY price_date ORDER BY fetched_at DESC, id DESC) rn "
           "FROM prices WHERE commodity=? AND price_date>=?")
    params = [commodity, cutoff]
    if price_type:
        sql += " AND price_type=?"
        params.append(price_type)
    sql += ") WHERE rn=1 ORDER BY price_date"
    return [[r["price_date"], r["value"], r["unit"]] for r in conn.execute(sql, params).fetchall()]


def _change_pct(row) -> float:
    if row["change_pct"] is not None:
        return float(row["change_pct"])
    change = row["change"]
    value = row["value"]
    if change is not None and value is not None and (value - change) > 0:
        return round(change / (value - change) * 100, 2)
    return None


def prices_payload(conn, days=SERIES_DAYS) -> dict:
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    type_map = {}
    for row in conn.execute(
            "SELECT DISTINCT commodity, price_type FROM prices ORDER BY commodity, price_type"):
        type_map.setdefault(row["commodity"], []).append(row["price_type"])
    series = {}
    for commodity, types in type_map.items():
        entry = {"全部": _series(conn, commodity, None, cutoff)}
        for price_type in types:
            entry[price_type] = _series(conn, commodity, price_type, cutoff)
        series[commodity] = entry
    latest = []
    rows = conn.execute(
        "SELECT p.*, (SELECT s.name FROM sources s WHERE s.key=p.source_key) AS source_name "
        "FROM prices p JOIN "
        "(SELECT id, ROW_NUMBER() OVER (PARTITION BY commodity, price_type "
        "ORDER BY price_date DESC, fetched_at DESC, id DESC) rn FROM prices) r "
        "ON r.id=p.id WHERE r.rn=1 "
        "ORDER BY p.price_date DESC, p.commodity").fetchall()
    for row in rows:
        latest.append({
            "commodity": row["commodity"],
            "price_type": row["price_type"],
            "value": row["value"],
            "unit": row["unit"],
            "change": row["change"],
            "change_pct": row["change_pct"],
            "pct": _change_pct(row),
            "price_date": row["price_date"],
            "source": row["source_name"] or row["source_key"] or "",
        })
    return {
        "generated_at": store.now_iso(),
        "days": int(days),
        "commodities": sorted(type_map.keys()),
        "type_map": type_map,
        "series": series,
        "latest": latest,
    }
