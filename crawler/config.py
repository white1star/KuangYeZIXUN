from dataclasses import dataclass
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    port: int
    summary_max_chars: int
    dedup_threshold: float
    request_timeout: int
    request_retries: int
    request_interval: float
    db_path: Path
    data_dir: Path
    logs_dir: Path


def _data_dir() -> Path:
    d = ROOT / "data"
    d.mkdir(exist_ok=True)
    return d


def _logs_dir() -> Path:
    d = ROOT / "logs"
    d.mkdir(exist_ok=True)
    return d


def load_settings(path=None) -> Settings:
    p = Path(path) if path else ROOT / "config" / "settings.yaml"
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    data_dir = _data_dir()
    return Settings(
        port=int(raw.get("port", 8080)),
        summary_max_chars=int(raw.get("summary_max_chars", 200)),
        dedup_threshold=float(raw.get("dedup_threshold", 0.85)),
        request_timeout=int(raw.get("request_timeout", 15)),
        request_retries=int(raw.get("request_retries", 2)),
        request_interval=float(raw.get("request_interval", 1.5)),
        db_path=data_dir / "news.db",
        data_dir=data_dir,
        logs_dir=_logs_dir(),
    )


def load_tags(path=None) -> dict:
    p = Path(path) if path else ROOT / "config" / "tags.yaml"
    return yaml.safe_load(p.read_text(encoding="utf-8"))


def load_sources(sources_dir=None) -> list:
    d = Path(sources_dir) if sources_dir else ROOT / "config" / "sources"
    sources = []
    for f in sorted(d.glob("*.yaml")):
        cfg = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        cfg.setdefault("key", f.stem)
        cfg.setdefault("enabled", True)
        sources.append(cfg)
    return sources
