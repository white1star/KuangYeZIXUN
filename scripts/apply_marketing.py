import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from crawler import store

FIELDS = ("short_uri", "author", "description", "transcript", "published_at", "cover_url", "link", "fetched_at")


def export(db_path, out_path, show=print) -> int:
    conn = store.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT short_uri, author, description, transcript, published_at, cover_url, link, fetched_at "
            "FROM marketing_copy ORDER BY id").fetchall()
        data = [{field: (row[field] if row[field] is not None else "") for field in FIELDS} for row in rows]
    finally:
        conn.close()
    Path(out_path).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    show(f"已导出 {len(data)} 条文案到 {out_path}")
    return 0


def apply(json_path, db_path, show=print) -> int:
    data = json.loads(Path(json_path).read_text(encoding="utf-8"))
    conn = store.connect(db_path)
    try:
        store.init_db(conn)
        conn.execute("DELETE FROM marketing_copy")
        conn.commit()
        for item in data:
            store.upsert_marketing_copy(conn, {field: item.get(field, "") for field in FIELDS})
        conn.commit()
    finally:
        conn.close()
    show(f"已导入 {len(data)} 条文案")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="导出/导入营销文案（用于办公室→服务器同步）")
    parser.add_argument("--export", metavar="JSON", help="从数据库导出到 JSON 文件")
    parser.add_argument("--apply", metavar="JSON", help="从 JSON 文件导入数据库（覆盖现有文案）")
    parser.add_argument("--db", default=str(ROOT / "data" / "news.db"), help="SQLite 数据库路径")
    args = parser.parse_args(argv)
    if args.export:
        return export(args.db, args.export)
    if args.apply:
        return apply(args.apply, args.db)
    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
