# -*- coding: utf-8 -*-
"""矿价搜索索引：品种（含别名/拼音/规格/市场）与地区（含省份/拼音）。

构建时生成，前端纯本地过滤，不新增后端接口。
"""
import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
ALIAS_FILE = ROOT / "config" / "price_aliases.yaml"
PINYIN_FILE = ROOT / "config" / "price_pinyin.json"

# 省级行政区（短名），用于把 "河北省/唐山市" "河南有色" 归到省
PROVINCES = ("北京", "天津", "上海", "重庆", "河北", "山西", "辽宁", "吉林", "黑龙江",
             "江苏", "浙江", "安徽", "福建", "江西", "山东", "河南", "湖北", "湖南",
             "广东", "广西", "海南", "四川", "贵州", "云南", "西藏", "陕西", "甘肃",
             "青海", "宁夏", "新疆", "内蒙古", "香港", "澳门", "台湾")


def _load_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _load_pinyin() -> dict:
    if not PINYIN_FILE.exists():
        return {}
    try:
        return json.loads(PINYIN_FILE.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {}


def pinyin_initials(text: str, table: dict) -> str:
    """取每个字的拼音首字母；英文数字原样保留。"""
    out = []
    for ch in str(text or ""):
        if "\u4e00" <= ch <= "\u9fff":
            out.append(table.get(ch, ""))
        elif ch.isalnum():
            out.append(ch.lower())
    return "".join(out)


def province_of(market: str) -> str:
    """把报价市场归到省：'河北省/唐山市'→河北，'河南有色'→河南，'长江现货'→''。"""
    text = str(market or "").strip()
    if not text:
        return ""
    head = text.split("/")[0].strip()
    for p in PROVINCES:
        if head.startswith(p):
            return p
    for p in PROVINCES:
        if text.startswith(p):
            return p
    return ""


def search_payload(prices: dict) -> dict:
    aliases = _load_yaml(ALIAS_FILE)
    table = _load_pinyin()

    commodities = []
    for name in prices.get("commodities") or []:
        rows = [r for r in prices.get("latest") or [] if r["commodity"] == name]
        markets = sorted({r["market"] for r in rows if r.get("market")})
        specs = sorted({r["spec"] for r in rows
                        if r.get("spec") and r["spec"] != "-"})
        alias_list = [str(a) for a in (aliases.get(name) or []) if str(a).strip()]
        commodities.append({
            "name": name,
            "pinyin": pinyin_initials(name, table),
            "alias_pinyin": [pinyin_initials(a, table) for a in alias_list],
            "aliases": alias_list,
            "markets": markets,
            "provinces": sorted({province_of(m) for m in markets if province_of(m)}),
            "specs": specs,
            "count": len(rows),
        })

    markets = []
    seen = set()
    for market in prices.get("markets") or []:
        if market in seen:
            continue
        seen.add(market)
        province = province_of(market)
        markets.append({
            "name": market,
            "province": province,
            "pinyin": pinyin_initials(market, table),
            "province_pinyin": pinyin_initials(province, table),
        })

    # 省级聚合入口：搜"广西"能看广西全省（含 广西/防城港市、广西有色…），
    # 而不是只命中名字刚好叫"广西"的那一个市场
    provinces = []
    for prov in sorted({m["province"] for m in markets if m["province"]}):
        provinces.append({
            "name": prov,
            "pinyin": pinyin_initials(prov, table),
            "markets": [m["name"] for m in markets if m["province"] == prov],
        })

    return {"commodities": commodities, "markets": markets, "provinces": provinces}
