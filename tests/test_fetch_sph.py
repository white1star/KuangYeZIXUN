import json
from datetime import datetime

from tools.fetch_sph import normalize_short_uri, parse_feed_payload

CREATETIME = 1757982000
SAMPLE = {
    "code": 0,
    "data": {
        "authorInfo": {"nickname": "老张说矿"},
        "feedInfo": {
            "description": "磷矿价格回暖，选矿设备更新正当时。\n像素智能，专注矿业智能化。",
            "createtime": CREATETIME,
            "coverUrl": "https://example.com/cover.jpg",
            "likeCountFmt": "1.2万",
            "commentCountFmt": "36",
        },
    },
}


def test_normalize_share_link():
    assert normalize_short_uri("https://weixin.qq.com/sph/AIUEY9XuiH") == "AIUEY9XuiH"


def test_normalize_preview_link():
    link = "https://channels.weixin.qq.com/finder-preview/pages/sph?id=AIUEY9XuiH"
    assert normalize_short_uri(link) == "AIUEY9XuiH"


def test_normalize_plain_short_uri():
    assert normalize_short_uri(" AIUEY9XuiH ") == "AIUEY9XuiH"


def test_normalize_share_link_with_query():
    assert normalize_short_uri("https://weixin.qq.com/sph/AIUEY9XuiH?from=group") == "AIUEY9XuiH"


def test_normalize_invalid():
    assert normalize_short_uri("") == ""
    assert normalize_short_uri("https://example.com/other") == ""


def test_parse_feed_payload_fields():
    info = parse_feed_payload(SAMPLE)
    assert info["author"] == "老张说矿"
    assert info["description"].startswith("磷矿价格回暖")
    assert "\n" in info["description"]
    assert info["cover_url"] == "https://example.com/cover.jpg"


def test_parse_feed_payload_time_conversion():
    info = parse_feed_payload(SAMPLE)
    expected = datetime.fromtimestamp(CREATETIME).strftime("%Y-%m-%d %H:%M")
    assert info["published_at"] == expected
    assert len(info["published_at"]) == 16


def test_parse_feed_payload_accepts_inner_data():
    info = parse_feed_payload(SAMPLE["data"])
    assert info["author"] == "老张说矿"
    assert info["description"]


def test_parse_feed_payload_missing_fields():
    info = parse_feed_payload({"code": 0, "data": {}})
    assert info == {"author": "", "description": "", "published_at": "", "cover_url": ""}
    assert parse_feed_payload(None)["description"] == ""


def test_sample_json_roundtrip():
    info = parse_feed_payload(json.loads(json.dumps(SAMPLE, ensure_ascii=False)))
    assert "像素智能" in info["description"]
