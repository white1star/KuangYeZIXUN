import socket
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

CRAWL_TASKS = [("矿news抓取07", "07:30"), ("矿news抓取12", "12:30"), ("矿news抓取18", "18:30")]
BACKUP_TASK = ("矿news备份", "19:00")


def sh_quote(value) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def ps_task_script(name, python_exe, arguments, workdir, *,
                   at_logon=False, daily_at=None, repeat_minutes=None,
                   start_when_available=True) -> str:
    parts = [
        f"$action = New-ScheduledTaskAction -Execute {sh_quote(python_exe)} "
        f"-Argument {sh_quote(arguments)} -WorkingDirectory {sh_quote(workdir)}",
    ]
    if at_logon:
        parts.append("$trigger = New-ScheduledTaskTrigger -AtLogOn")
    elif daily_at:
        parts.append(f"$trigger = New-ScheduledTaskTrigger -Daily -At {sh_quote(daily_at)}")
    else:
        parts.append(
            "$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) "
            f"-RepetitionInterval (New-TimeSpan -Minutes {int(repeat_minutes or 5)}) "
            "-RepetitionDuration ([TimeSpan]::MaxValue)")
    flags = []
    if start_when_available:
        flags.append("-StartWhenAvailable")
    flags += ["-RestartCount 3", "-RestartInterval (New-TimeSpan -Minutes 1)"]
    parts.append("$settings = New-ScheduledTaskSettingsSet " + " ".join(flags))
    parts.append(f"Register-ScheduledTask -TaskName {sh_quote(name)} "
                 f"-Action $action -Trigger $trigger -Settings $settings -Force")
    return "; ".join(parts)


def register_task(script: str) -> None:
    subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
                   check=True)


def firewall_rule(port) -> list:
    return ["netsh", "advfirewall", "firewall", "add", "rule", "name=矿news网站",
            "dir=in", "action=allow", "protocol=TCP", f"localport={int(port)}"]


def disable_sleep() -> list:
    return ["powercfg", "/change", "standby-timeout-ac", "0"]


def ensure_venv(requirements, python_exe=None) -> Path:
    python_exe = python_exe or sys.executable
    venv_dir = ROOT / ".venv"
    vpy = venv_dir / "Scripts" / "python.exe"
    if not vpy.exists():
        subprocess.run([python_exe, "-m", "venv", str(venv_dir)], check=True)
    for index_url in ("https://pypi.tuna.tsinghua.edu.cn/simple", "https://pypi.org/simple"):
        result = subprocess.run([str(vpy), "-m", "pip", "install", "-r", str(requirements), "-i", index_url],
                                capture_output=True, text=True)
        if result.returncode == 0:
            return vpy
    raise RuntimeError("依赖安装失败，请检查网络后重试")


def lan_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def main():
    if sys.version_info < (3, 11):
        raise SystemExit("需要 Python 3.11 及以上版本")
    requirements = ROOT / "requirements.txt"
    vpy = ensure_venv(requirements)
    subprocess.run([str(vpy), "-c", "from crawler import store; from crawler.config import load_settings; s=load_settings(); store.init_db(store.connect(s.db_path))"], cwd=str(ROOT), check=True)
    for name, when in CRAWL_TASKS:
        register_task(ps_task_script(name, vpy, "-m crawler.main --once", ROOT, daily_at=when))
    register_task(ps_task_script("矿news网站", vpy, "-m web.app", ROOT, at_logon=True))
    register_task(ps_task_script(BACKUP_TASK[0], vpy, "-m scripts.backup", ROOT, daily_at=BACKUP_TASK[1]))
    register_task(ps_task_script("矿news看门狗", vpy, "-m scripts.watchdog", ROOT, repeat_minutes=5))
    subprocess.run(firewall_rule(load_settings_port()), check=False)
    subprocess.run(disable_sleep(), check=False)
    print(f"安装完成，网站地址：http://{lan_ip()}:{load_settings_port()}")


def load_settings_port():
    sys.path.insert(0, str(ROOT))
    from crawler.config import load_settings
    return load_settings().port


if __name__ == "__main__":
    main()
