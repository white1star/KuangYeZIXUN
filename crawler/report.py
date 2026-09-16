from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def logs_dir() -> Path:
    d = ROOT / "logs"
    d.mkdir(exist_ok=True)
    return d


def snapshots_dir() -> Path:
    d = logs_dir() / "snapshots"
    d.mkdir(exist_ok=True)
    return d


def log(message: str, name: str = "crawler") -> None:
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}"
    path = logs_dir() / f"{name}_{datetime.now().strftime('%Y%m%d')}.log"
    with path.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
    print(line)


def save_snapshot(source_key: str, text: str, directory=None) -> Path:
    d = Path(directory) if directory else snapshots_dir()
    d.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = d / f"{source_key}_{stamp}.html"
    seq = 2
    while path.exists():
        path = d / f"{source_key}_{stamp}_{seq:03d}.html"
        seq += 1
    path.write_text(text or "", encoding="utf-8")
    return path


def prune_snapshots(source_key: str, keep: int = 3, directory=None) -> None:
    d = Path(directory) if directory else snapshots_dir()
    files = sorted(d.glob(f"{source_key}_*.html"))
    drop = files[:-keep] if keep > 0 else files
    for f in drop:
        f.unlink()
