"""规则版本号：把 config/ 下决定"抓什么、怎么分类"的文件内容哈希成版本号。

用途：回答"这批数据是哪版规则产出的"——排查数据异常时先对齐版本，
避免拿现在的规则去解释几天前规则抓出来的数据。
"""
import hashlib
from pathlib import Path

PREFIX = "rv-"
GLOBS = ("sources/*.yaml", "tags.yaml", "settings.yaml")


def compute_rules_version(config_dir) -> str:
    config_dir = Path(config_dir)
    if not config_dir.exists():
        return PREFIX + "unknown"
    h = hashlib.sha256()
    files = []
    for pattern in GLOBS:
        files.extend(sorted(config_dir.glob(pattern)))
    for path in sorted(files, key=lambda p: str(p.relative_to(config_dir))):
        h.update(str(path.relative_to(config_dir)).replace("\\", "/").encode("utf-8"))
        h.update(b"\0")
        h.update(path.read_bytes())
        h.update(b"\0")
    return PREFIX + h.hexdigest()[:10]
