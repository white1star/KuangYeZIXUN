"""各主流社媒/搜索源的热榜抓取。

设计原则：
- 每个平台独立容错，单源失败不影响整页；
- 只存标题、摘要、链接、作者/账号、时间和榜单名次，不存正文；
- 平台热搜先抓全榜，再按矿业词典筛；微信/百度资讯直接按关键词搜。
"""
import json
import re
import time
from datetime import datetime, timedelta
from urllib.parse import quote, urljoin

import requests
from bs4 import BeautifulSoup

from crawler.hot.keywords import (
    classify_category,
    compute_heat,
    is_mining,
    mining_hits,
    parse_cn_time,
)
from crawler.hot.store import now_iso

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
BASE_HEADERS = {
    "User-Agent": UA,
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9",
}


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update(BASE_HEADERS)
    return s


def _get(sess, url, referer="", timeout=20, retries=1):
    last = None
    for attempt in range(retries + 1):
        try:
            r = sess.get(url, headers={"Referer": referer} if referer else None,
                         timeout=timeout)
            if not r.encoding or r.encoding.lower() in ("iso-8859-1", "ascii"):
                r.encoding = r.apparent_encoding or "utf-8"
            if r.status_code < 400:
                return r
            last = RuntimeError(f"HTTP {r.status_code}")
        except Exception as exc:  # noqa: BLE001 - 单源失败要降级
            last = exc
        if attempt < retries:
            time.sleep(1.5)
    raise last or RuntimeError("请求失败")


def _clean(text: str) -> str:
    text = re.sub(r"!?\[[^\]]*\]\([^)]*\)", " ", text or "")  # Markdown 图片/链接
    text = re.sub(r"\S+\.(?:png|jpe?g|gif|webp|svg)(?![A-Za-z0-9])", " ",
                  text, flags=re.I)  # 图片文件名
    text = re.sub(r"<[^>]+>", "", text)
    text = (text.replace("&nbsp;", " ").replace("&amp;", "&")
            .replace("&quot;", '"').replace("&#39;", "'"))
    text = re.sub(r"\s+", " ", text).strip()
    # 搜狗等搜索页会高亮关键词，导致"矿业 公司""2026 年""【 煤矿 】"这种空格
    cjk = r"\u4e00-\u9fff\u3000-\u303f\uff00-\uffef"
    text = re.sub(rf"(?<=[{cjk}0-9A-Za-z])[ \t]+(?=[{cjk}])", "", text)
    return re.sub(rf"(?<=[{cjk}])[ \t]+(?=[0-9A-Za-z])", "", text)


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _search_url(platform: str, word: str) -> str:
    q = quote(word)
    return {
        "weibo": f"https://s.weibo.com/weibo?q={q}",
        "douyin": f"https://www.douyin.com/search/{q}",
        "toutiao": f"https://so.toutiao.com/search?keyword={q}",
        "baidu_hot": f"https://www.baidu.com/s?wd={q}",
        "zhihu": f"https://www.zhihu.com/search?q={q}",
        "bilibili": f"https://search.bilibili.com/all?keyword={q}",
    }.get(platform, f"https://www.baidu.com/s?wd={q}")


def _make(platform, source_name, title, url="", summary="", author="", published_at="",
          rank=1, rank_total=50, raw_heat=None) -> dict:
    return {
        "platform": platform,
        "source_name": source_name,
        "title": _clean(title),
        "url": url or "",
        "summary": _clean(summary),
        "author": _clean(author),
        "published_at": published_at or now_iso(),
        "rank": int(rank or 1),
        "rank_total": int(rank_total or 50),
        "raw_heat": raw_heat,
    }


def _blocked(title: str, cfg) -> bool:
    return any(word and word in title for word in cfg.block_terms)


def _keep(items, cfg, strict: bool = False) -> list:
    """strict=True 用于全站热搜榜：只看标题，避免长摘要里的"破碎/钢铁"误命中。"""
    out = []
    for item in items:
        title = item["title"]
        if _blocked(title, cfg):
            continue
        if strict:
            hits = mining_hits(title, cfg)
            total = sum(weight for _, weight in hits)
            if total < 4 and len(hits) < 2:
                continue
            item["category"] = classify_category(title, cfg)
            item["keywords"] = [w for w, _ in hits]
        else:
            text = f"{title} {item.get('summary', '')}"
            if not is_mining(text, cfg):
                continue
            # 标题优先，摘要兜底，避免摘要里的"设备/安全"把分类带偏
            item["category"] = classify_category(title, cfg, item.get("summary", ""))
            item["keywords"] = [w for w, _ in mining_hits(text, cfg)]
        item["heat_score"] = compute_heat(item, cfg)
        out.append(item)
    return out


# ---------- 微博 ----------

def fetch_weibo(sess, cfg) -> list:
    url = "https://weibo.com/ajax/side/hotSearch"
    try:
        r = _get(sess, url, referer="https://weibo.com/", timeout=cfg.request_timeout)
    except Exception:
        # 先访问首页拿访客 Cookie，再试一次
        _get(sess, "https://weibo.com/", referer="https://weibo.com/",
             timeout=cfg.request_timeout)
        r = _get(sess, url, referer="https://weibo.com/", timeout=cfg.request_timeout)
    data = r.json().get("data") or {}
    rows = data.get("realtime") or []
    items = []
    for i, row in enumerate(rows):
        word = _clean(row.get("word") or row.get("note") or "")
        if not word:
            continue
        items.append(_make(
            "weibo", "微博热搜", word, _search_url("weibo", word),
            summary=row.get("note") or "", rank=i + 1, rank_total=len(rows),
            raw_heat=_num(row.get("num") or row.get("raw_hot")),
        ))
    return _keep(items, cfg, strict=True)


# ---------- 百度热搜 ----------

def _flatten_baidu(node, out):
    if isinstance(node, dict):
        if isinstance(node.get("word"), str) and node.get("word"):
            out.append(node)
        for value in node.values():
            _flatten_baidu(value, out)
    elif isinstance(node, list):
        for value in node:
            _flatten_baidu(value, out)


def fetch_baidu_hot(sess, cfg) -> list:
    r = _get(sess, "https://top.baidu.com/api/board?platform=wise&tab=realtime",
             referer="https://top.baidu.com/board?tab=realtime", timeout=cfg.request_timeout)
    rows = []
    _flatten_baidu(r.json(), rows)
    # 去重，保留第一次出现
    seen = set()
    items = []
    for row in rows:
        word = _clean(row.get("word"))
        if not word or word in seen:
            continue
        seen.add(word)
        items.append(_make(
            "baidu_hot", "百度热搜", word, row.get("url") or _search_url("baidu_hot", word),
            summary=row.get("desc") or "", rank=len(items) + 1, rank_total=len(rows),
            raw_heat=_num(row.get("hotScore") or row.get("heatScore")),
        ))
    return _keep(items, cfg, strict=True)


# ---------- 今日头条 ----------

def fetch_toutiao(sess, cfg) -> list:
    r = _get(sess, "https://www.toutiao.com/hot-event/hot-board/?origin=toutiao_pc",
             referer="https://www.toutiao.com/", timeout=cfg.request_timeout)
    rows = r.json().get("data") or []
    items = []
    for i, row in enumerate(rows):
        title = _clean(row.get("Title") or row.get("title") or "")
        if not title:
            continue
        url = row.get("Url") or row.get("url") or _search_url("toutiao", title)
        items.append(_make(
            "toutiao", "今日头条", title, url,
            summary=row.get("Abstract") or "",
            rank=i + 1, rank_total=len(rows),
            raw_heat=_num(row.get("HotValue") or row.get("hot_value")),
        ))
    return _keep(items, cfg, strict=True)


# ---------- 抖音 ----------

def fetch_douyin(sess, cfg) -> list:
    r = _get(sess, "https://www.iesdouyin.com/web/api/v2/hotsearch/billboard/word/",
             referer="https://www.douyin.com/", timeout=cfg.request_timeout)
    rows = r.json().get("word_list") or []
    items = []
    for i, row in enumerate(rows):
        word = _clean(row.get("word") or "")
        if not word:
            continue
        items.append(_make(
            "douyin", "抖音热榜", word, _search_url("douyin", word),
            summary=row.get("sentence") or "", rank=i + 1, rank_total=len(rows),
            raw_heat=_num(row.get("hot_value")),
        ))
    return _keep(items, cfg, strict=True)


# ---------- 知乎 ----------

def fetch_zhihu(sess, cfg) -> list:
    r = _get(sess, "https://api.zhihu.com/topstory/hot-lists/total?limit=50&reverse_order=0",
             referer="https://www.zhihu.com/hot", timeout=cfg.request_timeout)
    rows = r.json().get("data") or []
    items = []
    for i, row in enumerate(rows):
        target = row.get("target") or {}
        title = _clean(target.get("title") or "")
        if not title:
            continue
        target_type = target.get("type") or "question"
        tid = target.get("id")
        if target_type == "article":
            url = f"https://zhuanlan.zhihu.com/p/{tid}"
        else:
            url = f"https://www.zhihu.com/question/{tid}"
        detail = _clean(row.get("detail_text") or "")
        heat = None
        m = re.search(r"([\d.]+)\s*万", detail)
        if m:
            heat = float(m.group(1)) * 10000
        items.append(_make(
            "zhihu", "知乎热榜", title, url, summary=detail, rank=i + 1,
            rank_total=len(rows), raw_heat=heat,
        ))
    return _keep(items, cfg, strict=True)


# ---------- B 站 ----------

def fetch_bilibili(sess, cfg) -> list:
    r = _get(sess, "https://api.bilibili.com/x/web-interface/ranking/v2?rid=0&type=all",
             referer="https://www.bilibili.com/", timeout=cfg.request_timeout)
    rows = (r.json().get("data") or {}).get("list") or []
    items = []
    for i, row in enumerate(rows):
        title = _clean(row.get("title") or "")
        if not title:
            continue
        pub = ""
        if row.get("pubdate"):
            pub = datetime.fromtimestamp(int(row["pubdate"])).strftime("%Y-%m-%d %H:%M")
        items.append(_make(
            "bilibili", "B站热门", title,
            f"https://www.bilibili.com/video/{row.get('bvid')}",
            summary=row.get("desc") or "", author=(row.get("owner") or {}).get("name") or "",
            published_at=pub, rank=i + 1, rank_total=len(rows),
            raw_heat=_num((row.get("stat") or {}).get("view")),
        ))
    return _keep(items, cfg, strict=True)


# ---------- 微信公众号（搜狗） ----------

def _parse_sogou(page: str) -> list:
    soup = BeautifulSoup(page or "", "lxml")
    nodes = soup.select("li[id^=sogou_vr_11002601_box]")
    out = []
    for node in nodes:
        a = node.select_one("h3 a")
        if not a:
            continue
        title = _clean(a.get_text(" ", strip=True))
        href = a.get("href") or ""
        if href.startswith("/"):
            href = "https://weixin.sogou.com" + href
        acc = node.select_one(".all-time-y2")
        ts = re.search(r"timeConvert\('(\d+)'\)", str(node))
        published = ""
        if ts:
            try:
                published = datetime.fromtimestamp(int(ts.group(1))).strftime("%Y-%m-%d %H:%M")
            except (ValueError, OSError):
                published = ""
        summary_node = node.select_one(".txt-box p")
        out.append({
            "title": title,
            "url": href,
            "author": _clean(acc.get_text(strip=True)) if acc else "",
            "published_at": published,
            "summary": _clean(summary_node.get_text(" ", strip=True)) if summary_node else "",
        })
    return out


def fetch_wechat(sess, cfg) -> list:
    keywords = cfg.search_keywords.get("wechat") or ["选矿"]
    cutoff = datetime.now() - timedelta(days=cfg.wechat_max_age_days)
    seen = set()
    raw = []
    for kw in keywords:
        url = (f"https://weixin.sogou.com/weixin?type=2&query={quote(kw)}"
               f"&ie=utf8&s_from=input")
        try:
            r = _get(sess, url, referer="https://weixin.sogou.com/",
                     timeout=cfg.request_timeout, retries=1)
        except Exception:
            continue
        rows = _parse_sogou(r.text)[:8]
        for i, row in enumerate(rows):
            title = row["title"]
            if not title or title in seen:
                continue
            seen.add(title)
            published = row["published_at"]
            if published:
                try:
                    dt = datetime.strptime(published, "%Y-%m-%d %H:%M")
                    if dt < cutoff:
                        continue
                except ValueError:
                    pass
            row.update({"platform": "wechat", "source_name": "微信公众号",
                        "rank": i + 1, "rank_total": len(rows)})
            row["published_at"] = published or now_iso()
            raw.append(row)
        time.sleep(cfg.request_interval)
    # 新的排前面；搜狗默认按相关度，时间只用于展示和热度
    raw.sort(key=lambda x: x.get("published_at") or "", reverse=True)
    items = []
    for i, row in enumerate(raw):
        item = _make("wechat", "微信公众号", row["title"], row.get("url", ""),
                     summary=row.get("summary", ""), author=row.get("author", ""),
                     published_at=row.get("published_at") or now_iso(),
                     rank=i + 1, rank_total=len(raw))
        items.append(item)
    return _keep(items, cfg)


# ---------- 百度资讯 ----------

def _looks_like_date(text: str) -> bool:
    return bool(re.search(
        r"(刚刚|分钟前|小时前|天前|今天|昨天|前天|\d{1,4}[年/-]\d{1,2}[月/-]\d{1,2}"
        r"|\d{1,2}月\d{1,2}日)", text or ""))


def _parse_news_date(text: str, now=None):
    now = now or datetime.now()
    dt = parse_cn_time(text, now=now)
    if dt is None:
        return None
    # 只有月日、且推算到今天之后，说明是去年的文章
    if not re.search(r"\d{4}", text or "") and dt > now + timedelta(days=1):
        try:
            dt = dt.replace(year=dt.year - 1)
        except ValueError:
            return None
    return dt


def _parse_baidu_news(page: str, kw: str) -> list:
    soup = BeautifulSoup(page or "", "lxml")
    nodes = soup.select("div.result, div.result-op")
    out = []
    for node in nodes:
        a = node.select_one("h3 a")
        if not a:
            continue
        title = _clean(a.get_text(" ", strip=True))
        href = a.get("href") or ""
        if href.startswith("/"):
            href = "https://www.baidu.com" + href
        metas = [_clean(x.get_text(" ", strip=True))
                 for x in node.select(".c-color-gray, .c-color-gray2, "
                                     ".news-source span, .news-source a, "
                                     ".source span, .source a")]
        date_text = next((t for t in metas if _looks_like_date(t)), "")
        source_text = next((t for t in metas if t and not _looks_like_date(t)
                            and len(t) <= 30), "")
        if not source_text:
            src_node = node.select_one(".news-source, .source")
            if src_node:
                text = _clean(src_node.get_text(" ", strip=True))
                if text and not _looks_like_date(text) and len(text) <= 30:
                    source_text = text
        summary_node = node.select_one(".c-summary, .c-span-last, .news-content")
        summary = _clean(summary_node.get_text(" ", strip=True)) if summary_node else ""
        if not date_text:
            # 有些结果把日期放在摘要开头："6月23日 本报讯..."
            head = summary[:24]
            if _looks_like_date(head):
                m = re.match(r"^([^\s，,。]{2,12}[日号]?)", head)
                date_text = m.group(1) if m else head
        out.append({
            "title": title, "url": href, "summary": summary,
            "author": source_text, "date_text": date_text, "keyword": kw,
        })
    return out


def fetch_baidu_news(sess, cfg) -> list:
    keywords = cfg.search_keywords.get("baidu_news") or ["选矿"]
    now = datetime.now()
    cutoff = now - timedelta(days=cfg.max_age_days)
    seen = set()
    raw = []
    captcha = 0
    for kw in keywords:
        url = ("https://www.baidu.com/s?tn=news&rtt=4&bsst=1&cl=2&wd="
               + quote(kw))
        try:
            r = _get(sess, url, referer="https://news.baidu.com/",
                     timeout=cfg.request_timeout, retries=1)
        except Exception:
            continue
        if "百度安全验证" in r.text or "wappass.baidu.com" in str(r.url):
            captcha += 1
            if captcha >= 2:
                raise RuntimeError("百度安全验证拦截，稍后重试")
            time.sleep(cfg.request_interval * 2)
            continue
        for i, row in enumerate(_parse_baidu_news(r.text, kw)):
            title = row["title"]
            if not title or title in seen:
                continue
            seen.add(title)
            dt = _parse_news_date(row.get("date_text", ""), now=now)
            if dt is not None and (dt < cutoff or dt > now + timedelta(days=1)):
                continue
            published = dt.strftime("%Y-%m-%d %H:%M") if dt else now_iso()
            raw.append({
                "title": title, "url": row["url"], "summary": row["summary"],
                "author": row["author"], "published_at": published, "rank": i + 1,
            })
        time.sleep(cfg.request_interval)
    raw.sort(key=lambda x: x.get("published_at") or "", reverse=True)
    items = []
    for i, row in enumerate(raw):
        items.append(_make("baidu_news", "百度资讯", row["title"], row["url"],
                           summary=row["summary"], author=row["author"],
                           published_at=row["published_at"], rank=i + 1,
                           rank_total=len(raw)))
    return _keep(items, cfg)


# ---------- B 站关键词搜索（UP 主讨论） ----------

def fetch_bilibili_search(sess, cfg) -> list:
    keywords = cfg.search_keywords.get("bilibili_search") or ["选矿"]
    now = datetime.now()
    cutoff = now - timedelta(days=cfg.max_age_days)
    seen = set()
    raw = []
    for kw in keywords:
        url = ("https://api.bilibili.com/x/web-interface/search/type"
               f"?search_type=video&order=totalrank&page=1&keyword={quote(kw)}")
        try:
            r = _get(sess, url, referer="https://search.bilibili.com/",
                     timeout=cfg.request_timeout)
            rows = ((r.json().get("data") or {}).get("result") or [])
        except Exception:
            continue
        for row in rows:
            title = _clean(row.get("title") or "")
            if not title or title in seen:
                continue
            pub_ts = int(row.get("pubdate") or 0)
            published = ""
            if pub_ts:
                dt = datetime.fromtimestamp(pub_ts)
                if dt < cutoff:
                    continue
                published = dt.strftime("%Y-%m-%d %H:%M")
            seen.add(title)
            bvid = row.get("bvid") or ""
            stat = row.get("stat") or {}
            raw.append(_make(
                "bilibili_search", "B站视频", title,
                f"https://www.bilibili.com/video/{bvid}" if bvid else "",
                summary=row.get("description") or "", author=row.get("author") or "",
                published_at=published or now_iso(),
                raw_heat=_num(row.get("play") or stat.get("view")),
            ))
        time.sleep(cfg.request_interval)
    # 近 7 天里按播放量排序，播放越高越像"正在被讨论"；标题严格匹配，剔除游戏/小说蹭词
    raw.sort(key=lambda x: (x.get("raw_heat") or 0), reverse=True)
    for i, item in enumerate(raw):
        item["rank"] = i + 1
        item["rank_total"] = len(raw)
    return _keep(raw, cfg, strict=True)


# ---------- 竞品动态（按竞品名搜公众号发文） ----------

def fetch_competitor(sess, cfg) -> list:
    competitors = [c for c in (cfg.competitors or ()) if c]
    if not competitors:
        return []
    cutoff = datetime.now() - timedelta(days=cfg.wechat_max_age_days)
    seen = set()
    raw = []
    for comp in competitors:
        url = (f"https://weixin.sogou.com/weixin?type=2&query={quote(comp)}"
               f"&ie=utf8&s_from=input")
        try:
            r = _get(sess, url, referer="https://weixin.sogou.com/",
                     timeout=cfg.request_timeout, retries=1)
        except Exception:
            time.sleep(cfg.request_interval)
            continue
        for row in _parse_sogou(r.text)[:6]:
            title = row["title"]
            if not title or title in seen:
                continue
            text = f"{title} {row.get('summary', '')}"
            # 搜狗会偏题，标题/摘要里得真提到这家竞品
            if comp not in text and comp[:2] not in text:
                continue
            seen.add(title)
            published = row["published_at"]
            if published:
                try:
                    if datetime.strptime(published, "%Y-%m-%d %H:%M") < cutoff:
                        continue
                except ValueError:
                    pass
            raw.append({**row, "competitor": comp,
                        "published_at": published or now_iso()})
        time.sleep(cfg.request_interval)

    raw.sort(key=lambda x: x.get("published_at") or "", reverse=True)
    items = []
    for i, row in enumerate(raw):
        item = _make("competitor", "竞品动态", row["title"], row.get("url", ""),
                     summary=row.get("summary", ""), author=row.get("author", ""),
                     published_at=row["published_at"], rank=i + 1,
                     rank_total=len(raw))
        item["category"] = classify_category(row["title"], cfg, row.get("summary", ""))
        item["keywords"] = [row["competitor"]]
        item["heat_score"] = compute_heat(item, cfg)
        items.append(item)
    return items


# ---------- 今日头条关键词搜索（m.toutiao 可搜，出真实金价/行情讨论） ----------

def _toutiao_rel(text: str, now):
    t = (text or "").strip()
    m = re.search(r"(\d+)\s*分钟前", t)
    if m:
        return (now - timedelta(minutes=int(m.group(1)))).strftime("%Y-%m-%d %H:%M")
    m = re.search(r"(\d+)\s*小时前", t)
    if m:
        return (now - timedelta(hours=int(m.group(1)))).strftime("%Y-%m-%d %H:%M")
    m = re.search(r"(\d+)\s*天前", t)
    if m:
        return (now - timedelta(days=int(m.group(1)))).strftime("%Y-%m-%d %H:%M")
    if "昨天" in t:
        return (now - timedelta(days=1)).strftime("%Y-%m-%d %H:%M")
    if "前天" in t:
        return (now - timedelta(days=2)).strftime("%Y-%m-%d %H:%M")
    return parse_cn_time(t, now=now)


def fetch_toutiao_search(sess, cfg) -> list:
    keywords = cfg.search_keywords.get("toutiao_search") or ["金价"]
    now = datetime.now()
    cutoff = now - timedelta(days=cfg.max_age_days)
    seen = set()
    raw = []
    for kw in keywords:
        url = "https://m.toutiao.com/search/?keyword=" + quote(kw)
        try:
            r = _get(sess, url, referer="https://m.toutiao.com/",
                     timeout=cfg.request_timeout, retries=1)
        except Exception:
            time.sleep(cfg.request_interval)
            continue
        soup = BeautifulSoup(r.text, "lxml")
        for node in soup.select(".result-content"):
            text = _clean(node.get_text(" ", strip=True))
            if not text or "大家都在搜" in text:
                continue
            m = re.search(r"(\d+\s*(?:分钟|小时|天)前|昨天|前天|刚刚)", text)
            if not m:
                continue  # 跳过"相关搜索"、行情卡片等无时间的结果
            time_txt = m.group(1)
            before = text[:m.start()].strip()
            parts = before.rsplit(" ", 1)
            if len(parts) == 2 and 2 <= len(parts[1]) <= 16 and "\n" not in parts[1]:
                author, title = _clean(parts[1]), _clean(parts[0])
            else:
                author, title = "", before
            # 头条搜索文本里混进了播放数/粉丝/时长等元数据
            title = re.sub(r"\d+\.?\d*[万]?次播放", " ", title)
            title = re.sub(r"\d+\.?\d*[万]?粉丝", " ", title)
            title = re.sub(r"优质\S{0,8}创作者", " ", title)
            title = re.sub(r"\b\d{1,2}:\d{2}(?::\d{2})?\b", " ", title)
            title = re.sub(r"头条号|浏览|-?\S*股吧\S*|@\S+", " ", title)
            title = _clean(title)
            if not title or len(title) < 5 or title in seen:
                continue
            seen.add(title)
            a = node.select_one("a[href*='jump'], a[href]")
            href = (a.get("href") if a else "") or ""
            if href.startswith("/"):
                href = "https://m.toutiao.com" + href
            dt = _toutiao_rel(time_txt, now)
            if dt:
                dd = datetime.strptime(dt, "%Y-%m-%d %H:%M")
                if dd < cutoff:
                    continue
            raw.append({"title": title, "url": href, "summary": "", "author": author,
                        "published_at": dt or now_iso()})
        time.sleep(cfg.request_interval)

    raw.sort(key=lambda x: x.get("published_at") or "", reverse=True)
    items = []
    for i, row in enumerate(raw):
        item = _make("toutiao", "今日头条", row["title"], row["url"],
                     summary=row["summary"], author=row["author"],
                     published_at=row["published_at"], rank=i + 1,
                     rank_total=len(raw))
        item["category"] = classify_category(row["title"], cfg)
        item["keywords"] = [w for w, _ in mining_hits(row["title"], cfg)]
        item["heat_score"] = compute_heat(item, cfg)
        items.append(item)
    return items


FETCHERS = {
    "wechat": fetch_wechat,
    "baidu_news": fetch_baidu_news,
    "bilibili_search": fetch_bilibili_search,
    "competitor": fetch_competitor,
    "weibo": fetch_weibo,
    "douyin": fetch_douyin,
    "toutiao": fetch_toutiao_search,
    "baidu_hot": fetch_baidu_hot,
    "zhihu": fetch_zhihu,
    "bilibili": fetch_bilibili,
}
