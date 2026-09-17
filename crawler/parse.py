import json
import re
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urljoin

from bs4 import BeautifulSoup

YMD = re.compile(r"(\d{4})\D{0,2}(\d{1,2})\D{0,2}(\d{1,2})")
MD = re.compile(r"(?<!\d)(\d{1,2})-(\d{1,2})(?!\d)")


@dataclass
class ParsedItem:
    title: str
    url: str
    published_at: str = ""
    summary: str = ""


def _ymd_valid(y, mo, d) -> str:
    y, mo, d = int(y), int(mo), int(d)
    if not (1990 <= y <= 2100 and 1 <= mo <= 12 and 1 <= d <= 31):
        return ""
    return f"{y:04d}-{mo:02d}-{d:02d}"


def parse_date(text: str, today=None) -> str:
    text = (text or "").strip()
    if not text:
        return ""
    for m in YMD.finditer(text):
        got = _ymd_valid(*m.groups())
        if got:
            return got
    m = MD.search(text)
    if m:
        mo, d = int(m.group(1)), int(m.group(2))
        if 1 <= mo <= 12 and 1 <= d <= 31:
            now = today or datetime.now()
            year = now.year - 1 if (mo, d) > (now.month, now.day) else now.year
            return f"{year:04d}-{mo:02d}-{d:02d}"
    return ""


def absolutize(base_url: str, href: str) -> str:
    href = (href or "").strip()
    if not href or href.lower().startswith(("javascript:", "#")):
        return ""
    return urljoin(base_url, href)


def _apply_keywords(items: list, cfg: dict) -> list:
    keywords = cfg.get("filter_keywords") or []
    if keywords:
        items = [i for i in items if any(k in i.title for k in keywords)]
    return items


def _json_at(data, path):
    node = data
    for part in str(path or "").split("."):
        if not part:
            continue
        if not isinstance(node, dict):
            return None
        node = node.get(part)
    return node


def parse_json_list(text: str, cfg: dict, base_url: str) -> list:
    lst = cfg.get("list") or {}
    try:
        data = json.loads((text or "").lstrip("\ufeff"))
    except ValueError:
        return []
    node = _json_at(data, lst.get("items"))
    if node is None:
        node = data
    if not isinstance(node, list):
        return []
    title_field = lst.get("title") or "title"
    link_field = lst.get("link") or "link"
    date_field = lst.get("date") or ""
    summary_field = lst.get("summary") or ""
    items = []
    for row in node:
        if not isinstance(row, dict):
            continue
        title = str(row.get(title_field) or "").strip()
        if not title:
            continue
        href = str(row.get(link_field) or "").strip()
        url = absolutize(base_url, href)
        if not url:
            continue
        published_at = ""
        if date_field:
            published_at = parse_date(str(row.get(date_field) or ""))
        if not published_at and lst.get("date_regex"):
            m = re.search(lst["date_regex"], href) or re.search(lst["date_regex"], title)
            if m:
                published_at = parse_date("".join(g for g in m.groups() if g))
        summary = str(row.get(summary_field) or "").strip() if summary_field else ""
        items.append(ParsedItem(title=title, url=url, published_at=published_at, summary=summary))
    return _apply_keywords(items, cfg)


def parse_list(html: str, cfg: dict, base_url: str) -> list:
    lst = cfg.get("list") or {}
    if str(lst.get("format") or "").lower() == "json":
        return parse_json_list(html, cfg, base_url)
    item_sel = lst.get("item")
    if not item_sel:
        raise ValueError("源配置缺少 list.item 选择器")
    soup = BeautifulSoup(html, "lxml")
    items = []
    for node in soup.select(item_sel):
        el = node.select_one(lst["title"]) if lst.get("title") else node
        if el is None:
            continue
        title = el.get_text(" ", strip=True)
        if not title:
            continue
        if lst.get("link"):
            a = node.select_one(lst["link"])
        elif el.name == "a":
            a = el
        else:
            a = node.find("a")
        href = a.get("href", "") if a is not None else ""
        url = absolutize(base_url, href)
        if not url:
            continue
        published_at = ""
        if lst.get("date"):
            dnode = node.select_one(lst["date"])
            if dnode is None and lst.get("date_sibling"):
                sib = node.find_next_sibling()
                hops = 0
                while dnode is None and sib is not None and hops < 2:
                    if hasattr(sib, "select_one"):
                        dnode = sib.select_one(lst["date"])
                    sib = sib.find_next_sibling()
                    hops += 1
            if dnode is not None:
                published_at = parse_date(dnode.get_text(" ", strip=True))
        if not published_at and lst.get("date_regex"):
            m = re.search(lst["date_regex"], href) or re.search(lst["date_regex"], node.get_text(" ", strip=True))
            if m:
                published_at = parse_date("".join(g for g in m.groups() if g))
        items.append(ParsedItem(title=title, url=url, published_at=published_at))
    return _apply_keywords(items, cfg)


def extract_summary(html: str, cfg: dict, max_chars: int) -> str:
    soup = BeautifulSoup(html, "lxml")
    selector = (cfg.get("detail") or {}).get("content")
    node = soup.select_one(selector) if selector else soup.body
    if node is None:
        return ""
    for bad in node.select("script,style,nav,footer,header"):
        bad.decompose()
    text = re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip()
    if len(text) > max_chars:
        text = text[: max_chars - 1].rstrip() + "…"
    return text
