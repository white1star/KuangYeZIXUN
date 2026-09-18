import argparse
import sys
import tempfile
from pathlib import Path

import paramiko
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.apply_marketing import export

CONFIG_PATH = ROOT / "config" / "server.local.yaml"


def load_settings(path=CONFIG_PATH):
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def sync(settings=None, db_path=None, show=print) -> int:
    settings = settings or load_settings()
    host = settings["host"]
    user = str(settings.get("user") or "root")
    password = settings["password"]
    remote_dir = str(settings.get("remote_dir") or "/opt/news")
    db = Path(db_path) if db_path else ROOT / "data" / "news.db"

    with tempfile.TemporaryDirectory() as tmp:
        json_path = Path(tmp) / "marketing.json"
        export(db, json_path, show=show)
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(host, username=user, password=password, timeout=25)
        try:
            sftp = client.open_sftp()
            sftp.put(str(json_path), "/root/marketing.json")
            sftp.close()
            show("文案文件已上传，服务器正在更新…")
            cmd = (
                f"cd {remote_dir} && .venv/bin/python -m scripts.apply_marketing --apply /root/marketing.json"
                f" && .venv/bin/python -m scripts.build_site"
            )
            stdin, stdout, stderr = client.exec_command(cmd, timeout=300)
            out = stdout.read().decode("utf-8", "replace").strip()
            err = stderr.read().decode("utf-8", "replace").strip()
            code = stdout.channel.recv_exit_status()
        finally:
            client.close()
    if out:
        show(out)
    if err:
        show("服务器输出：" + err[-500:])
    if code != 0:
        show(f"同步失败（退出码 {code}）")
        return 1
    show("同步完成：服务器文案已更新并重新构建")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="把本机营销文案同步到服务器并重新构建网站")
    parser.add_argument("--db", default=None, help="SQLite 数据库路径（默认 data/news.db）")
    args = parser.parse_args(argv)
    return sync(db_path=args.db)


if __name__ == "__main__":
    raise SystemExit(main())
