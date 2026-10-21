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


def _ensure_column(conn, table, column, ddl) -> None:
    columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")


PRICE_NEW_COLUMNS = {
    "market": "TEXT NOT NULL DEFAULT ''",
    "origin": "TEXT NOT NULL DEFAULT ''",
    "spec": "TEXT NOT NULL DEFAULT ''",
    "basis": "TEXT NOT NULL DEFAULT ''",
    "contract": "TEXT NOT NULL DEFAULT ''",
}
OLD_PRICE_UNIQUE = "UNIQUE(commodity,price_type,price_date,source_key)"
NEW_PRICE_UNIQUE = "UNIQUE(commodity,price_type,market,spec,price_date,source_key)"

PRICE_MIGRATION_SQL = """
CREATE TABLE prices_migrated (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  commodity TEXT NOT NULL,
  price_type TEXT NOT NULL,
  value REAL NOT NULL,
  unit TEXT NOT NULL DEFAULT '',
  change REAL,
  change_pct REAL,
  price_date TEXT NOT NULL,
  source_key TEXT NOT NULL,
  raw_label TEXT NOT NULL DEFAULT '',
  market TEXT NOT NULL DEFAULT '',
  origin TEXT NOT NULL DEFAULT '',
  spec TEXT NOT NULL DEFAULT '',
  basis TEXT NOT NULL DEFAULT '',
  contract TEXT NOT NULL DEFAULT '',
  fetched_at TEXT NOT NULL,
  UNIQUE(commodity, price_type, market, spec, price_date, source_key)
);
INSERT INTO prices_migrated(commodity,price_type,value,unit,change,change_pct,price_date,
                            source_key,raw_label,market,origin,spec,basis,contract,fetched_at)
SELECT commodity,price_type,value,unit,change,change_pct,price_date,
       source_key,raw_label,'','','','','',fetched_at FROM prices;
DROP TABLE prices;
ALTER TABLE prices_migrated RENAME TO prices;
CREATE INDEX IF NOT EXISTS idx_prices_commodity ON prices(commodity, price_date DESC);
CREATE INDEX IF NOT EXISTS idx_prices_market ON prices(commodity, price_type, market, price_date);
"""


def _table_sql(conn, table) -> str:
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
    return (row["sql"] or "") if row else ""


def _migrate_prices(conn) -> None:
    """旧唯一键是新键的子集，直接搬数据不会冲突，只需重建表以换唯一约束。"""
    sql = _table_sql(conn, "prices")
    if not sql:
        return
    flat = sql.replace(" ", "").replace("\n", "")
    if OLD_PRICE_UNIQUE in flat and NEW_PRICE_UNIQUE.replace(" ", "") not in flat:
        conn.executescript(PRICE_MIGRATION_SQL)
        return
    for column, ddl in PRICE_NEW_COLUMNS.items():
        _ensure_column(conn, "prices", column, ddl)


# 这些源的旧口径已被新解析器取代，历史行没有市场/规格维度且不可信，直接清空重抓：
#   ccmn     列表页混入废料/加工材（曾把破碎黄铜当成电解铜报价）
#   ccmn_sn  旧的"多市场均价"行，与现在的逐市场报价重复
#   pp100    旧口径同品类只留一条任意报价，跨地区被压平
#   cctd     旧口径把月度/年度长协价盖成抓取日
LEGACY_PRICE_SOURCES = ("ccmn", "ccmn_sn", "pp100", "cctd")


def _prune_legacy_prices(conn) -> None:
    """清掉换口径前的历史行：这些行既没有市场也没有规格，只会污染曲线。"""
    marks = ",".join("?" for _ in LEGACY_PRICE_SOURCES)
    conn.execute(
        f"DELETE FROM prices WHERE source_key IN ({marks}) AND market='' AND spec=''",
        LEGACY_PRICE_SOURCES)


def _backfill_legacy_market(conn) -> None:
    """给旧行补市场：指数名里带着地区限定词（CCI进口3800 → 进口）。"""
    try:
        from crawler.config import load_sources
    except ImportError:
        return
    maps = {s["key"]: s.get("market_map") or {} for s in load_sources()}
    maps = {k: v for k, v in maps.items() if v}
    if not maps:
        return
    rows = conn.execute(
        "SELECT id, commodity, price_type, spec, price_date, source_key, raw_label "
        "FROM prices WHERE market='' AND raw_label<>''").fetchall()
    for r in rows:
        mapping = maps.get(r["source_key"])
        if not mapping:
            continue
        target = ""
        for key, value in mapping.items():
            if key and str(key) in r["raw_label"]:
                target = value
                break
        if not target:
            continue
        dup = conn.execute(
            "SELECT id FROM prices WHERE commodity=? AND price_type=? AND market=? AND spec=? "
            "AND price_date=? AND source_key=? AND id<>?",
            (r["commodity"], r["price_type"], target, r["spec"], r["price_date"],
             r["source_key"], r["id"])).fetchone()
        if dup:
            conn.execute("DELETE FROM prices WHERE id=?", (r["id"],))
        else:
            conn.execute("UPDATE prices SET market=? WHERE id=?", (target, r["id"]))


def init_db(conn) -> None:
    # 先升级旧表结构，再跑 schema.sql：schema 里的新索引依赖 market 列
    _migrate_prices(conn)
    conn.executescript(SCHEMA.read_text(encoding="utf-8"))
    _ensure_column(conn, "marketing_copy", "transcript", "transcript TEXT NOT NULL DEFAULT ''")
    _ensure_column(conn, "crawl_runs", "rules_version", "rules_version TEXT NOT NULL DEFAULT ''")
    _prune_legacy_prices(conn)
    _backfill_legacy_market(conn)
    conn.commit()


def upsert_source(conn, key, name, board, url, enabled=True) -> None:
    conn.execute(
        "INSERT INTO sources(key,name,board,url,enabled) VALUES(?,?,?,?,?) "
        "ON CONFLICT(key) DO UPDATE SET name=excluded.name, board=excluded.board, url=excluded.url, enabled=excluded.enabled",
        (key, name, board, url, 1 if enabled else 0),
    )
    conn.commit()


def start_crawl_run(conn, source_key, rules_version="") -> int:
    cur = conn.execute(
        "INSERT INTO crawl_runs(source_key,started_at,status,rules_version) VALUES(?,?,?,?)",
        (source_key, now_iso(), "running", rules_version),
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
    "INSERT INTO marketing_copy(short_uri,author,description,transcript,published_at,cover_url,link,fetched_at) "
    "VALUES(?,?,?,?,?,?,?,?) "
    "ON CONFLICT(short_uri) DO UPDATE SET "
    "author=excluded.author,description=excluded.description,"
    "transcript=CASE WHEN excluded.transcript='' THEN transcript ELSE excluded.transcript END,"
    "published_at=excluded.published_at,cover_url=excluded.cover_url,link=excluded.link,"
    "fetched_at=excluded.fetched_at"
)


def upsert_marketing_copy(conn, item) -> int:
    conn.execute(
        UPSERT_MARKETING_SQL,
        (
            item["short_uri"], item.get("author", ""), item.get("description", ""),
            item.get("transcript", ""), item.get("published_at", ""), item.get("cover_url", ""),
            item.get("link", ""), item.get("fetched_at", now_iso()),
        ),
    )
    conn.commit()
    return 1


def list_marketing_copy(conn, limit=200):
    return conn.execute(
        "SELECT id, short_uri, author, description, transcript, published_at, cover_url, link, fetched_at "
        "FROM marketing_copy ORDER BY published_at DESC, id DESC LIMIT ?", (int(limit),)).fetchall()


def update_marketing_transcript(conn, copy_id, transcript) -> int:
    cur = conn.execute(
        "UPDATE marketing_copy SET transcript=? WHERE id=?", (transcript, int(copy_id)))
    conn.commit()
    return cur.rowcount


UPSERT_PRICE_SQL = (
    "INSERT INTO prices(commodity,price_type,market,spec,value,unit,change,change_pct,"
    "price_date,source_key,raw_label,origin,basis,contract,fetched_at) "
    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
    "ON CONFLICT(commodity,price_type,market,spec,price_date,source_key) DO UPDATE SET "
    "value=excluded.value,unit=excluded.unit,change=excluded.change,change_pct=excluded.change_pct,"
    "raw_label=excluded.raw_label,origin=excluded.origin,basis=excluded.basis,"
    "contract=excluded.contract,fetched_at=excluded.fetched_at"
)

def _previous_value(conn, row) -> float:
    """同品种同口径同市场的上一条报价，用于给没有涨跌的源补涨跌。"""
    prev = conn.execute(
        "SELECT value FROM prices WHERE commodity=? AND price_type=? AND market=? AND spec=? "
        "AND source_key=? AND price_date<? ORDER BY price_date DESC LIMIT 1",
        (row["commodity"], row["price_type"], row.get("market", ""), row.get("spec", ""),
         row["source_key"], row["price_date"])).fetchone()
    return float(prev["value"]) if prev and prev["value"] is not None else None


def _fill_change(conn, row) -> None:
    if row.get("change") is not None:
        return
    prev = _previous_value(conn, row)
    if prev is None or prev == 0:
        return
    change = round(float(row["value"]) - prev, 4)
    row["change"] = change
    row["change_pct"] = round(change / prev * 100, 2)


def upsert_prices(conn, rows) -> int:
    count = 0
    for r in rows:
        r.setdefault("market", "")
        r.setdefault("origin", "")
        r.setdefault("spec", "")
        r.setdefault("basis", "")
        r.setdefault("contract", "")
        _fill_change(conn, r)
        conn.execute(
            UPSERT_PRICE_SQL,
            (
                r["commodity"], r["price_type"], r["market"], r["spec"], float(r["value"]),
                r.get("unit", ""), r.get("change"), r.get("change_pct"), r["price_date"],
                r["source_key"], r.get("raw_label", ""), r["origin"], r["basis"], r["contract"],
                r.get("fetched_at", now_iso()),
            ),
        )
        count += 1
    _prune_empty_scope_rows(conn, rows)
    conn.commit()
    return count


def _prune_empty_scope_rows(conn, rows) -> None:
    """新口径已带市场/规格时，删掉同组遗留的空口径行（换口径前抓的乱数据）。"""
    combos = {(r["commodity"], r["price_type"], r["source_key"], r["price_date"])
              for r in rows if r.get("market") or r.get("spec")}
    for commodity, price_type, source_key, price_date in combos:
        conn.execute(
            "DELETE FROM prices WHERE commodity=? AND price_type=? AND source_key=? "
            "AND price_date=? AND market='' AND spec=''",
            (commodity, price_type, source_key, price_date))


def sync_price_source_day(conn, source_key, rows) -> None:
    """一个源当天抓完的全量即当日全量：源今天没再出的报价要清掉。

    必须在整源抓完（所有 URL 都解析完）后调用一次，不能按单个 URL 批次调用。
    """
    by_day: dict = {}
    for r in rows:
        by_day.setdefault((r["source_key"], r["price_date"]), set()).add(
            (r["commodity"], r["price_type"], r["market"], r["spec"]))
    for (src_key, price_date), keys in by_day.items():
        if src_key != source_key:
            continue
        pairs = {(commodity, price_type) for commodity, price_type, _m, _s in keys}
        for commodity, price_type in pairs:
            existing = conn.execute(
                "SELECT id, market, spec FROM prices WHERE source_key=? AND price_date=? "
                "AND commodity=? AND price_type=?",
                (src_key, price_date, commodity, price_type)).fetchall()
            for row in existing:
                if (commodity, price_type, row["market"], row["spec"]) not in keys:
                    conn.execute("DELETE FROM prices WHERE id=?", (row["id"],))
