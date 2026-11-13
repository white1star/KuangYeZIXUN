"""把本地构建好的 dist/hot 同步到服务器 /opt/news/dist/hot/。

本地每日流水线在构建后调用；服务器 /Xuankuang/ 直接 alias 到该目录。
"""
import sys
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOT_DIR = ROOT / "dist" / "hot"
SDD = ROOT / ".superpowers" / "sdd"


def make_tar() -> str:
    fd, path = tempfile.mkstemp(suffix=".tar.gz")
    with open(fd, "wb"):
        pass
    with tarfile.open(path, "w:gz") as tf:
        for p in HOT_DIR.iterdir():
            if p.is_file():
                tf.add(p, arcname=p.name)
    return path


def push() -> dict:
    if not HOT_DIR.exists():
        return {"status": "skip", "reason": "dist/hot 不存在"}
    sys.path.insert(0, str(SDD))
    import server  # .superpowers/sdd/server.py：connect()/run()/upload()

    tar_path = make_tar()
    try:
        client = server.connect()
        try:
            sftp = client.open_sftp()
            sftp.put(tar_path, "/tmp/hot_dist.tar.gz")
            sftp.close()
        finally:
            client.close()
        cmd = (
            "sudo -n rm -rf /opt/news/dist/hot && "
            "sudo -n mkdir -p /opt/news/dist/hot && "
            "sudo -n tar -xzf /tmp/hot_dist.tar.gz -C /opt/news/dist/hot && "
            "sudo -n chmod -R a+rX /opt/news/dist/hot && echo PUSH_OK && "
            "ls /opt/news/dist/hot | tr '\\n' ' '"
        )
        code, out, err = server.run(cmd, timeout=120)
        ok = code == 0 and "PUSH_OK" in out
        return {"status": "ok" if ok else "error", "code": code,
                "files": out.replace("PUSH_OK", "").strip(), "err": err.strip()[:160]}
    finally:
        try:
            Path(tar_path).unlink()
        except OSError:
            pass


if __name__ == "__main__":
    import json
    print("[push_hot]", json.dumps(push(), ensure_ascii=False))
