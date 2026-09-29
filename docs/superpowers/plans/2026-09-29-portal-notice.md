# 信息中心通知栏 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在信息中心门户页右上角加一个铃铛通知按钮，点击展开通知区，按时间排序，小红点提示未读且打开后消失；通知由 AI 写入数据文件并发布，全程纯静态。

**Architecture:** 通知数据放在门户仓库的 `notices.json`，由 `tools/build_portal.py` 校验、排序后注入 `index.html` 里的一对注释标记之间（数据内嵌，页面不运行时 fetch）。门户页推到 GitHub Pages 自动部署，服务器上的门户副本由既有 `mirror_portal.py` 同步。已读状态用 `localStorage` 记录最新通知 id。

**Tech Stack:** Python 3.12（办公端 venv）/ 纯静态 HTML+CSS+JS（无框架、无构建工具）/ pytest。

## Global Constraints

- 纯静态：不得引入后端接口、常驻服务、常驻进程。门户页必须能脱离网络独立工作。
- 通知数据**必须内嵌**进 `index.html`：服务器镜像 `mirror_portal.py` 的 `sync_portal()` 只下载改写 `index.html` 一个文件，页面运行时 `fetch('notices.json')` 会让 `39.96.27.206/` 的通知区空白。
- 通知字段：`id`（全局唯一，建议 `YYYYMMDD-NN`）、`date`（`YYYY-MM-DD`）、`title`（≤40 字）、`body`（≤300 字，纯文本）、`pinned`（可选，默认 false）。
- 排序规则：置顶优先，其余按 `date` 倒序。排序在注入前由脚本完成，前端按数组顺序渲染。
- 已读键名固定为 `portal_notice_read_id`；无通知时不显示小红点；`localStorage` 不可用时静默降级（不显示红点，不报错）。
- 正文与标题一律用 `textContent` 渲染，禁止用 `innerHTML` 拼接用户内容；注入时 JSON 中的 `<` `>` `&` 转成 ``\u003c`` ``\u003e`` ``\u0026``。
- 日常发通知只允许改 `notices.json`，不得手工编辑 `index.html` 的通知数据块。
- 门户工作副本固定放在 `E:\矿_news\.superpowers\sdd\portal`（`.superpowers/` 已被 gitignore，不污染仓库）。测试可用环境变量 `PORTAL_DIR` 覆盖。
- 界面文案、代码注释、提交信息一律中文。
- 每次发布必须核验两个地址：`https://white1star.github.io/` 与 `http://39.96.27.206/`。

---

## File Structure

| 文件 | 位置 | 职责 |
|---|---|---|
| `tools/build_portal.py` | 矿_news 仓库（新建） | 校验 `notices.json`、排序、渲染注入块、替换 `index.html` 标记区间、幂等写盘、CLI |
| `tests/test_portal_notice.py` | 矿_news 仓库（新建） | 数据校验/排序/注入/幂等/UI 契约的全部离线测试 |
| `index.html` | 门户仓库（修改） | 铃铛按钮、遮罩、通知面板、样式、交互脚本、数据标记 |
| `notices.json` | 门户仓库（新建） | 通知数据，唯一需要日常编辑的文件 |
| `.superpowers/sdd/server_deploy.md` | 矿_news 仓库（修改） | 记录通知发布流程 |

**为什么脚本和测试放矿_news 仓库**：门户仓库是纯静态产物仓库，没有 Python 测试基建；矿_news 已有 venv 与 pytest。门户仓库只保留"页面 + 数据"两样产物。

---

### Task 1: 通知数据校验、排序与最新 id

**Files:**
- Create: `tools/build_portal.py`
- Test: `tests/test_portal_notice.py`

**Interfaces:**
- Consumes: 无
- Produces:
  - `class NoticeError(ValueError)` — 数据不合法或页面缺标记
  - `load_notices(path: Path) -> list` — 读 `notices.json` 并校验；文件不存在返回 `[]`
  - `sort_notices(notices: list) -> list` — 置顶优先 + 日期倒序
  - `latest_notice_id(notices: list) -> str` — 排序后首条的 `id`，空列表返回 `""`
  - 常量 `NOTICES_BEGIN`、`NOTICES_END`、`MAX_TITLE=40`、`MAX_BODY=300`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_portal_notice.py`：

```python
import json
from pathlib import Path

import pytest

from tools import build_portal


def _write(path: Path, payload) -> Path:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def _notice(**kw):
    base = {"id": "20260929-01", "date": "2026-09-29", "title": "标题", "body": "内容"}
    base.update(kw)
    return base


def test_missing_file_is_empty_list(tmp_path):
    assert build_portal.load_notices(tmp_path / "nope.json") == []


def test_valid_notices_loaded(tmp_path):
    path = _write(tmp_path / "notices.json", [_notice()])
    assert build_portal.load_notices(path) == [_notice()]


def test_not_top_level_list_rejected(tmp_path):
    path = _write(tmp_path / "notices.json", {"id": "a"})
    with pytest.raises(build_portal.NoticeError, match="数组"):
        build_portal.load_notices(path)


@pytest.mark.parametrize("field", ["id", "date", "title", "body"])
def test_missing_field_rejected(tmp_path, field):
    bad = _notice()
    bad.pop(field)
    path = _write(tmp_path / "notices.json", [bad])
    with pytest.raises(build_portal.NoticeError, match=field):
        build_portal.load_notices(path)


def test_duplicate_id_rejected(tmp_path):
    path = _write(tmp_path / "notices.json", [_notice(), _notice()])
    with pytest.raises(build_portal.NoticeError, match="id 重复"):
        build_portal.load_notices(path)


@pytest.mark.parametrize("bad_date", ["2026/09/29", "2026-13-45", "26-09-29"])
def test_bad_date_rejected(tmp_path, bad_date):
    path = _write(tmp_path / "notices.json", [_notice(date=bad_date)])
    with pytest.raises(build_portal.NoticeError, match="date"):
        build_portal.load_notices(path)


def test_title_too_long_rejected(tmp_path):
    path = _write(tmp_path / "notices.json", [_notice(title="标" * 41)])
    with pytest.raises(build_portal.NoticeError, match="title"):
        build_portal.load_notices(path)


def test_body_too_long_rejected(tmp_path):
    path = _write(tmp_path / "notices.json", [_notice(body="长" * 301)])
    with pytest.raises(build_portal.NoticeError, match="body"):
        build_portal.load_notices(path)


def test_sort_pinned_first_then_date_desc():
    items = [
        _notice(id="a", date="2026-09-29", pinned=False),
        _notice(id="b", date="2026-09-29", pinned=True),
        _notice(id="c", date="2026-09-28", pinned=False),
    ]
    assert [n["id"] for n in build_portal.sort_notices(items)] == ["b", "a", "c"]


def test_sort_keeps_date_desc_inside_pinned_group():
    items = [
        _notice(id="old", date="2026-09-01", pinned=True),
        _notice(id="new", date="2026-09-20", pinned=True),
    ]
    assert [n["id"] for n in build_portal.sort_notices(items)] == ["new", "old"]


def test_latest_notice_id_after_sort():
    items = [
        _notice(id="old", date="2026-09-28"),
        _notice(id="pin", date="2026-09-01", pinned=True),
    ]
    assert build_portal.latest_notice_id(items) == "pin"


def test_latest_notice_id_empty_when_no_notices():
    assert build_portal.latest_notice_id([]) == ""
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv\Scripts\python.exe -m pytest tests\test_portal_notice.py -v`
Expected: 收集阶段报错 `ModuleNotFoundError: No module named 'tools.build_portal'`

- [ ] **Step 3: 写最小实现**

创建 `tools/build_portal.py`：

```python
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


def _read_json(path: Path):
    """读 JSON，把解码/语法错误收敛成 NoticeError，让调用方只需捕获一种异常。"""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise NoticeError("%s 不是合法 JSON：%s" % (path.name, exc)) from exc


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
        try:
            if item["id"] in seen:
                raise NoticeError(f"通知 id 重复：{item['id']}")
            seen.add(item["id"])
        except TypeError as exc:
            # id 若是数组/对象，in/add 会抛 unhashable TypeError，一并收敛成 NoticeError
            raise NoticeError(f"id 必须是字符串或数字：{item['id']}") from exc
        if not DATE_RE.match(str(item["date"])):
            raise NoticeError(f"date 必须是 YYYY-MM-DD：{item['date']}")
        try:
            datetime.strptime(str(item["date"]), "%Y-%m-%d")
        except ValueError as exc:
            # 拦下 2026-13-45 这类格式对但日历非法的日期，统一抛 NoticeError
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
```

（Task 1 不加 CLI，`main` 在 Task 2 补齐。）

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv\Scripts\python.exe -m pytest tests\test_portal_notice.py -v`
Expected: 25 passed

- [ ] **Step 5: 提交**

```bash
git add tools/build_portal.py tests/test_portal_notice.py
git commit -m "feat(portal): 通知数据校验、排序与最新 id"
```

---

### Task 2: 注入渲染、幂等写盘与 CLI

**Files:**
- Modify: `tools/build_portal.py`（替换 Task 1 里的临时 `main` 与 `build_portal_error_notice`）
- Test: `tests/test_portal_notice.py`（追加用例）

**Interfaces:**
- Consumes: Task 1 的 `NoticeError`、`sort_notices`、`latest_notice_id`、`NOTICES_BEGIN/END`
- Produces:
  - `render_block(notices: list) -> str` — 生成含标记的注入块
  - `inject(html: str, block: str) -> str` — 替换标记区间；标记不成对抛 `NoticeError`
  - `build(portal_dir, check: bool = False) -> dict` — 主流程，返回 `{"notices", "latest", "changed", "checked", "index"}`
  - `main(argv=None) -> int` — CLI，失败返回 1

- [ ] **Step 1: 写失败测试**

在 `tests/test_portal_notice.py` 末尾追加：

```python
HTML = "<html><body>\n%s\n%s\n<script>console.log(1)</script>\n</body></html>\n"


def _portal_html():
    return HTML % (build_portal.NOTICES_BEGIN, build_portal.NOTICES_END)


def test_inject_replaces_between_markers():
    # 注入块来自 render_block，自带首尾标记；build 也只传这种块
    block = "%s\nBLOCK\n%s" % (build_portal.NOTICES_BEGIN, build_portal.NOTICES_END)
    out = build_portal.inject(_portal_html(), block)
    assert "BLOCK" in out
    assert "console.log(1)" in out
    assert out.count(build_portal.NOTICES_BEGIN) == 1
    assert out.count(build_portal.NOTICES_END) == 1


def test_inject_requires_markers():
    with pytest.raises(build_portal.NoticeError, match="标记"):
        build_portal.inject("<html>没有标记</html>", "BLOCK")


def test_inject_rejects_duplicated_markers():
    with pytest.raises(build_portal.NoticeError, match="标记"):
        build_portal.inject(_portal_html() + build_portal.NOTICES_BEGIN, "BLOCK")


def test_inject_rejects_reversed_markers():
    html = "<html>%s%s</html>" % (build_portal.NOTICES_END, build_portal.NOTICES_BEGIN)
    with pytest.raises(build_portal.NoticeError, match="顺序"):
        build_portal.inject(html, "BLOCK")


def test_render_block_escapes_html_dangerous_chars():
    block = build_portal.render_block(
        [_notice(title="标题<b>", body='</script><img src=x onerror=alert(1)>"引号"')])
    assert "<img" not in block
    assert "</script><img" not in block
    assert "<b>" not in block
    assert "\\u003c" in block


def test_render_block_puts_pinned_first():
    block = build_portal.render_block([
        _notice(id="old", date="2026-09-01"),
        _notice(id="pin", date="2026-09-20", pinned=True),
    ])
    assert block.index('"pin"') < block.index('"old"')


def test_render_block_carries_latest_id():
    block = build_portal.render_block([_notice(id="newest", date="2026-09-29")])
    assert '__NOTICE_LATEST__="newest"' in block


def test_render_block_empty_notices():
    block = build_portal.render_block([])
    assert "window.__NOTICES__=[]" in block
    assert '__NOTICE_LATEST__=""' in block


def test_build_writes_then_is_idempotent(tmp_path):
    index = tmp_path / "index.html"
    index.write_text(_portal_html(), encoding="utf-8")
    _write(tmp_path / "notices.json", [_notice()])
    first = build_portal.build(tmp_path)
    assert first["changed"] is True
    assert first["notices"] == 1
    assert first["latest"] == "20260929-01"
    after_first = index.read_bytes()
    second = build_portal.build(tmp_path)
    assert second["changed"] is False
    assert index.read_bytes() == after_first


def test_build_check_does_not_write(tmp_path):
    index = tmp_path / "index.html"
    index.write_text(_portal_html(), encoding="utf-8")
    _write(tmp_path / "notices.json", [_notice()])
    before = index.read_bytes()
    result = build_portal.build(tmp_path, check=True)
    assert result["changed"] is True
    assert index.read_bytes() == before


def test_build_missing_index_raises(tmp_path):
    with pytest.raises(build_portal.NoticeError, match="找不到门户页面"):
        build_portal.build(tmp_path)


def test_build_bad_notices_leaves_index_untouched(tmp_path):
    index = tmp_path / "index.html"
    index.write_text(_portal_html(), encoding="utf-8")
    _write(tmp_path / "notices.json", [_notice(id="dup"), _notice(id="dup")])
    before = index.read_bytes()
    with pytest.raises(build_portal.NoticeError):
        build_portal.build(tmp_path)
    assert index.read_bytes() == before


def test_main_returns_1_on_bad_notices(tmp_path, capsys):
    index = tmp_path / "index.html"
    index.write_text(_portal_html(), encoding="utf-8")
    _write(tmp_path / "notices.json", [_notice(id="dup"), _notice(id="dup")])
    assert build_portal.main(["--portal", str(tmp_path)]) == 1
    assert "通知处理失败" in capsys.readouterr().out


def test_main_returns_0_on_success(tmp_path, capsys):
    index = tmp_path / "index.html"
    index.write_text(_portal_html(), encoding="utf-8")
    _write(tmp_path / "notices.json", [_notice()])
    assert build_portal.main(["--portal", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "通知 1 条" in out
    assert "20260929-01" in out
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv\Scripts\python.exe -m pytest tests\test_portal_notice.py -v`
Expected: 新增用例报 `AttributeError: module 'tools.build_portal' has no attribute 'inject'`

- [ ] **Step 3: 写实现**

把 `tools/build_portal.py` 里 Task 1 写的临时 `main` / `build_portal_error_notice` 两段整体替换为：

```python
def render_block(notices: list) -> str:
    """生成注入块。JSON 里的 < > & 转成 \\u 形式，防止 </script> 截断脚本。"""
    ordered = sort_notices(notices)
    payload = json.dumps(ordered, ensure_ascii=False, separators=(",", ":"))
    payload = (payload.replace("<", "\\u003c")
                      .replace(">", "\\u003e")
                      .replace("&", "\\u0026"))
    return "\n".join([
        NOTICES_BEGIN,
        "<script>window.__NOTICES__=%s;window.__NOTICE_LATEST__=\"%s\";</script>"
        % (payload, latest_notice_id(ordered)),
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
    parser.add_argument("--check", action="store_true", help="只校验并打印，不写文件")
    args = parser.parse_args(argv)
    try:
        result = build(args.portal, check=args.check)
    except NoticeError as exc:
        print("通知处理失败：%s" % exc)
        return 1
    if args.check:
        state = "校验通过" if result["changed"] else "无需改动"
    else:
        state = "已写入" if result["changed"] else "无需改动"
    print("通知 %d 条，最新 %s，%s：%s"
          % (result["notices"], result["latest"] or "（无）", state, result["index"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv\Scripts\python.exe -m pytest tests\test_portal_notice.py -v`
Expected: 39 passed

- [ ] **Step 5: 跑全量测试确认没打破别的**

Run: `.venv\Scripts\python.exe -m pytest -q`
Expected: 全部通过（此前基线 229 passed, 1 skipped；新增用例后数量增加，无新增失败）

- [ ] **Step 6: 提交**

```bash
git add tools/build_portal.py tests/test_portal_notice.py
git commit -m "feat(portal): 通知注入、幂等写盘与发布 CLI"
```

---

### Task 3: 门户页面通知 UI

**Files:**
- Create: `.superpowers/sdd/portal/`（clone 自 `https://github.com/white1star/white1star.github.io.git`）
- Modify: `.superpowers/sdd/portal/index.html`
- Test: `tests/test_portal_notice.py`（追加 UI 契约用例）
- Commit in: 门户仓库（`git -C .superpowers/sdd/portal commit`）

**Interfaces:**
- Consumes: Task 2 的 `NOTICES_BEGIN` / `NOTICES_END` 标记
- Produces: 门户页面上 id 为 `notice-bell`、`notice-dot`、`notice-mask`、`notice-panel`、`notice-close`、`notice-list` 的元素；读取 `window.__NOTICES__` 与 `window.__NOTICE_LATEST__`

- [ ] **Step 1: 克隆门户工作副本**

```bash
git clone https://github.com/white1star/white1star.github.io.git .superpowers\sdd\portal
```

Expected: 克隆成功，目录内只有 `index.html` 与 `.git`。若目录已存在则跳过（用 `git -C .superpowers\sdd\portal pull` 更新）。

- [ ] **Step 2: 写失败测试**

先在 `tests/test_portal_notice.py` 的导入区补一行 `import os`（排在 `import json` 之后）——Task 3 才用到它。

然后在文件末尾追加：

```python
PORTAL_DIR = Path(os.environ.get("PORTAL_DIR", r"E:\矿_news\.superpowers\sdd\portal"))


def _portal_page():
    index = PORTAL_DIR / "index.html"
    if not index.exists():
        pytest.skip("未找到门户工作副本（%s），先 clone white1star.github.io" % index)
    return index.read_text(encoding="utf-8")


def test_portal_has_notice_elements():
    html = _portal_page()
    for token in ('id="notice-bell"', 'id="notice-dot"', 'id="notice-mask"',
                  'id="notice-panel"', 'id="notice-close"', 'id="notice-list"'):
        assert token in html, "门户页面缺少 %s" % token


def test_portal_has_notice_markers():
    html = _portal_page()
    assert build_portal.NOTICES_BEGIN in html
    assert build_portal.NOTICES_END in html


def test_portal_read_state_logic_present():
    html = _portal_page()
    assert "portal_notice_read_id" in html
    assert "localStorage.getItem" in html
    assert "localStorage.setItem" in html
    assert "window.__NOTICE_LATEST__" in html


def test_portal_renders_notice_text_safely():
    """正文必须走 textContent，不能用 innerHTML 拼接。"""
    html = _portal_page()
    assert "textContent" in html
    inner_html_lines = [line for line in html.splitlines()
                        if "innerHTML" in line and "notice" in line.lower()]
    assert not inner_html_lines, "通知渲染禁止 innerHTML：%s" % inner_html_lines


def test_portal_bell_is_top_right():
    html = _portal_page().replace(" ", "")
    assert "justify-content:space-between" in html, "铃铛要靠右，head-inner 需要 space-between"
```

- [ ] **Step 3: 跑测试确认失败**

Run: `.venv\Scripts\python.exe -m pytest tests\test_portal_notice.py -v -k portal`
Expected: 5 failed（元素与标记都还没有）

- [ ] **Step 4: 改 CSS**

在 `.superpowers\sdd\portal\index.html` 里：

4a. 把第 13 行的 `.head-inner` 规则改成让品牌与铃铛两端对齐：

```css
.head-inner{display:flex;align-items:center;justify-content:space-between;height:54px;max-width:1156px;margin:0 auto;padding:0 20px}
```

4b. 在 `</style>` 之前（现有第 65 行 `@media` 块之后）插入通知相关样式：

```css
.bell{position:relative;display:flex;align-items:center;justify-content:center;width:36px;height:36px;padding:0;border:1px solid var(--line);border-radius:10px;background:#fff;color:var(--text);cursor:pointer}
.bell:hover{border-color:var(--brand);color:var(--brand)}
.bell-dot{position:absolute;top:-3px;right:-3px;width:9px;height:9px;border-radius:50%;background:#e5484d;border:1.5px solid #fff}
.notice-mask{position:fixed;inset:0;z-index:40;background:rgba(16,24,40,.28);opacity:0;pointer-events:none;transition:opacity .18s ease}
.notice-mask.on{opacity:1;pointer-events:auto}
.notice-panel{position:fixed;top:0;right:0;z-index:41;width:min(380px,100vw);height:100vh;background:var(--card);box-shadow:-8px 0 30px rgba(16,24,40,.14);transform:translateX(100%);transition:transform .2s ease;display:flex;flex-direction:column}
.notice-panel.on{transform:none}
.np-head{display:flex;align-items:center;justify-content:space-between;padding:16px 18px;border-bottom:1px solid var(--line);font-size:15px;font-weight:700}
.np-close{border:0;background:none;font-size:20px;line-height:1;color:var(--muted);cursor:pointer;padding:0 4px}
.np-close:hover{color:var(--brand)}
.np-list{flex:1;overflow:auto;padding:4px 18px 24px}
.np-item{padding:14px 0;border-bottom:1px solid var(--line)}
.np-item:last-child{border-bottom:0}
.np-date{font-size:12px;color:var(--muted)}
.np-pin{display:inline-block;margin-left:6px;padding:0 6px;border-radius:999px;background:var(--brand-soft);color:var(--brand-dark);font-size:11px}
.np-title{margin:5px 0 6px;font-size:15px;font-weight:700;line-height:1.4}
.np-body{margin:0;font-size:13px;line-height:1.7;color:#3c4650;white-space:pre-wrap;word-break:break-word}
.np-empty{padding:48px 0;text-align:center;color:var(--muted);font-size:13px}
@media (max-width:760px){ .notice-panel{width:100vw} }
```

- [ ] **Step 5: 插入铃铛按钮**

在 `</span>`（品牌文字结束，第 74 行）与 `</div>`（`.head-inner` 结束，第 75 行）之间插入：

```html
    <button class="bell" id="notice-bell" type="button" aria-label="通知" aria-expanded="false" aria-controls="notice-panel">
      <svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
        <path d="M18 8a6 6 0 1 0-12 0c0 7-3 9-3 9h18s-3-2-3-9"/>
        <path d="M13.7 21a2 2 0 0 1-3.4 0"/>
      </svg>
      <span class="bell-dot" id="notice-dot" hidden></span>
    </button>
```

- [ ] **Step 6: 插入面板、数据标记与脚本**

在 `</main>` 之后、`<footer class="site-foot">` 之前插入：

```html
<div class="notice-mask" id="notice-mask"></div>
<aside class="notice-panel" id="notice-panel" aria-label="通知区" aria-hidden="true">
  <div class="np-head">
    <span>通知</span>
    <button class="np-close" id="notice-close" type="button" aria-label="关闭">&times;</button>
  </div>
  <div class="np-list" id="notice-list"></div>
</aside>
<!-- NOTICES:BEGIN -->
<!-- NOTICES:END -->
<script>
(function () {
  var KEY = 'portal_notice_read_id';
  var list = window.__NOTICES__ || [];
  var latest = window.__NOTICE_LATEST__ || '';
  var bell = document.getElementById('notice-bell');
  var dot = document.getElementById('notice-dot');
  var panel = document.getElementById('notice-panel');
  var mask = document.getElementById('notice-mask');
  var closeBtn = document.getElementById('notice-close');
  var box = document.getElementById('notice-list');

  function readId() {
    try { return localStorage.getItem(KEY) || ''; } catch (e) { return ''; }
  }
  function markRead() {
    try { if (latest) localStorage.setItem(KEY, latest); } catch (e) { /* 隐私模式：静默降级 */ }
  }
  function render() {
    if (!list.length) {
      box.textContent = '';
      var empty = document.createElement('p');
      empty.className = 'np-empty';
      empty.textContent = '暂无通知';
      box.appendChild(empty);
      return;
    }
    box.textContent = '';
    list.forEach(function (n) {
      var item = document.createElement('article');
      item.className = 'np-item';
      var date = document.createElement('div');
      date.className = 'np-date';
      date.textContent = n.date;
      if (n.pinned) {
        var pin = document.createElement('span');
        pin.className = 'np-pin';
        pin.textContent = '置顶';
        date.appendChild(pin);
      }
      var title = document.createElement('h3');
      title.className = 'np-title';
      title.textContent = n.title;
      var body = document.createElement('p');
      body.className = 'np-body';
      body.textContent = n.body;
      item.appendChild(date);
      item.appendChild(title);
      item.appendChild(body);
      box.appendChild(item);
    });
  }
  function paint() {
    dot.hidden = !(latest && readId() !== latest);
  }
  function open() {
    panel.classList.add('on');
    panel.setAttribute('aria-hidden', 'false');
    mask.classList.add('on');
    bell.setAttribute('aria-expanded', 'true');
    markRead();
    paint();
  }
  function close() {
    panel.classList.remove('on');
    panel.setAttribute('aria-hidden', 'true');
    mask.classList.remove('on');
    bell.setAttribute('aria-expanded', 'false');
  }
  render();
  paint();
  bell.addEventListener('click', function () {
    if (panel.classList.contains('on')) { close(); } else { open(); }
  });
  closeBtn.addEventListener('click', close);
  mask.addEventListener('click', close);
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape') { close(); } });
})();
</script>
```

- [ ] **Step 7: 注入空数据块让页面自洽**

Run: `.venv\Scripts\python.exe -m tools.build_portal --portal .superpowers\sdd\portal`
Expected: `通知 0 条，最新 （无），已写入：.superpowers\sdd\portal\index.html`

- [ ] **Step 8: 跑测试确认通过**

Run: `.venv\Scripts\python.exe -m pytest tests\test_portal_notice.py -v -k portal`
Expected: 5 passed

- [ ] **Step 9: 本地预览人工核验**

```bash
.venv\Scripts\python.exe -m http.server 8099 -d .superpowers\sdd\portal
```

浏览器打开 `http://127.0.0.1:8099/`，逐项确认：铃铛在右上角；无通知时不显示红点；点击展开面板显示"暂无通知"；点遮罩、按 Esc、点关闭按钮都能收起；把窗口缩到 400px 宽，面板占满宽度且能滚动。核验完结束该进程。

- [ ] **Step 10: 在门户仓库提交**

```bash
git -C .superpowers\sdd\portal add index.html
git -C .superpowers\sdd\portal commit -m "feat: 信息中心通知栏（右上角铃铛 + 通知区 + 未读红点）"
```

**不要 push**——推送与服务器同步放到 Task 4 统一做，保证一次发布可完整核验。

- [ ] **Step 11: 在矿_news 仓库提交测试**

```bash
git add tests/test_portal_notice.py
git commit -m "test(portal): 门户通知 UI 契约测试"
```

---

### Task 4: 首发通知并发布到两个地址

**Files:**
- Create: `.superpowers/sdd/portal/notices.json`
- Modify: `.superpowers/sdd/server_deploy.md`
- Commit in: 门户仓库（推送）

**Interfaces:**
- Consumes: Task 2 的 CLI、Task 3 的门户页面
- Produces: 两个公网地址上可见的通知区；发布流程写进运维文档

- [ ] **Step 1: 写首批通知**

创建 `.superpowers\sdd\portal\notices.json`：

```json
[
  {
    "id": "20260929-01",
    "date": "2026-09-29",
    "title": "1#锡 现货已恢复每日更新",
    "body": "长江有色把 1#锡 从列表页下架了，导致锡价停在 9/21。已改用其报价接口，现在每 3 小时更新一次，现货和期货都能看到当日价。",
    "pinned": true
  },
  {
    "id": "20260929-02",
    "date": "2026-09-29",
    "title": "服务器 10 月 18 日到期，请注意续费",
    "body": "承载本站的阿里云轻量服务器将于 10 月 18 日到期。请部门负责人在 10 月 10 日前确认续费，以免站点中断。",
    "pinned": false
  }
]
```

- [ ] **Step 2: 注入并提交门户仓库**

```bash
.venv\Scripts\python.exe -m tools.build_portal --portal .superpowers\sdd\portal
git -C .superpowers\sdd\portal add index.html notices.json
git -C .superpowers\sdd\portal commit -m "docs: 首发两条通知（锡价恢复更新、服务器续费提醒）"
git -C .superpowers\sdd\portal push origin main
```

Expected: `通知 2 条，最新 20260929-01，已写入：...`；推送输出 `main -> main`

- [ ] **Step 3: 核验 GitHub Pages**

等待 1–2 分钟后：

```powershell
$h=(Invoke-WebRequest -Uri "https://white1star.github.io/?t=$(Get-Random)" -UseBasicParsing).Content
if ($h -match '20260929-01' -and $h -match 'notice-bell') { 'Pages OK' } else { 'Pages 未更新' }
```

Expected: `Pages OK`

- [ ] **Step 4: 触发服务器门户镜像同步**

```powershell
.venv\Scripts\python.exe .superpowers\sdd\server.py run "cd /opt/news && .venv/bin/python scripts/mirror_portal.py"
```

Expected: 输出含 `门户页已同步` 与 `竞品站已同步 N 个文件`

- [ ] **Step 5: 核验服务器地址**

```powershell
$h=(Invoke-WebRequest -Uri "http://39.96.27.206/?t=$(Get-Random)" -UseBasicParsing).Content
if ($h -match '20260929-01' -and $h -match 'notice-bell') { '服务器 OK' } else { '服务器未更新' }
```

Expected: `服务器 OK`

- [ ] **Step 6: 人工点一遍线上页面**

浏览器打开 `http://39.96.27.206/`，确认：铃铛在右上角且**红点可见**（本机首次访问）→ 点开面板显示两条通知（置顶那条带"置顶"标签、在最上）→ 关闭后**红点消失** → 刷新页面红点不再出现。

- [ ] **Step 7: 把发布流程写进两份文档**

7a. 服务器运维真相（本机留档，`.superpowers/` 已 gitignore，不提交）——在 `.superpowers\sdd\server_deploy.md` 末尾追加：

```markdown
## 2026-09-29：信息中心通知栏（纯静态）
- 门户源仓库：`white1star/white1star.github.io`（仅 `index.html` + `notices.json`）
- 办公端工作副本：`E:\矿_news\.superpowers\sdd\portal`；发布工具：`E:\矿_news\tools\build_portal.py`
- 发通知流程：改 `notices.json` → `python -m tools.build_portal --portal .superpowers\sdd\portal`
  → 提交推送门户仓库（Pages 自动部署）→ 抓 `white1star.github.io/` 核验
  → 服务器手动同步 `cd /opt/news && .venv/bin/python scripts/mirror_portal.py` → 抓 `39.96.27.206/` 核验
- 平时服务器镜像也会自动同步（cron 7/9/11/13 点），要求立刻生效时手动跑一次
- 注意：通知数据必须内嵌在 index.html（`sync_portal()` 只同步这一个文件），不能在页面里 fetch JSON
```

7b. 对外手册（**已入库**，README 第 12 节「公网部署」末尾）追加：

```markdown
### 发通知（全员可见）

门户页右上角的铃铛是通知入口。在项目目录执行：

```powershell
# 1. 编辑 .superpowers\sdd\portal\notices.json，按 schema 填 id / date / title / body（可加 pinned）
# 2. 注入页面（校验不通过会报错且不改动线上页面）
.venv\Scripts\python.exe -m tools.build_portal --portal .superpowers\sdd\portal
# 3. 提交推送，Pages 自动部署
git -C .superpowers\sdd\portal commit -am "docs: 发布通知"
git -C .superpowers\sdd\portal push origin main
# 4. 核验两个地址
Invoke-WebRequest "https://white1star.github.io/" -UseBasicParsing | Select-Object -Expand Content
Invoke-WebRequest "http://39.96.27.206/" -UseBasicParsing | Select-Object -Expand Content
# 5. 需要立刻在服务器生效时，手动同步门户镜像
.venv\Scripts\python.exe .superpowers\sdd\server.py run "cd /opt/news && .venv/bin/python scripts/mirror_portal.py"
```

通知是全员公开广播，只写可以公开说的内容；员工右下角的「反馈」按钮仍可私信管理员。
```

- [ ] **Step 8: 提交手册改动**

```bash
git add README.md
git commit -m "docs: 公网部署补充通知发布流程"
```

（7a 的 `.superpowers/sdd/server_deploy.md` 不入库，跳过提交。）

- [ ] **Step 9: 记录验收结果**

在本次交付的回复中写明：两个地址的核验结果、首批通知内容、以及"以后发通知只需对 AI 说一句"。

---

## 回滚

门户仓库 `git revert` 对应提交 → Pages 自动回退 → 服务器手动跑一次 `mirror_portal.py`。矿_news 侧无需回滚（只有工具与测试，不影响线上）。

## 后续可做（本次不做）

- 通知过期/自动隐藏（需要写 `expires` 字段并改渲染过滤）
- 通知按站点区分（矿业资讯站 vs 竞品站）
- 服务器镜像改为每次构建后自动触发，去掉 cron 延迟

> **注意（Task 3 完成后补记）**：本页 Task 3 的代码块是发布前的基线，实际实现经过 4 轮审查修复（eadId 返回 null 区分存储不可用、加固两条契约测试、抽屉补 inert+焦点管理+焦点陷阱、Esc 加打开态守卫），与下方代码块**不完全一致**。以 .superpowers\sdd/portal/index.html 实际代码与 .superpowers/sdd/task-3-report.md 为准。
