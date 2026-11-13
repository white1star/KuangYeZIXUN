"""手动清理热榜里的噪音条目（与矿业无关的生活/医药内容）。"""
from pathlib import Path

from crawler import store
from crawler.hot import store as hot_store

ROOT = Path(__file__).resolve().parent.parent


def main():
    conn = store.connect(str(ROOT / "data" / "news.db"))
    try:
        store.init_db(conn)
        noise = hot_store.purge_noise(conn)
        cleaned = hot_store.clean_titles(conn)
        summaries = hot_store.clean_summaries(conn)
    finally:
        conn.close()
    print(f"已清理噪音 {noise} 条，清洗标题 {cleaned} 条，摘要 {summaries} 条")


if __name__ == "__main__":
    main()
