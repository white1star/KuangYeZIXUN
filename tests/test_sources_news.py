from pathlib import Path

import pytest

from crawler import parse
from crawler.config import load_sources

FIXTURES = Path(__file__).resolve().parent / "fixtures"
ARTICLE_SOURCES = ["mnr", "chinamine", "ndrc", "mee", "nea", "hebei_zrzy", "tangshan_zygh",
                   "cwestc", "ccoalnews", "cnmn", "kyb",
                   "sx_zrzyt", "nmg_zrzyt", "yn_zrzyt", "sd_zrzyt",
                   "gz_zrzyt", "hn_zrzyt", "xj_zrzyt", "gx_zrzyt",
                   "gold_kyyw", "worldmr"]


@pytest.mark.parametrize("key", ARTICLE_SOURCES)
def test_source_parses_from_snapshot(key):
    src = [s for s in load_sources() if s["key"] == key][0]
    if not src.get("enabled", True):
        pytest.skip(f"{key} 已停用")
    ext = src.get("fixture_ext", "html")
    html = (FIXTURES / f"{key}_list.{ext}").read_text(encoding="utf-8")
    items = parse.parse_list(html, src, src["url"])
    assert len(items) >= 5, f"{key} 解析条数不足"
    assert all(i.title and i.url.startswith("http") for i in items), f"{key} 标题/链接异常"
    lst = src.get("list") or {}
    if lst.get("date") or lst.get("date_regex"):
        assert sum(1 for i in items if i.published_at) >= 3, f"{key} 日期解析异常"
