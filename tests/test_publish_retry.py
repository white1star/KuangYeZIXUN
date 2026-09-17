import pytest

from scripts import publish_data_branch as pub


class FakeResult:
    def __init__(self, code, err=""):
        self.returncode = code
        self.stdout = ""
        self.stderr = err


def test_push_retries_until_success(monkeypatch):
    results = [FakeResult(1, "fatal: unable to access github.com"), FakeResult(1, "timeout"), FakeResult(0)]
    calls = []

    def fake_git(args, input_bytes=None, check=True):
        calls.append(args)
        return results.pop(0)

    sleeps = []
    monkeypatch.setattr(pub, "git", fake_git)
    monkeypatch.setattr(pub, "report_log", lambda *a, **k: None)
    pub._push_with_retry("origin", "abc123456789", "data", attempts=3, sleep=sleeps.append)
    assert len(calls) == 3
    assert sleeps == [15, 45]


def test_push_raises_after_all_retries(monkeypatch):
    results = [FakeResult(1, "fatal: unable to access github.com")]

    def fake_git(args, input_bytes=None, check=True):
        return results[0]

    sleeps = []
    monkeypatch.setattr(pub, "git", fake_git)
    monkeypatch.setattr(pub, "report_log", lambda *a, **k: None)
    with pytest.raises(pub.PublishError):
        pub._push_with_retry("origin", "abc123456789", "data", attempts=3, sleep=sleeps.append)
    assert sleeps == [15, 45, 90]
