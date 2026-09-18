import json
import os
import random
import re
import sys
import time
from urllib.parse import parse_qs, urlparse

import requests

sys.path.insert(0, r"E:\矿_news\.superpowers\sdd")
sys.path.insert(0, r"E:\矿_news\tools")

from wxvideo_resolve import fetch_feed, parse_share

COOKIE_PATH = r"E:\矿_news\config\yuanbao_cookie.txt"
DEFAULT_DOWNLOAD_DIR = r"E:\矿_news\video_inbox"


def load_cookie():
    with open(COOKIE_PATH, "r", encoding="utf-8") as fh:
        return fh.read().strip()


def sanitize(name, max_len=40):
    name = re.sub(r"[\\/:*?\"<>|\r\n\t]", "", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name[:max_len] or "视频号视频"


def resolve(link):
    cookie = load_cookie()
    parsed = parse_share(link, cookie)
    playable = parsed.get("playable_url", "")
    qs = parse_qs(urlparse(playable).query)
    token = qs.get("token", [""])[0]
    eid = qs.get("eid", [""])[0]
    if not token or not eid:
        raise RuntimeError("播放入口里没有 token/eid")
    feed = fetch_feed(eid, token)
    info = feed.get("data", {}).get("feedInfo", {})
    media = {
        "link": link,
        "author": parsed.get("author", ""),
        "desc": parsed.get("desc", ""),
        "cover_url": parsed.get("cover_url", ""),
        "createtime": info.get("createtime") or parsed.get("createtime"),
        "h264": (info.get("h264VideoInfo") or {}).get("videoUrl") or info.get("videoUrl", ""),
        "h265": (info.get("h265VideoInfo") or {}).get("videoUrl", ""),
    }
    return media


def download(media, out_dir=DEFAULT_DOWNLOAD_DIR, prefer="h264"):
    os.makedirs(out_dir, exist_ok=True)
    url = media.get(prefer) or media.get("h264") or media.get("h265")
    if not url:
        raise RuntimeError("没有视频地址")
    ts = time.strftime("%Y%m%d-%H%M", time.localtime(media.get("createtime") or time.time()))
    codec = "H264" if url == media.get("h264") else "H265"
    name = f"{sanitize(media['author'], 20)}_{sanitize(media['desc'], 30)}_{codec}_{ts}.mp4"
    path = os.path.join(out_dir, name)
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36",
        "Referer": "https://channels.weixin.qq.com/",
    }
    with requests.get(url, headers=headers, stream=True, timeout=60) as resp:
        resp.raise_for_status()
        total = 0
        with open(path, "wb") as fh:
            for chunk in resp.iter_content(chunk_size=1024 * 256):
                fh.write(chunk)
                total += len(chunk)
    print(f"下载完成: {path}")
    print(f"大小: {total / 1024 / 1024:.1f} MB")
    with open(path, "rb") as fh:
        head = fh.read(24)
    print("文件头:", head[:16])
    meta = {
        "link": media.get("link", ""),
        "author": media.get("author", ""),
        "description": media.get("desc", ""),
        "cover_url": media.get("cover_url", ""),
        "createtime": media.get("createtime"),
        "downloaded_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    with open(path + ".json", "w", encoding="utf-8") as fh:
        json.dump(meta, fh, ensure_ascii=False, indent=1)
    print("已保存来源信息:", path + ".json")
    return path


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    link = args[0] if args else "https://weixin.qq.com/sph/Axv548mzBF"
    print(">>> 解析链接:", link)
    media = resolve(link)
    print("作者:", media["author"])
    print("简介:", media["desc"][:80])
    print("H264:", bool(media["h264"]), "| H265:", bool(media["h265"]))
    if "--download" in sys.argv:
        download(media)
    else:
        print("(加 --download 参数可直接下载)")


if __name__ == "__main__":
    main()
