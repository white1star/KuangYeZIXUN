# -*- coding: utf-8 -*-
"""矿价问答 API：模型只解析意图，数字一律由本地数据算。

POST /ask  {"question": "...", "history": [{"q": "...", "intent": {...}}]}
    → {"ok": true, "source": "llm", "intent": {...}, "card": {...}}
    → {"ok": false, "error": "..."}   前端退回本地关键词解析

设计约束（改代码前必读）：
1. 模型**不能**产出价格数字，只返回 {action, commodity, regions, days, spec}。
2. 所有数字来自 news.db，由本文件计算。
3. 每次问答写一行 JSONL 到 logs/ask.jsonl（问题/意图/耗时），便于倒查。
"""
import difflib
import json
import os
import re
import time
from datetime import datetime, timedelta
from pathlib import Path

import requests
import yaml
from fastapi import FastAPI
from pydantic import BaseModel

from crawler import store
from crawler.config import load_settings
from site_build.search import province_of

ROOT = Path(__file__).resolve().parent.parent
ASK_CONFIG = ROOT / "config" / "ask.local.yaml"
DEFAULT_MODEL = "deepseek-chat"
DEFAULT_BASE = "https://api.deepseek.com"
MARKET_PREF = ("长江现货", "长江综合", "国内市场", "上海地区", "无锡现货")
TYPE_ORDER = {"现货": 0, "港口现货": 1, "指数": 2, "月度长协": 3, "年度长协": 4, "期货": 5}

app = FastAPI(title="矿价问答")


class AskRequest(BaseModel):
    question: str = ""
    history: list = []


ALIAS_FILE = ROOT / "config" / "price_aliases.yaml"
ACTIONS = {"price", "compare", "trend", "export", "regions"}


def load_aliases() -> dict:
    """同义词表：{标准品种: [别名...]}。"""
    try:
        raw = yaml.safe_load(ALIAS_FILE.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {}
    return {str(k): [str(x) for x in (v or []) if str(x).strip()] for k, v in raw.items()}


def _norm(text) -> str:
    return re.sub(r"\s+", "", str(text or "")).lower()


def resolve_commodity(raw, commodities, aliases):
    """把模型给的名字对到标准品种。返回 (标准名|空, 说明)。"""
    name = _norm(raw)
    if not name:
        return "", ""
    known = set(commodities)
    for c in commodities:
        if _norm(c) == name:
            return c, ""
    for c, items in aliases.items():
        if c not in known:
            continue
        for alias in items:
            if _norm(alias) == name:
                return c, f"把「{raw}」理解为 {c}"
    hits = []
    for c in commodities:
        if name in _norm(c) or _norm(c) in name:
            hits.append(c)
    for c, items in aliases.items():
        if c not in known:
            continue
        if any(_norm(a) and _norm(a) in name for a in items):
            hits.append(c)
    uniq = sorted(set(hits), key=lambda c: -len(c))
    if len(uniq) == 1:
        return uniq[0], f"把「{raw}」理解为 {uniq[0]}"
    if raw and _norm(raw) in uniq:
        return _norm(raw), ""
    pool = list(commodities)
    for c, items in aliases.items():
        if c in known:
            pool.extend(items)
    close = difflib.get_close_matches(str(raw), pool, n=1, cutoff=0.6)
    if close:
        hit = close[0]
        target = hit if hit in known else next(
            (c for c, items in aliases.items() if hit in items and c in known), "")
        if target:
            return target, f"把「{raw}」理解为 {target}"
    return "", f"没找到品种「{raw}」"


def resolve_region(raw, provinces, markets):
    """把模型给的地区对到省或市场。返回 ((kind, name)|None, 说明)。"""
    name = _norm(raw)
    if not name:
        return None, ""
    for prov in provinces:
        if _norm(prov) == name:
            return ("province", prov), ""
    for market in markets:
        if _norm(market) == name:
            return ("market", market), ""
    for market in markets:
        parts = str(market).split("/")
        city = _norm(parts[-1])
        city = re.sub(r"(市|区|县|盟|地区)$", "", city)
        short = re.sub(r"(市|区|县|盟|地区)$", "", name)
        if city and (city == name or city == short):
            return ("market", market), f"把「{raw}」理解为市场 {market}"
    for market in markets:
        if name in _norm(market):
            return ("market", market), f"把「{raw}」理解为市场 {market}"
    for prov in provinces:
        if name in _norm(prov) or _norm(prov) in name:
            return ("province", prov), f"把「{raw}」理解为 {prov}"
    close = difflib.get_close_matches(str(raw), list(provinces) + list(markets), n=1, cutoff=0.6)
    if close:
        hit = close[0]
        if hit in provinces:
            return ("province", hit), f"把「{raw}」理解为 {hit}"
        return ("market", hit), f"把「{raw}」理解为市场 {hit}"
    return None, f"没找到地区「{raw}」"


def normalize_intent(intent: dict, commodities, provinces, markets, categories, aliases):
    """白名单强校验：认不出的品种/地区不硬猜，记进 problems 交给前端提示。"""
    notes, problems = [], []
    action = str(intent.get("action") or "price")
    if action not in ACTIONS:
        action = "unknown"

    commodity, note = resolve_commodity(intent.get("commodity"), commodities, aliases)
    (notes if note.startswith("把") else problems) and None
    if note:
        (notes if note.startswith("把") else problems).append(note)

    category = str(intent.get("category") or "")
    if category:
        if category in categories:
            pass
        else:
            close = difflib.get_close_matches(category, list(categories), n=1, cutoff=0.5)
            if close:
                notes.append(f"把「{category}」理解为分类 {close[0]}")
                category = close[0]
            else:
                problems.append(f"没找到分类「{category}」")
                category = ""

    regions = []
    for raw in (intent.get("regions") or []):
        hit, note = resolve_region(raw, provinces, markets)
        if hit:
            if hit[1] not in regions:
                regions.append(hit[1])
            if note:
                notes.append(note)
        elif note:
            problems.append(note)

    days = intent.get("days")
    try:
        days = int(days)
    except (TypeError, ValueError):
        days = 0
    if days not in (7, 30, 90):
        days = 30

    return ({"action": action, "commodity": commodity, "category": category,
             "regions": regions, "days": days,
             "spec": (intent.get("spec") or "")}, notes, problems)


def load_ask_config() -> dict:
    conf = {"api_key": os.environ.get("DEEPSEEK_API_KEY", ""),
            "model": os.environ.get("DEEPSEEK_MODEL", DEFAULT_MODEL),
            "base_url": os.environ.get("DEEPSEEK_BASE_URL", DEFAULT_BASE),
            "timeout": 20}
    if ASK_CONFIG.exists():
        try:
            raw = yaml.safe_load(ASK_CONFIG.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            raw = {}
        if not conf["api_key"]:
            conf["api_key"] = str(raw.get("deepseek_api_key") or "").strip()
        conf["model"] = str(raw.get("model") or conf["model"])
        conf["base_url"] = str(raw.get("base_url") or conf["base_url"])
        conf["timeout"] = int(raw.get("timeout") or conf["timeout"])
    return conf


def connect():
    settings = load_settings()
    return store.connect(settings.db_path), settings


# --------------------------------------------------------------------------
# 目录
# --------------------------------------------------------------------------

def catalog(conn) -> tuple:
    since = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    commodities = [r["commodity"] for r in conn.execute(
        "SELECT DISTINCT commodity FROM prices WHERE price_date>=? ORDER BY commodity",
        (since,)).fetchall() if r["commodity"]]
    markets = [r["market"] for r in conn.execute(
        "SELECT DISTINCT market FROM prices WHERE market<>'' ORDER BY market").fetchall()]
    provinces = sorted({province_of(m) for m in markets if province_of(m)})
    try:
        raw = yaml.safe_load((ROOT / "config" / "price_categories.yaml").read_text(
            encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        raw = {}
    known = set(commodities)
    categories = {}
    for name, names in raw.items():
        items = [n for n in (names or []) if n in known]
        if items:
            categories[str(name)] = items
    return commodities, provinces, markets, categories


# --------------------------------------------------------------------------
# 取数与格式化
# --------------------------------------------------------------------------

def latest_rows(conn, commodity=None) -> list:
    sql = ("SELECT p.*, (SELECT s.name FROM sources s WHERE s.key=p.source_key) AS source_name "
           "FROM prices p JOIN (SELECT id, ROW_NUMBER() OVER ("
           "PARTITION BY commodity, price_type, market, spec "
           "ORDER BY price_date DESC, fetched_at DESC, id DESC) rn FROM prices) r "
           "ON r.id=p.id WHERE r.rn=1")
    params = []
    if commodity:
        sql += " AND p.commodity=?"
        params.append(commodity)
    today = datetime.now().strftime("%Y-%m-%d")
    out = []
    for row in conn.execute(sql, params).fetchall():
        item = dict(row)
        item["province"] = province_of(item["market"])
        # 当天没出价（休市/源站没更新）也要保留：前端标"昨收"，问答不能当成没数据
        item["carried"] = bool(item["price_date"] and item["price_date"] < today)
        out.append(item)
    return out


def market_rank(row) -> int:
    market = row.get("market") or ""
    try:
        return MARKET_PREF.index(market)
    except ValueError:
        return len(MARKET_PREF) + (0 if "/" in market else 1)


def fmt_num(v) -> str:
    try:
        n = float(v)
    except (TypeError, ValueError):
        return str(v)
    if n.is_integer():
        return f"{int(n):,}"
    return f"{n:,.2f}".rstrip("0").rstrip(".")


def price_text(row) -> str:
    return f"{fmt_num(row['value'])} {row['unit'] or ''}".strip()


def change_text(row) -> str:
    change = row.get("change")
    if change is None:
        return "暂无涨跌"
    if float(change) == 0:
        return "持平"
    pct = row.get("change_pct")
    pct_text = f"（{'+' if pct and pct > 0 else ''}{pct}%）" if pct is not None else ""
    return f"{'+' if change > 0 else ''}{fmt_num(change)}{pct_text}"


def spec_label(row) -> str:
    spec = (row.get("spec") or "").strip()
    origin = (row.get("origin") or "").strip()
    short_origin = bool(origin) and len(origin) <= 4 and not any(c.isdigit() for c in origin)
    if spec and spec != "-":
        text = f"{spec} {origin}" if (short_origin and len(spec) <= 12 and origin != spec) else spec
    else:
        text = origin
    return (text[:18] + "…") if len(text) > 18 else text


def series(conn, commodity, market=None, days=30) -> list:
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    sql = ("SELECT price_date, value, price_type, market, spec FROM ("
           "SELECT price_date, value, price_type, market, spec, ROW_NUMBER() OVER ("
           "PARTITION BY price_date, price_type, market, spec "
           "ORDER BY fetched_at DESC, id DESC) rn FROM prices "
           "WHERE commodity=? AND price_date>=?) WHERE rn=1 ORDER BY price_date")
    rows = [dict(r) for r in conn.execute(sql, (commodity, cutoff)).fetchall()]
    if market:
        rows = [r for r in rows if r["market"] == market]
    if not rows:
        return []
    kind = min({r["price_type"] for r in rows}, key=lambda t: TYPE_ORDER.get(t, 9))
    picked = [r for r in rows if r["price_type"] == kind]
    # 一条曲线只能是一个市场 + 一个规格，否则涨跌会把价差和规格差算进去
    markets = {r["market"] for r in picked}
    if len(markets) > 1 and not market:
        best = min(markets, key=lambda m: MARKET_PREF.index(m) if m in MARKET_PREF else 99)
        picked = [r for r in picked if r["market"] == best]
    specs = {r["spec"] for r in picked}
    if len(specs) > 1:
        counts = {}
        for r in picked:
            counts[r["spec"]] = counts.get(r["spec"], 0) + 1
        best_spec = max(counts, key=counts.get)
        picked = [r for r in picked if r["spec"] == best_spec]
    return [(r["price_date"], r["value"]) for r in picked]


# --------------------------------------------------------------------------
# 执行意图
# --------------------------------------------------------------------------

def category_trend(conn, names: list, days: int) -> dict:
    """一批品种的涨跌概览：几个跌、几个涨，跌得最多的是谁。"""
    changes = []
    for name in names:
        pts = series(conn, name, days=days)
        if len(pts) >= 2 and pts[0][1]:
            pct = (pts[-1][1] - pts[0][1]) / pts[0][1] * 100
            changes.append((name, pct))
    if not changes:
        return {}
    changes.sort(key=lambda x: x[1])
    down = [c for c in changes if c[1] < -0.005]
    up = [c for c in changes if c[1] > 0.005]
    flat = len(changes) - len(down) - len(up)
    if down:
        headline = f"{len(down)} 个下跌 / {len(up)} 个上涨"
        detail = "跌幅前 3：" + "、".join(f"{n} {p:+.2f}%" for n, p in down[:3])
    elif up:
        headline = f"没有下跌（{len(up)} 涨 / {flat} 平）"
        detail = "涨幅前 3：" + "、".join(f"{n} {p:+.2f}%" for n, p in sorted(up, key=lambda x: -x[1])[:3])
    else:
        headline = f"全部持平（{len(changes)} 个品种）"
        detail = ""
    return {
        "value": headline,
        "sub": f"（近 {days} 天）",
        "meta": detail,
        "rows": [{"label": n, "value": f"{p:+.2f}%"} for n, p in changes[:8]],
    }


def execute(conn, intent: dict, provinces: list, categories: dict = None) -> dict:
    action = intent.get("action") or "price"
    commodity = intent.get("commodity") or ""
    category = intent.get("category") or ""
    regions = [r for r in (intent.get("regions") or []) if r]
    days = int(intent.get("days") or 30)
    spec = (intent.get("spec") or "").strip()
    categories = categories or {}
    cat_names = categories.get(category, []) if category else []

    if not commodity and not regions and not cat_names:
        return {"title": "", "value": "", "sub": "", "rows": [],
                "meta": "请说明查什么，比如「广西萤石多少钱」「萤石最近在跌吗」"}

    if cat_names and not commodity:
        card = {"title": category, "value": "", "sub": "", "meta": "", "rows": [], "export": None}
        if action == "trend":
            card.update(category_trend(conn, cat_names, days))
            if not card["value"]:
                card["meta"] = f"{category} 暂无可算走势的品种"
            return card
        # 分类查价：每个品种给一条代表价（主市场 + 首选口径）
        picked = []
        for name in cat_names:
            rs = latest_rows(conn, name)
            if not rs:
                continue
            kinds = {r["price_type"] for r in rs}
            if len(kinds) > 1:
                preferred = min(kinds, key=lambda t: TYPE_ORDER.get(t, 9))
                rs = [r for r in rs if r["price_type"] == preferred] or rs
            rs.sort(key=market_rank)
            picked.append((name, rs[0]))
        card["meta"] = f"{category} 共 {len(picked)} 个品种有报价 · 主市场代表价"
        card["rows"] = [{"label": n, "value": price_text(r)} for n, r in picked]
        return card

    province = market = ""
    region_pairs = []
    for name in regions:
        if name in provinces:
            region_pairs.append(("province", name))
        else:
            region_pairs.append(("market", name))
    if regions:
        first = regions[0]
        if first in provinces:
            province = first
        else:
            market = first
            province = province_of(first)

    def in_regions(row) -> bool:
        if not region_pairs:
            return True
        for kind, name in region_pairs:
            if kind == "province" and row["province"] == name:
                return True
            if kind == "market" and row["market"] == name:
                return True
        return False

    def pick(rows):
        if not spec:
            return rows
        key = spec.lower()
        hit = [r for r in rows if key in (r.get("spec") or "").lower()
               or key in (r.get("origin") or "").lower()
               or key in (r.get("raw_label") or "").lower()]
        return hit or rows

    if len(regions) > 2:
        region_text = f"{regions[0]} 等 {len(regions)} 个地区"
    else:
        region_text = "、".join(regions)
    card = {"title": " · ".join([p for p in (region_text, commodity) if p]),
            "value": "", "sub": "", "meta": "", "rows": [], "export": None}
    all_rows = latest_rows(conn, commodity)

    if action == "compare" and len(regions) >= 2:
        picked = []
        for name in regions[:4]:
            if name in provinces:
                rows = [r for r in all_rows if r["province"] == name]
            else:
                rows = [r for r in all_rows if r["market"] == name]
            if rows:
                picked.append((name, rows))
        spec_count = {}
        for _, rows in picked:
            for r in rows:
                spec_count[r["spec"]] = spec_count.get(r["spec"], 0) + 1
        use_spec = max(spec_count, key=spec_count.get) if spec_count else ""
        chosen = []
        for name, rows in picked:
            same = [r for r in rows if r["spec"] == use_spec] or rows
            same.sort(key=market_rank)
            chosen.append((name, same[0]))
        chosen.sort(key=lambda x: -x[1]["value"])
        if len(chosen) >= 2:
            hi, lo = chosen[0], chosen[-1]
            diff = hi[1]["value"] - lo[1]["value"]
            pct = (diff / lo[1]["value"] * 100) if lo[1]["value"] else 0
            card.update({
                "title": " vs ".join(n for n, _ in chosen) + (f" · {commodity}" if commodity else ""),
                "value": f"{hi[0]} 高 {fmt_num(diff)} {hi[1]['unit'] or ''}".strip(),
                "sub": f"（+{pct:.2f}%）",
                "meta": f"{spec_label(hi[1])} · {hi[1]['price_date']} · 最低 {lo[0]}",
                "rows": [{"label": n, "value": price_text(r)} for n, r in chosen],
            })
            return card

    rows = [r for r in all_rows if in_regions(r)]
    if cat_names and not commodity:
        rows = [r for r in rows if r["commodity"] in cat_names]
        all_rows = [r for r in all_rows if r["commodity"] in cat_names]
    rows = pick(rows)
    # 同一品种可能有期货/现货/指数多个口径，摘要只看一个
    kinds = {r["price_type"] for r in rows}
    if len(kinds) > 1:
        preferred = min(kinds, key=lambda t: TYPE_ORDER.get(t, 9))
        rows = [r for r in rows if r["price_type"] == preferred] or rows

    if not rows:
        alt = list(all_rows)
        if alt:
            kinds = {r["price_type"] for r in alt}
            preferred = min(kinds, key=lambda t: TYPE_ORDER.get(t, 9))
            alt = [r for r in alt if r["price_type"] == preferred] or alt
            alt.sort(key=market_rank)
        alt = alt[:4]
        card["meta"] = "没有匹配的报价" + (
            "；同品种其他地区：" + "、".join(f"{r['market']} {price_text(r)}" for r in alt)
            if alt else "")
        return card

    if action == "regions":
        seen = {}
        for r in rows:
            seen.setdefault(r["market"] or "全国", r)
        card["meta"] = f"{commodity} 共 {len(seen)} 个市场有报价"
        card["rows"] = [{"label": k, "value": price_text(v)} for k, v in list(seen.items())[:12]]
        return card

    if action == "export":
        card["export"] = "\n".join(
            f"{r['commodity']} {spec_label(r)} {r['market'] or ''} "
            f"{price_text(r)} {r['price_date']}" for r in rows[:12])
        card["meta"] = f"共 {len(rows)} 条，导出前 12 条"
        return card

    if action == "trend":
        pts = series(conn, commodity, market=market or None, days=days)
        if len(pts) >= 2:
            first, last = pts[0][1], pts[-1][1]
            change = last - first
            pct = (change / first * 100) if first else 0
            values = [p[1] for p in pts]
            flat = abs(change) < 0.005
            card.update({
                "value": "持平" if flat else f"{'+' if change > 0 else ''}{fmt_num(change)}",
                "sub": "（0%）" if flat else f"（{'+' if pct > 0 else ''}{pct:.2f}%）",
                "meta": f"{commodity} · 近 {days} 天：{fmt_num(first)} → {fmt_num(last)} · "
                        f"区间 {fmt_num(min(values))}~{fmt_num(max(values))}",
            })
            return card

    rows.sort(key=lambda r: (market_rank(r), -r["value"]))
    top = rows[0]
    specs = {spec_label(r) for r in rows}
    if len(specs) > 1:
        values = [r["value"] for r in rows]
        card.update({
            "value": f"{fmt_num(min(values))} ~ {fmt_num(max(values))}",
            "sub": top["unit"] or "",
            "meta": f"{len(rows)} 条报价 · {len(specs)} 个规格 · "
                    f"{len({r['market'] or '全国' for r in rows})} 个市场 · {top['price_date']}"
                    f"{'（含昨收）' if any(r.get('carried') for r in rows) else ''}",
            "rows": [{"label": (r["market"] or "全国") + " " + spec_label(r),
                      "value": price_text(r)} for r in rows[:3]],
        })
    else:
        carried_note = "（昨收，源站当天未出价）" if top.get("carried") else ""
        card.update({
            "value": price_text(top),
            "meta": f"{top['market'] or '全国'} · {spec_label(top)} · {top['price_date']}"
                    f"{carried_note} · {change_text(top)} · "
                    f"来源 {top['source_name'] or top['source_key']}",
        })
    return card


# --------------------------------------------------------------------------
# 模型：只解析意图
# --------------------------------------------------------------------------

PROMPT = """你是矿价查询的意图解析器。只输出一个 JSON 对象，不要任何解释。

字段：
- action: price(查价) | compare(比价) | trend(涨跌/走势) | export(导出报价文本) | regions(有哪些地区) | unknown
- commodity: 必须从【品种】里选一个，选不到填 null
- category: 问的是一类矿（如"非金属矿""稀土"）时填分类名，否则 null
- regions: 数组，从【地区】里选（省或具体市场都行），可以多个；问"全国/整体"填空数组
- days: 7 / 30 / 90 之一，没提就填 null
- spec: 规格关键词（如 "PB粉" "97" "准一级"），没有填 null

规则：
1. 只判断意图，不要计算、不要输出任何价格数字。
2. 问题是中文且可能没有空格，按语义理解。
3. 指代词（"那广西呢""换成锌"）要结合【最近对话】补全。
4. 用户提到具体城市（唐山/昆明/青岛/无锡），regions 里要填对应的**市场名**
   （如"河北省/唐山市""昆明现货"），不要退化成省份。
5. 用户说大区（华北/华东/华南），把它展开成该大区包含的省份。
6. commodity 和 regions 都填不出来时 action=unknown。

【品种】（括号里是同义词，用户说括号里的词也要映射到冒号前的标准名）
{commodities}

【分类】（可以填 category，commodity 留空）
{categories}

【地区】{regions}

【最近对话】{history}"""


def llm_parse(conf: dict, question: str, history: list, commodities, provinces,
              categories=None, markets=None) -> dict:
    api_key = conf.get("api_key") or ""
    if not api_key:
        raise RuntimeError("未配置 DEEPSEEK_API_KEY")
    hist_text = "\n".join(
        f"Q: {h.get('q','')} → {json.dumps(h.get('intent') or {}, ensure_ascii=False)}"
        for h in (history or [])[-3:]) or "（无）"
    aliases = load_aliases()
    com_lines = []
    for name in commodities:
        items = aliases.get(name) or []
        com_lines.append(f"{name}（{'、'.join(items)}）" if items else name)
    cat_text = "\n".join(f"{k}：{'、'.join(v)}" for k, v in (categories or {}).items()) or "（无）"
    region_text = "、".join(provinces)
    if markets:
        region_text += "；市场：" + "、".join(markets[:120])
    system = PROMPT.format(commodities="；".join(com_lines), categories=cat_text,
                           regions=region_text, history=hist_text)
    resp = requests.post(
        conf["base_url"].rstrip("/") + "/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={"model": conf["model"],
              "messages": [{"role": "system", "content": system},
                           {"role": "user", "content": question}],
              "temperature": 0, "max_tokens": 200,
              "response_format": {"type": "json_object"}},
        timeout=conf["timeout"])
    if resp.status_code != 200:
        raise RuntimeError(f"DeepSeek {resp.status_code}: {resp.text[:200]}")
    content = ((resp.json().get("choices") or [{}])[0].get("message") or {}).get("content", "")
    intent = json.loads(content)
    if not isinstance(intent, dict):
        raise RuntimeError("模型返回不是 JSON 对象")
    return intent


def log_ask(settings, record: dict) -> None:
    try:
        with (settings.logs_dir / "ask.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        pass


@app.get("/healthz")
def healthz():
    conf = load_ask_config()
    return {"ok": True, "llm": bool(conf.get("api_key")), "model": conf.get("model")}


@app.post("/ask")
def ask(req: AskRequest):
    question = (req.question or "").strip()
    started = time.time()
    conn, settings = connect()
    try:
        commodities, provinces, markets, categories = catalog(conn)
        conf = load_ask_config()
        try:
            intent = llm_parse(conf, question, req.history, commodities, provinces,
                               categories, markets)
        except Exception as exc:
            log_ask(settings, {"ts": datetime.now().isoformat(timespec="seconds"),
                               "q": question, "ok": False, "error": str(exc)[:200],
                               "ms": int((time.time() - started) * 1000)})
            return {"ok": False, "error": str(exc)[:200]}
        intent, notes, problems = normalize_intent(
            intent, commodities, provinces, markets, categories, load_aliases())
        if intent["action"] == "unknown" or not (
                intent["commodity"] or intent["regions"] or intent["category"]):
            return {"ok": False, "error": "没听懂", "intent": intent,
                    "clarify": "；".join(problems)[:120]}
        card = execute(conn, intent, provinces, categories)
        if notes:
            card["note"] = "；".join(notes)[:120]
        log_ask(settings, {"ts": datetime.now().isoformat(timespec="seconds"),
                           "q": question, "ok": True, "intent": intent,
                           "card": card, "ms": int((time.time() - started) * 1000)})
        return {"ok": True, "source": "llm", "intent": intent, "card": card}
    finally:
        conn.close()
