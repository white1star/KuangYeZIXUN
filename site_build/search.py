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
CATEGORY_FILE = ROOT / "config" / "price_categories.yaml"
PINYIN_FULL_FILE = ROOT / "config" / "price_pinyin_full.json"

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


# 城市 → 省（市场名里常见"城市+现货/有色/金属废料"，没有省前缀）
CITY_PROVINCE = {
    "上海": "上海", "北京": "北京", "天津": "天津", "重庆": "重庆",
    "广州": "广东", "佛山": "广东", "湛江": "广东", "清远": "广东", "东莞": "广东", "深圳": "广东",
    "无锡": "江苏", "南京": "江苏", "江阴": "江苏", "连云港": "江苏", "常州": "江苏", "徐州": "江苏",
    "唐山": "河北", "石家庄": "河北", "曹妃甸": "河北", "邯郸": "河北", "保定": "河北",
    "青岛": "山东", "日照": "山东", "烟台": "山东", "济南": "山东", "临沂": "山东",
    "宁波": "浙江", "台州": "浙江", "杭州": "浙江", "温州": "浙江",
    "洛阳": "河南", "济源": "河南", "郑州": "河南",
    "武汉": "湖北", "大冶": "湖北", "咸宁": "湖北", "宜昌": "湖北",
    "长沙": "湖南", "株洲": "湖南", "衡阳": "湖南",
    "鹰潭": "江西", "上饶": "江西", "赣州": "江西",
    "合肥": "安徽", "池州": "安徽", "芜湖": "安徽",
    "沈阳": "辽宁", "大连": "辽宁", "葫芦岛": "辽宁", "抚顺": "辽宁",
    "昆明": "云南", "曲靖": "云南", "个旧": "云南",
    "凉山": "四川", "成都": "四川", "攀枝花": "四川",
    "西安": "陕西", "宝鸡": "陕西",
    "兰州": "甘肃", "白银": "甘肃",
    "赤峰": "内蒙古", "包头": "内蒙古", "呼和浩特": "内蒙古",
    "贵阳": "贵州", "百色": "广西", "防城港": "广西", "南丹": "广西",
    "福州": "福建", "厦门": "福建", "龙岩": "福建",
    "太原": "山西", "吕梁": "山西", "临汾": "山西",
    "长春": "吉林", "哈尔滨": "黑龙江", "银川": "宁夏", "西宁": "青海",
    "乌鲁木齐": "新疆", "拉萨": "西藏", "海口": "海南",
}


def province_of(market: str) -> str:
    """把报价市场归到省：'河北省/唐山市'→河北，'河南有色'→河南，'广州现货'→广东。"""
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
    for city, prov in CITY_PROVINCE.items():
        if text.startswith(city):
            return prov
    return ""


def search_payload(prices: dict) -> dict:
    aliases = _load_yaml(ALIAS_FILE)
    categories = _load_yaml(CATEGORY_FILE)
    table = _load_pinyin()
    full_table = _load_json(PINYIN_FULL_FILE)

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
            "full_pinyin": full_pinyin(name, full_table),
            "alias_pinyin": [pinyin_initials(a, table) for a in alias_list],
            "alias_full_pinyin": [full_pinyin(a, full_table) for a in alias_list],
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

    # 左侧分面树：分类 → 品种（只保留真的有数据的）
    known = {c["name"] for c in commodities}
    cat_list = []
    mapped = set()
    for cat, names in (categories or {}).items():
        items = [n for n in (names or []) if n in known]
        if items:
            cat_list.append({"name": str(cat), "commodities": items})
            mapped.update(items)
    rest = sorted(known - mapped)
    if rest:
        cat_list.append({"name": "其他", "commodities": rest})

    return {"commodities": commodities, "markets": markets,
            "provinces": provinces, "categories": cat_list}


def full_pinyin(text: str, table: dict = None) -> str:
    """整词全拼。用生成好的静态表，运行时不依赖 pypinyin。"""
    if table is None:
        table = _load_json(PINYIN_FULL_FILE)
    return str(table.get(str(text or "").strip(), "")).lower()


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {}
