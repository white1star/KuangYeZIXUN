import json
import re
from pathlib import Path

import pytest

from crawler import price_sources

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _cfg(key, **kw):
    base = {"key": key, "board": "price", "unit": "元/吨", "price_type": "期货"}
    base.update(kw)
    return base


def test_sina_futures_real_sample():
    text = (FIXTURES / "sina_futures_list.txt").read_text(encoding="utf-8")
    cfg = _cfg("sina_futures",
               field_map={"name": 0, "last": 8, "prev_settle": 10},
               unit_map={"黄金": "元/克", "白银": "元/千克"},
               commodity_map={"JM0": "焦煤", "J0": "焦炭", "I0": "铁矿石", "CU0": "铜",
                              "AL0": "铝", "ZN0": "锌", "PB0": "铅", "SN0": "锡",
                              "AU0": "黄金", "AG0": "白银", "SM0": "锰硅", "SF0": "硅铁"})
    rows = price_sources.parse_futures_sina(text, cfg)
    assert len(rows) >= 8
    assert all(r["value"] > 0 for r in rows)
    assert all(re.match(r"^\d{4}-\d{2}-\d{2}$", r["price_date"]) for r in rows)
    assert {r["commodity"] for r in rows} <= set(cfg["commodity_map"].values())
    by = {r["commodity"]: r for r in rows}
    assert by["黄金"]["unit"] == "元/克"
    assert by["白银"]["unit"] == "元/千克"
    assert by["焦煤"]["unit"] == "元/吨"


def test_match_commodity_fallbacks():
    assert price_sources._match_commodity("cu2610", {"cu2610": "铜"}) == "铜"
    assert price_sources._match_commodity("磷矿石（30%品位）", {"磷矿石": ["磷矿石"]}) == "磷矿石"
    assert price_sources._match_commodity("焦煤2601", {"焦煤连续": "焦煤"}) == "焦煤"


def test_eastmoney_futures_contract():
    text = (FIXTURES / "eastmoney_futures_list.json").read_text(encoding="utf-8")
    cfg = _cfg("eastmoney_futures",
               field_map={"name": "f14", "last": "f2", "change": "f4", "change_pct": "f3"},
               commodity_map={"焦煤连续": "焦煤", "沪铜连续": "铜"})
    rows = price_sources.parse_futures_eastmoney(text, cfg)
    assert len(rows) == 2
    assert rows[0]["value"] == 2105
    assert rows[0]["change"] == -25
    assert rows[1]["commodity"] == "铜"


def test_eastmoney_non_json_raises():
    with pytest.raises(ValueError):
        price_sources.parse_futures_eastmoney("<html>被拦截</html>", _cfg("eastmoney_futures"))


def test_shfe_picks_max_open_interest_month():
    text = (FIXTURES / "shfe_list.json").read_text(encoding="utf-8")
    cfg = _cfg("shfe", commodity_map={"cu": "铜", "pb": "铅"})
    rows = price_sources.parse_shfe_daily(text, cfg)
    by = {r["commodity"]: r for r in rows}
    assert by["铜"]["value"] == 71250
    assert by["铅"]["value"] == 16800


def test_parse_unknown_parser_raises():
    with pytest.raises(ValueError):
        price_sources.parse("nope", "", {})


def test_ccmn_quota_keeps_each_market_quote():
    """长江有色报价接口：按报价市场逐条出价，不再跨市场平均。"""
    text = (FIXTURES / "ccmn_sn_list.json").read_text(encoding="utf-8")
    cfg = _cfg("ccmn_sn", price_type="现货",
               items="quotaVoList",
               quote={"name": "productSortName", "price": "avgPrice", "date": "publishDate",
                      "market": "marketName", "origin": "placeOrTrademark", "spec": "trademark"},
               commodity_map={"锡": ["1#锡"]})
    rows = price_sources.parse_ccmn_quota(text, cfg)
    assert rows, "未解析出任何报价"
    assert {r["commodity"] for r in rows} == {"锡"}
    assert all(r["price_type"] == "现货" and r["value"] > 0 for r in rows)
    assert all(re.match(r"^\d{4}-\d{2}-\d{2}$", r["price_date"]) for r in rows)
    # 每条报价独立成行：市场、产地/牌号都不丢
    payload = json.loads(text)
    items = payload["body"]["quotaVoList"]
    assert len(rows) == len(items)
    markets = {r["market"] for r in rows}
    assert markets == {i["marketName"] for i in items}
    assert len(markets) > 1, "长江有色应返回多个市场的报价"
    by_key = {(r["market"], r["origin"], r["spec"]): r["value"] for r in rows}
    for item in items:
        key = (item["marketName"], item["placeOrTrademark"], item["trademark"])
        # 同一市场同牌号只保留一条，值必须来自该市场该牌号的报价
        assert by_key[key] == round(item["avgPrice"], 2) or (
            item["marketName"], round(item["avgPrice"], 2)) in {
                (r["market"], r["value"]) for r in rows}


def test_ccmn_quota_exact_match_rejects_other_products():
    """精确匹配：1#电解铜板 / 压铸锌合金这类加工材不能混进铜/锌。"""
    text = (FIXTURES / "ccmn_sn_list.json").read_text(encoding="utf-8")
    cfg = _cfg("ccmn_sn", price_type="现货", exact_match=True,
               quote={"name": "productSortName", "price": "avgPrice", "date": "publishDate"},
               commodity_map={"铜": ["1#铜"]})
    rows = price_sources.parse_ccmn_quota(text, cfg)
    assert rows == []


def test_ccmn_quota_non_json_raises():
    with pytest.raises(ValueError):
        price_sources.parse_ccmn_quota("<html>被拦截</html>", _cfg("ccmn_sn"))
