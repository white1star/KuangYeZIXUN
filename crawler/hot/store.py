"""热榜数据存取。"""
import hashlib
import json
from datetime import datetime, timedelta

from crawler import dedup


def now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def start_run(conn, platform: str) -> int:
    cur = conn.execute(
        "INSERT INTO hot_runs(platform,started_at,status) VALUES(?,?,?)",
        (platform, now_iso(), "running"),
    )
    conn.commit()
    return cur.lastrowid


def finish_run(conn, run_id: int, status: str, found: int = 0, new: int = 0,
               error: str = "") -> None:
    conn.execute(
        "UPDATE hot_runs SET finished_at=?,status=?,items_found=?,items_new=?,error=? "
        "WHERE id=?",
        (now_iso(), status, int(found), int(new), error or "", int(run_id)),
    )
    conn.commit()


UPSERT_SQL = """
INSERT INTO hot_items(platform,source_name,title,title_hash,url,url_hash,summary,author,
                      published_at,rank,raw_heat,heat_score,category,keywords,
                      first_seen_at,last_seen_at)
VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
ON CONFLICT(platform,title_hash) DO UPDATE SET
  source_name=excluded.source_name,
  url=CASE WHEN excluded.url<>'' THEN excluded.url ELSE hot_items.url END,
  url_hash=CASE WHEN excluded.url_hash<>'' THEN excluded.url_hash ELSE hot_items.url_hash END,
  summary=CASE WHEN excluded.summary<>'' THEN excluded.summary ELSE hot_items.summary END,
  author=CASE WHEN excluded.author<>'' THEN excluded.author ELSE hot_items.author END,
  published_at=CASE WHEN excluded.published_at<>'' THEN excluded.published_at ELSE hot_items.published_at END,
  rank=excluded.rank,
  raw_heat=excluded.raw_heat,
  heat_score=excluded.heat_score,
  category=excluded.category,
  keywords=excluded.keywords,
  last_seen_at=excluded.last_seen_at
"""


def upsert_items(conn, items: list) -> tuple:
    """写入/更新热榜条目，返回 (新增数, 更新数)。"""
    now = now_iso()
    new_count = 0
    updated = 0
    for item in items:
        title = (item.get("title") or "").strip()
        if not title:
            continue
        th = dedup.title_hash(title)
        url = (item.get("url") or "").strip()
        url_hash = hashlib.sha1(dedup.normalize_url(url).encode("utf-8")).hexdigest() if url else ""
        exists = conn.execute(
            "SELECT 1 FROM hot_items WHERE platform=? AND title_hash=?",
            (item["platform"], th),
        ).fetchone()
        published = (item.get("published_at") or "").strip() or now
        conn.execute(
            UPSERT_SQL,
            (
                item["platform"], item.get("source_name") or item["platform"], title, th,
                url, url_hash, item.get("summary") or "", item.get("author") or "",
                published, int(item.get("rank") or 0),
                float(item["raw_heat"]) if item.get("raw_heat") not in (None, "") else None,
                int(item.get("heat_score") or 0), item.get("category") or "行业动态",
                json.dumps(item.get("keywords") or [], ensure_ascii=False),
                now, now,
            ),
        )
        if exists:
            updated += 1
        else:
            new_count += 1
    conn.commit()
    return new_count, updated


def load_items(conn, days: int = 7, limit: int = 1200) -> list:
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    rows = conn.execute(
        "SELECT * FROM hot_items WHERE last_seen_at>=? "
        "ORDER BY heat_score DESC, published_at DESC, id DESC LIMIT ?",
        (cutoff, int(limit)),
    ).fetchall()
    items = []
    for row in rows:
        item = dict(row)
        try:
            item["keywords"] = json.loads(item.get("keywords") or "[]")
        except (TypeError, ValueError):
            item["keywords"] = []
        items.append(item)
    return items


def latest_status(conn) -> dict:
    rows = conn.execute(
        "SELECT r.* FROM hot_runs r JOIN "
        "(SELECT platform, MAX(id) AS max_id FROM hot_runs GROUP BY platform) x "
        "ON x.max_id=r.id"
    ).fetchall()
    return {row["platform"]: dict(row) for row in rows}


def purge_blocked(conn, terms) -> int:
    """删除标题命中拉黑词的历史条目（例如招聘广告）。"""
    total = 0
    for term in terms or ():
        if not term:
            continue
        cur = conn.execute("DELETE FROM hot_items WHERE title LIKE ?", (f"%{term}%",))
        total += cur.rowcount
    if total:
        conn.commit()
    return total


def purge_noise(conn) -> int:
    """删除与矿业无关的噪音条目（如"碳酸锂"服药帖）。"""
    from crawler.hot.keywords import NOISE_WORDS
    return purge_blocked(conn, NOISE_WORDS)


def clean_titles(conn) -> int:
    """把库里的原始标题清洗成一句话（不改 title_hash，去重仍按原始标题）。"""
    from crawler.hot.keywords import clean_title
    rows = conn.execute("SELECT id, title FROM hot_items").fetchall()
    n = 0
    for row in rows:
        cleaned = clean_title(row[1] or "")
        if cleaned and cleaned != row[1]:
            conn.execute("UPDATE hot_items SET title=? WHERE id=?", (cleaned, row[0]))
            n += 1
    if n:
        conn.commit()
    return n


def clean_summaries(conn) -> int:
    """清洗库里的摘要（去 #/@/emoji/多余空白）。"""
    from crawler.hot.keywords import clean_summary
    rows = conn.execute("SELECT id, summary FROM hot_items WHERE summary<>''").fetchall()
    n = 0
    for row in rows:
        cleaned = clean_summary(row[1] or "")
        if cleaned and cleaned != row[1]:
            conn.execute("UPDATE hot_items SET summary=? WHERE id=?", (cleaned, row[0]))
            n += 1
    if n:
        conn.commit()
    return n


def cleanup(conn, days: int = 30) -> int:
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    cur = conn.execute("DELETE FROM hot_items WHERE last_seen_at<?", (cutoff,))
    conn.execute(
        "DELETE FROM hot_runs WHERE started_at<?",
        ((datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d %H:%M:%S"),),
    )
    conn.commit()
    return cur.rowcount
