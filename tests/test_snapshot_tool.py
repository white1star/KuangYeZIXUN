from crawler.fetch import FetchResult
from tools.snapshot import run_snapshot


def fake_fetcher(results):
    calls = []

    def _fetch(url, **kwargs):
        calls.append(url)
        return results.pop(0)

    return _fetch, calls


def test_failure_writes_no_file(tmp_path):
    fetcher, urls = fake_fetcher([FetchResult(ok=False, status=404, error="HTTP 404")])
    written = run_snapshot({"key": "demo"}, ["https://example.com/list"], tmp_path,
                           fetcher=fetcher, sleep=lambda s: None)
    assert written == []
    assert urls == ["https://example.com/list"]
    assert list(tmp_path.iterdir()) == []


def test_multiple_urls_sleep_before_second_fetch(tmp_path):
    fetcher, urls = fake_fetcher([
        FetchResult(ok=True, status=200, text="<html>1</html>"),
        FetchResult(ok=True, status=200, text="<html>2</html>"),
    ])
    sleeps = []
    written = run_snapshot({"key": "demo"}, ["https://a.example/list", "https://b.example/list"],
                           tmp_path, fetcher=fetcher, sleep=sleeps.append)
    assert sleeps == [1.0]
    assert urls == ["https://a.example/list", "https://b.example/list"]
    assert [p.name for p in written] == ["demo_list.html", "demo_list_2.html"]
    assert (tmp_path / "demo_list_2.html").read_text(encoding="utf-8") == "<html>2</html>"


def test_single_url_no_sleep(tmp_path):
    fetcher, _ = fake_fetcher([FetchResult(ok=True, status=200, text="ok")])
    sleeps = []
    written = run_snapshot({"key": "demo"}, ["https://a.example/list"], tmp_path,
                           fetcher=fetcher, sleep=sleeps.append)
    assert sleeps == []
    assert [p.name for p in written] == ["demo_list.html"]
