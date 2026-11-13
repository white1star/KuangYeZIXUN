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
    heat_label,
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
ARCHIVE_DAYS = 45


def _norm_title(title: str) -> str:
    text = re.sub(r"[^\w\u4e00-\u9fff]+", "", title or "").lower()
    return text[:26]


def _age_days(published_at: str, now: datetime):
    dt = _parse_dt(published_at or "")
    if dt is None:
        return None
    return max(0, (now - dt).days)


def _decorate(item: dict, cfg, now: datetime, cross: int = 1) -> dict:
    weight = float(source_conf(cfg, item.get("platform", "")).get("weight", 0.85))
    item["heat_score"] = compute_heat(
        item, cfg, source_weight=weight, cross_count=cross, now=now)
    item["heat_label"] = heat_label(item["heat_score"])
    item["time_label"] = time_label(item.get("published_at", ""), now=now)
    item["cross_count"] = cross
    age = _age_days(item.get("published_at", ""), now)
    item["age_days"] = age
    item["archive"] = bool(age is not None and age > ARCHIVE_DAYS)
    item["title"] = clean_title(item.get("title") or "")
    item["summary"] = clean_summary(item.get("summary") or "")
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
        ranked = sorted(entry["items"],
                        key=lambda x: x.get("heat_score") or 0, reverse=True)
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
    out.sort(key=lambda t: (t["platform_count"], t["count"], t["heat"]), reverse=True)
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
    ]

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

    # 微信搜狗结果偏旧：新的排前面，旧文标"资料"仍保留，作为技术文库
    wechat = sorted(
        by_platform.get("wechat", []),
        key=lambda x: (not x["archive"], x["heat_score"], x.get("published_at") or ""),
        reverse=True,
    )

    fresh = [i for i in raw_items if not i["archive"]]
    archive = [i for i in raw_items if i["archive"]]

    industry_raw = _take_recent(articles, "news", 5, 8, now)
    industry = [_from_article(a, "industry", cfg, now) for a in industry_raw]
    industry = [i for i in industry if i["category"] not in DROP_CATEGORIES]

    discussion = [i for i in fresh if i.get("platform") in DISCUSSION_PLATFORMS]

    # 今日热议：只来自自媒体/社交讨论，不用行业媒体/政策补位
    pool = sorted(discussion,
                  key=lambda x: (x["heat_score"], x.get("published_at") or ""),
                  reverse=True)
    top10 = []
    seen_titles = set()
    for item in pool:
        key = _norm_title(item.get("title", ""))[:18]
        if not key or key in seen_titles:
            continue
        seen_titles.add(key)
        top10.append(item)
        if len(top10) >= 10:
            break

    social = []
    for key in ("weibo", "douyin", "toutiao", "baidu_hot", "zhihu"):
        social.extend(by_platform.get(key, []))
    social.sort(key=lambda x: (x["heat_score"], x.get("published_at") or ""),
                reverse=True)

    def _plat(key, limit=10, keep_archive=False):
        rows = [i for i in by_platform.get(key, [])
                if keep_archive or not i["archive"]]
        rows.sort(key=lambda x: (x["heat_score"], x.get("published_at") or ""),
                  reverse=True)
        return _dedupe(rows)[:limit]

    bilibili = [i for i in (by_platform.get("bilibili", [])
                            + by_platform.get("bilibili_search", []))
                if not i["archive"]]
    bilibili.sort(key=lambda x: (x["heat_score"], x.get("published_at") or ""),
                  reverse=True)

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
        "baidu_news": _dedupe([i for i in by_platform.get("baidu_news", [])
                               if not i["archive"]][:80])[:50],
        "bilibili": _dedupe(bilibili[:80])[:50],
        "competitor": _plat("competitor", 20, keep_archive=True),
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
