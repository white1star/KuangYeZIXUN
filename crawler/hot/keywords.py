"""矿业关键词过滤、分类与热度计算。

热榜的"热度"是本站编辑热度，不是平台阅读量：
  时效 25% + 榜单排名 25% + 矿业相关度 15% + 来源权重 15% + 多源转载 20%
"""
import math
import re
from datetime import datetime, timedelta

from crawler.hot.config import HotConfig

CATEGORY_COLORS = {
    "技术工艺": "#2f7de1",
    "设备装备": "#7a5af8",
    "药剂材料": "#d97706",
    "市场行情": "#e5484d",
    "政策法规": "#0f766e",
    "企业动态": "#c026d3",
    "项目招采": "#2563eb",
    "安全环保": "#dc2626",
    "行业会议": "#0891b2",
    "行业动态": "#64748b",
}

# 与矿业无关的噪音（"碳酸锂"也是药物名，微博/知乎会搜到服药体验）
NOISE_WORDS = ("服用", "副作用", "抑郁", "治疗", "中毒", "剂量", "复诊",
               "医嘱", "吃药", "药物", "确诊", "患者", "情感稳定剂", "喹硫平",
               "精神科", "双相", "加药量", "药量", "服药", "咽")


def is_noise(title: str) -> bool:
    return any(w in (title or "") for w in NOISE_WORDS)


# 标题清洗：社媒原始文案带 #话题#、@、emoji、口水话，tophub 式的一句话才看得懂
_EMOJI = re.compile(
    "[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF"
    "\u2190-\u21FF\u2B00-\u2BFF\uFE0F\u200D]")
_HASHTAG_CHAIN = re.compile(r"(?:[#＃][^#＃\s]{1,50}[#＃])+")  # 相邻 #话题# 链
_HASHTAG_ONE = re.compile(r"[#＃][^#＃\s]{1,50}")
_AT = re.compile(r"@[A-Za-z0-9_\u4e00-\u9fff.\-]{1,30}")
_SPACES = re.compile(r"\s+")
_PUNCT_SPACE = re.compile(r"\s+([，。！？、；：,.;:!?])")
_PREFIX = re.compile(r"^(?:全文|全文\s*\.{2,}|\.{3,}|…+)\s*")
_CUT_CHARS = "，。！？、；;,"


def clean_title(title: str, max_len: int = 52) -> str:
    """把社媒原始文案清理成一句话标题。"""
    t = re.sub(r"<[^>]+>", "", title or "")
    t = _PREFIX.sub("", t)
    t = re.sub(r"^.{0,18}?\d{1,2}月\d{1,2}日(?:讯|消息|电|报道)[（(][^）)]{0,24}[）)]\s*", "", t)
    t = re.sub(r"^.{0,18}?\d{1,2}月\d{1,2}日(?:讯|消息|电|报道)\s*", "", t)
    t = _EMOJI.sub("", t)
    t = _HASHTAG_CHAIN.sub(" ", t)
    t = _HASHTAG_ONE.sub(" ", t)
    t = re.sub(r"[#＃]", " ", t)
    t = _AT.sub(" ", t)
    t = _SPACES.sub(" ", t)
    t = _PUNCT_SPACE.sub(r"\1", t)
    t = t.strip(" \t，,。.；;：:、|｜-—…·【】")
    if len(t) > max_len:
        cut = t[:max_len]
        idx = -1
        for ch in _CUT_CHARS:
            idx = max(idx, cut.rfind(ch))
        t = (cut[:idx] if idx >= 14 else cut).rstrip("，,。.、；;：: ｜|") + "…"
    return t.strip()


def clean_summary(text: str, max_len: int = 2000) -> str:
    """清洗摘要：去 #/@/emoji/相对时间前缀/多余空白，保留完整长度。"""
    t = re.sub(r"<[^>]+>", "", text or "")
    t = _PREFIX.sub("", t)
    t = re.sub(r"^(?:\d+\s*(?:分钟|小时|天)前|今天|昨天|前天|刚刚)\s*", "", t)
    t = _EMOJI.sub("", t)
    t = _HASHTAG_CHAIN.sub(" ", t)
    t = _HASHTAG_ONE.sub(" ", t)
    t = re.sub(r"[#＃]", " ", t)
    t = _AT.sub(" ", t)
    t = _SPACES.sub(" ", t)
    t = _PUNCT_SPACE.sub(r"\1", t)
    t = t.strip()
    if len(t) > max_len:
        t = t[:max_len].rstrip() + "…"
    return t


def clean_text(text: str, cfg: HotConfig) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    for word in cfg.excludes:
        if word:
            text = text.replace(word, " ")
    return text


def mining_hits(text: str, cfg: HotConfig) -> list:
    """返回命中的 (关键词, 权重) 列表。"""
    cleaned = clean_text(text, cfg)
    lowered = cleaned.lower()
    hits = []
    for word, weight in cfg.keywords.items():
        probe = word.lower()
        if probe and probe in lowered:
            hits.append((word, int(weight)))
    return hits


def mining_score(text: str, cfg: HotConfig) -> int:
    return sum(weight for _, weight in mining_hits(text, cfg))


def is_mining(text: str, cfg: HotConfig, threshold: int = 2) -> bool:
    return mining_score(text, cfg) >= threshold


def classify_category(title: str, cfg: HotConfig, summary: str = "") -> str:
    """先看标题，标题没命中再看摘要，避免摘要里的"设备/安全"把标题带偏。"""
    for raw in (title, summary):
        cleaned = clean_text(raw, cfg)
        if not cleaned:
            continue
        for name in cfg.category_priority:
            words = cfg.categories.get(name) or []
            if any(word and word.lower() in cleaned.lower() for word in words):
                return name
    return "行业动态"


def _parse_dt(value: str):
    value = (value or "").strip()
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%Y/%m/%d %H:%M",
                "%Y/%m/%d", "%Y年%m月%d日 %H:%M", "%Y年%m月%d日"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def parse_cn_time(text: str, now=None):
    """解析百度/微信常见的相对时间，返回 datetime 或 None。"""
    now = now or datetime.now()
    text = re.sub(r"\s+", " ", (text or "")).strip()
    if not text:
        return None
    # 纯时间戳（秒）
    if re.fullmatch(r"\d{10}", text):
        try:
            return datetime.fromtimestamp(int(text))
        except (ValueError, OSError):
            return None
    m = re.search(r"(\d{1,2}):(\d{2})", text)
    hh, mm = (int(m.group(1)), int(m.group(2))) if m else (0, 0)
    if "刚刚" in text:
        return now
    if "分钟前" in text:
        n = re.search(r"(\d+)\s*分钟前", text)
        return now - timedelta(minutes=int(n.group(1)) if n else 1)
    if "小时前" in text:
        n = re.search(r"(\d+)\s*小时前", text)
        return now - timedelta(hours=int(n.group(1)) if n else 1)
    if "今天" in text:
        return now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if "昨天" in text:
        base = now - timedelta(days=1)
        return base.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if "前天" in text:
        base = now - timedelta(days=2)
        return base.replace(hour=hh, minute=mm, second=0, microsecond=0)
    m = re.search(r"(\d+)\s*天前", text)
    if m:
        return (now - timedelta(days=int(m.group(1)))).replace(
            hour=hh, minute=mm, second=0, microsecond=0)
    for pattern in (r"(\d{4})年(\d{1,2})月(\d{1,2})日", r"(\d{4})-(\d{1,2})-(\d{1,2})",
                    r"(\d{4})/(\d{1,2})/(\d{1,2})"):
        m = re.search(pattern, text)
        if m:
            try:
                return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), hh, mm)
            except ValueError:
                return None
    m = re.search(r"(\d{1,2})月(\d{1,2})日", text)
    if m:
        try:
            return datetime(now.year, int(m.group(1)), int(m.group(2)), hh, mm)
        except ValueError:
            return None
    return None


def recency_score(published_at: str, now=None, half_life_hours: float = 36.0) -> float:
    now = now or datetime.now()
    dt = _parse_dt(published_at)
    if dt is None:
        return 0.45
    hours = max(0.0, (now - dt).total_seconds() / 3600.0)
    return max(0.05, math.exp(-hours / max(1.0, half_life_hours)))


def rank_score(rank: int, total: int) -> float:
    if not rank or rank < 1:
        return 0.5
    total = max(total, rank, 1)
    return max(0.05, 1.0 - (rank - 1) / total)


def specificity_score(hits: list) -> float:
    total = sum(weight for _, weight in hits)
    return min(1.0, total / 14.0)


def compute_heat(item: dict, cfg: HotConfig, source_weight: float = 0.85,
                 cross_count: int = 1, now=None) -> int:
    title = item.get("title", "")
    summary = item.get("summary", "")
    hits = mining_hits(f"{title} {summary}", cfg)
    rank = rank_score(int(item.get("rank") or 0), int(item.get("rank_total") or 50))
    rec = recency_score(item.get("published_at", ""), now=now)
    spec = specificity_score(hits)
    cross = min(1.0, max(1, cross_count) / 3.0)
    base = (0.25 * rank + 0.25 * rec + 0.15 * spec + 0.15 * source_weight
            + 0.20 * cross)
    # 映射到 55-99，避免满屏 20 分的"冷榜"
    return max(1, min(99, round(55 + base * 44)))


def heat_label(heat: int) -> str:
    if heat >= 85:
        return "爆"
    if heat >= 75:
        return "热"
    if heat >= 65:
        return "新"
    return ""


def time_label(published_at: str, now=None) -> str:
    now = now or datetime.now()
    raw = (published_at or "").strip()
    dt = _parse_dt(raw)
    if dt is None:
        return "今日"
    has_time = bool(re.search(r"\d{1,2}:\d{2}", raw))
    if dt.date() == now.date():
        return dt.strftime("%H:%M") if has_time else "今天"
    if dt.date() == (now - timedelta(days=1)).date():
        return ("昨天 " + dt.strftime("%H:%M")) if has_time else "昨天"
    if now - dt < timedelta(days=7):
        return dt.strftime("%m-%d %H:%M") if has_time else dt.strftime("%m-%d")
    return dt.strftime("%Y-%m-%d")
