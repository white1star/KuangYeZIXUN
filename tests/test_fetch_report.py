from pathlib import Path

import pytest

from crawler import report
from crawler.fetch import FetchResult, fetch


class FakeResponse:
    def __init__(self, status_code=200, text="ok", content=None, encoding="utf-8"):
        self.status_code = status_code
        self.text = text
        self.content = content if content is not None else text.encode(encoding)
        self.encoding = encoding
        self.url = "https://example.com/final"


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, headers=None, timeout=None, allow_redirects=True):
        self.calls.append({"url": url, "headers": dict(headers or {})})
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def test_fetch_sets_ua_and_referer():
    sess = FakeSession([FakeResponse(text="<html>甲</html>")])
    result = fetch("https://example.com/list", referer="https://ref.com", session=sess, sleep=lambda s: None)
    assert result.ok is True
    assert "Mozilla" in sess.calls[0]["headers"]["User-Agent"]
    assert sess.calls[0]["headers"]["Referer"] == "https://ref.com"


def test_fetch_retries_on_503_then_succeeds():
    sess = FakeSession([FakeResponse(status_code=503), FakeResponse(status_code=200, text="好")])
    sleeps = []
    result = fetch("https://example.com", session=sess, sleep=sleeps.append)
    assert result.ok is True
    assert result.text == "好"
    assert len(sess.calls) == 2
    assert sleeps == [1]


def test_fetch_network_error_returns_not_ok():
    sess = FakeSession([ConnectionError("boom"), ConnectionError("boom"), ConnectionError("boom")])
    result = fetch("https://example.com", retries=2, session=sess, sleep=lambda s: None)
    assert result.ok is False
    assert "ConnectionError" in result.error


def test_fetch_decodes_gbk():
    payload = "秦皇岛动力煤".encode("gb18030")
    sess = FakeSession([FakeResponse(text="", content=payload)])
    result = fetch("https://example.com", encoding="gb18030", session=sess, sleep=lambda s: None)
    assert result.text == "秦皇岛动力煤"


def test_snapshot_and_prune(tmp_path):
    for i in range(4):
        p = report.save_snapshot("demo", f"<html>{i}</html>", directory=tmp_path)
        p.write_text(f"<html>{i}</html>", encoding="utf-8")
    report.prune_snapshots("demo", keep=3, directory=tmp_path)
    left = sorted(tmp_path.glob("demo_*.html"))
    assert len(left) == 3
