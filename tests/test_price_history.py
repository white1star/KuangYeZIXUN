from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from crawler import price_history
from crawler.fetch import FetchResult

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _cfg():
    return yaml.safe_load(
        (ROOT / "config" / "sources" / "sina_futures.yaml").read_text(encoding="utf-8"))


def _points():
    text = (FIXTURES / "sina_kline.jsonp").read_text(encoding="utf-8")
    return price_history.parse_kline(text)


def test_parse_kline_real_fixture():
    points = _points()
    assert len(points) > 3000
    assert {"d", "o", "h", "l", "c", "v"} <= set(points[0])
    dates = [p["d"] for p in points]
    assert dates == sorted(dates)
    assert dates[-1] >= "2026-09-01"


def test_parse_kline_bad_text_raises():
    with pytest.raises(ValueError):
        price_history.parse_kline("<html>被拦截</html>")


def test_build_rows_fields_change_and_window():
    points = _points()
    cfg = _cfg()
    now = datetime(2026, 9, 16)
    rows = price_history.build_rows(points, cfg, "JM0", 90, now=now)
    assert rows
    assert rows[0]["price_date"] >= "2026-06-18"
    assert all(r["commodity"] == "焦煤" for r in rows)
    assert all(r["price_type"] == "期货" for r in rows)
    assert all(r["source_key"] == "sina_futures" for r in rows)
    assert all(r["raw_label"] == "JM0" for r in rows)
    assert all(r["unit"] == "元/吨" for r in rows)
    assert all(r["change"] is not None for r in rows)
    closes = {p["d"]: float(p["c"]) for p in points}
    dates = sorted(closes)
    last = rows[-1]
    assert last["price_date"] == "2026-09-16"
    assert last["value"] == closes["2026-09-16"]
    prev_close = closes[dates[dates.index("2026-09-16") - 1]]
    assert last["change"] == round(last["value"] - prev_close, 4)
    assert last["change_pct"] == round(last["change"] / prev_close * 100, 2)
    first = rows[0]
    before = closes[dates[dates.index(first["price_date"]) - 1]]
    assert first["change"] == round(first["value"] - before, 4)


def test_build_rows_days_filtering():
    points = _points()
    cfg = _cfg()
    now = datetime(2026, 9, 16)
    rows7 = price_history.build_rows(points, cfg, "JM0", 7, now=now)
    rows90 = price_history.build_rows(points, cfg, "JM0", 90, now=now)
    all_dates = {p["d"] for p in points}
    assert {r["price_date"] for r in rows7} == {d for d in all_dates if d >= "2026-09-09"}
    assert len(rows7) < len(rows90) <= 90
    assert rows7[-1]["price_date"] == rows90[-1]["price_date"] == "2026-09-16"


def test_build_rows_unit_map_for_metals():
    cfg = _cfg()
    points = [{"d": "2026-09-15", "c": "780.00"}, {"d": "2026-09-16", "c": "785.50"}]
    rows = price_history.build_rows(points, cfg, "AU0", 7, now=datetime(2026, 9, 16))
    assert len(rows) == 2
    assert rows[-1]["commodity"] == "黄金"
    assert rows[-1]["unit"] == "元/克"
    assert rows[-1]["change"] == 5.5


def test_run_writes_rows_and_isolates_failure(tmp_path, monkeypatch):
    text = (FIXTURES / "sina_kline.jsonp").read_text(encoding="utf-8")
    monkeypatch.setattr(price_history, "log", lambda *a, **k: None)

    def fake_fetch(url, **kwargs):
        if "CU0" in url:
            return FetchResult(ok=False, status=500, error="HTTP 500")
        return FetchResult(ok=True, status=200, text=text)

    settings = SimpleNamespace(request_timeout=5, request_retries=0,
                               db_path=tmp_path / "t.db")
    stats = price_history.run(days=90, fetcher=fake_fetch, sleep=lambda s: None,
                              settings=settings, now=datetime(2026, 9, 16))
    expected = price_history.build_rows(_points(), _cfg(), "JM0", 90,
                                        now=datetime(2026, 9, 16))
    assert stats["CU0"]["error"]
    assert stats["JM0"]["days"] == len(expected)
    assert stats["JM0"]["latest"] == "2026-09-16"
    ok_days = sum(s["days"] for c, s in stats.items() if c != "CU0")
    assert ok_days == 11 * len(expected)
    from crawler import store
    conn = store.connect(settings.db_path)
    try:
        total = conn.execute("SELECT COUNT(*) c FROM prices WHERE source_key='sina_futures'").fetchone()["c"]
        cu = conn.execute("SELECT COUNT(*) c FROM prices WHERE commodity='铜'").fetchone()["c"]
        unit = conn.execute(
            "SELECT unit FROM prices WHERE commodity='黄金' LIMIT 1").fetchone()["unit"]
    finally:
        conn.close()
    assert total == ok_days
    assert cu == 0
    assert unit == "元/克"
