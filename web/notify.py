from datetime import datetime
from email.message import EmailMessage
from pathlib import Path
import smtplib

import yaml

from crawler.report import log

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PATH = ROOT / "config" / "notify.local.yaml"
SUBJECT_PREFIX = "【矿业资讯站】收到一条新反馈"


def load_notify_config(path=None) -> dict | None:
    p = Path(path) if path else DEFAULT_PATH
    if not p.exists():
        return None
    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    except Exception as exc:
        log(f"反馈邮件通知配置读取失败：{exc}", name="notify")
        return None
    if not isinstance(raw, dict) or not raw.get("enabled"):
        return None
    return raw


def send_feedback_email(content, contact="", page="", config=None) -> bool:
    cfg = config if config is not None else load_notify_config()
    if not cfg:
        log("反馈邮件未发送：通知配置未启用", name="notify")
        return False
    try:
        subject = SUBJECT_PREFIX + (f"（来自 {contact}）" if contact else "")
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        body = "\n".join([
            "收到一条新反馈：",
            f"称呼：{contact or '匿名'}",
            f"时间：{now}",
            f"页面：{page or '未提供'}",
            "",
            "内容：",
            str(content),
        ])
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = cfg["sender"]
        msg["To"] = cfg["recipient"]
        msg.set_content(body)
        with smtplib.SMTP_SSL(cfg["smtp_host"], int(cfg["smtp_port"]), timeout=10) as server:
            server.login(cfg["sender"], cfg["password"])
            server.send_message(msg)
        log(f"反馈邮件已发送至 {cfg['recipient']}", name="notify")
        return True
    except Exception as exc:
        log(f"反馈邮件发送失败：{exc}", name="notify")
        return False
