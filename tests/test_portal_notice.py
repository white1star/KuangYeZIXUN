import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from tools import build_portal

NODE = shutil.which("node")
requires_node = pytest.mark.skipif(NODE is None, reason="未安装 node，跳过 JS 求值/行为断言")
SCRIPT_EVAL = Path(__file__).with_name("notice_script_eval.js")


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


@pytest.mark.parametrize("broken", ["{不是合法 JSON", "", '{"id": "a",}'])
def test_broken_json_rejected(tmp_path, broken):
    path = tmp_path / "notices.json"
    path.write_text(broken, encoding="utf-8")
    with pytest.raises(build_portal.NoticeError, match="JSON"):
        build_portal.load_notices(path)


def test_non_object_element_rejected(tmp_path):
    path = _write(tmp_path / "notices.json", [123])
    with pytest.raises(build_portal.NoticeError, match="对象"):
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


@pytest.mark.parametrize("bad_id", [["20260929-01"], {"k": "v"}])
def test_unhashable_id_rejected(tmp_path, bad_id):
    path = _write(tmp_path / "notices.json", [_notice(id=bad_id)])
    with pytest.raises(build_portal.NoticeError, match="id"):
        build_portal.load_notices(path)


def test_blank_field_rejected(tmp_path):
    path = _write(tmp_path / "notices.json", [_notice(title="   ")])
    with pytest.raises(build_portal.NoticeError, match="title"):
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


def test_sort_does_not_mutate_input():
    items = [
        _notice(id="old", date="2026-09-28"),
        _notice(id="pin", date="2026-09-01", pinned=True),
    ]
    before = [dict(n) for n in items]
    ordered = build_portal.sort_notices(items)
    assert [n["id"] for n in ordered] == ["pin", "old"]
    assert items == before
    assert [n["id"] for n in items] == ["old", "pin"]
    assert ordered is not items


def test_latest_notice_id_after_sort():
    items = [
        _notice(id="old", date="2026-09-28"),
        _notice(id="pin", date="2026-09-01", pinned=True),
    ]
    assert build_portal.latest_notice_id(items) == "pin"


def test_latest_notice_id_empty_when_no_notices():
    assert build_portal.latest_notice_id([]) == ""


# 任务书原夹具把 console.log(1) 放在两个标记之间，而 inject 的契约是"替换标记区间"，
# 二者不可兼得（脚本必然被删掉）。断言本意是"注入不影响标记以外的页面内容"，
# 故把该脚本移到标记区间之外，断言逐条保持原样。
HTML = "<html><body>\n%s\n%s\n<script>console.log(1)</script>\n</body></html>\n"


def _portal_html():
    return HTML % (build_portal.NOTICES_BEGIN, build_portal.NOTICES_END)


def _injected_block(html: str) -> str:
    """取出 index.html 里两个 NOTICES 标记之间的注入块原文（含标记本身）。"""
    start = html.index(build_portal.NOTICES_BEGIN)
    end = html.index(build_portal.NOTICES_END)
    return html[start:end + len(build_portal.NOTICES_END)]


def _data_expr(block: str) -> str:
    """取出注入块里 <script> 与 </script> 之间的 JS 源码（去掉定界标签）。

    不能对整块断言"不含 < > &"：定界标签 </script> 自身就带 >。
    """
    m = re.search(r"<script>([\s\S]*)</script>", block)
    assert m, "注入块缺少 <script> 定界标签"
    return m.group(1)


def _eval_page_with_node(index: Path) -> dict:
    """用 node 真实解析注入的数据脚本，返回求值结果。

    脚本原文逐字取自生成出来的 index.html，node 内部语法错误会直接抛异常
    （非零退出），因此"id 里的引号把脚本打死了"这种故障在这里必然暴露。
    """
    proc = subprocess.run([NODE, str(SCRIPT_EVAL), str(index)],
                          capture_output=True, encoding="utf-8")
    assert proc.returncode == 0, "node 求值失败：%s%s" % (proc.stdout, proc.stderr)
    return json.loads(proc.stdout)


def test_inject_replaces_between_markers():
    # 注入块自带首尾标记（render_block 就是这样产出的，build 也只这样传），
    # 所以"标记各出现一次"才成立；传裸 BLOCK 与 inject 的"替换标记区间"契约冲突。
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


@pytest.mark.parametrize("raw,escaped", [("<", "\\u003c"), (">", "\\u003e"), ("&", "\\u0026")])
def test_render_block_escapes_each_dangerous_char(raw, escaped):
    """三个危险字符必须逐一被转义。

    原用例只断言了 \\u003c，把实现里 replace(">")/replace("&") 两行删掉照样全绿。
    这里按字符参数化：任一行的转义被摘掉，只有对应参数这一条会红。
    断言"转义形式存在"的同时断言"原字符消失"，避免"页面里多写了一份"式蒙混。
    """
    block = build_portal.render_block([_notice(title="甲%s乙" % raw, body="丙%s丁" % raw)])
    expr = _data_expr(block)
    assert escaped in expr, "%s 没有被转义成 %s" % (raw, escaped)
    assert raw not in expr, "注入块里仍残留裸字符 %s" % raw


def test_render_block_escapes_dangerous_chars_in_latest_id():
    """id 与 payload 同源，必须共用同一套转义。"""
    expr = _data_expr(build_portal.render_block([_notice(id="a<b>c&d")]))
    assert "__NOTICE_LATEST__" in expr
    assert '"a\\u003cb\\u003ec\\u0026d"' in expr


# load_notices 只查空/重复/可哈希，不拦 id 里的尖括号与引号，
# 所以下面的 id 都是"合法数据、危险输出"——必须由渲染层兜住。
@requires_node
@pytest.mark.parametrize("bad_id", [
    "</script><img src=x onerror=alert(1)>",
    'say "hi"',
    '反斜杠\\与"引号"混排',
    "</script><script>alert(1)</script>",
])
def test_latest_id_injection_is_neutralized(tmp_path, bad_id):
    """裸 %s 插值 id 的两种真实后果都要被挡住。

    1) id 含 </script>：裸标签落进页面，HTML 解析器提前截断脚本；
    2) id 含 "：JS 字符串字面量提前闭合，整段数据脚本语法错误。
    后者最阴险——页面不报错，只是静默显示"暂无通知"，看起来像"没人发通知"。
    """
    index = tmp_path / "index.html"
    index.write_text(_portal_html(), encoding="utf-8")
    _write(tmp_path / "notices.json", [_notice(id=bad_id)])
    result = build_portal.build(tmp_path)
    assert result["latest"] == bad_id

    block = _injected_block(index.read_text(encoding="utf-8"))
    # 注入块里只允许有它自己的那一个闭合 </script>（行尾定界标签）
    assert block.count("</script>") == 1, "注入块里出现了额外的 </script>"
    assert "</script><img" not in block
    assert "<img" not in block
    assert "</script><script>" not in block
    # 单引号插值处的 id 必须是合法的 JS 字符串字面量：node 能解析且求值回原值
    got = _eval_page_with_node(index)
    assert got["latest"] == bad_id, "转义后的 id 求值不等于原 id"
    assert got["notices"][0]["id"] == bad_id


def test_latest_id_and_payload_escape_are_the_same_function():
    """id 与 payload 必须共用同一个转义实现，不允许日后各写一套。

    行为测试已经证明"两者都被转义"，这条只补结构约束：实现里再出现第二套
    转义字面量，就说明有人复制粘贴了逻辑，只改了其中一处。
    """
    src = Path(build_portal.__file__).read_text(encoding="utf-8")
    for char, code in (("<", "003c"), (">", "003e"), ("&", "0026")):
        hits = re.findall(r'\.replace\(\s*"%s"\s*,\s*"\\\\u%s"\s*\)' % (char, code), src)
        assert len(hits) == 1, "字符 %s 的转义实现出现 %d 处，id 与 payload 可能走偏" % (char, len(hits))


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


def test_build_second_run_does_not_touch_index_on_disk(tmp_path):
    """幂等必须钉在 I/O 层，不能只钉返回值。

    只断言 changed is False 的话，把 `if not check and changed:` 去掉、
    改成无条件 write_bytes，字节数一样、返回值一样，全部用例照样绿——
    但每次 build 都会刷新 mtime，git 与增量备份都被无意义地搅动。
    """
    index = tmp_path / "index.html"
    index.write_text(_portal_html(), encoding="utf-8")
    _write(tmp_path / "notices.json", [_notice()])
    build_portal.build(tmp_path)
    before = index.stat()
    stamp = getattr(before, "st_mtime_ns", None)
    if stamp is None:  # 极端平台的兜底：拿不到纳秒时间戳就退回 mtime，再不行就放弃断言
        stamp = before.st_mtime
    # 留出足够间隔：文件系统的 mtime 精度不足以分辨"同一瞬间"的两次写，
    # 间隔太短会把"真的重写了"误判成"没重写"，测试就成了假绿。
    time.sleep(0.05)
    assert build_portal.build(tmp_path)["changed"] is False
    after = index.stat()
    after_stamp = getattr(after, "st_mtime_ns", None)
    if after_stamp is None:
        after_stamp = after.st_mtime
    assert after_stamp == stamp, "内容未变却重写了 index.html，幂等没落到 I/O 层"


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


def test_main_check_returns_1_when_page_is_stale(tmp_path, capsys):
    """--check 是发布前的防错闸门：页面没跟上 notices.json 就必须挡住 push。

    漏跑 build（或 build 报错被忽略）时，页面会原样上线，通知静默不出现，
    员工只会以为没人发通知。退出码非 0 才能让 README 里的 push 步骤停下来。
    """
    index = tmp_path / "index.html"
    index.write_text(_portal_html(), encoding="utf-8")
    _write(tmp_path / "notices.json", [_notice()])
    assert build_portal.main(["--portal", str(tmp_path), "--check"]) == 1
    out = capsys.readouterr().out
    assert "页面未注入最新通知" in out
    assert "不带 --check 的 build" in out
    assert "20260929-01" in out
    # 只校验不写盘：闸门不能顺手把页面改了
    assert index.read_text(encoding="utf-8") == _portal_html()


def test_main_check_returns_1_when_only_title_changed(tmp_path, capsys):
    """最常见的漏跑场景：只改了 notices.json，页面还是上一版。"""
    index = tmp_path / "index.html"
    index.write_text(_portal_html(), encoding="utf-8")
    _write(tmp_path / "notices.json", [_notice()])
    assert build_portal.main(["--portal", str(tmp_path)]) == 0
    capsys.readouterr()
    _write(tmp_path / "notices.json", [_notice(title="新标题")])
    assert build_portal.main(["--portal", str(tmp_path), "--check"]) == 1
    assert "页面未注入最新通知" in capsys.readouterr().out
    assert "新标题" not in index.read_text(encoding="utf-8")


def test_main_check_returns_0_when_in_sync(tmp_path, capsys):
    """成功路径不能被误伤：页面已同步时 --check 仍返回 0。"""
    index = tmp_path / "index.html"
    index.write_text(_portal_html(), encoding="utf-8")
    _write(tmp_path / "notices.json", [_notice()])
    assert build_portal.main(["--portal", str(tmp_path)]) == 0
    capsys.readouterr()
    assert build_portal.main(["--portal", str(tmp_path), "--check"]) == 0
    out = capsys.readouterr().out
    assert "校验通过" in out
    assert "20260929-01" in out


def test_main_check_returns_0_with_no_notices_at_all(tmp_path, capsys):
    """门户仓库里 notices.json 缺失（从未发过通知）时不算陈旧。"""
    index = tmp_path / "index.html"
    index.write_text(_portal_html(), encoding="utf-8")
    assert build_portal.main(["--portal", str(tmp_path)]) == 0
    capsys.readouterr()
    assert build_portal.main(["--portal", str(tmp_path), "--check"]) == 0
    assert "（无）" in capsys.readouterr().out


PORTAL_DIR = Path(os.environ.get("PORTAL_DIR", r"E:\矿_news\.superpowers\sdd\portal"))


def _portal_index() -> Path:
    index = PORTAL_DIR / "index.html"
    if not index.exists():
        pytest.skip("未找到门户工作副本（%s），先 clone white1star.github.io" % index)
    return index


def _portal_page():
    return _portal_index().read_text(encoding="utf-8")



def _css_rule_body(html, selector):
    """取出某条 CSS 规则自身花括号内的声明。

    整页字符串搜索没有鉴别力：页面里 .e-head/.foot-inner/.np-head 以及中文注释
    都含 `justify-content:space-between`，删掉 .head-inner 的那条声明照样能命中。
    所以必须按选择器定位到规则起点，再按花括号配平取到声明体。
    """
    m = re.search(r"(?<![\w.-])" + re.escape(selector) + r"\s*\{", html)
    assert m, "找不到 CSS 规则 %s" % selector
    i, depth = m.end(), 1
    while depth and i < len(html):
        depth += (html[i] == "{") - (html[i] == "}")
        i += 1
    assert depth == 0, "CSS 规则 %s 花括号不配平" % selector
    return html[m.end():i - 1]


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
    """正文必须走 textContent，不能用 innerHTML 拼接。

    整页禁 innerHTML：注入时 < > & 已转义、不会截断 </script>，该页也没有任何
    正当的 innerHTML 需求；按字段逐一断言 textContent，防止有人只改标题就蒙混过关。
    """
    html = _portal_page()
    assert "innerHTML" not in html, "门户页面禁止 innerHTML（通知内容是纯文本）"
    for field in ("n.title", "n.body", "n.date"):
        assert re.search(r"\.textContent\s*=\s*" + re.escape(field) + r"\b", html), \
            "%s 必须用 textContent 渲染" % field


def test_portal_bell_is_top_right():
    body = _css_rule_body(_portal_page(), ".head-inner")
    assert "justify-content:space-between" in body.replace(" ", ""), \
        "铃铛要靠右，.head-inner 规则本身必须含 justify-content:space-between"
