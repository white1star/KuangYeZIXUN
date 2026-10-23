# -*- coding: utf-8 -*-
"""数据源扩容的回归测试：页面级品种、同键中位数聚合、品类覆盖。"""
from pathlib import Path

from bs4 import BeautifulSoup

from crawler import price_sources, store
from crawler.config import load_sources
from crawler.main import _url_specs

SOURCE_DIR = Path(__file__).resolve().parent.parent / "config" / "sources"


def _cfg(key):
    return next(s for s in load_sources() if s["key"] == key)


# --------------------------------------------------------------------------
# 页面级品种（生意社一个品类页 = 一个品种）
# --------------------------------------------------------------------------

def test_url_specs_accept_plain_strings_and_dicts():
    assert _url_specs({"key": "x", "url": "https://a"}) == [{"url": "https://a"}]
    specs = _url_specs({"key": "x", "urls": ["https://a", {"url": "https://b", "commodity": "铜"}]})
    assert specs == [{"url": "https://a"}, {"url": "https://b", "commodity": "铜"}]


def test_table_parser_uses_page_level_commodity():
    html = """<table>
      <tr><td>品名甲</td><td>规格A</td><td>国产</td><td>1,000 元/吨</td><td>市场价</td><td>河南</td><td>某厂</td><td>2026-10-23</td></tr>
      <tr><td>品名乙</td><td>规格B</td><td>国产</td><td>2,000 元/吨</td><td>出厂价</td><td>山东</td><td>某厂</td><td>2026-10-23</td></tr>
    </table>"""
    cfg = {"key": "t", "commodity": "铁矿石", "price_type": "现货", "unit": "元/吨",
           "table": {"row": "table tr", "cell": "td",
                     "columns": {"name": 0, "spec": 1, "origin": 2, "price": 3,
                                 "basis": 4, "market": 5, "date": 7}}}
    rows = price_sources.parse_table(html, cfg)
    assert {r["commodity"] for r in rows} == {"铁矿石"}
    assert {r["market"] for r in rows} == {"河南", "山东"}
    assert {r["spec"] for r in rows} == {"规格A", "规格B"}
    assert {r["basis"] for r in rows} == {"市场价", "出厂价"}
    assert all(r["price_date"] == "2026-10-23" for r in rows)


def test_page_level_map_beats_source_level_map():
    html = """<table>
      <tr><td>钼铁</td><td>FeMo60</td><td>国产</td><td>334,700 元/吨</td><td>市场价</td><td>河南</td><td>某厂</td><td>2026-10-23</td></tr>
    </table>"""
    cfg = {"key": "t", "price_type": "现货", "unit": "元/吨",
           "table": {"row": "table tr", "cell": "td",
                     "columns": {"name": 0, "spec": 1, "origin": 2, "price": 3,
                                 "basis": 4, "market": 5, "date": 7}},
           "commodity_map": {"钼铁": ["钼铁"], "钼酸铵": ["钼酸铵"]}}
    assert price_sources.parse_table(html, cfg)[0]["commodity"] == "钼铁"


# --------------------------------------------------------------------------
# 同一市场多家报价 → 中位数
# --------------------------------------------------------------------------

def _row(value, market="河南", spec="二级冶金焦", source="pp100"):
    return {"commodity": "焦炭", "price_type": "现货", "value": value, "unit": "元/吨",
            "change": None, "change_pct": None, "price_date": "2026-10-23",
            "source_key": source, "raw_label": "焦炭", "market": market,
            "origin": "国产", "spec": spec, "basis": "市场价", "contract": "",
            "fetched_at": store.now_iso()}


def test_same_market_quotes_collapse_to_median(tmp_path):
    conn = store.connect(tmp_path / "t.db")
    store.init_db(conn)
    store.upsert_prices(conn, [_row(1000.0), _row(5000.0), _row(2000.0)])
    got = conn.execute("SELECT value FROM prices WHERE commodity='焦炭'").fetchall()
    assert len(got) == 1
    assert got[0]["value"] == 2000.0, "同市场同规格应取中位数，不能随机留最后一条"
    conn.close()


def test_different_specs_stay_separate(tmp_path):
    conn = store.connect(tmp_path / "t.db")
    store.init_db(conn)
    store.upsert_prices(conn, [_row(1000.0, spec="二级冶金焦"),
                               _row(1800.0, spec="准一级冶金焦")])
    got = conn.execute("SELECT value FROM prices ORDER BY value").fetchall()
    assert [r["value"] for r in got] == [1000.0, 1800.0]
    conn.close()


# --------------------------------------------------------------------------
# 品类覆盖配置
# --------------------------------------------------------------------------

def test_pp100_covers_iron_ore_across_ports():
    cfg = _cfg("pp100")
    specs = [s for s in cfg["urls"] if isinstance(s, dict)]
    iron = [s for s in specs if s.get("commodity") == "铁矿石"]
    assert len(iron) >= 3, "铁矿石应覆盖多页（港口/品种多）"
    assert "铁矿石" in (cfg.get("covered_commodities") or [])


def test_pp100_does_not_mix_molybdenum_products():
    """钼精矿/钼铁/钼酸铵必须分开，且口径混杂的钼酸铵页已停采。"""
    cfg = _cfg("pp100")
    names = {s.get("commodity") for s in cfg["urls"] if isinstance(s, dict)}
    assert "钼" not in names
    assert "钼酸铵" not in names, "该页同规格价格从 2.3 万到 39 万，已停采"
    assert "钼酸铵" not in (cfg.get("covered_commodities") or [])


def test_pp100_covers_non_metal_ores():
    """选矿设备客户常见的非金属矿要有地区报价。"""
    covered = set(_cfg("pp100").get("covered_commodities") or [])
    for name in ("萤石", "石英砂", "高岭土", "滑石", "硅藻土", "生石灰", "铝土矿", "萤石精矿"):
        assert name in covered, f"缺少非金属矿: {name}"


def test_ccmn_small_metals_and_rare_earth():
    xjs = _cfg("ccmn_xjs")
    xtjs = _cfg("ccmn_xtjs")
    assert {"镁", "铟", "碲", "铋", "金属硅"} <= set(xjs["covered_commodities"])
    assert {"氧化钕", "氧化镨", "金属镝"} <= set(xtjs["covered_commodities"])
    for src in (xjs, xtjs):
        assert src["parser"] == "ccmn_quota"
        assert src.get("exact_match") is True
