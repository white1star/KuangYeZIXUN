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
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from crawler import wechat  # noqa: E402
from crawler.config import load_sources  # noqa: E402

OUT = ROOT / "data" / "ore_daily_url.json"
SERVER_CONF = ROOT / "config" / "server.local.yaml"
REMOTE = "/opt/news/data/ore_daily_url.json"


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
    import yaml
    import paramiko

    if not SERVER_CONF.exists():
        print(f"没有 {SERVER_CONF}，无法上传；文件已写在 {path}")
        return 1
    conf = yaml.safe_load(SERVER_CONF.read_text(encoding="utf-8"))
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(conf["host"], username=conf["user"],
                   password=conf["password"], timeout=25)
    try:
        sftp = client.open_sftp()
        sftp.put(str(path), "/tmp/ore_daily_url.json")
        sftp.close()
        cmd = (f"sudo -n mv /tmp/ore_daily_url.json {REMOTE} && "
               f"sudo -n chown root:root {REMOTE}")
        _stdin, stdout, stderr = client.exec_command(cmd, timeout=60)
        err_text = stderr.read().decode("utf-8", "replace")
        status = stdout.channel.recv_exit_status()
        if status != 0:
            print(err_text.strip() or f"远端命令失败 exit={status}")
            return 1
        print(f"已推送：{REMOTE}")
        # 链接有签名有效期，推完立刻让服务器抓一次，别等到整点任务
        _stdin, stdout, stderr = client.exec_command(
            f"cd {conf.get('remote_dir', '/opt/news')} && "
            "sudo -n .venv/bin/python -m crawler.main --once --only ore_daily",
            timeout=180)
        out_text = stdout.read().decode("utf-8", "replace")
        err_text = stderr.read().decode("utf-8", "replace")
        status = stdout.channel.recv_exit_status()
        tail = (out_text.strip().splitlines() or [""])[-1]
        print(f"服务器抓取：{tail or err_text.strip() or status}")
        return 0 if status == 0 else 1
    finally:
        client.close()


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
