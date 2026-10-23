# -*- coding: utf-8 -*-
"""每日矿石价格日报解析。"""
from datetime import date

from crawler import wechat
from crawler.ore_daily import parse


def _cfg():
    return {"key": "ore_daily", "price_type": "现货"}


def test_rare_earth_ores_with_folded_unit():
    text = "\n".join([
        "以下是2026年10月20日『17:23』，各种矿石价格。",
        "【有色金属◆稀有金属矿石】",
        "一、钨(W)精矿",
        "黑钨精矿",
        "≥65%：29.0万元/吨(北方有色网报价)/30.5万元/吨(中钨在线报价)。",
        "≥55%：28.6万元/标吨(北方有色网报价，折合实吨24.2万元/吨)/30.1万元/吨。",
        "二、钼(Mo)精矿",
        "40-45%品位：5340-5400元/吨度(主流成交价围绕5400元/吨度附近)。",
        "三、钛(Ti)精矿",
        "1. 四川地区(攀枝花主产区)",
        "TiO2≥46%(10矿)：1120-1160元/吨(出厂不含税)",
    ])
    rows = parse(text, _cfg())
    by = {(r["commodity"], r["spec"]): r for r in rows}
    assert by[("钨精矿", "黑钨精矿 ≥65%")]["value"] == 290000
    assert by[("钨精矿", "黑钨精矿 ≥65%")]["unit"] == "元/吨"
    assert by[("钨精矿", "黑钨精矿 ≥55%")]["value"] == 242000
    assert by[("钼精矿", "40-45%")]["unit"] == "元/吨度"
    assert by[("钼精矿", "40-45%")]["value"] == 5370
    ti = by[("钛精矿", "TiO2≥46%")]
    assert ti["market"] == "四川"
    assert ti["value"] == 1140
    assert all(r["price_date"] == "2026-10-20" for r in rows)


def test_coal_spec_and_region():
    text = "\n".join([
        "以下是2026年10月20日。",
        "【煤炭】",
        "一、动力煤价格",
        "港口市场：北方港口，5500大卡主流报价在1030-1040元/吨，5000大卡报价在930-940元/吨。",
        "二、炼焦煤价格",
        "山西地区：部分优质低硫主焦煤(如安泽)暂稳于2370元/吨，部分高硫瘦煤(如吕梁)跌至1900元/吨。",
    ])
    rows = parse(text, _cfg())
    coal = {r["spec"]: r for r in rows if r["commodity"] == "动力煤"}
    assert coal["5500大卡"]["value"] == 1035
    assert coal["5500大卡"]["market"] == "北方港口"
    assert coal["5000大卡"]["value"] == 935
    ck = {r["market"]: r for r in rows if r["commodity"] == "焦煤"}
    assert ck["安泽"]["spec"] == "低硫主焦煤"
    assert ck["安泽"]["value"] == 2370
    assert ck["吕梁"]["spec"] == "高硫瘦煤"


def test_bare_yuan_uses_unit_line():
    text = "\n".join([
        "以下是2026年10月21日。",
        "【黑色金属矿石】",
        "一、铁(Fe)矿石",
        "1、港口现货价格(单位：元/湿吨，含税自提价)",
        "青岛港：PB粉(61.5%)652元，PB粉(60.8%)648-650元。",
    ])
    rows = parse(text, _cfg())
    pb = [r for r in rows if r["commodity"] == "铁矿石"]
    assert pb and pb[0]["unit"] == "元/湿吨"
    assert pb[0]["market"] == "青岛港"
    assert pb[0]["value"] == 652


def test_wechat_pick_prefers_newest_posted_by_account():
    items = wechat.search_items("""
    <li id="sogou_vr_11002601_box_0">
      <h3><a href="/link?url=abc" uigs="article_title_0">10月21日，各种矿石价格</a></h3>
      <div class="s-p"><span class="all-time-y2">矿业咨讯</span>
      <span class="s2"><script>document.write(timeConvert('1792533660'))</script></span></div>
    </li>
    <li id="sogou_vr_11002601_box_1">
      <h3><a href="/link?url=def" uigs="article_title_1">10月22日，各种矿石价格</a></h3>
      <div class="s-p"><span class="all-time-y2">其他号</span>
      <span class="s2"><script>document.write(timeConvert('1792610000'))</script></span></div>
    </li>
    """)
    assert len(items) == 2
    hit = wechat.pick(items, account="矿业咨讯", keyword="各种矿石价格",
                      max_age_days=30, today=date(2026, 10, 23))
    assert hit["title"].startswith("10月21日")
