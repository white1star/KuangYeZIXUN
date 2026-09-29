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
