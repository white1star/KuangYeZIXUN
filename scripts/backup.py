import sqlite3
from datetime import datetime, timedelta
from pathlib import Path


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
    print(run_backup(s.db_path, s.data_dir / "backup"))
