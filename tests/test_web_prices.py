from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from crawler import store
from web.app import create_app


def seed(db):
    conn = store.connect(db)
    store.init_db(conn)
    days = [(datetime.now() - timedelta(days=delta)).strftime("%Y-%m-%d") for delta in (2, 1, 0)]
    for i, day in enumerate(days):
        conn.execute(
            "INSERT INTO prices(commodity,price_type,value,unit,change,change_pct,price_date,source_key,raw_label,fetched_at) "
            "VALUES('铜','期货',?, '元/吨',NULL,NULL,?, 'sina','cu',?)",
            (71000 + i * 100, day, store.now_iso()))
    conn.commit()
    conn.close()


def seed_same_day_multi_source(db):
    conn = store.connect(db)
    store.init_db(conn)
    day = datetime.now().strftime("%Y-%m-%d")
    for source_key, value, fetched in (("mysteel", 2131.6, " 09:00:00"), ("sxcoal", 1990.0, " 09:05:00")):
        conn.execute(
            "INSERT INTO prices(commodity,price_type,value,unit,change,change_pct,price_date,source_key,raw_label,fetched_at) "
            "VALUES('焦炭','指数',?,'元/吨',NULL,NULL,?,?,'',?)",
            (value, day, source_key, day + fetched))
    conn.commit()
    store.upsert_prices(conn, [{
        "commodity": "焦炭", "price_type": "指数", "value": 2140.0, "unit": "元/吨",
        "change": None, "change_pct": None, "price_date": day, "source_key": "mysteel",
        "raw_label": "", "fetched_at": day + " 09:10:00"}])
    conn.close()


def seed_mixed_types(db):
    conn = store.connect(db)
    store.init_db(conn)
    days = [(datetime.now() - timedelta(days=delta)).strftime("%Y-%m-%d") for delta in (2, 1, 0)]
    for i, day in enumerate(days):
        conn.execute(
            "INSERT INTO prices(commodity,price_type,value,unit,change,change_pct,price_date,source_key,raw_label,fetched_at) "
            "VALUES('铜','期货',?,'元/吨',NULL,NULL,?,'sina','cu',?)",
            (71000 + i * 100, day, store.now_iso()))
        conn.execute(
            "INSERT INTO prices(commodity,price_type,value,unit,change,change_pct,price_date,source_key,raw_label,fetched_at) "
            "VALUES('铜','现货',?,'元/吨',NULL,NULL,?,'smm','cu_spot',?)",
            (60000 + i * 100, day, store.now_iso()))
    conn.commit()
    conn.close()


def test_prices_page(tmp_path):
    db = tmp_path / "t.db"
    seed(db)
    client = TestClient(create_app(db))
    resp = client.get("/prices")
    assert resp.status_code == 200
    assert "矿价行情" in resp.text
    assert "铜" in resp.text
    assert "最新报价" in resp.text
    assert "元/吨" in resp.text
    assert 'id="chart-title"' in resp.text
    assert 'id="chart"' in resp.text


def test_price_api(tmp_path):
    db = tmp_path / "t.db"
    seed(db)
    client = TestClient(create_app(db))
    resp = client.get("/api/prices/铜?days=7")
    assert resp.status_code == 200
    data = resp.json()
    assert data["commodity"] == "铜"
    expected_days = [(datetime.now() - timedelta(days=delta)).strftime("%Y-%m-%d") for delta in (2, 1, 0)]
    assert [p["price_date"] for p in data["points"]] == expected_days
    assert data["points"][0]["value"] == 71000
    assert data["points"][0]["unit"] == "元/吨"


def test_price_api_same_day_multi_source_latest(tmp_path):
    db = tmp_path / "t.db"
    seed_same_day_multi_source(db)
    client = TestClient(create_app(db))
    resp = client.get("/api/prices/焦炭?days=7")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["points"]) == 1
    assert data["points"][0]["value"] == 2140.0


def test_price_api_filters_by_price_type(tmp_path):
    db = tmp_path / "t.db"
    seed_mixed_types(db)
    client = TestClient(create_app(db))
    resp = client.get("/api/prices/铜?days=7&price_type=现货")
    assert resp.status_code == 200
    data = resp.json()
    assert [p["value"] for p in data["points"]] == [60000, 60100, 60200]


def test_prices_page_embeds_type_selector(tmp_path):
    db = tmp_path / "t.db"
    seed_mixed_types(db)
    client = TestClient(create_app(db))
    resp = client.get("/prices")
    assert resp.status_code == 200
    assert 'id="ptype"' in resp.text
    assert "TYPE_MAP" in resp.text
    assert "期货" in resp.text
    assert "现货" in resp.text
