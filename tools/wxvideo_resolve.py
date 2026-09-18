import json
import random
import sys
import time
from urllib.parse import parse_qs, unquote, urlparse

import requests

COOKIE_PATH = r"E:\矿_news\config\yuanbao_cookie.txt"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"

PARSE_HEADERS = {
    "accept": "application/json, text/plain, */*",
    "accept-language": "zh-CN,zh;q=0.9,en;q=0.8",
    "content-type": "application/json",
    "origin": "https://yuanbao.tencent.com",
    "referer": "https://yuanbao.tencent.com/chat/naQivTmsDa/cf4d0079-ed1b-4c55-a3f3-2ca1379727d1",
    "user-agent": UA,
    "sec-ch-ua": '"Chromium";v="148", "Google Chrome";v="148", "Not/A)Brand";v="99"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"macOS"',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
    "t-userid": "b9575f6b0a8c4a55a08096904a5ef20a",
    "x-agentid": "naQivTmsDa/cf4d0079-ed1b-4c55-a3f3-2ca1379727d1",
    "x-commit-tag": "72282a0d",
    "x-device-id": "1921b001708100d7fa31002b9646bd0cc15a3e2e1f",
    "x-hy106": "",
    "x-hy92": "e963067ffa31002b9646bd0c03000008b1951a",
    "x-hy93": "1921b001708100d7fa31002b9646bd0cc15a3e2e1f",
    "x-id": "b9575f6b0a8c4a55a08096904a5ef20a",
    "x-instance-id": "5",
    "x-language": "zh-CN",
    "x-os_version": "Mac OS(10.15.7)-Blink",
    "x-platform": "mac",
    "x-requested-with": "XMLHttpRequest",
    "x-source": "web",
    "x-web-third-source": "main",
    "x-webdriver": "0",
    "x-webversion": "2.69.0",
    "x-ybuitest": "0",
}


def load_cookie():
    with open(COOKIE_PATH, "r", encoding="utf-8") as fh:
        return fh.read().strip()


def rid():
    ts = format(int(time.time()), "x")
    rnd = "".join(random.choice("0123456789abcdef") for _ in range(8))
    return f"{ts}-{rnd}"


def parse_share(link, cookie):
    headers = dict(PARSE_HEADERS)
    headers["cookie"] = cookie
    payload = {"type": "video_channel_url", "url": link, "scene": 1}
    resp = requests.post("https://yuanbao.tencent.com/api/weixin/get_parse_result", headers=headers, json=payload, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != 0:
        raise RuntimeError(f"解析失败: {data}")
    return data["data"]


def fetch_feed(export_id, general_token):
    params = {
        "_rid": rid(),
        "_pageUrl": "https://channels.weixin.qq.com/finder-preview/pages/feed",
    }
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Connection": "keep-alive",
        "Content-Type": "application/json",
        "Origin": "https://channels.weixin.qq.com",
        "Referer": (
            "https://channels.weixin.qq.com/finder-preview/pages/feed"
            f"?entry_card_type=48&comment_scene=39&appid=0&token={general_token}&entry_scene=0&eid={export_id}"
        ),
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
        "User-Agent": UA,
    }
    body = {"baseReq": {"generalToken": general_token}, "exportId": export_id}
    resp = requests.post(
        "https://channels.weixin.qq.com/finder-preview/api/feed/get_feed_info",
        params=params,
        headers=headers,
        json=body,
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def main():
    link = sys.argv[1] if len(sys.argv) > 1 else "https://weixin.qq.com/sph/Axv548mzBF"
    cookie = load_cookie()
    print(">>> 第 1 步：元宝解析分享链接")
    parsed = parse_share(link, cookie)
    print("作者:", parsed.get("author"))
    print("简介:", parsed.get("desc"))
    print("封面:", parsed.get("cover_url", "")[:120], "...")
    playable = parsed.get("playable_url", "")
    print("播放入口:", playable[:160], "...")

    qs = parse_qs(urlparse(playable).query)
    token = qs.get("token", [""])[0]
    eid = qs.get("eid", [""])[0]
    print(f">>> 提取到 token 长度: {len(token)} | eid: {eid[:60]}")

    print(">>> 第 2 步：用 token+eid 拉视频详情")
    feed = fetch_feed(eid, token)
    with open(r"E:\矿_news\.superpowers\sdd\sph_feed_with_token.json", "w", encoding="utf-8") as fh:
        json.dump(feed, fh, ensure_ascii=False, indent=1)
    print("完整响应已存 sph_feed_with_token.json（", len(json.dumps(feed)), "字节）")
    print(json.dumps(feed, ensure_ascii=False, indent=1)[:4000])


if __name__ == "__main__":
    main()
