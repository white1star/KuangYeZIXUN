import hashlib
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from crawler import store

TRACKING = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
            "spm", "share_token", "from"}
DECOR = [
    re.compile(r"^[【\[][^】\]]{1,12}[】\]]"),
    re.compile(r"^(?:转载|转发)[：:]"),
    re.compile(r"^[（(](?:转载|转发)[）)]"),
    re.compile(r"[（(](?:附全文|全文|附视频|视频|图集|图解|名单|详情|链接|原文|点击查看|阅读原文)[）)]$"),
    re.compile(r"[（(]来源[：:][^）)]{1,20}[）)]$"),
    re.compile(r"^[|｜\-—\s]+|[|｜\-—\s]+$"),
]


def normalize_url(url: str) -> str:
    parts = urlsplit((url or "").strip())
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
             if k.lower() not in TRACKING]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))


def normalize_title(title: str) -> str:
    return re.sub(r"[\W_]+", "", title or "", flags=re.UNICODE).lower()


def core_title(title: str) -> str:
    t = (title or "").strip()
    for _ in range(2):
        for pat in DECOR:
            new = pat.sub("", t).strip()
            if new:
                t = new
    return t


def title_hash(title: str) -> str:
    return hashlib.sha1(normalize_title(title).encode("utf-8")).hexdigest()[:16]


def trigrams(text: str) -> set:
    s = normalize_title(text)
    if not s:
        return set()
    if len(s) < 3:
        return {s}
    return {s[i:i + 3] for i in range(len(s) - 2)}


def _jaccard(a: str, b: str) -> float:
    ta, tb = trigrams(a), trigrams(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def similarity(a: str, b: str) -> float:
    pairs = ((a, b), (core_title(a), b), (a, core_title(b)), (core_title(a), core_title(b)))
    return max(_jaccard(x, y) for x, y in pairs)


def submit_item(conn, item: dict, threshold: float = 0.85) -> str:
    url_hash = hashlib.sha1(normalize_url(item["url"]).encode("utf-8")).hexdigest()
    if store.url_exists(conn, url_hash):
        return "skipped"
    th = title_hash(item["title"])
    for row in store.find_recent_titles(conn, days=3):
        if title_hash(row["title"]) == th or similarity(row["title"], item["title"]) >= threshold:
            store.insert_article(conn, item, item["classification"], url_hash, th,
                                 cluster_id=row["cluster_id"], is_primary=0)
            return "merged"
    store.insert_article(conn, item, item["classification"], url_hash, th)
    return "new"
