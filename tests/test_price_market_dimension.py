# -*- coding: utf-8 -*-
"""矿价口径维度回归：P0 止血 + P1 地区/口径维度。

覆盖：
  P0-a 长江有色列表页不再把废铜/废铝当成电解铜报价
  P0-b "全部口径"不再把不同口径拼成一条假线
  P0-c 期货涨跌按昨结算；现货/指数缺涨跌时用库内上一条同口径报价补算
  P0-c 报价日取源站日期，而不是抓取日
  P1   prices 表新增 market/origin/spec/basis/contract，并进入唯一键
  P1   同品种多市场可并存，并在页面上分别展示
"""
import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pytest
import yaml

from crawler import price_sources, store
from crawler.config import load_sources
from site_build.builder import build

FIXTURES = Path(__file__).resolve().parent / "fixtures"
SOURCE_DIR = Path(__file__).resolve().parent.parent / "config" / "sources"


def _cfg(key):
    return next(s for s in load_sources() if s["key"] == key)


def _today():
    return datetime.now().strftime("%Y-%m-%d")


# --------------------------------------------------------------------------
# P0-a：废铜不能再冒充电解铜
# --------------------------------------------------------------------------

def test_ccmn_list_page_never_quotes_scrap_as_electrolytic():
    """列表页第 1 张是废料表，抓铜时不能命中"破碎黄铜""马达铜"这类废铜。"""
    cfg = _cfg("ccmn")
    html = (FIXTURES / "ccmn_list.html").read_text(encoding="utf-8")
    rows = price_sources.parse(cfg["parser"], html, cfg)
    assert rows, "ccmn 列表页应至少解析出 1#铜"
    assert {r["commodity"] for r in rows} <= {"铜", "铅锌"}
    assert all("废" not in r["raw_label"] for r in rows)
    for r in rows:
        assert r["raw_label"] in ("1#铜", "还原铅(98%)", "再生精铅"), r["raw_label"]


def test_ccmn_list_page_only_parses_first_table():
    """只解析第 0 张表（常规有色），废料表/升贴水表不参与。"""
    cfg = _cfg("ccmn")
    assert cfg["table"]["index"] == 0
    assert cfg.get("exact_match") is True


def test_exact_match_blocks_contains_match():
    assert price_sources._match_commodity("1#铜", {"铜": ["1#铜"]}) == "铜"
    assert price_sources._match_commodity("1#电解铜板", {"铜": ["1#铜"]}) is None
    assert price_sources._match_commodity("破碎熟铝", {"铝": ["A00铝"]}) is None
    assert price_sources._match_commodity("破碎熟铝", {"铝": ["A00铝"]}, exact=True) is None


# --------------------------------------------------------------------------
# P1：口径字段入库
# --------------------------------------------------------------------------

def test_prices_table_has_market_dimension():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    store.init_db(conn)
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(prices)")}
    assert {"market", "origin", "spec", "basis", "contract"} <= cols
    sql = conn.execute("SELECT sql FROM sqlite_master WHERE name='prices'").fetchone()[0]
    flat = sql.replace(" ", "").replace("\n", "")
    assert "UNIQUE(commodity,price_type,market,spec,price_date,source_key)" in flat
    conn.close()


def test_migration_keeps_rows_and_adds_columns(tmp_path):
    """旧库迁移：老数据不丢，新字段补齐。"""
    db = tmp_path / "old.db"
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE prices (id INTEGER PRIMARY KEY AUTOINCREMENT, commodity TEXT NOT NULL, "
        "price_type TEXT NOT NULL, value REAL NOT NULL, unit TEXT NOT NULL DEFAULT '', "
        "change REAL, change_pct REAL, price_date TEXT NOT NULL, source_key TEXT NOT NULL, "
        "raw_label TEXT NOT NULL DEFAULT '', fetched_at TEXT NOT NULL, "
        "UNIQUE(commodity, price_type, price_date, source_key))")
    conn.execute(
        "INSERT INTO prices(commodity,price_type,value,unit,price_date,source_key,raw_label,fetched_at) "
        "VALUES('铜','期货',109000,'元/吨','2026-10-20','sina_futures','CU0','2026-10-20 12:00:00')")
    conn.commit()
    conn.close()

    conn = store.connect(db)
    store.init_db(conn)
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(prices)")}
    assert {"market", "origin", "spec", "basis", "contract"} <= cols
    assert conn.execute("SELECT COUNT(*) c FROM prices").fetchone()["c"] == 1
    conn.close()


def test_migration_purges_replaced_scope_rows(tmp_path):
    """换口径的源（列表页混入废料）留下的空口径历史行要被清掉。"""
    db = tmp_path / "old.db"
    conn = sqlite3.connect(str(db))
    conn.execute(
        "CREATE TABLE prices (id INTEGER PRIMARY KEY AUTOINCREMENT, commodity TEXT NOT NULL, "
        "price_type TEXT NOT NULL, value REAL NOT NULL, unit TEXT NOT NULL DEFAULT '', "
        "change REAL, change_pct REAL, price_date TEXT NOT NULL, source_key TEXT NOT NULL, "
        "raw_label TEXT NOT NULL DEFAULT '', fetched_at TEXT NOT NULL, "
        "UNIQUE(commodity, price_type, price_date, source_key))")
    conn.execute(
        "INSERT INTO prices(commodity,price_type,value,unit,price_date,source_key,raw_label,fetched_at) "
        "VALUES('铜','现货',59100,'元/吨','2026-10-20','ccmn','破碎黄铜','2026-10-20 12:00:00')")
    conn.commit()
    conn.close()

    conn = store.connect(db)
    store.init_db(conn)
    assert conn.execute("SELECT COUNT(*) c FROM prices").fetchone()["c"] == 0
    conn.close()


def test_upsert_keeps_same_commodity_in_different_markets(tmp_path):
    """同一品种不同市场要能并存（原来会被唯一键压成一条）。"""
    conn = store.connect(tmp_path / "t.db")
    store.init_db(conn)
    rows = [{
        "commodity": "铜", "price_type": "现货", "value": 110740.0, "unit": "元/吨",
        "change": None, "change_pct": None, "price_date": "2026-10-21",
        "source_key": "ccmn_cu", "raw_label": "1#铜", "market": "长江现货",
        "origin": "国产", "spec": "1#", "basis": "含税", "contract": "",
        "fetched_at": store.now_iso(),
    }]
    store.upsert_prices(conn, rows)
    rows[0]["value"] = 110340.0
    rows[0]["market"] = "辽宁有色"
    store.upsert_prices(conn, rows)
    got = conn.execute(
        "SELECT market, value FROM prices WHERE commodity='铜' ORDER BY market").fetchall()
    assert [(r["market"], r["value"]) for r in got] == [("辽宁有色", 110340.0), ("长江现货", 110740.0)]
    conn.close()


def test_source_day_snapshot_drops_removed_product(tmp_path):
    """源今天不再出的报价要清掉（改了商品映射后不留残行）。"""
    conn = store.connect(tmp_path / "t.db")
    store.init_db(conn)
    base = {"commodity": "铜精矿", "price_type": "现货", "unit": "元/干吨",
            "change": None, "change_pct": None, "price_date": "2026-10-21",
            "source_key": "ccmn_jskc", "raw_label": "铜精矿(20%)", "market": "山东有色",
            "origin": "青岛", "spec": "20%", "basis": "", "contract": "",
            "fetched_at": store.now_iso()}
    store.upsert_prices(conn, [dict(base, value=31650.0),
                               dict(base, value=31600.0, market="广东有色", origin="广州")])
    store.sync_price_source_day(conn, "ccmn_jskc", [dict(base, value=31600.0,
                                                          market="广东有色", origin="广州")])
    got = conn.execute("SELECT market FROM prices WHERE commodity='铜精矿'").fetchall()
    assert [r["market"] for r in got] == ["广东有色"]
    conn.close()


# --------------------------------------------------------------------------
# P0-c：涨跌口径
# --------------------------------------------------------------------------

def test_change_is_filled_from_previous_quote(tmp_path):
    """源不提供涨跌时，用库内上一条同口径同市场报价补算。"""
    conn = store.connect(tmp_path / "t.db")
    store.init_db(conn)
    for day, value in (("2026-10-19", 100.0), ("2026-10-20", 110.0)):
        store.upsert_prices(conn, [{
            "commodity": "萤石", "price_type": "现货", "value": value, "unit": "元/吨",
            "change": None, "change_pct": None, "price_date": day,
            "source_key": "pp100", "raw_label": "萤石", "market": "广西",
            "origin": "国产", "spec": "70%", "basis": "出厂价", "contract": "",
            "fetched_at": store.now_iso(),
        }])
    row = conn.execute(
        "SELECT value, change, change_pct FROM prices WHERE price_date='2026-10-20'").fetchone()
    assert row["change"] == 10.0
    assert row["change_pct"] == 10.0
    conn.close()


def test_futures_change_uses_prev_settle():
    """新浪期货的涨跌按昨结算算（交易所口径），不是反推昨收。"""
    cfg = _cfg("sina_futures")
    text = (FIXTURES / "sina_futures_list.txt").read_text(encoding="utf-8")
    rows = price_sources.parse(cfg["parser"], text, cfg)
    assert rows
    for r in rows:
        assert r["basis"] == "不含税·昨结算"
        assert r["contract"]


def test_cctd_uses_source_quote_date_not_fetch_day():
    """cctd 的报价日取页面"日期："，不是抓取当天。"""
    cfg = _cfg("cctd")
    html = (FIXTURES / "cctd_list.html").read_text(encoding="utf-8")
    rows = price_sources.parse(cfg["parser"], html, cfg)
    assert rows
    assert all(r["price_date"] != _today() for r in rows)
    assert {r["price_type"] for r in rows} == {"港口现货", "月度长协", "年度长协"}
    assert {r["market"] for r in rows} == {"秦皇岛", "综合交易", "年度长协"}


def test_sxcoal_index_market_comes_from_index_name():
    cfg = _cfg("sxcoal")
    html = (FIXTURES / "sxcoal_list.html").read_text(encoding="utf-8")
    rows = price_sources.parse(cfg["parser"], html, cfg)
    assert rows
    assert {r["market"] for r in rows} == {"进口", "山西", "吕梁"}


# --------------------------------------------------------------------------
# P0-b / P1：曲线不再跨口径拼接
# --------------------------------------------------------------------------

def _seed_markets(db):
    conn = store.connect(db)
    store.init_db(conn)
    rows = []
    today = datetime.now().date()
    for offset in (2, 1, 0):
        day = (today - timedelta(days=offset)).strftime("%Y-%m-%d")
        rows.append({"commodity": "铜", "price_type": "期货", "value": 109000.0, "unit": "元/吨",
                     "change": None, "change_pct": None, "price_date": day,
                     "source_key": "sina_futures", "raw_label": "CU0", "market": "",
                     "origin": "", "spec": "", "basis": "不含税·昨结算", "contract": "连续",
                     "fetched_at": store.now_iso()})
        for market, value in (("长江现货", 110740.0), ("辽宁有色", 110340.0)):
            rows.append({"commodity": "铜", "price_type": "现货", "value": value, "unit": "元/吨",
                         "change": None, "change_pct": None, "price_date": day,
                         "source_key": "ccmn_cu", "raw_label": "1#铜", "market": market,
                         "origin": "国产", "spec": "1#", "basis": "含税", "contract": "",
                         "fetched_at": store.now_iso()})
    store.upsert_prices(conn, rows)
    conn.close()


def test_series_are_split_by_type_and_market(tmp_path):
    db = tmp_path / "t.db"
    _seed_markets(db)
    out = tmp_path / "dist"
    build(db_path=db, out_dir=out, feedback_email="")
    payload = json.loads((out / "prices.json").read_text(encoding="utf-8"))
    entries = payload["series"]["铜"]
    keys = {(e["price_type"], e["market"]) for e in entries}
    assert keys == {("期货", ""), ("现货", "长江现货"), ("现货", "辽宁有色")}
    # 没有"全部口径"这种跨口径拼接的曲线
    assert all(e["price_type"] in {"期货", "现货"} for e in entries)
    for e in entries:
        if e["market"] == "辽宁有色":
            assert all(p[1] == 110340.0 for p in e["points"]), "不同市场的点不能混在一条线里"
    # 每种口径有一条主线
    assert sum(1 for e in entries if e["main"]) == 2


def test_latest_rows_expose_market_and_spread(tmp_path):
    db = tmp_path / "t.db"
    _seed_markets(db)
    out = tmp_path / "dist"
    build(db_path=db, out_dir=out, feedback_email="")
    payload = json.loads((out / "prices.json").read_text(encoding="utf-8"))
    spot = [r for r in payload["latest"] if r["price_type"] == "现货"]
    assert {r["market"] for r in spot} == {"长江现货", "辽宁有色"}
    for r in spot:
        assert r["market_spread"] == 400.0
        assert r["spec"] == "1#"
        assert r["basis"] == "含税"
    html = (out / "prices.html").read_text(encoding="utf-8")
    assert "长江现货" in html
    assert "辽宁有色" in html
    assert "市场" in html


def test_spread_ignores_carried_quotes(tmp_path):
    """沿用昨收的市场不参与价差：一个没更新的市场不该把价差拉大。"""
    db = tmp_path / "t.db"
    conn = store.connect(db)
    store.init_db(conn)
    today = datetime.now().strftime("%Y-%m-%d")
    old = (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d")
    base = {"commodity": "铜", "price_type": "现货", "unit": "元/吨", "change": None,
            "change_pct": None, "source_key": "ccmn_cu", "raw_label": "1#铜",
            "origin": "国产", "spec": "1#", "basis": "含税", "contract": "",
            "fetched_at": store.now_iso()}
    store.upsert_prices(conn, [
        dict(base, price_date=today, market="长江现货", value=108790.0),
        dict(base, price_date=today, market="辽宁有色", value=108410.0),
        # 山东有色当天没更新，停在两天前的价
        dict(base, price_date=old, market="山东有色", value=110560.0),
        dict(base, price_date=old, market="长江现货", value=110740.0),
        dict(base, price_date=old, market="辽宁有色", value=110340.0),
    ])
    conn.close()
    out = tmp_path / "dist"
    build(db_path=db, out_dir=out, feedback_email="")
    payload = json.loads((out / "prices.json").read_text(encoding="utf-8"))
    rows = [r for r in payload["latest"] if r["price_type"] == "现货"]
    fresh = [r for r in rows if not r["carried"]]
    stale = [r for r in rows if r["carried"]]
    assert {r["market"] for r in fresh} == {"长江现货", "辽宁有色"}
    assert [r["market"] for r in stale] == ["山东有色"]
    for r in fresh:
        assert r["market_spread"] == 380.0, "价差只按当天真实报价算"
        assert r["market_fresh_date"] == today


def test_spread_suppressed_when_source_mixes_scopes(tmp_path):
    """同规格价差超过 50% 说明源站混了口径（如钼酸铵 2.3万~39万），不给价差。"""
    db = tmp_path / "t.db"
    conn = store.connect(db)
    store.init_db(conn)
    today = datetime.now().strftime("%Y-%m-%d")
    base = {"commodity": "钼酸铵", "price_type": "现货", "unit": "元/吨", "change": None,
            "change_pct": None, "source_key": "pp100", "raw_label": "钼酸铵",
            "origin": "国产", "spec": "99%", "basis": "出厂价", "contract": "",
            "fetched_at": store.now_iso()}
    store.upsert_prices(conn, [
        dict(base, price_date=today, market="湖北武汉", value=23000.0),
        dict(base, price_date=today, market="山东", value=390000.0),
    ])
    conn.close()
    out = tmp_path / "dist"
    build(db_path=db, out_dir=out, feedback_email="")
    payload = json.loads((out / "prices.json").read_text(encoding="utf-8"))
    rows = [r for r in payload["latest"] if r["commodity"] == "钼酸铵"]
    assert rows
    assert all(r["market_spread"] is None for r in rows)


def test_market_map_and_global_market_list(tmp_path):
    db = tmp_path / "t.db"
    _seed_markets(db)
    out = tmp_path / "dist"
    build(db_path=db, out_dir=out, feedback_email="")
    payload = json.loads((out / "prices.json").read_text(encoding="utf-8"))
    assert set(payload["market_map"]["铜"]["现货"]) == {"长江现货", "辽宁有色"}
    assert "长江现货" in payload["markets"]
    assert "辽宁有色" in payload["markets"]


# --------------------------------------------------------------------------
# 配置自检
# --------------------------------------------------------------------------

def test_mall_sources_use_exact_match_and_carry_market():
    for src in load_sources():
        if src.get("parser") != "ccmn_quota":
            continue
        assert src.get("exact_match") is True, src["key"]
        assert src["quote"]["market"] == "marketName"
        assert src["quote"]["origin"] == "placeOrTrademark"
        assert src["quote"]["spec"] == "trademark"


def test_jskc_source_skips_unverified_quote():
    """源站那条 100,590 元/吨与同品位 31,650 元/干吨口径不一致，未核实前不采。"""
    cfg = _cfg("ccmn_jskc")
    assert "铜精矿(湖北)" not in cfg["commodity_map"]["铜精矿"]
    assert cfg["unit"] == "", "源站没标计价单位时不要猜口径"
