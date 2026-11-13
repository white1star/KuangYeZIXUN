"""清洗 articles 正文库的标题和摘要（去 #/emoji/@/发稿前缀，标题不截断）。

只改 title / summary，不动 url_hash / title_hash，去重不受影响。
"""
from pathlib import Path

from crawler import store
from crawler.hot.keywords import clean_summary, clean_title

ROOT = Path(__file__).resolve().parent.parent


def main():
    conn = store.connect(str(ROOT / "data" / "news.db"))
    try:
        store.init_db(conn)
        rows = conn.execute("SELECT id, title FROM articles").fetchall()
        n = 0
        for row in rows:
            cleaned = clean_title(row[1] or "", max_len=300)
            if cleaned and cleaned != row[1]:
                conn.execute("UPDATE articles SET title=? WHERE id=?", (cleaned, row[0]))
                n += 1

        srows = conn.execute(
            "SELECT id, summary FROM articles WHERE summary<>''").fetchall()
        m = 0
        for row in srows:
            cleaned = clean_summary(row[1] or "")
            if cleaned and cleaned != row[1]:
                conn.execute("UPDATE articles SET summary=? WHERE id=?", (cleaned, row[0]))
                m += 1
        conn.commit()
    finally:
        conn.close()
    print(f"清洗文章标题 {n} / {len(rows)} 条，摘要 {m} 条")


if __name__ == "__main__":
    main()
