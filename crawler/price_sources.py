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


def _num_text(s):
    """从 '1,050 元/吨' / '-0.12%' / '+1.88%' 里取数值。"""
    if s is None:
        return None
    cleaned = re.sub(r"[^\d.+-]", "", str(s))
    if cleaned in {"", "-", "+", ".", "-."}:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _opt_num(s):
    """可选数值：没有数字时返回 None，0 原样返回。"""
    value = _num_text(s)
    return value


def _scaled(v, scale):
    f = _to_float(v)
    if f is None:
        return None
    return round(f / float(scale), 4) if scale else f


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _make_row(commodity, price_type, value, cfg, raw_label,
              change=None, change_pct=None, price_date=None,
              market="", origin="", spec="", basis="", contract="", unit=None):
    unit = unit or (cfg.get("unit_map") or {}).get(commodity) or cfg.get("unit", "")
    return {
        "commodity": commodity,
        "price_type": price_type,
        "value": value,
        "unit": unit,
        "change": change,
        "change_pct": change_pct,
        "price_date": price_date or cfg.get("price_date") or _today(),
        "source_key": cfg["key"],
        "raw_label": raw_label,
        "market": market or "",
        "origin": origin or "",
        "spec": spec or "",
        "basis": basis or "",
        "contract": contract or "",
        "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def _match_commodity(label, mapping, exact=False):
    label = (label or "").strip()
    if not label:
        return None
    if label in mapping:
        return label if isinstance(mapping[label], list) else mapping[label]
    if exact:
        # 只认完全一致的产品名：宁可漏抓，也不能把废铜当成电解铜
        for key, value in mapping.items():
            if isinstance(value, list) and label in [str(w).strip() for w in value if w is not None]:
                return key
            if isinstance(value, str) and value == label:
                return value
        return None
    # 精确命中列表项优先，避免 "1#铜" 被 "铜" 这类宽泛关键字抢先（会抓到废铜）
    for key, value in mapping.items():
        if isinstance(value, list) and label in [str(w).strip() for w in value if w is not None]:
            return key
    for key, value in mapping.items():
        if isinstance(value, list):
            if any(str(w) and str(w) in label for w in value if w is not None):
                return key
        elif isinstance(value, str) and value and value in label:
            return value
    return None


def _match_by_keywords(label, mapping):
    """按关键字在名称里找市场/产地/规格，返回第一个命中的值。"""
    label = (label or "").strip()
    for key, value in (mapping or {}).items():
        if key and str(key) in label:
            return value
    return ""


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
        name = (field("name") or "").strip()
        contract = "连续" if "连续" in name else name
        rows.append(_make_row(commodity, "期货", value, cfg, code,
                              change=change, change_pct=change_pct,
                              market=cfg.get("market", ""),
                              spec=cfg.get("spec", ""),
                              basis=cfg.get("basis", "不含税·昨结算"),
                              contract=contract))
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
        code = str(item.get(fm.get("code", "f12"), ""))
        contract = "".join(ch for ch in code if ch.isdigit())
        rows.append(_make_row(commodity, "期货", value, cfg, label,
                              change=change, change_pct=change_pct,
                              market=cfg.get("market", ""),
                              spec=cfg.get("spec", ""),
                              basis=cfg.get("basis", "不含税"),
                              contract=contract or cfg.get("contract", "")))
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
        rows.append(_make_row(commodity, "期货", value, cfg, label,
                              market=cfg.get("market", ""),
                              basis=cfg.get("basis", "不含税"),
                              contract=cfg.get("contract", "")))
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


def _cell_text(cells, idx):
    if idx is None or idx >= len(cells):
        return ""
    return cells[idx]


def _cell_float(cells, idx):
    return _num_text(_cell_text(cells, idx))


def parse_ccmn_quota(text: str, cfg: dict) -> list:
    """长江有色报价接口：按报价市场逐条出价，不做跨市场平均。

    一天同���可能有几十家报价商、覆盖十几个市场，平均会把"哪个地区多少钱"抹掉，
    所以每条报价独立成行，地区记在 market、产地/牌号记在 origin、品位牌号记在 spec。
    """
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        raise ValueError("长江有色报价接口返回不是 JSON")
    items = ((data.get("body") or {}).get(cfg.get("items", "quotaVoList"))) or []
    q = cfg.get("quote", {})
    date_field = q.get("date", "publishDateTime")
    price_field = q.get("price", "avgPrice")
    name_field = q.get("name", "productSortName")
    market_field = q.get("market", "marketName")
    origin_field = q.get("origin", "placeOrTrademark")
    spec_field = q.get("spec", "trademark")
    unit_field = q.get("unit", "unit")
    rows = []
    for item in items:
        label = str(item.get(name_field, "") or "").strip()
        commodity = _match_commodity(label, cfg.get("commodity_map", {}),
                                     exact=bool(cfg.get("exact_match")))
        if not commodity:
            continue
        value = _to_float(item.get(price_field))
        if value is None or value <= 0:
            continue
        day = parse_date(item.get(date_field)) or _today()
        rows.append(_make_row(
            commodity, cfg.get("price_type", "现货"), round(value, 2), cfg, label,
            price_date=day,
            market=str(item.get(market_field, "") or "").strip(),
            origin=str(item.get(origin_field, "") or "").strip(),
            spec=str(item.get(spec_field, "") or "").strip(),
            basis=cfg.get("basis", ""),
            unit=str(item.get(unit_field, "") or "").strip() or None,
        ))
    return rows


PARSERS["ccmn_quota"] = parse_ccmn_quota


def parse_table(html: str, cfg: dict) -> list:
    t = cfg["table"]
    soup = BeautifulSoup(html, "lxml")
    tables = soup.select("table")
    index = t.get("index")
    if index is not None:
        tables = [tables[index]] if len(tables) > int(index) else []
    rows = []
    for tbl in tables:
        for tr in tbl.select(t.get("row", "tr")):
            cells = [c.get_text(" ", strip=True) for c in tr.select(t.get("cell", "td"))]
            cols = t.get("columns", {})
            if "name" not in cols or "price" not in cols:
                raise ValueError("表格价格源缺少 columns.name/price")
            if len(cells) <= max(cols[k] for k in ("name", "price")):
                continue
            label = cells[cols["name"]]
            commodity = _match_commodity(label, cfg.get("commodity_map", {}),
                                         exact=bool(cfg.get("exact_match")))
            if not commodity:
                continue
            value = _num_text(_cell_text(cells, cols["price"]))
            if value is None or value <= 0:
                continue
            rows.append(_make_row(
                commodity, cfg.get("price_type", "现货"), value, cfg, label,
                change=_cell_float(cells, cols.get("change")),
                change_pct=_cell_float(cells, cols.get("change_pct")),
                price_date=parse_date(_cell_text(cells, cols.get("date"))) or None,
                market=_cell_text(cells, cols.get("market")),
                origin=_cell_text(cells, cols.get("origin")),
                spec=_cell_text(cells, cols.get("spec")),
                basis=_cell_text(cells, cols.get("basis")),
                unit=_cell_text(cells, cols.get("unit")) or None,
            ))
    return rows


def parse_regex(html: str, cfg: dict) -> list:
    r = cfg["regex"]
    soup = BeautifulSoup(html, "lxml")
    text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))
    rows = []
    for m in re.finditer(r["pattern"], text):
        def group(name):
            key = r.get(f"{name}_group", name)
            try:
                return (m.group(key) or "").strip()
            except (IndexError, re.error):
                return ""

        label = group("name")
        commodity = _match_commodity(label, cfg.get("commodity_map", {}),
                                     exact=bool(cfg.get("exact_match")))
        if not commodity:
            continue
        value = _num_text(group("price"))
        if value is None or value <= 0:
            continue
        price_type = cfg.get("price_type", "指数")
        market = group("market")
        if not market:
            market = _match_by_keywords(label, cfg.get("market_map") or {})
        if market in (cfg.get("price_type_map") or {}):
            price_type = cfg["price_type_map"][market]
        spec = group("spec") or _match_by_keywords(label, cfg.get("spec_map") or {})
        rows.append(_make_row(
            commodity, price_type, value, cfg, label,
            change=_opt_num(group("change")),
            change_pct=_opt_num(group("change_pct")),
            price_date=parse_date(group("date")) or None,
            market=market,
            origin=_match_by_keywords(label, cfg.get("origin_map") or {}),
            spec=spec,
            basis=cfg.get("basis", ""),
        ))
    return rows


PARSERS["table"] = parse_table
PARSERS["regex"] = parse_regex
