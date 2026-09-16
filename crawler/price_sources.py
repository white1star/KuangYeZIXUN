import json
import re
from datetime import datetime

from bs4 import BeautifulSoup

from crawler.parse import parse_date


def _to_float(s):
    if s is None:
        return None
    s = str(s).replace(",", "").strip()
    if s in {"", "-", "--", "暂无", "None"}:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _scaled(v, scale):
    f = _to_float(v)
    if f is None:
        return None
    return round(f / float(scale), 4) if scale else f


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _make_row(commodity, price_type, value, cfg, raw_label,
              change=None, change_pct=None, price_date=None):
    return {
        "commodity": commodity,
        "price_type": price_type,
        "value": value,
        "unit": cfg.get("unit", ""),
        "change": change,
        "change_pct": change_pct,
        "price_date": price_date or cfg.get("price_date") or _today(),
        "source_key": cfg["key"],
        "raw_label": raw_label,
        "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def _match_commodity(label, mapping):
    label = (label or "").strip()
    if label in mapping:
        return mapping[label]
    for commodity, keywords in mapping.items():
        words = keywords if isinstance(keywords, list) else [keywords]
        if any(w and w in label for w in words):
            return commodity
    return None


SINA_VAR = re.compile(r'var\s+hq_str_nf_([A-Za-z0-9]+)="([^"]*)"')


def parse_futures_sina(text: str, cfg: dict) -> list:
    rows = []
    fm = cfg.get("field_map", {})
    for m in SINA_VAR.finditer(text or ""):
        code, payload = m.group(1), m.group(2)
        commodity = cfg.get("commodity_map", {}).get(code)
        if not commodity:
            continue
        parts = payload.split(",")

        def field(name):
            idx = fm.get(name)
            if idx is None or idx >= len(parts):
                return None
            return parts[idx]

        value = _to_float(field("last"))
        if value is None or value <= 0:
            continue
        prev = _to_float(field("prev_settle"))
        change = round(value - prev, 4) if prev else None
        change_pct = round((value - prev) / prev * 100, 2) if prev else None
        rows.append(_make_row(commodity, "期货", value, cfg, code,
                              change=change, change_pct=change_pct))
    return rows


def parse_futures_eastmoney(text: str, cfg: dict) -> list:
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        raise ValueError("东方财富返回不是 JSON")
    diff = ((data.get("data") or {}).get("diff")) or []
    fm = cfg.get("field_map", {})
    scale = cfg.get("scale", {})
    rows = []
    for item in diff:
        label = str(item.get(fm.get("name", "f14"), ""))
        commodity = _match_commodity(label, cfg.get("commodity_map", {}))
        if not commodity:
            continue
        value = _scaled(item.get(fm.get("last", "f2")), scale.get("last"))
        if value is None or value <= 0:
            continue
        change = _scaled(item.get(fm.get("change", "f4")), scale.get("change"))
        change_pct = _scaled(item.get(fm.get("change_pct", "f3")), scale.get("change_pct"))
        rows.append(_make_row(commodity, "期货", value, cfg, label,
                              change=change, change_pct=change_pct))
    return rows


def parse_shfe_daily(text: str, cfg: dict) -> list:
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        raise ValueError("上期所返回不是 JSON")
    raw_rows = data.get("o_curinstrument") or data.get("o_curinstrumentList") or []
    best = {}
    for item in raw_rows:
        product = str(item.get("PRODUCTID", "")).strip().rstrip("_f")
        commodity = cfg.get("commodity_map", {}).get(product)
        if not commodity:
            continue
        oi = _to_float(item.get("OPENINTEREST")) or 0.0
        if commodity not in best or oi > best[commodity][0]:
            best[commodity] = (oi, product, item)
    close_field = cfg.get("close_field", "CLOSEPRICE")
    rows = []
    for commodity, (_, product, item) in best.items():
        value = _to_float(item.get(close_field))
        if value is None or value <= 0:
            continue
        label = f"{product}{item.get('DELIVERYMONTH', '')}"
        rows.append(_make_row(commodity, "期货", value, cfg, label))
    return rows


PARSERS = {
    "sina_futures": parse_futures_sina,
    "eastmoney_futures": parse_futures_eastmoney,
    "shfe_daily": parse_shfe_daily,
}


def parse(parser: str, text: str, cfg: dict) -> list:
    fn = PARSERS.get(parser)
    if fn is None:
        raise ValueError(f"未知价格解析器: {parser}")
    return fn(text, cfg)
