# -*- coding: utf-8 -*-
"""问答 API 的离线测试：执行层不依赖模型，模型层只产出意图。"""
import json
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from crawler import store
from web import ask_api


def _seed(db):
    conn = store.connect(db)
    store.init_db(conn)
    store.upsert_source(conn, "ccmn_cu", "长江有色·铜", "price", "https://e.com", True)
    today = datetime.now().strftime("%Y-%m-%d")
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    rows = []
    for day, base in ((yesterday, 110000.0), (today, 109000.0)):
        for market, delta in (("长江现货", 0.0), ("河北省/唐山市", -300.0)):
            rows.append({
                "commodity": "铜", "price_type": "现货", "value": base + delta,
                "unit": "元/吨", "change": None, "change_pct": None, "price_date": day,
                "source_key": "ccmn_cu", "raw_label": "1#铜", "market": market,
                "origin": "国产", "spec": "1#", "basis": "含税", "contract": "",
                "fetched_at": store.now_iso(),
            })
    for market, value in (("河北省/唐山市", 660.0), ("山东省/青岛市", 650.0)):
        rows.append({
            "commodity": "铁矿石", "price_type": "现货", "value": value, "unit": "元/吨",
            "change": None, "change_pct": None, "price_date": today,
            "source_key": "ccmn_cu", "raw_label": "PB粉", "market": market,
            "origin": "澳大利亚", "spec": "PB粉 62%", "basis": "市场价", "contract": "",
            "fetched_at": store.now_iso(),
        })
    store.upsert_prices(conn, rows)
    conn.close()


def _conn(db):
    return store.connect(db)


def test_execute_price_prefers_main_market(tmp_path):
    db = tmp_path / "t.db"
    _seed(db)
    conn = _conn(db)
    try:
        card = ask_api.execute(conn, {"action": "price", "commodity": "铜"}, ["河北"])
        assert card["value"].startswith("109,000")
        assert "长江现货" in card["meta"]
    finally:
        conn.close()


def test_execute_price_by_province(tmp_path):
    db = tmp_path / "t.db"
    _seed(db)
    conn = _conn(db)
    try:
        card = ask_api.execute(conn, {"action": "price", "commodity": "铜", "regions": ["河北"]}, ["河北"])
        assert card["value"].startswith("108,700")
        assert "唐山" in card["meta"]
    finally:
        conn.close()


def test_execute_compare_same_spec(tmp_path):
    db = tmp_path / "t.db"
    _seed(db)
    conn = _conn(db)
    try:
        card = ask_api.execute(conn, {"action": "compare", "commodity": "铁矿石",
                                      "regions": ["河北", "山东"]}, ["河北", "山东"])
        assert "高 10" in card["value"]
        labels = [r["label"] for r in card["rows"]]
        assert labels == ["河北", "山东"]
    finally:
        conn.close()


def test_execute_trend(tmp_path):
    db = tmp_path / "t.db"
    _seed(db)
    conn = _conn(db)
    try:
        card = ask_api.execute(conn, {"action": "trend", "commodity": "铜", "days": 7}, ["河北"])
        assert card["value"].startswith("-1,000")
        assert "近 7 天" in card["meta"]
    finally:
        conn.close()


def test_execute_export(tmp_path):
    db = tmp_path / "t.db"
    _seed(db)
    conn = _conn(db)
    try:
        card = ask_api.execute(conn, {"action": "export", "commodity": "铁矿石", "regions": ["河北"]}, ["河北"])
        assert card["export"]
        assert "铁矿石" in card["export"].split("\n")[0]
    finally:
        conn.close()


def test_execute_regions(tmp_path):
    db = tmp_path / "t.db"
    _seed(db)
    conn = _conn(db)
    try:
        card = ask_api.execute(conn, {"action": "regions", "commodity": "铁矿石"}, ["河北", "山东"])
        assert "2 个市场" in card["meta"]
    finally:
        conn.close()


def test_execute_unknown_commodity_gives_hint(tmp_path):
    db = tmp_path / "t.db"
    _seed(db)
    conn = _conn(db)
    try:
        card = ask_api.execute(conn, {"action": "price", "commodity": "铅"}, ["河北"])
        assert card["value"] == ""
        assert "没有匹配" in card["meta"]
    finally:
        conn.close()


def test_llm_parse_requires_key(monkeypatch, tmp_path):
    monkeypatch.setattr(ask_api, "ASK_CONFIG", tmp_path / "none.yaml")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    conf = ask_api.load_ask_config()
    with pytest.raises(RuntimeError):
        ask_api.llm_parse(conf, "铜多少钱", [], ["铜"], ["河北"])


def test_api_returns_ok_false_without_key(monkeypatch, tmp_path):
    """没配 key 时返回 ok:false，前端会自动退回本地关键词解析。"""
    db = tmp_path / "t.db"
    _seed(db)
    monkeypatch.setattr(ask_api, "ASK_CONFIG", tmp_path / "none.yaml")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setattr(ask_api, "connect",
                        lambda: (store.connect(db), type("S", (), {"logs_dir": tmp_path})()))
    client = TestClient(ask_api.app)
    resp = client.post("/ask", json={"question": "铜多少钱"})
    data = resp.json()
    assert data["ok"] is False
    assert "DEEPSEEK_API_KEY" in data["error"]


def test_healthz_reports_llm_flag(monkeypatch, tmp_path):
    monkeypatch.setattr(ask_api, "ASK_CONFIG", tmp_path / "none.yaml")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    client = TestClient(ask_api.app)
    data = client.get("/healthz").json()
    assert data["ok"] is True and data["llm"] is False

# --------------------------------------------------------------------------
# 意图归一：白名单 / 别名 / 错字 / 城市
# --------------------------------------------------------------------------

ALIASES = {
    "铜": ["电解铜", "1#铜", "cu"],
    "萤石": ["氟石", "氟化钙"],
    "铜精矿": ["铜矿", "铜精粉"],
    "锌精矿": ["锌矿"],
}
COMS = ["铜", "萤石", "铜精矿", "锌精矿", "铁矿石"]
PROVS = ["河北", "山东", "广西"]
MKTS = ["河北省/唐山市", "山东省/青岛市", "昆明现货", "长江现货", "广西有色"]


def test_resolve_commodity_exact_and_alias():
    assert ask_api.resolve_commodity("铜", COMS, ALIASES)[0] == "铜"
    assert ask_api.resolve_commodity("电解铜", COMS, ALIASES)[0] == "铜"
    assert ask_api.resolve_commodity("氟石", COMS, ALIASES)[0] == "萤石"
    assert ask_api.resolve_commodity("铜矿", COMS, ALIASES)[0] == "铜精矿"


def test_resolve_commodity_fuzzy_typo():
    name, note = ask_api.resolve_commodity("锌精粉", COMS, ALIASES)
    assert name == "锌精矿" and "理解为" in note


def test_resolve_commodity_rejects_unknown():
    name, note = ask_api.resolve_commodity("火星矿石", COMS, ALIASES)
    assert name == "" and "没找到" in note


def test_resolve_region_city_to_market():
    hit, _ = ask_api.resolve_region("唐山", PROVS, MKTS)
    assert hit == ("market", "河北省/唐山市")
    hit2, _ = ask_api.resolve_region("广西", PROVS, MKTS)
    assert hit2 == ("province", "广西")
    assert ask_api.resolve_region("火星", PROVS, MKTS)[0] is None


def test_normalize_intent_alias_and_drop_unknown_region():
    intent, notes, problems = ask_api.normalize_intent(
        {"action": "price", "commodity": "氟石", "regions": ["火星", "广西"]},
        COMS, PROVS, MKTS, {}, ALIASES)
    assert intent["commodity"] == "萤石"
    assert intent["regions"] == ["广西"]
    assert any("理解为" in n for n in notes)
    assert any("火星" in p for p in problems)


def test_normalize_intent_rejects_bad_action_and_days():
    intent, _, _ = ask_api.normalize_intent(
        {"action": "hack", "commodity": "铜", "days": 999},
        COMS, PROVS, MKTS, {}, ALIASES)
    assert intent["action"] == "unknown"
    assert intent["days"] == 30
