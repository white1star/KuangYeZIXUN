import json
from datetime import datetime, timedelta

from crawler import store
from site_build.builder import build


def seed(db, days):
    conn = store.connect(db)
    store.init_db(conn)
    store.upsert_source(conn, "sina", "新浪期货", "price", "https://example.com/f", True)
    store.upsert_prices(conn, [
        {"commodity": "锡", "price_type": "现货", "value": 393303.33, "unit": "元/吨",
         "change": None, "change_pct": None, "price_date": day, "source_key": "sina",
         "raw_label": "", "fetched_at": store.now_iso()}
        for day in days])
    conn.close()


def build_payload(db, tmp_path):
    out = tmp_path / "dist"
    build(db_path=db, out_dir=out, feedback_email="")
    return json.loads((out / "prices.json").read_text(encoding="utf-8"))


def test_carry_forward_appends_today_when_last_quote_old(tmp_path):
    db = tmp_path / "t.db"
    old = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d")
    seed(db, [old])
    payload = build_payload(db, tmp_path)
    today = datetime.now().strftime("%Y-%m-%d")
    spot = payload["series"]["锡"]["现货"]
    assert spot[0] == [old, 393303.33, "元/吨"]
    assert spot[-1] == [today, 393303.33, "元/吨"]
    assert payload["latest"][0]["price_date"] == today


def test_carry_forward_redates_latest_only(tmp_path):
    db = tmp_path / "t.db"
    old = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d")
    seed(db, [old])
    payload = build_payload(db, tmp_path)
    today = datetime.now().strftime("%Y-%m-%d")
    latest = payload["latest"][0]
    assert latest["value"] == 393303.33
    assert latest["price_date"] == today


def test_carried_row_marks_quote_date_and_flag(tmp_path):
    db = tmp_path / "t.db"
    old = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d")
    seed(db, [old])
    payload = build_payload(db, tmp_path)
    latest = payload["latest"][0]
    assert latest["carried"] is True
    assert latest["quote_date"] == old


def test_fresh_row_not_marked_carried(tmp_path):
    db = tmp_path / "t.db"
    today = datetime.now().strftime("%Y-%m-%d")
    seed(db, [today])
    payload = build_payload(db, tmp_path)
    latest = payload["latest"][0]
    assert latest["carried"] is False
    assert latest["quote_date"] == today
    assert latest["price_date"] == today


def test_no_duplicate_when_last_quote_is_today(tmp_path):
    db = tmp_path / "t.db"
    today = datetime.now().strftime("%Y-%m-%d")
    old = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d")
    seed(db, [old, today])
    payload = build_payload(db, tmp_path)
    dates = [p[0] for p in payload["series"]["锡"]["现货"]]
    assert dates.count(today) == 1
    assert dates[-1] == today
    assert payload["latest"][0]["price_date"] == today


def test_prices_page_shows_carry_tag_for_carried_row(tmp_path):
    db = tmp_path / "t.db"
    old = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d")
    seed(db, [old])
    out = tmp_path / "dist"
    build(db_path=db, out_dir=out, feedback_email="")
    html = (out / "prices.html").read_text(encoding="utf-8")
    assert "昨收" in html
    assert old in html  # tooltip shows the real quote date


def test_prices_page_has_no_carry_tag_for_fresh_row(tmp_path):
    db = tmp_path / "t.db"
    today = datetime.now().strftime("%Y-%m-%d")
    seed(db, [today])
    out = tmp_path / "dist"
    build(db_path=db, out_dir=out, feedback_email="")
    html = (out / "prices.html").read_text(encoding="utf-8")
    assert "昨收" not in html
