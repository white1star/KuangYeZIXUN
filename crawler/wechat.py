"""微信文章通道：搜狗发现 → 真实链接 → 正文按行。

公众号没有公开的文章列表，搜狗微信是唯一稳定的入口；
一天一次抓取，量很小，不会触发验证码。
"""
import html as html_lib
import re
from datetime import date

import requests

from crawler.fetch import fetch

BASE = "https://weixin.sogou.com"
ITEM_RE = re.compile(r'<li id="sogou_vr_11002601_box_\d+".*?</li>', re.S)
TITLE_RE = re.compile(r'<h3>\s*<a[^>]*href="(/link\?url=[^"]+)"[^>]*>(.*?)</a>', re.S)
ACCOUNT_RE = re.compile(r'<span class="all-time-y2">(.*?)</span>')
TIME_RE = re.compile(r"timeConvert\('(\d+)'\)")


def _clean(s):
    s = html_lib.unescape(re.sub(r"<[^>]+>", "", s or ""))
    return re.sub(r"\s+", " ", s).strip()


def search_items(page):
    out = []
    for block in ITEM_RE.findall(page or ""):
        m = TITLE_RE.search(block)
        if not m:
            continue
        acc = ACCOUNT_RE.search(block)
        ts = TIME_RE.search(block)
        out.append({
            "href": m.group(1),
            "title": _clean(m.group(2)),
            "account": _clean(acc.group(1)) if acc else "",
            "ts": int(ts.group(1)) if ts else 0,
        })
    return out


def pick(items, account="", keyword="", max_age_days=7, today=None):
    """最新一篇符合账号/标题的文章。"""
    today = today or date.today()
    best = None
    for it in items:
        if account and it["account"] != account:
            continue
        if keyword and keyword not in it["title"]:
            continue
        if it["ts"]:
            age = (today - date.fromtimestamp(it["ts"])).days
            if age > max_age_days:
                continue
        if best is None or it["ts"] > best["ts"]:
            best = it
    return best


def resolve(sess, href):
    """搜狗跳转链接 → mp.weixin.qq.com 真实链接。"""
    r = fetch(BASE + href, referer=BASE + "/weixin", session=sess, timeout=25, retries=1)
    if not r.ok:
        raise RuntimeError(f"搜狗跳转失败：{r.error or r.status}")
    url = "".join(re.findall(r"url \+= '(.*?)'", r.text)).replace("@", "")
    if not url:
        m = re.search(r'window\.location\.href\s*=\s*"([^"]+)"', r.text)
        url = m.group(1) if m else ""
    if not url.startswith("http"):
        raise RuntimeError("没拿到微信文章真实链接")
    return url


def article_lines(page):
    """正文（js_content）→ 行。"""
    m = re.search(r'id="js_content"[^>]*>(.*?)(?:</div>\s*</div>|<script)', page or "", re.S)
    if not m:
        raise RuntimeError("微信正文没找到 js_content")
    raw = m.group(1)
    raw = re.sub(r"<br\s*/?>", "\n", raw)
    raw = re.sub(r"</(p|section|li|blockquote|h\d|div)>", "\n", raw)
    text = html_lib.unescape(re.sub(r"<[^>]+>", "", raw))
    text = text.replace("\u200b", "").replace("\xa0", " ")
    return [ln.strip() for ln in text.splitlines() if ln.strip()]


def discover(conf, timeout=25):
    """按配置找到今天（或最近）那篇文章的 URL。"""
    sess = requests.Session()
    page = fetch(conf["search"], session=sess, timeout=timeout, retries=1)
    if not page.ok:
        raise RuntimeError(f"搜狗搜索失败：{page.error or page.status}")
    items = search_items(page.text)
    if not items:
        raise RuntimeError("搜狗没返回文章（可能是验证码）")
    hit = pick(items, account=conf.get("account", ""),
               keyword=conf.get("title_keyword", ""),
               max_age_days=int(conf.get("max_age_days", 7)))
    if not hit:
        raise RuntimeError("搜狗结果里没有符合账号/标题的文章")
    url = resolve(sess, hit["href"])
    return url, hit["title"]
