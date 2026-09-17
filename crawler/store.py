import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

SCHEMA = Path(__file__).resolve().parent.parent / "db" / "schema.sql"


def now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def connect(db_path):
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(conn) -> None:
    conn.executescript(SCHEMA.read_text(encoding="utf-8"))
    conn.commit()


def upsert_source(conn, key, name, board, url, enabled=True) -> None:
    conn.execute(
        "INSERT INTO sources(key,name,board,url,enabled) VALUES(?,?,?,?,?) "
        "ON CONFLICT(key) DO UPDATE SET name=excluded.name, board=excluded.board, url=excluded.url, enabled=excluded.enabled",
        (key, name, board, url, 1 if enabled else 0),
    )
    conn.commit()


def start_crawl_run(conn, source_key) -> int:
    cur = conn.execute(
        "INSERT INTO crawl_runs(source_key,started_at,status) VALUES(?,?,?)",
        (source_key, now_iso(), "running"),
    )
    conn.commit()
    return cur.lastrowid


def finish_crawl_run(conn, run_id, status, found, new, error="") -> None:
    conn.execute(
        "UPDATE crawl_runs SET finished_at=?,status=?,items_found=?,items_new=?,error=? WHERE id=?",
        (now_iso(), status, int(found), int(new), error, run_id),
    )
    conn.commit()


def url_exists(conn, url_hash) -> bool:
    return conn.execute("SELECT 1 FROM articles WHERE url_hash=?", (url_hash,)).fetchone() is not None


def find_recent_titles(conn, days=3):
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    return conn.execute(
        "SELECT id,title,cluster_id FROM articles WHERE fetched_at>=? ORDER BY id DESC", (cutoff,)
    ).fetchall()


def insert_article(conn, item, classification, url_hash, title_hash, cluster_id=None, is_primary=1) -> int:
    cur = conn.execute(
        "INSERT INTO articles(url,url_hash,title,title_hash,summary,source_key,board,minerals,regions,types,"
        "published_at,fetched_at,cluster_id,is_primary) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            item["url"], url_hash, item["title"], title_hash, item.get("summary", ""),
            item["source_key"], classification["board"],
            json.dumps(classification.get("minerals", []), ensure_ascii=False),
            json.dumps(classification.get("regions", []), ensure_ascii=False),
            json.dumps(classification.get("types", []), ensure_ascii=False),
            item.get("published_at", ""), item.get("fetched_at", now_iso()),
            cluster_id, 1 if is_primary else 0,
        ),
    )
    aid = cur.lastrowid
    if cluster_id is None:
        cur2 = conn.execute(
            "INSERT INTO article_clusters(primary_article_id,member_count,last_seen) VALUES(?,1,?)",
            (aid, now_iso()),
        )
        conn.execute("UPDATE articles SET cluster_id=? WHERE id=?", (cur2.lastrowid, aid))
    else:
        conn.execute(
            "UPDATE article_clusters SET member_count=member_count+1,last_seen=? WHERE id=?",
            (now_iso(), cluster_id),
        )
    conn.commit()
    return aid


UPSERT_MARKETING_SQL = (
    "INSERT INTO marketing_copy(short_uri,author,description,published_at,cover_url,link,fetched_at) "
    "VALUES(?,?,?,?,?,?,?) "
    "ON CONFLICT(short_uri) DO UPDATE SET "
    "author=excluded.author,description=excluded.description,published_at=excluded.published_at,"
    "cover_url=excluded.cover_url,link=excluded.link,fetched_at=excluded.fetched_at"
)


def upsert_marketing_copy(conn, item) -> int:
    conn.execute(
        UPSERT_MARKETING_SQL,
        (
            item["short_uri"], item.get("author", ""), item.get("description", ""),
            item.get("published_at", ""), item.get("cover_url", ""), item.get("link", ""),
            item.get("fetched_at", now_iso()),
        ),
    )
    conn.commit()
    return 1


UPSERT_PRICE_SQL = (
    "INSERT INTO prices(commodity,price_type,value,unit,change,change_pct,price_date,source_key,raw_label,fetched_at) "
    "VALUES(?,?,?,?,?,?,?,?,?,?) "
    "ON CONFLICT(commodity,price_type,price_date,source_key) DO UPDATE SET "
    "value=excluded.value,unit=excluded.unit,change=excluded.change,change_pct=excluded.change_pct,"
    "raw_label=excluded.raw_label,fetched_at=excluded.fetched_at"
)


def upsert_prices(conn, rows) -> int:
    count = 0
    for r in rows:
        conn.execute(
            UPSERT_PRICE_SQL,
            (
                r["commodity"], r["price_type"], float(r["value"]), r.get("unit", ""),
                r.get("change"), r.get("change_pct"), r["price_date"], r["source_key"],
                r.get("raw_label", ""), r.get("fetched_at", now_iso()),
            ),
        )
        count += 1
    conn.commit()
    return count
