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
import json
import os
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
    return commodities, provinces, markets


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
        if item["price_date"] and item["price_date"] < today:
            continue
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
    sql = ("SELECT price_date, value, price_type, market FROM ("
           "SELECT price_date, value, price_type, market, ROW_NUMBER() OVER ("
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
    # 一条曲线只能是一个市场，否则涨跌会把两个市场的价差算进去
    markets = {r["market"] for r in picked}
    if len(markets) > 1 and not market:
        best = min(markets, key=lambda m: MARKET_PREF.index(m) if m in MARKET_PREF else 99)
        picked = [r for r in picked if r["market"] == best]
    return [(r["price_date"], r["value"]) for r in picked]


# --------------------------------------------------------------------------
# 执行意图
# --------------------------------------------------------------------------

def execute(conn, intent: dict, provinces: list) -> dict:
    action = intent.get("action") or "price"
    commodity = intent.get("commodity") or ""
    regions = [r for r in (intent.get("regions") or []) if r]
    days = int(intent.get("days") or 30)
    spec = (intent.get("spec") or "").strip()

    province = market = ""
    if regions:
        first = regions[0]
        if first in provinces:
            province = first
        else:
            market = first
            province = province_of(first)

    def pick(rows):
        if not spec:
            return rows
        key = spec.lower()
        hit = [r for r in rows if key in (r.get("spec") or "").lower()
               or key in (r.get("origin") or "").lower()
               or key in (r.get("raw_label") or "").lower()]
        return hit or rows

    card = {"title": " · ".join([p for p in (regions[0] if regions else "", commodity) if p]),
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

    rows = [r for r in all_rows
            if (not province or r["province"] == province)
            and (not market or r["market"] == market)]
    rows = pick(rows)

    if not rows:
        alt = all_rows[:4]
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
            card.update({
                "value": f"{'+' if change > 0 else ''}{fmt_num(change)}",
                "sub": f"（{'+' if pct > 0 else ''}{pct:.2f}%）",
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
                    f"{len({r['market'] or '全国' for r in rows})} 个市场 · {top['price_date']}",
            "rows": [{"label": r["market"] or "全国", "value": price_text(r)} for r in rows[:3]],
        })
    else:
        card.update({
            "value": price_text(top),
            "meta": f"{top['market'] or '全国'} · {spec_label(top)} · {top['price_date']} · "
                    f"{change_text(top)} · 来源 {top['source_name'] or top['source_key']}",
        })
    return card


# --------------------------------------------------------------------------
# 模型：只解析意图
# --------------------------------------------------------------------------

PROMPT = """你是矿价查询的意图解析器。只输出一个 JSON 对象，不要任何解释。

字段：
- action: price(查价) | compare(比价) | trend(涨跌/走势) | export(导出报价文本) | regions(有哪些地区) | unknown
- commodity: 必须从【品种】里选一个，选不到填 null
- regions: 数组，从【地区】里选，可以多个；问"全国/整体"填空数组
- days: 7 / 30 / 90 之一，没提就填 null
- spec: 规格关键词（如 "PB粉" "97" "准一级"），没有填 null

规则：
1. 只判断意图，不要计算、不要输出任何价格数字。
2. 问题是中文且可能没有空格，按语义理解。
3. 指代词（"那广西呢""换成锌"）要结合【最近对话】补全。
4. commodity 和 regions 都填不出来时 action=unknown。

【品种】{commodities}

【地区】{regions}

【最近对话】{history}"""


def llm_parse(conf: dict, question: str, history: list, commodities, provinces) -> dict:
    api_key = conf.get("api_key") or ""
    if not api_key:
        raise RuntimeError("未配置 DEEPSEEK_API_KEY")
    hist_text = "\n".join(
        f"Q: {h.get('q','')} → {json.dumps(h.get('intent') or {}, ensure_ascii=False)}"
        for h in (history or [])[-3:]) or "（无）"
    system = PROMPT.format(commodities="、".join(commodities),
                           regions="、".join(provinces), history=hist_text)
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
        commodities, provinces, _ = catalog(conn)
        conf = load_ask_config()
        try:
            intent = llm_parse(conf, question, req.history, commodities, provinces)
        except Exception as exc:
            log_ask(settings, {"ts": datetime.now().isoformat(timespec="seconds"),
                               "q": question, "ok": False, "error": str(exc)[:200],
                               "ms": int((time.time() - started) * 1000)})
            return {"ok": False, "error": str(exc)[:200]}
        if (intent.get("action") or "") == "unknown":
            return {"ok": False, "error": "没听懂", "intent": intent}
        card = execute(conn, intent, provinces)
        log_ask(settings, {"ts": datetime.now().isoformat(timespec="seconds"),
                           "q": question, "ok": True, "intent": intent,
                           "card": card, "ms": int((time.time() - started) * 1000)})
        return {"ok": True, "source": "llm", "intent": intent, "card": card}
    finally:
        conn.close()
