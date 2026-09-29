"""门户通知：校验 notices.json 并注入门户 index.html（纯静态，无接口）。

发布：
    python -m tools.build_portal --portal .superpowers/sdd/portal
    python -m tools.build_portal --portal .superpowers/sdd/portal --check
"""
import argparse
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


def _read_json(path: Path):
    """读并解析 notices.json。

    文件内容损坏或为空时 json.loads 抛的是 JSONDecodeError 而非 NoticeError，
    调用方（Task 2 的 CLI）只按 NoticeError 提示中文错误，会因此漏出 traceback，
    故在此处统一收敛成本项目的异常类型。
    """
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise NoticeError(f"notices.json 不是合法 JSON：{exc}") from exc


def load_notices(path: Path) -> list:
    """读并校验 notices.json；文件不存在按"无通知"处理。"""
    path = Path(path)
    if not path.exists():
        return []
    raw = _read_json(path)
    if not isinstance(raw, list):
        raise NoticeError("notices.json 顶层必须是数组")
    seen = set()
    for item in raw:
        if not isinstance(item, dict):
            raise NoticeError(f"通知必须是对象：{item}")
        for key in ("id", "date", "title", "body"):
            if not str(item.get(key, "")).strip():
                raise NoticeError(f"通知缺少 {key}：{item}")
        # id 若是数组/对象，set 查重会抛 TypeError，调用方 except NoticeError 接不住；
        # 统一转成 NoticeError，并带出原值便于定位是哪条数据的问题
        try:
            if item["id"] in seen:
                raise NoticeError(f"通知 id 重复：{item['id']}")
            seen.add(item["id"])
        except TypeError as exc:
            raise NoticeError(f"id 必须是字符串或数字：{item['id']}") from exc
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


def _escape_json(text: str) -> str:
    """把 JSON 文本里的 < > & 转成 \\u 形式。

    三个字符在 HTML 语境下都可能提前闭合 script 标签或开启新标签；转成
    \\uXXXX 后对 JSON 解析结果完全等价，但落到页面上不再是裸字符。
    payload 与 __NOTICE_LATEST__ 的 id 共用这一个函数，不另写第二套转义。
    """
    return (text.replace("<", "\\u003c")
                .replace(">", "\\u003e")
                .replace("&", "\\u0026"))


def _js_string(value: str) -> str:
    """把字符串渲染成 JS 字符串字面量（含两侧引号）并同样转义。

    id 来自 notices.json 的自由文本，和 title/body 一样会原样落进页面。
    早先这里是裸 %s 插值，于是 id 里带 </script> 会截断脚本、带 " 会造成
    JS 语法错误——整段数据脚本随之失效，页面静默显示"暂无通知"且零报错，
    排查成本极高。id 与 payload 是同一份不可信输入，必须走同一套转义。
    """
    return _escape_json(json.dumps(str(value), ensure_ascii=False))


def render_block(notices: list) -> str:
    """生成注入块。JSON 里的 < > & 转成 \\u 形式，防止 </script> 截断脚本。"""
    ordered = sort_notices(notices)
    payload = _escape_json(json.dumps(ordered, ensure_ascii=False, separators=(",", ":")))
    return "\n".join([
        NOTICES_BEGIN,
        "<script>window.__NOTICES__=%s;window.__NOTICE_LATEST__=%s;</script>"
        % (payload, _js_string(latest_notice_id(ordered))),
        NOTICES_END,
    ])


def inject(html: str, block: str) -> str:
    """把标记之间的内容换成 block。标记缺失、重复或顺序颠倒都报错。"""
    if html.count(NOTICES_BEGIN) != 1 or html.count(NOTICES_END) != 1:
        raise NoticeError("index.html 缺少成对的 NOTICES 标记")
    if html.index(NOTICES_BEGIN) > html.index(NOTICES_END):
        raise NoticeError("index.html 的 NOTICES 标记顺序颠倒")
    head, _, rest = html.partition(NOTICES_BEGIN)
    _, _, tail = rest.partition(NOTICES_END)
    return "%s%s%s" % (head, block, tail)


def build(portal_dir, check: bool = False) -> dict:
    """读 notices → 校验排序 → 注入 index.html。内容没变就不写，保证幂等。"""
    portal_dir = Path(portal_dir)
    index = portal_dir / "index.html"
    if not index.exists():
        raise NoticeError("找不到门户页面：%s" % index)
    notices = load_notices(portal_dir / "notices.json")
    raw = index.read_bytes()
    new_bytes = inject(raw.decode("utf-8"), render_block(notices)).encode("utf-8")
    changed = new_bytes != raw
    if not check and changed:
        index.write_bytes(new_bytes)
    return {"notices": len(notices), "latest": latest_notice_id(notices),
            "changed": changed, "checked": check, "index": str(index)}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="把 notices.json 注入门户 index.html")
    parser.add_argument("--portal", required=True, help="门户仓库目录（含 index.html 与 notices.json）")
    parser.add_argument("--check", action="store_true",
                        help="只校验不写文件；页面与 notices.json 不同步时返回非零（发布前防错闸门）")
    args = parser.parse_args(argv)
    try:
        result = build(args.portal, check=args.check)
    except NoticeError as exc:
        print("通知处理失败：%s" % exc)
        return 1
    if args.check and result["changed"]:
        # --check 是发布流程的防错闸门：改了 notices.json 却忘了跑 build
        #（或 build 报错被忽略）时，页面会原样推上线，通知静默不出现，
        # 读者只会以为没人发通知。所以"不同步"必须返回非零挡住后续 push。
        print("通知 %d 条，最新 %s，页面未注入最新通知：%s"
              % (result["notices"], result["latest"] or "（无）", result["index"]))
        print("请先跑不带 --check 的 build 确认写入，再提交推送："
              "python -m tools.build_portal --portal %s" % args.portal)
        return 1
    if args.check:
        state = "校验通过（页面已与 notices.json 同步）"
    else:
        state = "已写入" if result["changed"] else "无需改动"
    print("通知 %d 条，最新 %s，%s：%s"
          % (result["notices"], result["latest"] or "（无）", state, result["index"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
