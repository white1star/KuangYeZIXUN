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
               commodity_map={"JM0": "焦煤", "J0": "焦炭", "I0": "铁矿石", "CU0": "铜",
                              "AL0": "铝", "ZN0": "锌", "PB0": "铅", "SN0": "锡",
                              "AU0": "黄金", "AG0": "白银", "SM0": "锰硅", "SF0": "硅铁"})
    rows = price_sources.parse_futures_sina(text, cfg)
    assert len(rows) >= 8
    assert all(r["value"] > 0 for r in rows)
    assert all(re.match(r"^\d{4}-\d{2}-\d{2}$", r["price_date"]) for r in rows)
    assert {r["commodity"] for r in rows} <= set(cfg["commodity_map"].values())


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
