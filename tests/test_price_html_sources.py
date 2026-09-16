from pathlib import Path

import pytest

from crawler import price_sources
from crawler.config import load_sources

FIXTURES = Path(__file__).resolve().parent / "fixtures"
PRICE_HTML_SOURCES = ["pp100", "ccmn", "sxcoal", "cctd", "mysteel"]
MIN_ROWS = {"pp100": 10}
EXPECTED = {
    "pp100_list.html": ("焦炭", 1900.0, "元/吨"),
    "pp100_list_2.html": ("萤石", 1700.0, "元/吨"),
    "pp100_list_3.html": ("石英砂", 800.0, "元/吨"),
    "pp100_list_4.html": ("锑", 105500.0, "元/吨"),
    "pp100_list_5.html": ("锰", 18100.0, "元/吨"),
    "pp100_list_6.html": ("钨", 600.0, "元/千克"),
    "pp100_list_7.html": ("钼", 285000.0, "元/吨"),
    "pp100_list_8.html": ("焦煤", 2540.0, "元/吨"),
    "ccmn_list.html": ("铜", 108900.0, "元/吨"),
    "sxcoal_list.html": ("动力煤", 673.03, "元/吨"),
    "cctd_list.html": ("动力煤", 754.0, "元/吨"),
    "mysteel_list.html": ("铁矿石", 774.12, "元/吨"),
}


def _snapshots():
    return [
        pytest.param(key, path, id=path.name)
        for key in PRICE_HTML_SOURCES
        for path in sorted(FIXTURES.glob(f"{key}_list*.html"))
    ]


@pytest.mark.parametrize("key", PRICE_HTML_SOURCES)
def test_price_source_has_snapshot(key):
    assert list(FIXTURES.glob(f"{key}_list*.html")), f"{key} 缺少快照样本"


@pytest.mark.parametrize("key,path", _snapshots())
def test_price_source_parses_from_snapshot(key, path):
    src = [s for s in load_sources() if s["key"] == key][0]
    if not src.get("enabled", True):
        pytest.skip(f"{key} 已停用")
    html = path.read_text(encoding="utf-8")
    rows = price_sources.parse(src["parser"], html, src)
    min_rows = MIN_ROWS.get(key, 1)
    assert len(rows) >= min_rows, f"{path.name} 解析条数不足: {len(rows)} < {min_rows}"
    assert all(r["value"] > 0 for r in rows), f"{path.name} 出现非法价格"
    unknown = {r["commodity"] for r in rows} - set(src.get("commodity_map", {}).keys())
    assert not unknown, f"{path.name} 出现未知品种: {unknown}"
    unit_map = src.get("unit_map") or {}
    for r in rows:
        expected_unit = unit_map.get(r["commodity"]) or src["unit"]
        assert r["unit"] == expected_unit, (
            f"{path.name} {r['commodity']} 单位异常: {r['unit']} != {expected_unit}"
        )
    expected = EXPECTED.get(path.name)
    assert expected, f"{path.name} 缺少人工核对期望值"
    hit = [r for r in rows if (r["commodity"], r["value"]) == expected[:2]]
    assert hit, f"{path.name} 未解析出期望行: {expected[:2]}"
    assert hit[0]["unit"] == expected[2], (
        f"{path.name} 期望行单位不符: {hit[0]['unit']} != {expected[2]}"
    )


def test_table_parser_with_keyword_matching():
    html = """<table><tr><th>商品</th><th>价格</th><th>涨跌幅</th></tr>
    <tr><td>磷矿石（30%品位）</td><td>1,050</td><td>+1.2%</td></tr>
    <tr><td>萤石（97%湿粉）</td><td>3,300</td><td>-0.5%</td></tr></table>"""
    cfg = {"key": "t", "unit": "元/吨", "price_type": "现货",
           "table": {"row": "table tr", "cell": "td",
                     "columns": {"name": 0, "price": 1, "change_pct": 2}},
           "commodity_map": {"磷矿石": ["磷矿石"], "萤石": ["萤石"]}}
    rows = price_sources.parse_table(html, cfg)
    assert {r["commodity"] for r in rows} == {"磷矿石", "萤石"}
    assert rows[0]["value"] == 1050.0
    assert rows[0]["change_pct"] == 1.2


def test_regex_parser():
    html = "<div>秦皇岛5500K动力煤现货价 650 元/吨，秦皇岛5000K 560 元/吨</div>"
    cfg = {"key": "c", "unit": "元/吨", "price_type": "现货", "commodity_map": {"动力煤": ["5500", "5000"]},
           "regex": {"pattern": "(?P<name>秦皇岛(?:5500|5000)K?)[^0-9]{0,8}(?P<price>\\d{3,4})"}}
    rows = price_sources.parse_regex(html, cfg)
    assert len(rows) == 2
    assert rows[0]["value"] == 650.0


def test_match_commodity_exact_key_with_list_value():
    assert price_sources._match_commodity("磷矿石", {"磷矿石": ["磷矿石"]}) == "磷矿石"


def test_match_commodity_numeric_keywords():
    assert price_sources._match_commodity("综合交易5500", {"动力煤": [5500, 5000]}) == "动力煤"
