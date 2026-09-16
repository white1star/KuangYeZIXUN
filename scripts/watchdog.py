import subprocess
import sys
from pathlib import Path

import requests


def http_ok(url, timeout=3) -> bool:
    try:
        return requests.get(url, timeout=timeout).status_code == 200
    except requests.RequestException:
        return False


def read_pid(pid_file):
    try:
        return int(Path(pid_file).read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def kill_pid(pid) -> None:
    subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True)


def start_web(python_exe, workdir) -> None:
    subprocess.Popen(
        [python_exe, "-m", "web.app"],
        cwd=str(workdir),
        creationflags=getattr(subprocess, "DETACHED_PROCESS", 0),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def check_and_restart(base_url, pid_file, python_exe=None, workdir=None) -> str:
    python_exe = python_exe or sys.executable
    workdir = Path(workdir) if workdir else Path(__file__).resolve().parent.parent
    if http_ok(base_url + "/healthz"):
        return "ok"
    pid = read_pid(pid_file)
    if pid:
        kill_pid(pid)
    start_web(python_exe, workdir)
    return "restarted" if pid else "started"


if __name__ == "__main__":
    from crawler.config import load_settings
    s = load_settings()
    print(check_and_restart(f"http://127.0.0.1:{s.port}", s.data_dir / "web.pid"))
