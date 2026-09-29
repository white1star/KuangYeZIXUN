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
