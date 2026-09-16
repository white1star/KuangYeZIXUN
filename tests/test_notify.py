import web.notify as notify

CFG = {
    "enabled": True,
    "smtp_host": "smtp.qq.com",
    "smtp_port": 465,
    "sender": "sender@qq.com",
    "password": "test-password",
    "recipient": "boss@qq.com",
}


def test_load_notify_config_missing(tmp_path):
    assert notify.load_notify_config(tmp_path / "notify.local.yaml") is None


def test_load_notify_config_disabled(tmp_path):
    path = tmp_path / "notify.local.yaml"
    path.write_text("enabled: false\nsmtp_host: smtp.qq.com\n", encoding="utf-8")
    assert notify.load_notify_config(path) is None


def test_load_notify_config_enabled(tmp_path):
    path = tmp_path / "notify.local.yaml"
    path.write_text("enabled: true\nsmtp_host: smtp.qq.com\nsmtp_port: 465\n", encoding="utf-8")
    cfg = notify.load_notify_config(path)
    assert cfg["smtp_host"] == "smtp.qq.com"


class FakeSMTP:
    instances = []

    def __init__(self, host, port, timeout=None):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.login_args = None
        self.message = None
        FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def login(self, user, password):
        self.login_args = (user, password)

    def send_message(self, msg):
        self.message = msg


class BrokenSMTP(FakeSMTP):
    def login(self, user, password):
        raise RuntimeError("授权码错误")


def test_send_feedback_email_ok(monkeypatch):
    FakeSMTP.instances.clear()
    monkeypatch.setattr(notify.smtplib, "SMTP_SSL", FakeSMTP)
    monkeypatch.setattr(notify, "log", lambda message, name="crawler": None)
    assert notify.send_feedback_email("内容A", contact="老王", page="/prices", config=CFG) is True
    server = FakeSMTP.instances[-1]
    assert (server.host, server.port, server.timeout) == ("smtp.qq.com", 465, 10)
    assert server.login_args == ("sender@qq.com", "test-password")
    assert server.message["To"] == "boss@qq.com"
    subject = str(server.message["Subject"])
    assert "新反馈" in subject
    assert "老王" in subject
    body = server.message.get_content()
    assert "内容A" in body
    assert "/prices" in body


def test_send_feedback_email_without_contact(monkeypatch):
    FakeSMTP.instances.clear()
    monkeypatch.setattr(notify.smtplib, "SMTP_SSL", FakeSMTP)
    monkeypatch.setattr(notify, "log", lambda message, name="crawler": None)
    assert notify.send_feedback_email("内容B", config=CFG) is True
    subject = str(FakeSMTP.instances[-1].message["Subject"])
    assert "新反馈" in subject
    assert "来自" not in subject


def test_send_feedback_email_failure(monkeypatch):
    FakeSMTP.instances.clear()
    logs = []
    monkeypatch.setattr(notify.smtplib, "SMTP_SSL", BrokenSMTP)
    monkeypatch.setattr(notify, "log", lambda message, name="crawler": logs.append(message))
    assert notify.send_feedback_email("内容C", contact="小李", config=CFG) is False
    assert logs
    assert "失败" in logs[-1]
