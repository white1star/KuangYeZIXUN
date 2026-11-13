from datetime import datetime

from crawler.hot.config import load_hot_config
from crawler.hot.keywords import classify_category, compute_heat, time_label
from crawler.hot.sources import _clean, _keep, _parse_baidu_news, _parse_news_date

CFG = load_hot_config()
NOW = datetime(2026, 11, 12, 14, 0)


def item(title, summary="", platform="bilibili", rank=1):
    return {
        "platform": platform,
        "source_name": "测试来源",
        "title": title,
        "url": "https://example.com/x",
        "summary": summary,
        "author": "",
        "published_at": "2026-11-12 10:00",
        "rank": rank,
        "rank_total": 50,
    }


def test_clean_removes_search_highlight_spaces():
    assert _clean("矿业 公司绿色开采") == "矿业公司绿色开采"
    assert _clean("【 煤矿 】神木市德泉矿业") == "【煤矿】神木市德泉矿业"
    assert _clean("2026 年 11 月 选矿 技术") == "2026年11月选矿技术"
    assert _clean("XRT 智能干选 设备") == "XRT智能干选设备"


def test_clean_removes_image_placeholders():
    assert _clean("配图/illustration.png先别慌，金豆是实物") == "先别慌，金豆是实物"
    assert _clean("看这里 ![图](https://a.com/x.jpg) 继续") == "看这里继续"


def test_classify_uses_title_before_summary():
    assert classify_category("美腾科技智能干选机完成工业试验", CFG,
                             "公司同时加强尾矿库安全管理") == "设备装备"
    assert classify_category("某铜矿尾矿库完成生态修复", CFG,
                             "项目采购了新的分选设备") == "安全环保"


def test_strict_mode_keeps_price_discussion():
    gold = item("金价今天大跌，金店排队卖金", "网友讨论现在该不该入手")
    kept = _keep([gold], CFG, strict=True)
    assert len(kept) == 1
    assert kept[0]["category"] == "市场行情"
    assert "金价" in kept[0]["keywords"]

    coal = item("煤炭价格连续上涨", "市场关注冬季保供")
    kept = _keep([coal], CFG, strict=True)
    assert len(kept) == 1
    assert kept[0]["category"] == "市场行情"


def test_strict_mode_drops_generic_words_from_rankings():
    generic = item("我用钢铁拍了一部科幻长片", "全片围绕钢铁机甲展开")
    assert _keep([generic], CFG, strict=True) == []

    weak = item("钢铁行业月度观察", "")
    assert _keep([weak], CFG, strict=True) == []


def test_notice_titles_are_blocked():
    notice = item("某矿业公司尾矿库项目招标公告", "选矿厂设备采购")
    assert _keep([notice], CFG) == []
    auction = item("砂岩矿采矿权拍卖出让公告", "矿业权出让")
    assert _keep([auction], CFG) == []


def test_game_gold_titles_are_blocked():
    game = item("魔兽世界无限金价下跌原因总结", "游戏币交易")
    assert _keep([game], CFG, strict=True) == []


def test_block_terms_drop_recruitment_titles():
    ad = item("【曲靖招聘】矿业公司社会招聘公告", "矿业岗位招聘")
    assert _keep([ad], CFG) == []


def test_news_date_rolls_back_when_month_day_is_in_future():
    assert _parse_news_date("6月23日", now=NOW) == datetime(2026, 6, 23)
    assert _parse_news_date("12月30日", now=NOW) == datetime(2025, 12, 30)
    assert _parse_news_date("2026年11月11日", now=NOW) == datetime(2026, 11, 11)
    assert _parse_news_date("2小时前", now=NOW) == datetime(2026, 11, 12, 12, 0)


def test_parse_baidu_news_separates_source_and_date():
    html = """
    <html><body>
      <div class="result">
        <h3><a href="/link/1">美腾科技智能干选机完成工业试验</a></h3>
        <div class="news-source"><span class="c-color-gray">新浪财经</span>
          <span class="c-color-gray2">6月23日</span></div>
        <div class="c-summary">近日，美腾科技在选煤厂完成智能干选机工业试验。</div>
      </div>
      <div class="result-op">
        <h3><a href="https://example.com/2">尾矿库治理项目招标公告</a></h3>
        <div class="news-source"><span class="c-color-gray">中国矿业报</span>
          <span class="c-color-gray2">2小时前</span></div>
      </div>
    </body></html>
    """
    rows = _parse_baidu_news(html, "选矿")
    assert len(rows) == 2
    assert rows[0]["author"] == "新浪财经"
    assert rows[0]["date_text"] == "6月23日"
    assert "智能干选机" in rows[0]["summary"]
    assert rows[1]["url"] == "https://example.com/2"
    assert rows[1]["author"] == "中国矿业报"


def test_time_label_does_not_invent_midnight():
    assert time_label("2026-11-12", now=NOW) == "今天"
    assert time_label("2026-11-11", now=NOW) == "昨天"
    assert time_label("2026-11-12 09:30", now=NOW) == "09:30"


def test_compute_heat_stays_in_range():
    hot = item("智能干选机在铜矿尾矿项目投产", "矿业公司采购设备")
    heat = compute_heat(hot, CFG, source_weight=1.0, cross_count=2, now=NOW)
    assert 55 <= heat <= 99


def test_topic_clusters_group_by_primary_keyword():
    from site_build.hot.data import _topic_clusters

    items = [
        dict(item("金价大跌，金店排长队", platform="wechat"), keywords=["金价"], heat_score=90),
        dict(item("金价还能追吗？UP主聊聊", platform="bilibili_search"), keywords=["金价"], heat_score=88),
        dict(item("铜价反弹了", platform="wechat"), keywords=["铜价"], heat_score=80),
    ]
    topics = _topic_clusters(items, CFG)
    assert topics[0]["word"] == "金价"
    assert topics[0]["count"] == 2
    assert topics[0]["platform_count"] == 2
    assert set(topics[0]["platforms"]) == {"wechat", "bilibili_search"}
    # 代表条目每个平台取一条
    assert len(topics[0]["sample"]) == 2
    assert topics[1]["word"] == "铜价"
    assert topics[1]["platform_count"] == 1


def test_vertical_gate_rejects_generic_mining_news():
    from site_build.hot.data import _is_vertical

    assert _is_vertical(item("美腾科技智能干选机完成工业试验"), CFG)
    assert _is_vertical(item("尾矿再选实验：摇床和离心机对比"), CFG)
    # 泛矿业行情/贸易新闻不进选矿热榜
    assert not _is_vertical(item("金价大跌，金店排队卖金", "美联储加息，美元走强"), CFG)
    assert not _is_vertical(item("刚果（金）禁止铜钴精矿出口", "全球钴供给受影响"), CFG)
    # 标题不垂直就不进榜，哪怕摘要提到选矿
    assert not _is_vertical(item("稀土是怎么长出来的", "伴生矿选矿很难"), CFG)
    # 竞品动态不受垂直门槛限制
    assert _is_vertical(item("公司荣获省级绿色工厂称号", platform="competitor"), CFG)


def test_vertical_gate_rejects_homonym_sorting():
    from site_build.hot.data import _is_vertical

    # "分选"同名不同行：水果/光电/LED/再生铝都不是矿石分选
    assert not _is_vertical(item("苹果分选机让果子排队上市"), CFG)
    assert not _is_vertical(item("LED 灯珠光电分选设备"), CFG)
    assert not _is_vertical(item("小件铝破碎分选生产线"), CFG)
    # 真正的选矿装备仍保留
    assert _is_vertical(item("铁矿石破碎筛分生产线发货"), CFG)
    assert _is_vertical(item("XRT 智能干选机分选铜矿石"), CFG)


def test_noise_words_cover_social_homonyms():
    from crawler.hot.keywords import is_noise

    assert is_noise("第五人格陪玩代打 xrt")
    assert is_noise("现代途胜 XRT 混动四驱")
    assert is_noise("苹果分选机让果子排队上市")
    assert is_noise("再生铝破碎分选生产线")
    assert not is_noise("XRT 智能干选机分选铜矿石")
