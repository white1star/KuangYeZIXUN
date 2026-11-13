"""每日社媒刷新：MediaCrawler 抓 微博/知乎/抖音 → 桥接进 hot_items。

本机运行（账号安全），由 daily_hot 脚本/计划任务调用。
Cookie 存在 config/social_cookies.json；过期则该平台跳过并提示，不影响其他平台。
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
MC_DIR = Path(os.environ.get("MEDIA_CRAWLER_DIR", r"E:\MediaCrawler"))
COOKIE_FILE = ROOT / "config" / "social_cookies.json"
CONFIG_FILE = ROOT / "config" / "hot.yaml"


def _keywords() -> str:
    """社媒搜索词跟 config/hot.yaml 的 social_keywords 保持一致（选矿垂直词）。"""
    try:
        data = yaml.safe_load(CONFIG_FILE.read_text(encoding="utf-8")) or {}
        kws = [str(x).strip() for x in (data.get("social_keywords") or []) if str(x).strip()]
        if kws:
            return ",".join(kws)
    except (OSError, yaml.YAMLError):
        pass
    return "选矿,选煤,智能干选,矿石分选,尾矿,浮选"


KEYWORDS = _keywords()

# cli 平台名 → (MediaCrawler data 子目录, 中文名)
PLATFORMS = {
    "wb": ("weibo", "微博热搜"),
    "zhihu": ("zhihu", "知乎热榜"),
    "dy": ("douyin", "抖音热榜"),
}


def _mc_python() -> str:
    for p in (MC_DIR / ".venv" / "Scripts" / "python.exe", MC_DIR / ".venv" / "bin" / "python"):
        if p.exists():
            return str(p)
    return sys.executable


def _latest_jsonl(data_dir: str):
    files = list((MC_DIR / "data" / data_dir).glob("**/*.jsonl"))
    return max(files, key=lambda p: p.stat().st_mtime) if files else None


def _load_cookies() -> dict:
    try:
        return json.loads(COOKIE_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {}


def run_platform(cli: str, cookies: dict) -> dict:
    data_dir, name = PLATFORMS[cli]
    cookie = (cookies.get(cli) or "").strip()
    if not cookie:
        return {"platform": cli, "name": name, "status": "no_cookie"}
    if cli == "dy" and "LOGIN_STATUS=1" not in cookie:
        cookie += "; LOGIN_STATUS=1"

    before = _now = __import__("time").time()
    cmd = [_mc_python(), "main.py", "--platform", cli, "--lt", "cookie",
           "--cookies", cookie, "--type", "search", "--keywords", KEYWORDS,
           "--save_data_option", "jsonl", "--headless", "true",
           "--crawler_max_notes_count", "30"]
    try:
        proc = subprocess.run(cmd, cwd=str(MC_DIR), capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=1800)
    except subprocess.TimeoutExpired:
        return {"platform": cli, "name": name, "status": "timeout"}

    f = _latest_jsonl(data_dir)
    # 文件没更新 → 多半是 Cookie 过期/登录失败
    if not f or f.stat().st_mtime < before - 10:
        tail = ((proc.stdout or "") + (proc.stderr or ""))[-160:].replace("\n", " ")
        return {"platform": cli, "name": name, "status": "no_data",
                "hint": tail or "可能是 Cookie 过期"}

    bridge = subprocess.run(
        [sys.executable, "-m", "tools.hot_from_media_crawler",
         "--platform", cli, "--file", str(f)],
        cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8", errors="replace")
    return {"platform": cli, "name": name, "status": "ok",
            "file": str(f), "ingest": (bridge.stdout or bridge.stderr or "").strip()[-160:]}


def main(argv=None):
    parser = argparse.ArgumentParser(description="社媒（微博/知乎/抖音）刷新并入热榜")
    parser.add_argument("--only", help="只跑指定平台（逗号分隔：wb,zhihu,dy）")
    args = parser.parse_args(argv)
    only = {x.strip() for x in (args.only or "").split(",") if x.strip()}
    cookies = _load_cookies()
    if not cookies:
        print("[social] 未找到 config/social_cookies.json，跳过")
        return
    results = []
    for cli in PLATFORMS:
        if only and cli not in only:
            continue
        res = run_platform(cli, cookies)
        results.append(res)
        print("[social]", json.dumps(res, ensure_ascii=False))
    expired = [r["name"] for r in results if r["status"] in ("no_data", "no_cookie")]
    if expired:
        print("[social] 注意：以下平台登录态可能失效，需更新 Cookie/扫码：" + "、".join(expired))


if __name__ == "__main__":
    main()
