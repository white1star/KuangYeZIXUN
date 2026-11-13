"""选矿热榜页面数据组装。

取向：只展示"大家在讨论什么"。
- 今日热议只来自自媒体/社交平台，行业媒体仅在数量不足时补位；
- 政策法规、行业会议不进热榜页（原资讯站已有）；
- 热度在展示层按"多源转载"再算一次，同一话题被多个平台讨论时加分。
"""
import re
from datetime import datetime

from crawler.hot.config import load_hot_config, source_conf
from crawler.hot.keywords import (
    CATEGORY_COLORS,
    _parse_dt,
    classify_category,
    clean_summary,
    clean_title,
    compute_heat,
    engagement_score,
    heat_label,
    is_noise,
    mining_hits,
    time_label,
)
from crawler.hot.store import latest_status, load_items

# 卡片顺序：自媒体/社交在前，行业媒体收尾
PLATFORM_ORDER = ["wechat", "baidu_news", "bilibili_search", "competitor", "weibo",
                  "douyin", "toutiao", "baidu_hot", "zhihu", "bilibili", "industry",
                  "prices"]

PLATFORM_META = {
    "wechat": {"color": "#07c160", "short": "微信"},
    "baidu_news": {"color": "#2b6cff", "short": "百度资讯"},
    "bilibili_search": {"color": "#fb7299", "short": "B站视频"},
    "competitor": {"color": "#c2410c", "short": "竞品"},
    "weibo": {"color": "#e6162d", "short": "微博"},
    "douyin": {"color": "#161823", "short": "抖音"},
    "toutiao": {"color": "#f04142", "short": "头条"},
    "baidu_hot": {"color": "#2932e1", "short": "百度热搜"},
    "zhihu": {"color": "#0066ff", "short": "知乎"},
    "bilibili": {"color": "#fb7299", "short": "B站热门"},
    "industry": {"color": "#289048", "short": "行业媒体"},
    "prices": {"color": "#e5484d", "short": "矿价"},
}

# 只有这些平台的内容能进"今日热议"
DISCUSSION_PLATFORMS = {"wechat", "baidu_news", "bilibili_search", "competitor",
                        "weibo", "douyin", "toutiao", "baidu_hot", "zhihu", "bilibili"}
# 官媒通知类分类，不进热榜页
DROP_CATEGORIES = {"政策法规", "行业会议"}

# 讨论热词里过滤掉没有信息量的泛词
GENERIC_WORDS = {"矿业", "矿山", "矿石", "资源", "价格", "行情", "供需", "库存",
                 "产量", "进口", "出口", "地质", "勘探", "公司", "项目", "市场",
                 "上涨", "下跌", "涨", "跌"}

WEEKDAYS = "一二三四五六日"


def _fmt_heat(n) -> str:
    """把互动量格式化成 tophub 式热度：7670785→767万，28038→2.8万，5751→5751。"""
    try:
        n = float(n or 0)
    except (TypeError, ValueError):
        return ""
    if n <= 0:
        return ""
    if n >= 1e8:
        return f"{n / 1e8:.1f}亿"
    if n >= 1e5:
        return f"{n / 1e4:.0f}万"
    if n >= 1e4:
        return f"{n / 1e4:.1f}万"
    return str(int(n))


def _norm_title(title: str) -> str:
    text = re.sub(r"[^\w\u4e00-\u9fff]+", "", title or "").lower()
    return text[:26]


def _age_days(published_at: str, now: datetime):
    dt = _parse_dt(published_at or "")
    if dt is None:
        return None
    return max(0, (now - dt).days)


def _heat_key(item: dict):
    """统一排序口径：有互动热度的按互动量降序，没有的排在后面按编辑分降序。

    页面右侧显示的正是这个口径（有互动显示赞/播放，没有显示编辑分），
    列表顺序和显示数字保持一致，避免"767万排第3、12万排第8"的错位感。
    """
    try:
        raw = float(item.get("raw_heat") or 0)
    except (TypeError, ValueError):
        raw = 0.0
    return (raw > 0, raw, item.get("heat_score") or 0)


# 标题级核心词：页面标题里必须出现，才算"选矿垂直内容"。
# 只认工艺/装备词，不认"分选/筛分/破碎"这类泛词，避免再生铝、砂石、水果分拣混进来。
CORE_VERTICAL = (
    "选矿", "选煤", "洗煤", "洗选", "干选", "智能干选", "矿石分选", "矿物分选",
    "光电分选", "射线分选", "XRT", "TDS", "预抛废", "抛废", "排矸", "煤矸石",
    "矸石", "浮选", "磁选", "重选", "电选", "重介", "跳汰", "摇床", "磨矿",
    "球磨", "旋流器", "尾矿", "矿浆", "捕收剂", "起泡剂", "絮凝剂",
    "选矿厂", "选煤厂", "洗选厂", "选厂", "矿物加工", "选矿设备", "选煤设备",
    "分选机", "干选机", "破碎机", "破碎筛分", "振动筛", "磁选机", "浮选机", "渣浆泵",
    "压滤机", "浓缩机", "煤泥", "尾煤", "选矿技术", "选煤技术",
    "智能选矿", "智能选煤", "选矿自动化", "磁化焙烧", "难选铁矿",
)


def _is_vertical(item: dict, cfg) -> bool:
    """选矿垂直门槛：标题必须出现选矿工艺/装备核心词（竞品动态卡不受限）。

    标题是用户唯一看到的内容，标题不垂直就不进榜，宁可少而准。
    """
    if item.get("platform") == "competitor":
        return True
    title = item.get("title") or ""
    # 同名不同行（水果分选机、LED 分选机、再生铝破碎）先当噪音排掉
    if is_noise(title):
        return False
    return any(term in title for term in CORE_VERTICAL)


def _decorate(item: dict, cfg, now: datetime, cross: int = 1) -> dict:
    weight = float(source_conf(cfg, item.get("platform", "")).get("weight", 0.85))
    item["heat_score"] = compute_heat(
        item, cfg, source_weight=weight, cross_count=cross, now=now)
    item["heat_label"] = heat_label(item["heat_score"])
    item["time_label"] = time_label(item.get("published_at", ""), now=now)
    item["cross_count"] = cross
    age = _age_days(item.get("published_at", ""), now)
    item["age_days"] = age
    item["archive"] = bool(age is not None and age > cfg.max_age_days)
    item["title"] = clean_title(item.get("title") or "")
    item["summary"] = clean_summary(item.get("summary") or "")
    item["heat_value"] = _fmt_heat(item.get("raw_heat"))
    item["author"] = item.get("author") or ""
    item["url"] = item.get("url") or ""
    if item.get("platform") == "competitor":
        item["competitor_tag"] = (item.get("keywords") or [""])[0]
    return item


def _from_article(article: dict, platform: str, cfg, now: datetime) -> dict:
    title = article.get("title") or ""
    summary = article.get("summary") or ""
    item = {
        "platform": platform,
        "source_name": article.get("source_name") or PLATFORM_META[platform]["short"],
        "title": title,
        "url": article.get("url") or "",
        "summary": summary,
        "author": "",
        "published_at": article.get("published_at") or "",
        "rank": 1,
        "rank_total": 50,
    }
    item["category"] = classify_category(title, cfg, summary)
    item["keywords"] = [w for w, _ in mining_hits(f"{title} {summary}", cfg)]
    return _decorate(item, cfg, now)


def _take_recent(articles, board: str, days: int, limit: int, now: datetime) -> list:
    picked = []
    for article in articles:
        if article.get("board") != board:
            continue
        age = _age_days(article.get("published_at") or "", now)
        if age is not None and age > days:
            continue
        picked.append(article)
    picked.sort(key=lambda a: a.get("published_at") or "", reverse=True)
    return picked[:limit]


def _price_movers(prices: dict, limit: int = 8) -> list:
    rows = [p for p in (prices.get("latest") or []) if p.get("pct") is not None]
    rows.sort(key=lambda p: abs(float(p["pct"])), reverse=True)
    seen = set()
    out = []
    for row in rows:
        key = (row.get("commodity"), row.get("price_type"), row.get("market"))
        if key in seen:
            continue
        seen.add(key)
        pct = float(row["pct"])
        value = row.get("value")
        unit = row.get("unit") or ""
        out.append({
            "commodity": row.get("commodity") or "",
            "price_type": row.get("price_type") or "",
            "market": row.get("market") or "",
            "spec": row.get("spec_label") or "",
            "value": value,
            "unit": unit,
            "pct": pct,
            "pct_label": f"{pct:+.2f}%",
            "up": pct > 0,
            "quote_date": row.get("quote_date") or "",
            "category": "市场行情",
            "platform": "prices",
            "source_name": row.get("source") or "矿价",
        })
        if len(out) >= limit:
            break
    return out


def _dedupe(items: list) -> list:
    seen = set()
    out = []
    for item in items:
        key = _norm_title(item.get("title", ""))[:18]
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _kw_weight(cfg, word: str) -> int:
    return int((cfg.keywords or {}).get(word) or 0)


def _topic_clusters(items: list, cfg, limit: int = 8) -> list:
    """把讨论条目按主关键词聚成话题：一个话题被越多平台讨论，越靠前。"""
    topics: dict = {}
    for item in items:
        keywords = [w for w in (item.get("keywords") or []) if w not in GENERIC_WORDS]
        if not keywords:
            continue
        # 主话题取配置权重最高的命中词（如"金价""铜价"），避免"矿业/公司"这类泛词当话题
        primary = max(keywords, key=lambda w: (_kw_weight(cfg, w), len(w)))
        entry = topics.setdefault(primary, {"word": primary, "items": [], "platforms": set()})
        entry["items"].append(item)
        entry["platforms"].add(item.get("platform") or "")

    out = []
    for entry in topics.values():
        ranked = sorted(entry["items"], key=_heat_key, reverse=True)
        # 代表条目：每个平台最多 1 条，直观呈现"多平台在聊同一件事"
        sample, seen_plat = [], set()
        for it in ranked:
            plat = it.get("platform")
            if plat in seen_plat:
                continue
            seen_plat.add(plat)
            sample.append(it)
            if len(sample) >= 2:
                break
        out.append({
            "word": entry["word"],
            "count": len(entry["items"]),
            "platforms": sorted(p for p in entry["platforms"] if p),
            "platform_count": len(entry["platforms"]),
            "sample": sample,
            "heat": max(i.get("heat_score") or 0 for i in entry["items"]),
        })
    # 统一按热度排序：热度相同再比覆盖平台数、讨论条数
    out.sort(key=lambda t: (t["heat"], t["platform_count"], t["count"]), reverse=True)
    return out[:limit]


def _hot_words(items: list, limit: int = 12) -> list:
    counts: dict = {}
    for item in items:
        for word in item.get("keywords") or []:
            if len(word) < 2 or word in GENERIC_WORDS:
                continue
            counts[word] = counts.get(word, 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return [{"word": word, "count": count} for word, count in ranked[:limit]]


def build_payload(conn, articles: list, prices: dict, build_time: str, now=None) -> dict:
    now = now or datetime.now()
    cfg = load_hot_config()

    raw_items = load_items(conn, days=max(30, cfg.cleanup_days), limit=1500)
    blocked = tuple(cfg.block_terms)
    raw_items = [
        item for item in raw_items
        if (item.get("category") or "行业动态") not in DROP_CATEGORIES
        and not any(word and word in (item.get("title") or "") for word in blocked)
        and not is_noise(item.get("title") or "")
    ]
    if cfg.strict_vertical and cfg.vertical_terms:
        raw_items = [item for item in raw_items if _is_vertical(item, cfg)]

    groups: dict = {}
    for item in raw_items:
        groups.setdefault(_norm_title(item.get("title", "")), set()).add(
            item.get("platform") or "")
    for item in raw_items:
        cross = len(groups.get(_norm_title(item.get("title", "")), ())) or 1
        _decorate(item, cfg, now, cross=cross)
    # 清洗后只剩标签/碎片（<4字）的，丢掉
    raw_items = [i for i in raw_items if len(i.get("title") or "") >= 4]

    order = {key: i for i, key in enumerate(PLATFORM_ORDER)}
    raw_items.sort(key=lambda x: (
        order.get(x.get("platform"), 99),
        x.get("archive", False),
        -x["heat_score"],
    ))

    by_platform = {key: [] for key in PLATFORM_ORDER}
    for item in raw_items:
        by_platform.setdefault(item.get("platform"), []).append(item)

    # 微信搜狗结果偏旧：只留一周内，统一按热度排序
    wechat = sorted(
        [i for i in by_platform.get("wechat", []) if not i["archive"]],
        key=_heat_key,
        reverse=True,
    )

    fresh = [i for i in raw_items if not i["archive"]]
    archive = [i for i in raw_items if i["archive"]]

    industry_raw = _take_recent(articles, "news", 5, 8, now)
    industry = [_from_article(a, "industry", cfg, now) for a in industry_raw]
    industry = [i for i in industry if i["category"] not in DROP_CATEGORIES]

    discussion = [i for i in fresh if i.get("platform") in DISCUSSION_PLATFORMS]

    # 今日热议：只来自自媒体/社交讨论，按热度（显示口径）排序
    pool = sorted(discussion, key=_heat_key, reverse=True)
    top10 = []
    seen_titles = set()
    plat_count = {}
    for item in pool:
        key = _norm_title(item.get("title", ""))[:18]
        if not key or key in seen_titles:
            continue
        plat = item.get("platform")
        if plat_count.get(plat, 0) >= 3:   # 每个平台最多 3 条，避免单一来源刷屏
            continue
        seen_titles.add(key)
        plat_count[plat] = plat_count.get(plat, 0) + 1
        top10.append(item)
        if len(top10) >= 10:
            break

    social = []
    for key in ("weibo", "douyin", "toutiao", "baidu_hot", "zhihu"):
        social.extend(by_platform.get(key, []))
    social.sort(key=_heat_key, reverse=True)

    def _plat(key, limit=10, keep_archive=False):
        rows = [i for i in by_platform.get(key, [])
                if keep_archive or not i["archive"]]
        rows.sort(key=_heat_key, reverse=True)
        return _dedupe(rows)[:limit]

    bilibili = [i for i in (by_platform.get("bilibili", [])
                            + by_platform.get("bilibili_search", []))
                if not i["archive"]]
    bilibili.sort(key=_heat_key, reverse=True)

    movers = _price_movers(prices)

    cat_counts = {}
    for item in fresh + industry:
        name = item.get("category") or "行业动态"
        cat_counts[name] = cat_counts.get(name, 0) + 1
    categories = [
        {"name": name, "count": count, "color": CATEGORY_COLORS.get(name, "#64748b")}
        for name, count in sorted(cat_counts.items(), key=lambda kv: -kv[1])
    ]

    runs = latest_status(conn)
    source_status = []
    for key in PLATFORM_ORDER:
        run = runs.get(key) or {}
        source_status.append({
            "key": key,
            "name": (cfg.sources.get(key) or {}).get("name") or PLATFORM_META[key]["short"],
            "color": PLATFORM_META[key]["color"],
            "status": run.get("status") or "none",
            "found": int(run.get("items_found") or 0),
            "new": int(run.get("items_new") or 0),
            "finished_at": (run.get("finished_at") or "")[11:16],
            "error": run.get("error") or "",
        })

    return {
        "date_label": f"{now.year}年{now.month}月{now.day}日 星期{WEEKDAYS[now.weekday()]}",
        "build_time": build_time,
        "updated_at": (build_time or "")[11:16],
        "top10": top10,
        "wechat": _dedupe(wechat[:80])[:50],
        "baidu_news": _dedupe(sorted(
            (i for i in by_platform.get("baidu_news", []) if not i["archive"]),
            key=_heat_key, reverse=True))[:50],
        "bilibili": _dedupe(bilibili[:80])[:50],
        "competitor": _plat("competitor", 20),
        "weibo": _plat("weibo", 50),
        "douyin": _plat("douyin", 50),
        "toutiao": _plat("toutiao", 50),
        "baidu_hot": _plat("baidu_hot", 50),
        "zhihu": _plat("zhihu", 50),
        "social": _dedupe(social[:32])[:16],
        "industry": industry,
        "prices": movers,
        "hot_words": _hot_words(discussion),
        "topics": _topic_clusters(discussion, cfg, limit=20),
        "categories": categories,
        "platform_meta": PLATFORM_META,
        "source_status": source_status,
        "stats": {
            "total": len(fresh),
            "archive": len(archive),
            "sources": len({i.get("platform") for i in fresh}),
            "discussion": len(discussion),
            "social": len(social),
            "industry": len(industry),
            "prices": len(movers),
            "top_heat": top10[0]["heat_score"] if top10 else 0,
        },
    }
