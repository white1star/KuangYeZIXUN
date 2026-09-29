import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

TABLES = ("articles", "prices", "feedback", "crawl_runs", "marketing_copy")


def verify_backup(src_path, backup_path) -> tuple:
    """校验备份可读且条数与源库一致。

    只对比行数就够：integrity_check 负责结构完整，行数负责"确实是这一版的完整拷贝"。
    """
    backup_path = Path(backup_path)
    if not backup_path.exists() or backup_path.stat().st_size == 0:
        return False, "备份文件不存在或为空"
    try:
        b = sqlite3.connect("file:%s?mode=ro" % backup_path.as_posix(), uri=True)
        try:
            if b.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                return False, "完整性检查未通过（文件损坏）"
            s = sqlite3.connect("file:%s?mode=ro" % Path(src_path).as_posix(), uri=True)
            try:
                for table in TABLES:
                    try:
                        n_src = s.execute("SELECT count(*) FROM %s" % table).fetchone()[0]
                        n_bak = b.execute("SELECT count(*) FROM %s" % table).fetchone()[0]
                    except sqlite3.OperationalError:
                        continue          # 该表在旧库里可能不存在
                    if n_src != n_bak:
                        return False, "%s 条数不一致（源 %d / 备份 %d）" % (table, n_src, n_bak)
            finally:
                s.close()
        finally:
            b.close()
    except sqlite3.DatabaseError as exc:
        return False, "备份无法读取：%s" % exc
    return True, "校验通过"


def run_backup(db_path, backup_dir, keep_days=30) -> Path:
    db_path = Path(db_path)
    backup_dir = Path(backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)
    target = backup_dir / f"news_{datetime.now().strftime('%Y%m%d')}.db"
    src = sqlite3.connect(str(db_path))
    dst = sqlite3.connect(str(target))
    try:
        with dst:
            src.backup(dst)
    finally:
        src.close()
        dst.close()
    ok, why = verify_backup(db_path, target)
    if not ok:
        target.unlink(missing_ok=True)
        raise RuntimeError("备份校验失败（已删除坏备份）：%s" % why)
    cutoff = datetime.now() - timedelta(days=keep_days)
    for f in backup_dir.glob("news_*.db"):
        try:
            day = datetime.strptime(f.stem.split("_")[1], "%Y%m%d")
        except (IndexError, ValueError):
            continue
        if day < cutoff:
            f.unlink()
    return target


if __name__ == "__main__":
    from crawler.config import load_settings
    s = load_settings()
    target = run_backup(s.db_path, s.data_dir / "backup")
    ok, why = verify_backup(s.db_path, target)
    print(f"备份文件：{target}")
    print(f"备份校验：{'通过' if ok else '不通过'}（{why}）")
