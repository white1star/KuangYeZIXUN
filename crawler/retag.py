import json

from crawler import classify, store
from crawler.config import load_settings, load_tags


def retag(conn, tags) -> int:
    rows = conn.execute("SELECT id,title,summary,board FROM articles ORDER BY id").fetchall()
    updated = 0
    for row in rows:
        cls = classify.classify(row["title"], row["summary"] or "", row["board"], tags)
        conn.execute(
            "UPDATE articles SET minerals=?,regions=?,types=? WHERE id=?",
            (json.dumps(cls["minerals"], ensure_ascii=False),
             json.dumps(cls["regions"], ensure_ascii=False),
             json.dumps(cls["types"], ensure_ascii=False),
             row["id"]),
        )
        updated += 1
    conn.commit()
    return updated


def main():
    settings = load_settings()
    tags = load_tags()
    conn = store.connect(settings.db_path)
    store.init_db(conn)
    try:
        count = retag(conn, tags)
    finally:
        conn.close()
    print(f"重新打标完成：更新 {count} 条文章")


if __name__ == "__main__":
    main()
