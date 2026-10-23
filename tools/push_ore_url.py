# -*- coding: utf-8 -*-
"""本机发现当天矿石日报链接 → 写 data/ore_daily_url.json → 推到服务器。

服务器（腾讯云）访问 mp.weixin.qq.com 正常，只有搜狗被拦；
所以发现动作放在本机，解析和入库仍在服务器。

用法：
    python tools/push_ore_url.py            # 只发现并写文件
    python tools/push_ore_url.py --push     # 再上传到服务器
"""
import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from crawler import wechat  # noqa: E402
from crawler.config import load_sources  # noqa: E402

OUT = ROOT / "data" / "ore_daily_url.json"
HELPER = ROOT / ".superpowers" / "sdd" / "server.py"


def _source():
    for src in load_sources():
        if src.get("key") == "ore_daily":
            return src
    raise SystemExit("找不到 ore_daily 源配置")


def discover() -> dict:
    src = _source()
    url, title = wechat.discover(src["discover"])
    data = {"url": url, "title": title,
            "found_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data


def push(path: Path) -> int:
    if not HELPER.exists():
        print(f"没有 {HELPER}，请手动上传 {path} 到服务器 data/ore_daily_url.json")
        return 1
    up = subprocess.run([sys.executable, str(HELPER), "upload", str(path),
                         "/tmp/ore_daily_url.json"])
    if up.returncode != 0:
        return up.returncode
    return subprocess.run([
        sys.executable, str(HELPER), "run",
        "sudo -n mv /tmp/ore_daily_url.json /opt/news/data/ore_daily_url.json",
    ]).returncode


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="发现矿石日报链接并推送到服务器")
    ap.add_argument("--push", action="store_true", help="发现后上传到服务器")
    args = ap.parse_args(argv)
    data = discover()
    print(f"发现：{data['title']}")
    print(f"链接：{data['url'][:90]}")
    print(f"已写：{OUT}")
    if args.push:
        return push(OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
