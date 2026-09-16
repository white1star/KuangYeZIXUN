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
    sql = ("SELECT a.*, (SELECT member_count FROM article_clusters c WHERE c.id=a.cluster_id) AS member_count "
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
        "SELECT p.* FROM prices p JOIN "
        "(SELECT id, ROW_NUMBER() OVER (PARTITION BY commodity, price_type "
        "ORDER BY price_date DESC, fetched_at DESC, id DESC) rn FROM prices) r "
        "ON r.id=p.id WHERE r.rn=1 "
        "ORDER BY p.commodity LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


def price_series(conn, commodity, days=30, price_type=None) -> list:
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    sql = "SELECT price_date, AVG(value) value FROM prices WHERE commodity=? AND price_date>=?"
    params = [commodity, cutoff]
    if price_type:
        sql += " AND price_type=?"
        params.append(price_type)
    sql += " GROUP BY price_date ORDER BY price_date"
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def distinct_commodities(conn) -> list:
    return [r["commodity"] for r in
            conn.execute("SELECT DISTINCT commodity FROM prices ORDER BY commodity").fetchall()]


def search_articles(conn, q="", mineral=None, board=None, source=None,
                    date_from=None, date_to=None, limit=100) -> list:
    where = ["a.is_primary=1"]
    params = []
    sql = ("SELECT a.*, (SELECT member_count FROM article_clusters c WHERE c.id=a.cluster_id) AS member_count "
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
