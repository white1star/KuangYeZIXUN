from scripts import crawl_publish


def _summary(errors=0):
    return {
        "sources_total": 3,
        "sources_ok": 3 - errors,
        "sources_error": errors,
        "articles_found": 10,
        "articles_new": 5,
        "prices": 2,
        "errors": [f"bad: HTTP 500"] if errors else [],
    }


def test_run_success_crawls_then_publishes():
    calls = []

    def runner(settings=None):
        calls.append("crawl")
        return _summary()

    def publisher():
        calls.append("publish")
        return "abc123def456"

    assert crawl_publish.run(runner=runner, publisher=publisher) == 0
    assert calls == ["crawl", "publish"]


def test_run_partial_failure_publishes_but_exit_1():
    calls = []

    def runner(settings=None):
        calls.append("crawl")
        return _summary(errors=1)

    def publisher():
        calls.append("publish")
        return "abc123def456"

    assert crawl_publish.run(runner=runner, publisher=publisher) == 1
    assert calls == ["crawl", "publish"]


def test_run_publish_failure_returns_1():
    calls = []

    def runner(settings=None):
        calls.append("crawl")
        return _summary()

    def publisher():
        calls.append("publish")
        raise RuntimeError("推送失败：凭据过期")

    assert crawl_publish.run(runner=runner, publisher=publisher) == 1
    assert calls == ["crawl", "publish"]


def test_run_crawl_exception_skips_publish():
    published = []

    def runner(settings=None):
        raise RuntimeError("网络不可达")

    assert crawl_publish.run(runner=runner, publisher=lambda: published.append(1)) == 1
    assert published == []


def test_run_no_sources_is_failure():
    def runner(settings=None):
        return {"sources_total": 0, "sources_ok": 0, "sources_error": 0,
                "articles_new": 0, "prices": 0, "errors": []}

    called = []

    def publisher():
        called.append("publish")
        return "abc123def456"

    assert crawl_publish.run(runner=runner, publisher=publisher) == 1
    assert called == ["publish"]


def test_run_passes_settings_and_uses_defaults(monkeypatch):
    seen = {}

    class FakeSettings:
        db_path = "x.db"

    def fake_runner(settings=None):
        seen["settings"] = settings
        return _summary()

    def fake_publisher(db_path=None, **kwargs):
        seen["publish_called"] = db_path
        return "abc123def456"

    monkeypatch.setattr(crawl_publish, "run_once", fake_runner)
    monkeypatch.setattr(crawl_publish, "publish", fake_publisher)
    settings = FakeSettings()
    assert crawl_publish.run(settings=settings) == 0
    assert seen == {"settings": settings, "publish_called": None}


def test_main_returns_run_exit_code(monkeypatch):
    monkeypatch.setattr(crawl_publish, "run", lambda: 1)
    assert crawl_publish.main([]) == 1
    monkeypatch.setattr(crawl_publish, "run", lambda: 0)
    assert crawl_publish.main([]) == 0
