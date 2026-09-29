"""门户通知：校验 notices.json 并注入门户 index.html（纯静态，无接口）。

发布：
    python -m tools.build_portal --portal .superpowers/sdd/portal
    python -m tools.build_portal --portal .superpowers/sdd/portal --check
"""
import json
import re
from datetime import datetime
from pathlib import Path

NOTICES_BEGIN = "<!-- NOTICES:BEGIN -->"
NOTICES_END = "<!-- NOTICES:END -->"
MAX_TITLE = 40
MAX_BODY = 300
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class NoticeError(ValueError):
    """通知数据不合法，或门户页面缺少注入标记。"""


def load_notices(path: Path) -> list:
    """读并校验 notices.json；文件不存在按"无通知"处理。"""
    path = Path(path)
    if not path.exists():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise NoticeError("notices.json 顶层必须是数组")
    seen = set()
    for item in raw:
        if not isinstance(item, dict):
            raise NoticeError(f"通知必须是对象：{item}")
        for key in ("id", "date", "title", "body"):
            if not str(item.get(key, "")).strip():
                raise NoticeError(f"通知缺少 {key}：{item}")
        if item["id"] in seen:
            raise NoticeError(f"通知 id 重复：{item['id']}")
        seen.add(item["id"])
        if not DATE_RE.match(str(item["date"])):
            raise NoticeError(f"date 必须是 YYYY-MM-DD：{item['date']}")
        try:
            datetime.strptime(str(item["date"]), "%Y-%m-%d")
        except ValueError as exc:
            # 形如 2026-13-45 的日历非法日期，统一转成 NoticeError 抛给调用方
            raise NoticeError(f"date 不是合法日期：{item['date']}") from exc
        if len(str(item["title"])) > MAX_TITLE:
            raise NoticeError(f"title 超长（>{MAX_TITLE}）：{item['id']}")
        if len(str(item["body"])) > MAX_BODY:
            raise NoticeError(f"body 超长（>{MAX_BODY}）：{item['id']}")
    return raw


def sort_notices(notices: list) -> list:
    """置顶优先，其余按日期倒序。sort 稳定，两段排序即可。"""
    ordered = sorted(notices, key=lambda n: str(n["date"]), reverse=True)
    ordered.sort(key=lambda n: 0 if n.get("pinned") else 1)
    return ordered


def latest_notice_id(notices: list) -> str:
    """排序后第一条的 id 即最新；无通知返回空串。"""
    ordered = sort_notices(notices)
    return str(ordered[0]["id"]) if ordered else ""
