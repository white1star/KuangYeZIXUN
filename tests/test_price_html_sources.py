from pathlib import Path

import pytest

from crawler import price_sources
from crawler.config import load_sources

FIXTURES = Path(__file__).resolve().parent / "fixtures"
PRICE_HTML_SOURCES = ["pp100", "ccmn", "sxcoal", "cctd", "mysteel"]


@pytest.mark.parametrize("key", PRICE_HTML_SOURCES)
def test_price_source_parses_from_snapshot(key):
    src = [s for s in load_sources() if s["key"] == key][0]
    if not src.get("enabled", True):
        pytest.skip(f"{key} 已停用")
    html = (FIXTURES / f"{key}_list.html").read_text(encoding="utf-8")
    rows = price_sources.parse(src["parser"], html, src)
    assert len(rows) >= 1, f"{key} 未解析出任何价格"
    assert all(r["value"] > 0 for r in rows), f"{key} 出现非法价格"
    unknown = {r["commodity"] for r in rows} - set(src.get("commodity_map", {}).keys())
    assert not unknown, f"{key} 出现未知品种: {unknown}"


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
