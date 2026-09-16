import json
from datetime import datetime, timedelta


def _decode(row) -> dict:
    d = dict(row)
    for key in ("minerals", "regions", "types"):
        if key in d and isinstance(d[key], str):
            try:
                d[key] = json.loads(d[key])
            except ValueError:
                d[key] = []
    return d


def today_stats(conn) -> dict:
    day = datetime.now().strftime("%Y-%m-%d")
    rows = conn.execute(
        "SELECT board, COUNT(*) c FROM articles WHERE fetched_at LIKE ? GROUP BY board",
        (day + "%",)).fetchall()
    by_board = {r["board"]: r["c"] for r in rows}
    return {"total": sum(by_board.values()), "by_board": by_board}


def last_runs(conn) -> list:
    rows = conn.execute(
        "SELECT source_key, status, finished_at, items_found FROM crawl_runs WHERE id IN "
        "(SELECT MAX(id) FROM crawl_runs GROUP BY source_key) ORDER BY source_key").fetchall()
    return [dict(r) for r in rows]


def latest_articles(conn, limit=30, board=None) -> list:
    sql = ("SELECT a.*, (SELECT member_count FROM article_clusters c WHERE c.id=a.cluster_id) AS member_count, "
           "(SELECT s.name FROM sources s WHERE s.key=a.source_key) AS source_name "
           "FROM articles a WHERE a.is_primary=1")
    params = []
    if board:
        sql += " AND a.board=?"
        params.append(board)
    sql += " ORDER BY a.id DESC LIMIT ?"
    params.append(limit)
    return [_decode(r) for r in conn.execute(sql, params).fetchall()]


def latest_policies(conn, limit=8) -> list:
    return latest_articles(conn, limit=limit, board="policy")


def price_latest(conn, limit=20) -> list:
    rows = conn.execute(
        "SELECT p.*, (SELECT s.name FROM sources s WHERE s.key=p.source_key) AS source_name "
        "FROM prices p JOIN "
        "(SELECT id, ROW_NUMBER() OVER (PARTITION BY commodity, price_type "
        "ORDER BY price_date DESC, fetched_at DESC, id DESC) rn FROM prices) r "
        "ON r.id=p.id WHERE r.rn=1 "
        "ORDER BY p.commodity LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


def price_series(conn, commodity, days=30, price_type=None) -> list:
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    sql = ("SELECT price_date, value FROM ("
           "SELECT price_date, value, ROW_NUMBER() OVER "
           "(PARTITION BY price_date ORDER BY fetched_at DESC, id DESC) rn "
           "FROM prices WHERE commodity=? AND price_date>=?")
    params = [commodity, cutoff]
    if price_type:
        sql += " AND price_type=?"
        params.append(price_type)
    sql += ") WHERE rn=1 ORDER BY price_date"
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def price_overview(conn, commodities=None, limit=6) -> list:
    sql = ("SELECT p.*, (SELECT s.name FROM sources s WHERE s.key=p.source_key) AS source_name "
           "FROM prices p JOIN (SELECT id, ROW_NUMBER() OVER (PARTITION BY commodity "
           "ORDER BY price_date DESC, fetched_at DESC, id DESC) rn FROM prices")
    params = []
    if commodities:
        marks = ",".join("?" for _ in commodities)
        sql += f" WHERE commodity IN ({marks})"
        params.extend(commodities)
    sql += ") r ON r.id=p.id WHERE r.rn=1 ORDER BY p.commodity LIMIT ?"
    params.append(limit)
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def source_dots(conn) -> list:
    rows = conn.execute(
        "SELECT s.key, s.name, r.status, r.finished_at FROM sources s LEFT JOIN crawl_runs r "
        "ON r.id = (SELECT MAX(id) FROM crawl_runs WHERE source_key = s.key) "
        "ORDER BY s.key").fetchall()
    return [dict(r) for r in rows]


def today_fail_count(conn) -> int:
    row = conn.execute(
        "SELECT COUNT(*) c FROM crawl_runs WHERE id IN "
        "(SELECT MAX(id) FROM crawl_runs GROUP BY source_key) AND status='error'").fetchone()
    return row["c"] if row else 0


def last_fetch_time(conn) -> str:
    row = conn.execute(
        "SELECT MAX(finished_at) t FROM crawl_runs WHERE id IN "
        "(SELECT MAX(id) FROM crawl_runs GROUP BY source_key)").fetchone()
    return (row["t"] or "") if row else ""


def commodity_types(conn) -> dict:
    rows = conn.execute(
        "SELECT DISTINCT commodity, price_type FROM prices ORDER BY commodity, price_type").fetchall()
    result = {}
    for r in rows:
        result.setdefault(r["commodity"], []).append(r["price_type"])
    return result


def distinct_commodities(conn) -> list:
    return [r["commodity"] for r in
            conn.execute("SELECT DISTINCT commodity FROM prices ORDER BY commodity").fetchall()]


def distinct_minerals(conn) -> list:
    rows = conn.execute(
        "SELECT DISTINCT je.value AS m FROM articles a, json_each(a.minerals) je "
        "WHERE a.is_primary=1 ORDER BY m").fetchall()
    return [r["m"] for r in rows]


def search_articles(conn, q="", mineral=None, board=None, source=None,
                    date_from=None, date_to=None, limit=100) -> list:
    where = ["a.is_primary=1"]
    params = []
    sql = ("SELECT a.*, (SELECT member_count FROM article_clusters c WHERE c.id=a.cluster_id) AS member_count, "
           "(SELECT s.name FROM sources s WHERE s.key=a.source_key) AS source_name "
           "FROM articles a ")
    text = (q or "").strip()
    if len(text) >= 3:
        sql += "JOIN articles_fts f ON f.rowid=a.id "
        where.append("articles_fts MATCH ?")
        params.append('"' + text.replace('"', " ") + '"')
    elif text:
        where.append("(a.title LIKE ? OR a.summary LIKE ?)")
        params.extend([f"%{text}%", f"%{text}%"])
    if board:
        where.append("a.board=?")
        params.append(board)
    if source:
        where.append("a.source_key=?")
        params.append(source)
    if mineral:
        where.append("a.minerals LIKE ?")
        params.append(f'%"{mineral}"%')
    if date_from:
        where.append("a.fetched_at>=?")
        params.append(date_from)
    if date_to:
        where.append("a.fetched_at<=?")
        params.append(date_to + " 23:59:59")
    sql += " WHERE " + " AND ".join(where) + " ORDER BY a.id DESC LIMIT ?"
    params.append(limit)
    return [_decode(r) for r in conn.execute(sql, params).fetchall()]


def source_health(conn) -> list:
    rows = conn.execute(
        "SELECT s.key, s.name, s.board, s.enabled, r.status, r.finished_at, r.items_found, r.items_new, r.error "
        "FROM sources s LEFT JOIN crawl_runs r ON r.id = "
        "(SELECT MAX(id) FROM crawl_runs WHERE source_key=s.key) ORDER BY s.board, s.key").fetchall()
    return [dict(r) for r in rows]
