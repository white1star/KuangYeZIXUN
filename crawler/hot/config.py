"""选矿热榜配置加载。"""
from dataclasses import dataclass
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_CONFIG = ROOT / "config" / "hot.yaml"


@dataclass(frozen=True)
class HotConfig:
    path: Path
    enabled: bool
    max_age_days: int
    wechat_max_age_days: int
    cleanup_days: int
    request_timeout: int
    request_interval: float
    keywords: dict
    excludes: tuple
    categories: dict
    category_priority: list
    sources: dict
    search_keywords: dict
    block_terms: tuple
    competitors: tuple


DEFAULTS = {
    "enabled": True,
    "max_age_days": 7,
    "wechat_max_age_days": 730,
    "cleanup_days": 30,
    "request_timeout": 20,
    "request_interval": 1.5,
}


def load_hot_config(path=None) -> HotConfig:
    p = Path(path) if path else DEFAULT_CONFIG
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raw = {}
    values = {**DEFAULTS, **{k: v for k, v in raw.items() if v is not None}}
    keywords = values.get("mining_keywords") or {}
    categories = values.get("categories") or {}
    sources = values.get("sources") or {}
    search = values.get("search_keywords") or {}
    return HotConfig(
        path=p,
        enabled=bool(values["enabled"]),
        max_age_days=int(values["max_age_days"]),
        wechat_max_age_days=int(values["wechat_max_age_days"]),
        cleanup_days=int(values["cleanup_days"]),
        request_timeout=int(values["request_timeout"]),
        request_interval=float(values["request_interval"]),
        keywords={str(k): int(v) for k, v in keywords.items()},
        excludes=tuple(str(x) for x in (values.get("exclude_terms") or [])),
        categories={str(k): [str(x) for x in (v or [])] for k, v in categories.items()},
        category_priority=[str(x) for x in (values.get("category_priority") or list(categories))],
        sources={str(k): dict(v or {}) for k, v in sources.items()},
        search_keywords={str(k): [str(x) for x in (v or [])] for k, v in search.items()},
        block_terms=tuple(str(x) for x in (values.get("block_terms") or [])),
        competitors=tuple(str(x) for x in (values.get("competitors") or [])),
    )


def source_conf(cfg: HotConfig, key: str) -> dict:
    conf = dict(cfg.sources.get(key) or {})
    conf.setdefault("name", key)
    conf.setdefault("enabled", True)
    conf.setdefault("weight", 0.8)
    return conf
