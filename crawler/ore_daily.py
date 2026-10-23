"""矿业咨讯·「各种矿石价格」日报解析。

这份日报每天排版都会变（有时带单位、有时省掉，标题也换说法），
所以不按固定模板切，而是：小标题定品种 → 逐句取「标签 + 价格 + 单位」，
标签里的括号/品位/地区/产地再拆成 spec / market / origin。

宁可少一条，也不要把「计价系数」「美元/磅」错认成某一档价格。
"""
import re
from datetime import date, datetime

from crawler import wechat

NUM = r"(\d+(?:\.\d+)?)"
RANGE = NUM + r"(?:\s*[-~～]\s*" + NUM + r")?"
PRICE_UNIT = re.compile(RANGE + r"\s*(万元|元|美元)\s*/\s*(吨度|金属吨|湿吨|干吨|标吨|吨|磅|千克|千吨)")
PRICE_BARE = re.compile(RANGE + r"\s*(万元|元|美元)")
SECTION = re.compile(r"【(.+?)】")
H2 = re.compile(r"^[一二三四五六七八九十]+、(.+)$")
DATE_RE = re.compile(r"(\d{4})年(\d{1,2})月(\d{1,2})日")
UNIT_LINE = re.compile(r"单位[：:]\s*([^，,；;）)]+)")

PROVINCES = ("黑龙江", "内蒙古", "河北", "山西", "辽宁", "吉林", "江苏", "浙江", "安徽",
             "福建", "江西", "山东", "河南", "湖北", "湖南", "广东", "广西", "海南",
             "四川", "贵州", "云南", "陕西", "甘肃", "青海", "宁夏", "新疆", "西藏",
             "上海", "天津", "重庆", "北京")
ORIGINS = ("南非", "加蓬", "澳籽", "澳块", "澳洲", "澳大利亚", "土耳其", "巴布韦",
           "印尼", "菲律宾", "几内亚", "巴基斯坦", "越南", "莫桑比克", "尼日利亚",
           "蒙古", "巴西", "科特迪瓦", "智利", "秘鲁")
ORIGIN_ALIAS = {"澳籽": "澳大利亚", "澳块": "澳大利亚", "澳洲": "澳大利亚",
                "巴布韦": "津巴布韦"}

# 标签里的品种关键词（顺序敏感：先具体后笼统）
LABEL_COMMODITY = (
    ("钨精矿", ("钨精矿", "黑钨", "白钨")),
    ("钼精矿", ("钼精矿", "钼")),
    ("钛精矿", ("钛精矿", "TiO2")),
    ("锂辉石", ("锂辉石",)),
    ("锂云母", ("锂云母",)),
    ("锂矿石", ("磷锂铝石", "锂矿")),
    ("钴精矿", ("钴精矿", "钴中间品", "钴矿")),
    ("石墨", ("石墨",)),
    ("磷矿石", ("磷矿",)),
    ("萤石", ("萤石",)),
    ("硅藻土", ("硅藻土",)),
    ("焦炭", ("焦炭", "冶金焦")),
    ("焦煤", ("炼焦煤", "主焦", "气煤", "瘦煤", "肥煤")),
    ("动力煤", ("动力煤", "电煤", "煤炭")),
    ("铬矿", ("铬矿", "铬精粉", "铬原矿", "铬块矿")),
    ("锰矿石", ("锰矿", "半碳酸", "富锰渣", "加蓬", "澳块", "澳籽")),
    ("红土镍矿", ("红土镍矿",)),
    ("镍精矿", ("镍精矿",)),
    ("铜精矿", ("铜精矿",)),
    ("铅精矿", ("铅精矿",)),
    ("锌精矿", ("锌精矿",)),
    ("锡精矿", ("锡精矿",)),
    ("锑精矿", ("锑精矿",)),
    ("铝土矿", ("铝土矿", "铝矾土")),
    ("白云石", ("白云石",)),
    ("铁精粉", ("精粉", "铁粉", "钒钛")),
    ("铁矿石", ("PB粉", "PB块", "卡粉", "麦克粉", "金布巴", "纽曼", "超特粉")),
)

UNIT_DEFAULT = {
    "锰矿石": "元/吨度", "铬矿": "元/吨度", "钼精矿": "元/吨度",
    "铁矿石": "元/湿吨", "红土镍矿": "美元/湿吨", "钴精矿": "美元/磅",
}
SPEC_TOKEN = re.compile(
    r"(TiO2[≥＜<>][\d.]+%|Q\d+|≥\d+(?:\.\d+)?%|"
    r"\d+(?:\.\d+)?%?\s*[-~～]\s*\d+(?:\.\d+)?%|\d+(?:\.\d+)?%|\d+大卡)")
NOISE = ("价格", "报价", "参考", "市场", "均价", "主流", "左右", "之间", "约为",
         "大致", "部分", "其中", "例如", "如", "为", "在", "约")
QUAL_SPEC = re.compile(r"(低硫主焦煤|中硫主焦煤|高硫主焦煤|主焦精煤|主焦煤|"
                       r"高硫瘦煤|低硫瘦煤|中硫瘦煤|瘦煤|气煤|肥煤|"
                       r"准一级干熄焦|喷吹煤|钒钛粉)")


def _rows_ctx(cfg, price_date):
    return {"key": cfg["key"], "price_type": cfg.get("price_type", "现货"),
            "date": price_date, "basis": cfg.get("basis", "")}


def _mid(lo, hi):
    return round((lo + hi) / 2, 4) if hi is not None else lo


def _value(m):
    lo = float(m.group(1))
    hi = float(m.group(2)) if m.group(2) else None
    cur = m.group(3) if m.lastindex and m.lastindex >= 3 else "元"
    return _mid(lo, hi), cur


def _date_of(lines):
    for ln in lines[:3]:
        m = DATE_RE.search(ln)
        if m:
            try:
                return date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
            except ValueError:
                return ""
    return ""


def _clean_spec(s):
    s = re.sub(r"[（）()]", " ", s or "")
    s = re.sub(r"\s+", " ", s).strip(" ，,、")
    return s


def _origin_of(text):
    for o in ORIGINS:
        if o in (text or ""):
            return ORIGIN_ALIAS.get(o, o)
    return ""


def _market_of(label, default=""):
    m = re.search(r"如([\u4e00-\u9fa5]{2,4})", label)
    if m:
        return m.group(1)
    m = re.search(r"([\u4e00-\u9fa5]{2,4}港)", label)
    if m:
        return m.group(1)
    m = re.search(r"([\u4e00-\u9fa5]{2,6})地区", label)
    if m:
        return m.group(1)
    if "全国" in label or "国内" in label:
        return "全国"
    for p in PROVINCES:
        if label.startswith(p):
            return p
    return default


def _spec_of(label):
    """括号优先，但「0.9%品位(Al≥7%)」这种括号是杂质，品位在前。"""
    paren = re.search(r"[（(]([^（）()]{1,30})[）)]", label)
    tok = SPEC_TOKEN.search(label)
    if tok and paren and tok.end() <= paren.start() + 1:
        return _clean_spec(tok.group(1))
    if paren:
        inner = paren.group(1)
        if (re.search(r"\d|Mn|TiO2|Fe|Al|Zn|Q\d|品位|大卡", inner)
                or (len(inner) <= 8 and not re.match(r"^(以|如|例如)", inner))):
            return _clean_spec(inner)
    return _clean_spec(tok.group(1)) if tok else ""


def _commodity_of(label, h2):
    for name, keys in LABEL_COMMODITY:
        if any(k in label for k in keys):
            return name
    h2 = re.sub(r"[（(][A-Za-z]+[)）]", "", h2 or "")
    for name, keys in LABEL_COMMODITY:
        if any(k in h2 for k in keys):
            return name
    return ""


def _trim(label):
    label = re.sub(r"^\s*\d+[、)）]\s*", "", label or "")
    label = re.sub(r"^\s*\d+\.(?!\d)\s*", "", label)
    label = re.sub(r"^(其中|例如|如)[：:]?", "", label)
    return label.strip(" ：:，,。；;、")


def _rows_of(line, section, h2, product, unit_ctx, ctx, basis_ctx="",
             market_ctx=""):
    out = []
    line_market = _market_of(line, "").replace("北方港", "北方港口")
    line_spec = _spec_of(_trim(line.split("，")[0]))
    if "FOB" in line and ("到港" in line or "CIF" in line):
        line = re.sub(r"FOB\s*价?\s*\d+(?:\.\d+)?\s*美元[，,]?\s*", "", line)
    for seg in re.split(r"[，,；;]", line):
        if not seg.strip():
            continue
        # 同一段里 FOB/CIF 并列时，只留送到价（到港/CIF），FOB 是离岸口径
        if "FOB" in seg and ("到港" in seg or "CIF" in seg):
            cut = seg.find("FOB")
            nxt = min([i for i in (seg.find("到港"), seg.find("CIF")) if i >= 0] or [len(seg)])
            if cut < nxt:
                seg = seg[:cut] + seg[nxt:]
        folded = re.search(r"折合实吨\s*" + NUM + r"\s*万元/吨", seg)
        if folded:
            head = PRICE_BARE.search(seg)
            label = seg[:head.start()] if head else seg
            value = round(float(folded.group(1)) * 10000, 4)
            unit = "元/吨"
        else:
            m = PRICE_UNIT.search(seg)
            if m:
                label = seg[:m.start()]
                value, cur = _value(m)
                unit = f"{cur}/{m.group(4)}"
                if cur == "万元":
                    value = round(value * 10000, 4)
                    unit = f"元/{m.group(4)}"
            else:
                m = PRICE_BARE.search(seg)
                if not m:
                    continue
                label = seg[:m.start()]
                value, cur = _value(m)
                unit = unit_ctx or ""
                if cur == "万元":
                    value = round(value * 10000, 4)
                    cur = "元"
                if unit and unit.split("/")[0] in ("万元", "元", "美元"):
                    unit = f"{cur}/{unit.split('/')[-1]}"
        label = _trim(label)
        if not label or value <= 0 or value > 50000000:
            continue
        commodity = _commodity_of(label + product, h2)
        if not commodity:
            continue
        if not unit:
            unit = UNIT_DEFAULT.get(commodity, "元/吨")
        spec = _spec_of(label)
        if not spec:
            q = QUAL_SPEC.search(label)
            if q:
                spec = q.group(1)
        if not spec:
            spec = line_spec
        if product and product not in spec:
            spec = _clean_spec(f"{product} {spec}".strip())
        market = _market_of(label, "")
        if market and not line_market:
            line_market = market
        if spec and not line_spec:
            line_spec = spec
        if not market:
            market = line_market or market_ctx
        spec = re.sub(r"^(主要指标|按[^，,]{0,8}划分|综合参考|参考)", "", spec).strip()
        if spec and not re.search(r"\d", spec) and len(spec) > 6:
            spec = ""
        if "负极" in label and "负极" not in spec:
            spec = _clean_spec(f"负极 {spec}")
        if len(spec) > 20 or "以" in spec:
            spec = ""
        basis = basis_ctx
        for b in ("CIF", "FOB", "到港", "出厂不含税", "不含税", "含税", "车板", "坑口",
                  "湿基", "干基", "自提", "送到"):
            if b in seg:
                basis = b
                break
        out.append({
            "commodity": commodity,
            "price_type": ctx["price_type"],
            "value": value,
            "unit": unit,
            "change": None,
            "change_pct": None,
            "price_date": ctx["date"],
            "source_key": ctx["key"],
            "raw_label": seg.strip()[:120],
            "market": market,
            "origin": _origin_of(label),
            "spec": spec,
            "basis": basis,
            "contract": "",
            "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        })
    return out


def parse(text, cfg):
    text = text or ""
    if "js_content" in text or text.lstrip().startswith("<"):
        lines = wechat.article_lines(text)
    else:
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    ctx = _rows_ctx(cfg, _date_of(lines))
    out = []
    h2 = product = unit_ctx = market_ctx = ""
    for line in lines:
        if SECTION.search(line):
            h2 = product = ""
            continue
        m = H2.match(line)
        if m:
            h2 = m.group(1)
            product = ""
            continue
        if line in ("黑钨精矿", "白钨精矿"):
            product = line
            continue
        core = re.sub(r"^\s*\d+[、.)）]\s*", "", line)
        if core.startswith("锂辉石"):
            product = "锂辉石"
        elif core.startswith("锂云母"):
            product = "锂云母"
        elif core.startswith("磷锂铝石"):
            product = "磷锂铝石"
        if not PRICE_BARE.search(line):
            rm = re.match(r"^\s*(?:\d+[、.)）]\s*)?([\u4e00-\u9fa5]{2,6}地区)", line)
            if rm:
                market_ctx = rm.group(1).replace("地区", "")
        u = UNIT_LINE.search(line)
        if u:
            unit_ctx = u.group(1).strip()
            if unit_ctx and "/" not in unit_ctx:
                unit_ctx = ""
        basis_ctx = ""
        if re.search(r"CIF|FOB|外盘", line) and not re.search(r"\d", line):
            basis_ctx = "CIF" if "FOB" not in line else "FOB"
        out.extend(_rows_of(line, "", h2, product, unit_ctx, ctx, basis_ctx,
                            market_ctx))
    seen = set()
    uniq = []
    for r in out:
        key = (r["commodity"], r["market"], r["spec"], r["basis"], r["unit"])
        if key in seen:
            continue
        seen.add(key)
        uniq.append(r)
    return uniq
