# 矿业资讯内部站（矿_news）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在办公 Windows 电脑上交付"抓取器 + 内网网站"：每天 07:30/12:30/18:30 自动抓取矿价、政策、行业新闻，支持标签筛选、自动去重、全文搜索，仅存标题+≤200字摘要+链接。

**Architecture:** 路线A 分离式本地应用：抓取器为独立 CLI（Windows 计划任务触发，每次新进程、单源故障隔离）；网站为常驻 FastAPI 进程读同一 SQLite；信息源、标签词典全部 YAML 配置驱动（加源/改源不改代码）。

**Tech Stack:** Python 3.11+、requests、BeautifulSoup4+lxml、FastAPI+Uvicorn、Jinja2、SQLite(FTS5 trigram)、PyYAML、pytest+httpx、ECharts（本地静态文件，不依赖外网 CDN）。

**Spec:** `docs/superpowers/specs/2026-09-15-mineral-news-site-design.md`

## Global Constraints

- 只存 标题 + ≤200 字摘要 + 原文链接 + 元数据；不存正文全文
- 单源请求间隔 ≥1 秒；单请求超时 15 秒；重试 ≤2 次；不绕过登录墙/验证码
- 抓取节奏 07:30 / 12:30 / 18:30；网站 `http://<IP>:8080`，无登录，仅内网
- v1 不做：推送、AI 摘要、公众号抓取、账号体系
- 全部 UI/日志/测试数据/文档用中文；代码标识符用英文；**代码不写注释**
- 测试命令统一 `python -m pytest`；每个任务结束必须提交 git（消息用 `feat:`/`test:`/`docs:` + 中文描述）
- 新增第三方依赖必须先加进 `requirements.txt`

## 文件结构（最终形态）

```
E:\矿_news\
├── config\
│   ├── settings.yaml            全局参数（端口/阈值/超时）
│   ├── tags.yaml                矿种/类型/地区关键词词典
│   └── sources\*.yaml           每个信息源一份配置
├── crawler\
│   ├── config.py                配置加载
│   ├── store.py                 SQLite 数据访问
│   ├── fetch.py                 HTTP 抓取（UA/Referer/编码/重试）
│   ├── parse.py                 通用列表解析 + 日期/URL 处理
│   ├── classify.py              标签分类
│   ├── dedup.py                 三层去重
│   ├── price_sources.py         价格解析器（期货/表格/正则）
│   ├── report.py                日志与失败快照
│   └── main.py                  抓取编排（CLI: python -m crawler.main --once）
├── db\schema.sql                建表 + FTS5 + 触发器
├── web\
│   ├── app.py                   FastAPI 应用（python -m web.app 启动）
│   ├── queries.py               页面查询
│   ├── templates\*.html         Jinja2 模板
│   └── static\                  样式/app.js/vendor/echarts.min.js
├── scripts\
│   ├── backup.py                每日备份（保留30天）
│   ├── watchdog.py              健康检查+自动拉起
│   └── install.py               一键安装（venv/计划任务/防火墙/关睡眠）
├── tools\snapshot.py            抓源站样本到 tests/fixtures（接入与修源用）
├── tests\                       pytest 测试 + fixtures 离线样本
├── data\                        运行时生成（gitignore）：news.db、web.pid、backup\
├── logs\                        运行时生成（gitignore）
├── requirements.txt
├── README.md                    中文运维文档
└── 安装.bat                     可选一行转发（调 python scripts\install.py）
```

---

## Task 1: 项目骨架 + 配置加载 + 数据库

**Files:**
- Create: `.gitignore`, `requirements.txt`, `config/settings.yaml`, `config/tags.yaml`
- Create: `crawler/__init__.py`, `crawler/config.py`, `db/schema.sql`, `crawler/store.py`
- Create: `tests/__init__.py`, `tests/conftest.py`, `tests/test_config_store.py`

**Interfaces:**
- Consumes: 无（首个任务）
- Produces:
  - `crawler.config.Settings`（字段：port, summary_max_chars, dedup_threshold, request_timeout, request_retries, request_interval, db_path, data_dir, logs_dir）
  - `crawler.config.load_settings(path=None) -> Settings`、`load_tags(path=None) -> dict`、`load_sources(sources_dir=None) -> list[dict]`
  - `crawler.store.now_iso() -> str`、`connect(db_path) -> sqlite3.Connection`、`init_db(conn)`、`upsert_source(conn, key, name, board, url, enabled)`、`start_crawl_run(conn, source_key) -> int`、`finish_crawl_run(conn, run_id, status, found, new, error="")`、`url_exists(conn, url_hash) -> bool`、`find_recent_titles(conn, days=3) -> list[sqlite3.Row]`（含 id/title/cluster_id）、`insert_article(conn, item, classification, url_hash, title_hash, cluster_id=None, is_primary=1) -> int`、`upsert_prices(conn, rows) -> int`

- [ ] **Step 1: 写骨架文件**

`.gitignore`:
```
.venv/
__pycache__/
*.pyc
.pytest_cache/
data/
logs/
.superpowers/
```

`requirements.txt`:
```
requests>=2.31
beautifulsoup4>=4.12
lxml>=5.2
PyYAML>=6.0
fastapi>=0.110
uvicorn>=0.29
jinja2>=3.1
pytest>=8.0
httpx>=0.27
```

`config/settings.yaml`:
```yaml
port: 8080
summary_max_chars: 200
dedup_threshold: 0.85
request_timeout: 15
request_retries: 2
request_interval: 1.5
```

`config/tags.yaml`:
```yaml
minerals:
  煤炭: [煤炭, 煤价, 煤企, 煤矿, 煤矸石, 选煤, 洗煤, 动力煤, 炼焦煤, 主焦煤, 焦煤, 焦炭, 无烟煤]
  铁矿石: [铁矿石, 铁矿, 铁精粉, 铁精矿, 赤铁矿, 磁铁矿, 球团矿]
  铜: [铜矿, 铜精矿, 电解铜, 铜价, 阴极铜]
  铅锌: [铅锌, 铅矿, 锌矿, 铅精矿, 锌精矿, 锌锭, 铅锭]
  金: [金矿, 黄金, 金价, 金精矿, 合质金]
  银: [银矿, 白银, 银价, 银精矿]
  锰: [锰矿, 锰硅, 硅锰, 电解锰, 富锰渣]
  钨: [钨矿, 黑钨, 白钨, 钨精矿, 仲钨酸铵]
  钼: [钼矿, 钼精矿, 钼铁]
  锑: [锑矿, 锑锭, 锑价, 三氧化二锑]
  锡: [锡矿, 锡锭, 锡价, 焊锡]
  磷矿: [磷矿, 磷矿石, 磷化工, 磷肥, 磷酸, 黄磷]
  萤石: [萤石, 氟化钙, 氢氟酸, 氟化工]
  石英砂: [石英砂, 石英石, 硅砂, 高纯石英]
  滑石: [滑石, 滑石粉]
  长石: [长石, 钾长石, 钠长石]
  高岭土: [高岭土, 瓷土, 砂质高岭土]
types:
  政策: [通知, 公告, 办法, 条例, 规划, 意见, 方案, 整治, 督察, 审批, 矿业权, 采矿权, 探矿权, 资源税, 修订, 征求意见]
  安全: [事故, 安全事故, 坍塌, 透水, 瓦斯, 停产整顿, 安全监察, 隐患排查]
  价格: [价格, 报价, 行情, 上调, 下调, 上涨, 下跌, 涨价, 跌价, 涨跌]
  技术: [XRT, 智能分选, 色选, 射线分选, 光电分选, 抛废, 干选, 干法分选, 预选, 排矸, 算法]
  企业: [投产, 扩产, 中标, 签约, 合作, 收购, 重组, 上市, 项目开工, 竣工验收]
  市场: [需求, 供应, 库存, 产能, 产量, 进口, 出口, 订单]
regions: [河北, 唐山, 山西, 内蒙古, 山东, 云南, 黑龙江, 湖南, 广西, 新疆, 青海, 贵州, 四川, 蒙古, 赞比亚]
```

- [ ] **Step 2: 写失败测试**

`tests/conftest.py`:
```python
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
```

`tests/test_config_store.py`:
```python
from crawler import config, store


def test_load_settings_overrides(tmp_path):
    p = tmp_path / "settings.yaml"
    p.write_text("port: 9000\nsummary_max_chars: 150\n", encoding="utf-8")
    s = config.load_settings(p)
    assert s.port == 9000
    assert s.summary_max_chars == 150
    assert s.dedup_threshold == 0.85
    assert s.db_path.name == "news.db"


def test_load_tags_has_minerals():
    tags = config.load_tags()
    assert "磷矿" in tags["minerals"]
    assert "政策" in tags["types"]
    assert "河北" in tags["regions"]


def test_load_sources_defaults(tmp_path):
    d = tmp_path / "sources"
    d.mkdir()
    (d / "a.yaml").write_text("name: 甲\nboard: news\nurl: http://e.com\n", encoding="utf-8")
    srcs = config.load_sources(d)
    assert len(srcs) == 1
    assert srcs[0]["key"] == "a"
    assert srcs[0]["enabled"] is True


def test_runs_and_articles(tmp_path):
    conn = store.connect(tmp_path / "t.db")
    store.init_db(conn)
    store.upsert_source(conn, "a", "甲", "news", "http://e.com", True)
    run_id = store.start_crawl_run(conn, "a")
    store.finish_crawl_run(conn, run_id, "ok", 10, 3)
    row = conn.execute("SELECT * FROM crawl_runs").fetchone()
    assert row["status"] == "ok"
    assert row["items_found"] == 10

    item = {"url": "http://e.com/1", "title": "标题一", "summary": "", "source_key": "a", "published_at": ""}
    cls = {"board": "news", "minerals": ["铜"], "regions": [], "types": []}
    aid = store.insert_article(conn, item, cls, "uh1", "th1")
    art = conn.execute("SELECT * FROM articles WHERE id=?", (aid,)).fetchone()
    assert art["cluster_id"] is not None
    assert art["is_primary"] == 1
    assert store.url_exists(conn, "uh1") is True
    assert len(store.find_recent_titles(conn, days=3)) == 1


def test_upsert_prices_dedups(tmp_path):
    conn = store.connect(tmp_path / "t.db")
    store.init_db(conn)
    row = {"commodity": "铜", "price_type": "期货", "value": 70000.0, "unit": "元/吨",
           "price_date": "2026-09-15", "source_key": "sina", "raw_label": "cu2610",
           "change": 100.0, "change_pct": 0.14, "fetched_at": store.now_iso()}
    assert store.upsert_prices(conn, [row]) == 1
    row["value"] = 70100.0
    assert store.upsert_prices(conn, [row]) == 1
    assert conn.execute("SELECT COUNT(*) c FROM prices").fetchone()["c"] == 1
    assert conn.execute("SELECT value FROM prices").fetchone()["value"] == 70100.0
```

- [ ] **Step 3: 运行测试确认失败**

Run: `python -m pytest tests/test_config_store.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'crawler'`）

- [ ] **Step 4: 实现 config.py / schema.sql / store.py**

`crawler/__init__.py`: 空文件。

`crawler/config.py`:
```python
from dataclasses import dataclass
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    port: int
    summary_max_chars: int
    dedup_threshold: float
    request_timeout: int
    request_retries: int
    request_interval: float
    db_path: Path
    data_dir: Path
    logs_dir: Path


def _data_dir() -> Path:
    d = ROOT / "data"
    d.mkdir(exist_ok=True)
    return d


def _logs_dir() -> Path:
    d = ROOT / "logs"
    d.mkdir(exist_ok=True)
    return d


def load_settings(path=None) -> Settings:
    p = Path(path) if path else ROOT / "config" / "settings.yaml"
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    data_dir = _data_dir()
    return Settings(
        port=int(raw.get("port", 8080)),
        summary_max_chars=int(raw.get("summary_max_chars", 200)),
        dedup_threshold=float(raw.get("dedup_threshold", 0.85)),
        request_timeout=int(raw.get("request_timeout", 15)),
        request_retries=int(raw.get("request_retries", 2)),
        request_interval=float(raw.get("request_interval", 1.5)),
        db_path=data_dir / "news.db",
        data_dir=data_dir,
        logs_dir=_logs_dir(),
    )


def load_tags(path=None) -> dict:
    p = Path(path) if path else ROOT / "config" / "tags.yaml"
    return yaml.safe_load(p.read_text(encoding="utf-8"))


def load_sources(sources_dir=None) -> list:
    d = Path(sources_dir) if sources_dir else ROOT / "config" / "sources"
    sources = []
    for f in sorted(d.glob("*.yaml")):
        cfg = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        cfg.setdefault("key", f.stem)
        cfg.setdefault("enabled", True)
        sources.append(cfg)
    return sources
```

`db/schema.sql`:
```sql
CREATE TABLE IF NOT EXISTS sources (
  key TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  board TEXT NOT NULL,
  url TEXT NOT NULL,
  enabled INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS articles (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  url TEXT NOT NULL,
  url_hash TEXT NOT NULL UNIQUE,
  title TEXT NOT NULL,
  title_hash TEXT NOT NULL,
  summary TEXT NOT NULL DEFAULT '',
  source_key TEXT NOT NULL,
  board TEXT NOT NULL,
  minerals TEXT NOT NULL DEFAULT '[]',
  regions TEXT NOT NULL DEFAULT '[]',
  types TEXT NOT NULL DEFAULT '[]',
  published_at TEXT NOT NULL DEFAULT '',
  fetched_at TEXT NOT NULL,
  cluster_id INTEGER,
  is_primary INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_articles_fetched ON articles(fetched_at DESC);
CREATE INDEX IF NOT EXISTS idx_articles_board ON articles(board);
CREATE INDEX IF NOT EXISTS idx_articles_title_hash ON articles(title_hash);
CREATE INDEX IF NOT EXISTS idx_articles_cluster ON articles(cluster_id);

CREATE TABLE IF NOT EXISTS article_clusters (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  primary_article_id INTEGER NOT NULL,
  member_count INTEGER NOT NULL DEFAULT 1,
  last_seen TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS prices (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  commodity TEXT NOT NULL,
  price_type TEXT NOT NULL,
  value REAL NOT NULL,
  unit TEXT NOT NULL DEFAULT '',
  change REAL,
  change_pct REAL,
  price_date TEXT NOT NULL,
  source_key TEXT NOT NULL,
  raw_label TEXT NOT NULL DEFAULT '',
  fetched_at TEXT NOT NULL,
  UNIQUE(commodity, price_type, price_date, source_key)
);
CREATE INDEX IF NOT EXISTS idx_prices_commodity ON prices(commodity, price_date DESC);

CREATE TABLE IF NOT EXISTS crawl_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source_key TEXT NOT NULL,
  started_at TEXT NOT NULL,
  finished_at TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'running',
  items_found INTEGER NOT NULL DEFAULT 0,
  items_new INTEGER NOT NULL DEFAULT 0,
  error TEXT NOT NULL DEFAULT ''
);

CREATE VIRTUAL TABLE IF NOT EXISTS articles_fts USING fts5(
  title, summary,
  content='articles', content_rowid='id',
  tokenize='trigram'
);
CREATE TRIGGER IF NOT EXISTS articles_ai AFTER INSERT ON articles BEGIN
  INSERT INTO articles_fts(rowid, title, summary) VALUES (new.id, new.title, new.summary);
END;
CREATE TRIGGER IF NOT EXISTS articles_ad AFTER DELETE ON articles BEGIN
  INSERT INTO articles_fts(articles_fts, rowid, title, summary) VALUES ('delete', old.id, old.title, old.summary);
END;
CREATE TRIGGER IF NOT EXISTS articles_au AFTER UPDATE ON articles BEGIN
  INSERT INTO articles_fts(articles_fts, rowid, title, summary) VALUES ('delete', old.id, old.title, old.summary);
  INSERT INTO articles_fts(rowid, title, summary) VALUES (new.id, new.title, new.summary);
END;
```

`crawler/store.py`:
```python
import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

SCHEMA = Path(__file__).resolve().parent.parent / "db" / "schema.sql"


def now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def connect(db_path):
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(conn) -> None:
    conn.executescript(SCHEMA.read_text(encoding="utf-8"))
    conn.commit()


def upsert_source(conn, key, name, board, url, enabled=True) -> None:
    conn.execute(
        "INSERT INTO sources(key,name,board,url,enabled) VALUES(?,?,?,?,?) "
        "ON CONFLICT(key) DO UPDATE SET name=excluded.name, board=excluded.board, url=excluded.url, enabled=excluded.enabled",
        (key, name, board, url, 1 if enabled else 0),
    )
    conn.commit()


def start_crawl_run(conn, source_key) -> int:
    cur = conn.execute(
        "INSERT INTO crawl_runs(source_key,started_at,status) VALUES(?,?,?)",
        (source_key, now_iso(), "running"),
    )
    conn.commit()
    return cur.lastrowid


def finish_crawl_run(conn, run_id, status, found, new, error="") -> None:
    conn.execute(
        "UPDATE crawl_runs SET finished_at=?,status=?,items_found=?,items_new=?,error=? WHERE id=?",
        (now_iso(), status, int(found), int(new), error, run_id),
    )
    conn.commit()


def url_exists(conn, url_hash) -> bool:
    return conn.execute("SELECT 1 FROM articles WHERE url_hash=?", (url_hash,)).fetchone() is not None


def find_recent_titles(conn, days=3):
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    return conn.execute(
        "SELECT id,title,cluster_id FROM articles WHERE fetched_at>=? ORDER BY id DESC", (cutoff,)
    ).fetchall()


def insert_article(conn, item, classification, url_hash, title_hash, cluster_id=None, is_primary=1) -> int:
    cur = conn.execute(
        "INSERT INTO articles(url,url_hash,title,title_hash,summary,source_key,board,minerals,regions,types,"
        "published_at,fetched_at,cluster_id,is_primary) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            item["url"], url_hash, item["title"], title_hash, item.get("summary", ""),
            item["source_key"], classification["board"],
            json.dumps(classification.get("minerals", []), ensure_ascii=False),
            json.dumps(classification.get("regions", []), ensure_ascii=False),
            json.dumps(classification.get("types", []), ensure_ascii=False),
            item.get("published_at", ""), item.get("fetched_at", now_iso()),
            cluster_id, 1 if is_primary else 0,
        ),
    )
    aid = cur.lastrowid
    if cluster_id is None:
        cur2 = conn.execute(
            "INSERT INTO article_clusters(primary_article_id,member_count,last_seen) VALUES(?,1,?)",
            (aid, now_iso()),
        )
        conn.execute("UPDATE articles SET cluster_id=? WHERE id=?", (cur2.lastrowid, aid))
    else:
        conn.execute(
            "UPDATE article_clusters SET member_count=member_count+1,last_seen=? WHERE id=?",
            (now_iso(), cluster_id),
        )
    conn.commit()
    return aid


UPSERT_PRICE_SQL = (
    "INSERT INTO prices(commodity,price_type,value,unit,change,change_pct,price_date,source_key,raw_label,fetched_at) "
    "VALUES(?,?,?,?,?,?,?,?,?,?) "
    "ON CONFLICT(commodity,price_type,price_date,source_key) DO UPDATE SET "
    "value=excluded.value,unit=excluded.unit,change=excluded.change,change_pct=excluded.change_pct,"
    "raw_label=excluded.raw_label,fetched_at=excluded.fetched_at"
)


def upsert_prices(conn, rows) -> int:
    count = 0
    for r in rows:
        conn.execute(
            UPSERT_PRICE_SQL,
            (
                r["commodity"], r["price_type"], float(r["value"]), r.get("unit", ""),
                r.get("change"), r.get("change_pct"), r["price_date"], r["source_key"],
                r.get("raw_label", ""), r.get("fetched_at", now_iso()),
            ),
        )
        count += 1
    conn.commit()
    return count
```

- [ ] **Step 5: 运行测试确认通过**

Run: `python -m pytest tests/test_config_store.py -v`
Expected: 5 passed

- [ ] **Step 6: 提交**

```bash
git add -A
git commit -m "feat: 项目骨架/配置加载/SQLite 存储与 FTS5"
```

---

## Task 2: HTTP 抓取层 + 失败快照 + 样本工具

**Files:**
- Create: `crawler/fetch.py`, `crawler/report.py`, `tools/__init__.py`, `tools/snapshot.py`
- Test: `tests/test_fetch_report.py`

**Interfaces:**
- Consumes: `crawler.config.load_sources`
- Produces:
  - `crawler.fetch.FetchResult`（ok, status, text, final_url, error, elapsed）
  - `crawler.fetch.fetch(url, referer="", encoding=None, timeout=15, retries=2, session=None, sleep=time.sleep) -> FetchResult`
  - `crawler.report.log(message, name="crawler")`、`save_snapshot(source_key, text, directory=None) -> Path`、`prune_snapshots(source_key, keep=3, directory=None)`
  - 源 YAML 支持字段：`referer`、`encoding`、`timeout`、`fixture_ext`（快照扩展名，默认 html）

- [ ] **Step 1: 写失败测试**

`tests/test_fetch_report.py`:
```python
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
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_fetch_report.py -v`
Expected: FAIL（`No module named 'crawler.fetch'`）

- [ ] **Step 3: 实现 fetch.py / report.py / tools/snapshot.py**

`crawler/fetch.py`:
```python
import time
from dataclasses import dataclass

import requests

DEFAULT_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
RETRY_STATUS = (429, 500, 502, 503, 504)


@dataclass
class FetchResult:
    ok: bool
    status: int = 0
    text: str = ""
    final_url: str = ""
    error: str = ""
    elapsed: float = 0.0


def fetch(url, referer="", encoding=None, timeout=15, retries=2, session=None, sleep=time.sleep):
    sess = session or requests.Session()
    headers = {"User-Agent": DEFAULT_UA}
    if referer:
        headers["Referer"] = referer
    result = FetchResult(ok=False, final_url=url)
    for attempt in range(retries + 1):
        started = time.time()
        try:
            resp = sess.get(url, headers=headers, timeout=timeout, allow_redirects=True)
            result.status = resp.status_code
            result.final_url = resp.url
            if encoding:
                result.text = resp.content.decode(encoding, errors="replace")
            else:
                result.text = resp.text
            result.elapsed = round(time.time() - started, 3)
            if resp.status_code in RETRY_STATUS and attempt < retries:
                result.error = f"HTTP {resp.status_code}"
                sleep(2 ** attempt)
                continue
            result.ok = resp.status_code < 400
            if not result.ok:
                result.error = f"HTTP {resp.status_code}"
            return result
        except requests.RequestException as e:
            result.error = f"{type(e).__name__}: {e}"
            result.elapsed = round(time.time() - started, 3)
            if attempt < retries:
                sleep(2 ** attempt)
                continue
            return result
    return result
```

`crawler/report.py`:
```python
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def logs_dir() -> Path:
    d = ROOT / "logs"
    d.mkdir(exist_ok=True)
    return d


def snapshots_dir() -> Path:
    d = logs_dir() / "snapshots"
    d.mkdir(exist_ok=True)
    return d


def log(message: str, name: str = "crawler") -> None:
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}"
    path = logs_dir() / f"{name}_{datetime.now().strftime('%Y%m%d')}.log"
    with path.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
    print(line)


def save_snapshot(source_key: str, text: str, directory=None) -> Path:
    d = Path(directory) if directory else snapshots_dir()
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{source_key}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
    path.write_text(text or "", encoding="utf-8")
    return path


def prune_snapshots(source_key: str, keep: int = 3, directory=None) -> None:
    d = Path(directory) if directory else snapshots_dir()
    files = sorted(d.glob(f"{source_key}_*.html"))
    drop = files[:-keep] if keep > 0 else files
    for f in drop:
        f.unlink()
```

`tools/__init__.py`: 空文件。

`tools/snapshot.py`:
```python
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from crawler.config import load_sources
from crawler.fetch import fetch


def main():
    if len(sys.argv) < 2:
        print("用法: python -m tools.snapshot <source_key> [--url 覆盖地址]")
        raise SystemExit(1)
    key = sys.argv[1]
    override = sys.argv[sys.argv.index("--url") + 1] if "--url" in sys.argv else None
    match = [s for s in load_sources() if s["key"] == key]
    if not match:
        print(f"未找到源: {key}")
        raise SystemExit(1)
    src = match[0]
    urls = [override] if override else (src.get("urls") or [src["url"]])
    out_dir = ROOT / "tests" / "fixtures"
    out_dir.mkdir(parents=True, exist_ok=True)
    ext = src.get("fixture_ext", "html")
    for index, url in enumerate(urls):
        result = fetch(url, referer=src.get("referer", ""), encoding=src.get("encoding"),
                       timeout=src.get("timeout", 15))
        suffix = "" if index == 0 else f"_{index + 1}"
        out = out_dir / f"{key}_list{suffix}.{ext}"
        out.write_text(result.text, encoding="utf-8")
        print(f"ok={result.ok} status={result.status} bytes={len(result.text)} -> {out}")
        if not result.ok:
            print(f"error: {result.error}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_fetch_report.py -v`
Expected: 5 passed

- [ ] **Step 5: 提交**

```bash
git add -A
git commit -m "feat: HTTP 抓取层/失败快照/源站样本工具"
```

---

## Task 3: 通用列表解析

**Files:**
- Create: `crawler/parse.py`
- Test: `tests/test_parse.py`

**Interfaces:**
- Consumes: 无
- Produces:
  - `crawler.parse.ParsedItem`（title, url, published_at, summary）
  - `crawler.parse.parse_date(text) -> str`（ISO `YYYY-MM-DD` 或 `""`）
  - `crawler.parse.absolutize(base_url, href) -> str`
  - `crawler.parse.parse_list(html, cfg, base_url) -> list[ParsedItem]`；`cfg` 结构：`{"list": {"item": CSS, "title": CSS, "link": CSS 可选, "date": CSS 可选, "date_regex": 可选}}`
  - `crawler.parse.extract_summary(html, cfg, max_chars) -> str`；`cfg["detail"]["content"]` 为正文 CSS 选择器

- [ ] **Step 1: 写失败测试**

`tests/test_parse.py`:
```python
from crawler.parse import ParsedItem, absolutize, extract_summary, parse_date, parse_list

LIST_HTML = """
<html><body>
<ul class="list">
  <li><a href="/x/202609/t20260915_1.html">河北开展磷矿安全生产整治</a><span class="date">2026-09-15</span></li>
  <li><a href="http://e.com/x/2.html">关于开展矿山安全监察的通知</a><span class="date">2026年9月14日</span></li>
  <li><a href="/x/3.html">铜价近日震荡上行</a><span class="date">[20260913]</span></li>
  <li><a href="/x/4.html">萤石市场周报</a><span class="date">09-12</span></li>
  <li><a href="/x/5.html">无日期的普通新闻</a><span class="date">暂无</span></li>
</ul>
</body></html>
"""

CFG = {"list": {"item": "ul.list li", "title": "a", "date": "span.date"}}


def test_parse_list_basic():
    items = parse_list(LIST_HTML, CFG, "https://www.mnr.gov.cn/dt/ywbb/")
    assert len(items) == 5
    assert isinstance(items[0], ParsedItem)
    assert items[0].title == "河北开展磷矿安全生产整治"
    assert items[0].url == "https://www.mnr.gov.cn/x/202609/t20260915_1.html"
    assert items[1].url == "http://e.com/x/2.html"


def test_parse_list_dates():
    items = parse_list(LIST_HTML, CFG, "https://www.mnr.gov.cn/")
    assert items[0].published_at == "2026-09-15"
    assert items[1].published_at == "2026-09-14"
    assert items[2].published_at == "2026-09-13"
    assert items[3].published_at.endswith("-09-12")
    assert items[4].published_at == ""


def test_parse_date_variants():
    assert parse_date("2026/09/15") == "2026-09-15"
    assert parse_date("2026年9月5日") == "2026-09-05"
    assert parse_date("t20260915_16.html") == "2026-09-15"
    assert parse_date("12345.67") == ""
    assert parse_date("") == ""


def test_absolutize():
    assert absolutize("https://a.com/b/", "/c/d.html") == "https://a.com/c/d.html"
    assert absolutize("https://a.com/b/", "https://x.com/y") == "https://x.com/y"
    assert absolutize("https://a.com/b/", "javascript:void(0)") == ""


DETAIL_HTML = """
<html><body><div class="nav">导航</div>
<div class="article"><script>bad()</script>
  近日，河北省自然资源厅印发通知，部署开展磷矿安全生产专项整治工作，
  对全省磷矿开采企业开展全覆盖检查，重点排查边坡、尾矿库等风险隐患。
</div></body></html>
"""


def test_extract_summary_truncates_and_collapses():
    cfg = {"detail": {"content": "div.article"}}
    s = extract_summary(DETAIL_HTML, cfg, max_chars=40)
    assert "河北省自然资源厅" in s
    assert "bad()" not in s
    assert s.endswith("…")
    assert len(s) <= 41


def test_extract_summary_without_selector():
    s = extract_summary("<html><body><p>正文一句话</p></body></html>", {}, max_chars=200)
    assert s == "正文一句话"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_parse.py -v`
Expected: FAIL（`No module named 'crawler.parse'`）

- [ ] **Step 3: 实现 parse.py**

`crawler/parse.py`:
```python
import re
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urljoin

from bs4 import BeautifulSoup

YMD = re.compile(r"(\d{4})\D{0,2}(\d{1,2})\D{0,2}(\d{1,2})")
MD = re.compile(r"(?<!\d)(\d{1,2})-(\d{1,2})(?!\d)")


@dataclass
class ParsedItem:
    title: str
    url: str
    published_at: str = ""
    summary: str = ""


def _ymd_valid(y, mo, d) -> str:
    y, mo, d = int(y), int(mo), int(d)
    if not (1990 <= y <= 2100 and 1 <= mo <= 12 and 1 <= d <= 31):
        return ""
    return f"{y:04d}-{mo:02d}-{d:02d}"


def parse_date(text: str) -> str:
    text = (text or "").strip()
    if not text:
        return ""
    for m in YMD.finditer(text):
        got = _ymd_valid(*m.groups())
        if got:
            return got
    m = MD.search(text)
    if m:
        mo, d = int(m.group(1)), int(m.group(2))
        if 1 <= mo <= 12 and 1 <= d <= 31:
            return f"{datetime.now().year:04d}-{mo:02d}-{d:02d}"
    return ""


def absolutize(base_url: str, href: str) -> str:
    href = (href or "").strip()
    if not href or href.lower().startswith(("javascript:", "#")):
        return ""
    return urljoin(base_url, href)


def parse_list(html: str, cfg: dict, base_url: str) -> list:
    lst = cfg.get("list") or {}
    item_sel = lst.get("item")
    if not item_sel:
        raise ValueError("源配置缺少 list.item 选择器")
    soup = BeautifulSoup(html, "lxml")
    items = []
    for node in soup.select(item_sel):
        el = node.select_one(lst["title"]) if lst.get("title") else node
        if el is None:
            continue
        title = el.get_text(" ", strip=True)
        if not title:
            continue
        if lst.get("link"):
            a = node.select_one(lst["link"])
        elif el.name == "a":
            a = el
        else:
            a = node.find("a")
        href = a.get("href", "") if a is not None else ""
        url = absolutize(base_url, href)
        if not url:
            continue
        published_at = ""
        if lst.get("date"):
            dnode = node.select_one(lst["date"])
            if dnode is not None:
                published_at = parse_date(dnode.get_text(" ", strip=True))
        if not published_at and lst.get("date_regex"):
            m = re.search(lst["date_regex"], href) or re.search(lst["date_regex"], node.get_text(" ", strip=True))
            if m:
                published_at = parse_date("".join(g for g in m.groups() if g))
        items.append(ParsedItem(title=title, url=url, published_at=published_at))
    return items


def extract_summary(html: str, cfg: dict, max_chars: int) -> str:
    soup = BeautifulSoup(html, "lxml")
    selector = (cfg.get("detail") or {}).get("content")
    node = soup.select_one(selector) if selector else soup.body
    if node is None:
        return ""
    for bad in node.select("script,style,nav,footer,header"):
        bad.decompose()
    text = re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip()
    if len(text) > max_chars:
        text = text[:max_chars].rstrip() + "…"
    return text
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_parse.py -v`
Expected: 7 passed

- [ ] **Step 5: 提交**

```bash
git add -A
git commit -m "feat: 通用列表解析与日期/摘要处理"
```

---

## Task 4: 分类打标 + 三层去重

**Files:**
- Create: `crawler/classify.py`, `crawler/dedup.py`
- Test: `tests/test_classify_dedup.py`

**Interfaces:**
- Consumes: `crawler.store`（url_exists / find_recent_titles / insert_article）
- Produces:
  - `crawler.classify.classify(title, summary, source_board, tags) -> {"board","minerals","regions","types"}`
  - `crawler.classify.detect_keywords(text, mapping) -> list[str]`
  - `crawler.dedup.normalize_url(url) -> str`、`normalize_title(title) -> str`、`core_title(title) -> str`、`title_hash(title) -> str`、`similarity(a, b) -> float`
  - `crawler.dedup.submit_item(conn, item, threshold=0.85) -> "new" | "merged" | "skipped"`；`item` 必须含 `url/title/summary/source_key/published_at/classification`

- [ ] **Step 1: 写失败测试**

`tests/test_classify_dedup.py`:
```python
from crawler import config, dedup, store
from crawler.classify import classify


def _tags():
    return config.load_tags()


def test_classify_example_from_spec():
    cls = classify("河北开展磷矿安全生产整治", "部署开展专项整治工作", "policy", _tags())
    assert cls["board"] == "policy"
    assert "磷矿" in cls["minerals"]
    assert "河北" in cls["regions"]
    assert "政策" in cls["types"]


def test_classify_tech_news():
    cls = classify("XRT 智能分选机在钨矿投用", "", "news", _tags())
    assert "钨" in cls["minerals"]
    assert "技术" in cls["types"]


def test_normalize_url_strips_tracking():
    a = dedup.normalize_url("https://e.com/a?utm_source=x&id=1#frag")
    assert a == "https://e.com/a?id=1"


def test_core_title_strips_decoration():
    assert dedup.core_title("【转载】铜价上涨（附全文）") == "铜价上涨"
    assert dedup.normalize_title("河北：磷矿，2026！") == "河北磷矿2026"


def test_similarity_edges():
    assert dedup.similarity("河北开展磷矿安全生产整治", "河北开展磷矿安全生产整治") == 1.0
    assert dedup.similarity("河北开展磷矿安全生产整治", "河北开展磷矿安全生产整治（附全文）") >= 0.85
    assert dedup.similarity("河北开展磷矿安全生产整治", "云南铜矿项目投产") < 0.2


def _article(url, title):
    return {"url": url, "title": title, "summary": "", "source_key": "a",
            "published_at": "", "classification": {"board": "news", "minerals": [], "regions": [], "types": []}}


def test_submit_item_three_outcomes(tmp_path):
    conn = store.connect(tmp_path / "t.db")
    store.init_db(conn)
    assert dedup.submit_item(conn, _article("https://e.com/1?utm_source=x", "河北开展磷矿安全生产整治")) == "new"
    assert dedup.submit_item(conn, _article("https://e.com/1", "完全一样标题不应重复")) == "skipped"
    assert dedup.submit_item(conn, _article("https://e.com/2", "河北开展磷矿安全生产整治（附全文）")) == "merged"
    row = conn.execute("SELECT member_count FROM article_clusters").fetchone()
    assert row["member_count"] == 2
    assert conn.execute("SELECT COUNT(*) c FROM articles").fetchone()["c"] == 2
    assert dedup.submit_item(conn, _article("https://e.com/3", "云南铜矿项目投产")) == "new"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_classify_dedup.py -v`
Expected: FAIL（`No module named 'crawler.classify'`）

- [ ] **Step 3: 实现 classify.py 与 dedup.py**

`crawler/classify.py`:
```python
def detect_keywords(text: str, mapping: dict) -> list:
    hits = []
    for key, words in mapping.items():
        if any(w in text for w in words):
            hits.append(key)
    return hits


def classify(title: str, summary: str, source_board: str, tags: dict) -> dict:
    text = f"{title} {summary or ''}"
    regions_map = {r: [r] for r in tags.get("regions", [])}
    return {
        "board": source_board,
        "minerals": detect_keywords(text, tags.get("minerals", {})),
        "regions": detect_keywords(text, regions_map),
        "types": detect_keywords(text, tags.get("types", {})),
    }
```

`crawler/dedup.py`:
```python
import hashlib
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from crawler import store

TRACKING = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
            "spm", "share_token", "from"}
DECOR = [
    re.compile(r"^[【\[][^】\]]{1,12}[】\]]"),
    re.compile(r"[（(][^）)]{0,20}[）)]$"),
    re.compile(r"^[|｜\-—\s]+|[|｜\-—\s]+$"),
]


def normalize_url(url: str) -> str:
    parts = urlsplit((url or "").strip())
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
             if k.lower() not in TRACKING]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))


def normalize_title(title: str) -> str:
    return re.sub(r"[\W_]+", "", title or "", flags=re.UNICODE).lower()


def core_title(title: str) -> str:
    t = (title or "").strip()
    for _ in range(2):
        for pat in DECOR:
            new = pat.sub("", t).strip()
            if new:
                t = new
    return t


def title_hash(title: str) -> str:
    return hashlib.sha1(normalize_title(title).encode("utf-8")).hexdigest()[:16]


def trigrams(text: str) -> set:
    s = normalize_title(text)
    if not s:
        return set()
    if len(s) < 3:
        return {s}
    return {s[i:i + 3] for i in range(len(s) - 2)}


def _jaccard(a: str, b: str) -> float:
    ta, tb = trigrams(a), trigrams(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def similarity(a: str, b: str) -> float:
    pairs = ((a, b), (core_title(a), b), (a, core_title(b)), (core_title(a), core_title(b)))
    return max(_jaccard(x, y) for x, y in pairs)


def submit_item(conn, item: dict, threshold: float = 0.85) -> str:
    url_hash = hashlib.sha1(normalize_url(item["url"]).encode("utf-8")).hexdigest()
    if store.url_exists(conn, url_hash):
        return "skipped"
    th = title_hash(item["title"])
    for row in store.find_recent_titles(conn, days=3):
        if title_hash(row["title"]) == th or similarity(row["title"], item["title"]) >= threshold:
            store.insert_article(conn, item, item["classification"], url_hash, th,
                                 cluster_id=row["cluster_id"], is_primary=0)
            return "merged"
    store.insert_article(conn, item, item["classification"], url_hash, th)
    return "new"
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_classify_dedup.py -v`
Expected: 7 passed

- [ ] **Step 5: 提交**

```bash
git add -A
git commit -m "feat: 关键词分类与三层去重"
```

---

## Task 5: 价格解析器（期货组）

**Files:**
- Create: `crawler/price_sources.py`
- Create: `config/sources/sina_futures.yaml`, `config/sources/eastmoney_futures.yaml`, `config/sources/shfe.yaml`
- Test: `tests/test_price_sources.py`, `tests/fixtures/eastmoney_futures_list.json`, `tests/fixtures/shfe_list.json`（手工构造）；`tests/fixtures/sina_futures_list.txt`（用 tools.snapshot 抓真实样本）
- `sina_futures.yaml` 增加字段：`fixture_ext: txt`；`eastmoney_futures.yaml`/`shfe.yaml` 增加：`fixture_ext: json`

**Interfaces:**
- Consumes: `crawler.parse.parse_date`
- Produces:
  - `crawler.price_sources.parse_futures_sina(text, cfg) -> list[dict]`
  - `crawler.price_sources.parse_futures_eastmoney(text, cfg) -> list[dict]`
  - `crawler.price_sources.parse_shfe_daily(text, cfg) -> list[dict]`
  - `crawler.price_sources.parse(parser, text, cfg) -> list[dict]`；行字段：`commodity, price_type, value, unit, change, change_pct, price_date, source_key, raw_label, fetched_at`

- [ ] **Step 1: 写失败测试 + 构造 JSON 样本**

`tests/fixtures/eastmoney_futures_list.json`:
```json
{"data": {"diff": [
  {"f12": "JM0", "f14": "焦煤连续", "f2": 2105, "f3": -1.2, "f4": -25},
  {"f12": "CU0", "f14": "沪铜连续", "f2": 71230, "f3": 0.35, "f4": 250}
]}}
```

`tests/fixtures/shfe_list.json`:
```json
{"o_curinstrument": [
  {"PRODUCTID": "cu", "DELIVERYMONTH": "2609", "CLOSEPRICE": 71000, "OPENINTEREST": 1200},
  {"PRODUCTID": "cu", "DELIVERYMONTH": "2610", "CLOSEPRICE": 71250, "OPENINTEREST": 5800},
  {"PRODUCTID": "pb", "DELIVERYMONTH": "2610", "CLOSEPRICE": 16800, "OPENINTEREST": 900},
  {"PRODUCTID": "xx", "DELIVERYMONTH": "2610", "CLOSEPRICE": 1, "OPENINTEREST": 9999}
]}
```

`tests/test_price_sources.py`:
```python
import json
import re
from pathlib import Path

import pytest

from crawler import price_sources

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _cfg(key, **kw):
    base = {"key": key, "board": "price", "unit": "元/吨", "price_type": "期货"}
    base.update(kw)
    return base


def test_sina_futures_real_sample():
    text = (FIXTURES / "sina_futures_list.txt").read_text(encoding="utf-8")
    cfg = _cfg("sina_futures",
               field_map={"name": 0, "last": 8, "prev_settle": 10},
               commodity_map={"JM0": "焦煤", "J0": "焦炭", "I0": "铁矿石", "CU0": "铜",
                              "AL0": "铝", "ZN0": "锌", "PB0": "铅", "SN0": "锡",
                              "AU0": "黄金", "AG0": "白银", "SM0": "锰硅", "SF0": "硅铁"})
    rows = price_sources.parse_futures_sina(text, cfg)
    assert len(rows) >= 8
    assert all(r["value"] > 0 for r in rows)
    assert all(re.match(r"^\d{4}-\d{2}-\d{2}$", r["price_date"]) for r in rows)
    assert {r["commodity"] for r in rows} <= set(cfg["commodity_map"].values())


def test_eastmoney_futures_contract():
    text = (FIXTURES / "eastmoney_futures_list.json").read_text(encoding="utf-8")
    cfg = _cfg("eastmoney_futures",
               field_map={"name": "f14", "last": "f2", "change": "f4", "change_pct": "f3"},
               commodity_map={"焦煤连续": "焦煤", "沪铜连续": "铜"})
    rows = price_sources.parse_futures_eastmoney(text, cfg)
    assert len(rows) == 2
    assert rows[0]["value"] == 2105
    assert rows[0]["change"] == -25
    assert rows[1]["commodity"] == "铜"


def test_eastmoney_non_json_raises():
    with pytest.raises(ValueError):
        price_sources.parse_futures_eastmoney("<html>被拦截</html>", _cfg("eastmoney_futures"))


def test_shfe_picks_max_open_interest_month():
    text = (FIXTURES / "shfe_list.json").read_text(encoding="utf-8")
    cfg = _cfg("shfe", commodity_map={"cu": "铜", "pb": "铅"})
    rows = price_sources.parse_shfe_daily(text, cfg)
    by = {r["commodity"]: r for r in rows}
    assert by["铜"]["value"] == 71250
    assert by["铅"]["value"] == 16800


def test_parse_unknown_parser_raises():
    with pytest.raises(ValueError):
        price_sources.parse("nope", "", {})
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_price_sources.py -v`
Expected: FAIL（`No module named 'crawler.price_sources'`）；其中 sina 样本文件尚不存在

- [ ] **Step 3: 实现 price_sources.py（期货组）+ 三个源 YAML**

`crawler/price_sources.py`:
```python
import json
import re
from datetime import datetime

from bs4 import BeautifulSoup

from crawler.parse import parse_date


def _to_float(s):
    if s is None:
        return None
    s = str(s).replace(",", "").strip()
    if s in {"", "-", "--", "暂无", "None"}:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _scaled(v, scale):
    f = _to_float(v)
    if f is None:
        return None
    return round(f / float(scale), 4) if scale else f


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _make_row(commodity, price_type, value, cfg, raw_label,
              change=None, change_pct=None, price_date=None):
    return {
        "commodity": commodity,
        "price_type": price_type,
        "value": value,
        "unit": cfg.get("unit", ""),
        "change": change,
        "change_pct": change_pct,
        "price_date": price_date or cfg.get("price_date") or _today(),
        "source_key": cfg["key"],
        "raw_label": raw_label,
        "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def _match_commodity(label, mapping):
    label = (label or "").strip()
    if label in mapping:
        return mapping[label]
    for commodity, keywords in mapping.items():
        words = keywords if isinstance(keywords, list) else [keywords]
        if any(w and w in label for w in words):
            return commodity
    return None


SINA_VAR = re.compile(r'var\s+hq_str_nf_([A-Za-z0-9]+)="([^"]*)"')


def parse_futures_sina(text: str, cfg: dict) -> list:
    rows = []
    fm = cfg.get("field_map", {})
    for m in SINA_VAR.finditer(text or ""):
        code, payload = m.group(1), m.group(2)
        commodity = cfg.get("commodity_map", {}).get(code)
        if not commodity:
            continue
        parts = payload.split(",")

        def field(name):
            idx = fm.get(name)
            if idx is None or idx >= len(parts):
                return None
            return parts[idx]

        value = _to_float(field("last"))
        if value is None or value <= 0:
            continue
        prev = _to_float(field("prev_settle"))
        change = round(value - prev, 4) if prev else None
        change_pct = round((value - prev) / prev * 100, 2) if prev else None
        rows.append(_make_row(commodity, "期货", value, cfg, code,
                              change=change, change_pct=change_pct))
    return rows


def parse_futures_eastmoney(text: str, cfg: dict) -> list:
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        raise ValueError("东方财富返回不是 JSON")
    diff = ((data.get("data") or {}).get("diff")) or []
    fm = cfg.get("field_map", {})
    scale = cfg.get("scale", {})
    rows = []
    for item in diff:
        label = str(item.get(fm.get("name", "f14"), ""))
        commodity = _match_commodity(label, cfg.get("commodity_map", {}))
        if not commodity:
            continue
        value = _scaled(item.get(fm.get("last", "f2")), scale.get("last"))
        if value is None or value <= 0:
            continue
        change = _scaled(item.get(fm.get("change", "f4")), scale.get("change"))
        change_pct = _scaled(item.get(fm.get("change_pct", "f3")), scale.get("change_pct"))
        rows.append(_make_row(commodity, "期货", value, cfg, label,
                              change=change, change_pct=change_pct))
    return rows


def parse_shfe_daily(text: str, cfg: dict) -> list:
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        raise ValueError("上期所返回不是 JSON")
    raw_rows = data.get("o_curinstrument") or data.get("o_curinstrumentList") or []
    best = {}
    for item in raw_rows:
        product = str(item.get("PRODUCTID", "")).strip().rstrip("_f")
        commodity = cfg.get("commodity_map", {}).get(product)
        if not commodity:
            continue
        oi = _to_float(item.get("OPENINTEREST")) or 0.0
        if commodity not in best or oi > best[commodity][0]:
            best[commodity] = (oi, product, item)
    close_field = cfg.get("close_field", "CLOSEPRICE")
    rows = []
    for commodity, (_, product, item) in best.items():
        value = _to_float(item.get(close_field))
        if value is None or value <= 0:
            continue
        label = f"{product}{item.get('DELIVERYMONTH', '')}"
        rows.append(_make_row(commodity, "期货", value, cfg, label))
    return rows


PARSERS = {
    "sina_futures": parse_futures_sina,
    "eastmoney_futures": parse_futures_eastmoney,
    "shfe_daily": parse_shfe_daily,
}


def parse(parser: str, text: str, cfg: dict) -> list:
    fn = PARSERS.get(parser)
    if fn is None:
        raise ValueError(f"未知价格解析器: {parser}")
    return fn(text, cfg)
```

`config/sources/sina_futures.yaml`:
```yaml
key: sina_futures
name: 新浪期货行情
board: price
parser: sina_futures
url: "https://hq.sinajs.cn/list=nf_JM0,nf_J0,nf_I0,nf_CU0,nf_AL0,nf_ZN0,nf_PB0,nf_SN0,nf_AU0,nf_AG0,nf_SM0,nf_SF0"
referer: "https://finance.sina.com.cn"
encoding: gb18030
fixture_ext: txt
unit: 元/吨
field_map: {name: 0, last: 8, prev_settle: 10}
commodity_map:
  JM0: 焦煤
  J0: 焦炭
  I0: 铁矿石
  CU0: 铜
  AL0: 铝
  ZN0: 锌
  PB0: 铅
  SN0: 锡
  AU0: 黄金
  AG0: 白银
  SM0: 锰硅
  SF0: 硅铁
```

`config/sources/eastmoney_futures.yaml`:
```yaml
key: eastmoney_futures
name: 东方财富期货（备用）
board: price
parser: eastmoney_futures
url: "https://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=100&po=1&np=1&fltt=2&invt=2&fid=f3&fs=m:113&fields=f2,f3,f4,f12,f14"
fixture_ext: json
unit: 元/吨
field_map: {name: f14, last: f2, change: f4, change_pct: f3}
scale: {}
commodity_map:
  焦煤连续: 焦煤
  焦炭连续: 焦炭
  铁矿石连续: 铁矿石
  沪铜连续: 铜
  沪铝连续: 铝
  沪锌连续: 锌
  沪铅连续: 铅
  沪锡连续: 锡
  沪金连续: 黄金
  沪银连续: 白银
  锰硅连续: 锰硅
  硅铁连续: 硅铁
```

`config/sources/shfe.yaml`:
```yaml
key: shfe
name: 上期所日行情
board: price
parser: shfe_daily
url: "https://www.shfe.com.cn/data/dailydata/kx/kx20260915.dat"
fixture_ext: json
unit: 元/吨
close_field: CLOSEPRICE
commodity_map:
  cu: 铜
  al: 铝
  zn: 锌
  pb: 铅
  sn: 锡
  au: 黄金
  ag: 白银
```

- [ ] **Step 4: 抓真实 sina 样本并校准字段**

Run: `python -m tools.snapshot sina_futures`
Expected: 生成 `tests/fixtures/sina_futures_list.txt`（内容形如 `var hq_str_nf_JM0="焦煤,开,高,低,...,收,结算,...";`）。
打开样本数出逗号分隔的字段位置，把 `last`（最新价/收盘价）与 `prev_settle`（昨结算）的正确索引写进 `sina_futures.yaml` 的 `field_map`；同时把 `shfe.yaml` 的 `url` 日期替换为"今天"（真实联网验证端点，若 403/404 则把 `enabled: false` 写入该 YAML 并在 README"已知限制"记录，不阻塞本任务）。
Run: `python -m pytest tests/test_price_sources.py -v`
Expected: 5 passed；若 sina 断言失败，先按样本修正 `field_map`（测试里的 `field_map` 与 YAML 保持一致）

- [ ] **Step 5: 提交**

```bash
git add -A
git commit -m "feat: 期货价格解析器（新浪/东方财富/上期所）与源配置"
```

---

## Task 6: 价格解析器（表格/正则组）+ 现货与指数源

**Files:**
- Modify: `crawler/price_sources.py`（追加 `parse_table`、`parse_regex`、`_cell_*`、注册进 `PARSERS`）
- Create: `config/sources/pp100.yaml`, `config/sources/ccmn.yaml`, `config/sources/sxcoal.yaml`, `config/sources/cctd.yaml`, `config/sources/mysteel.yaml`
- Test: `tests/test_price_html_sources.py` + 5 份快照样本（`tests/fixtures/{key}_list.html`，用 `tools.snapshot` 抓取）

**Interfaces:**
- Consumes: Task 1-5 全部
- Produces:
  - `parse_table(html, cfg)`：`cfg["table"] = {"row": CSS, "cell": CSS 默认 td, "columns": {"name": idx, "price": idx, "change": idx?, "change_pct": idx?, "date": idx?}}`
  - `parse_regex(html, cfg)`：`cfg["regex"] = {"pattern": 带命名组, "name_group": "name", "price_group": "price"}`
  - 品种匹配规则 `_match_commodity(label, mapping)`：先精确匹配 key，再对 value（字符串或关键词列表）做包含匹配

- [ ] **Step 1: 写失败测试**

`tests/test_price_html_sources.py`:
```python
from pathlib import Path

import pytest

from crawler import price_sources
from crawler.config import load_sources

FIXTURES = Path(__file__).resolve().parent / "fixtures"
PRICE_HTML_SOURCES = ["pp100", "ccmn", "sxcoal", "cctd", "mysteel"]


@pytest.mark.parametrize("key", PRICE_HTML_SOURCES)
def test_price_source_parses_from_snapshot(key):
    src = [s for s in load_sources() if s["key"] == key][0]
    if not src.get("enabled", True):
        pytest.skip(f"{key} 已停用")
    html = (FIXTURES / f"{key}_list.html").read_text(encoding="utf-8")
    rows = price_sources.parse(src["parser"], html, src)
    assert len(rows) >= 1, f"{key} 未解析出任何价格"
    assert all(r["value"] > 0 for r in rows), f"{key} 出现非法价格"
    unknown = {r["commodity"] for r in rows} - set(src.get("commodity_map", {}).keys())
    assert not unknown, f"{key} 出现未知品种: {unknown}"


def test_table_parser_with_keyword_matching():
    html = """<table><tr><th>商品</th><th>价格</th><th>涨跌幅</th></tr>
    <tr><td>磷矿石（30%品位）</td><td>1,050</td><td>+1.2%</td></tr>
    <tr><td>萤石（97%湿粉）</td><td>3,300</td><td>-0.5%</td></tr></table>"""
    cfg = {"key": "t", "unit": "元/吨", "price_type": "现货",
           "table": {"row": "table tr", "cell": "td",
                     "columns": {"name": 0, "price": 1, "change_pct": 2}},
           "commodity_map": {"磷矿石": ["磷矿石"], "萤石": ["萤石"]}}
    rows = price_sources.parse_table(html, cfg)
    assert {r["commodity"] for r in rows} == {"磷矿石", "萤石"}
    assert rows[0]["value"] == 1050.0
    assert rows[0]["change_pct"] == 1.2


def test_regex_parser():
    html = "<div>秦皇岛5500K动力煤现货价 650 元/吨，秦皇岛5000K 560 元/吨</div>"
    cfg = {"key": "c", "unit": "元/吨", "price_type": "现货", "commodity_map": {"动力煤": ["5500", "5000"]},
           "regex": {"pattern": "(?P<name>秦皇岛(?:5500|5000)K?)[^0-9]{0,8}(?P<price>\\d{3,4})"}}
    rows = price_sources.parse_regex(html, cfg)
    assert len(rows) == 2
    assert rows[0]["value"] == 650.0
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_price_html_sources.py -v`
Expected: FAIL（`parse_table` 不存在 / 快照文件不存在）

- [ ] **Step 3: 实现 table/regex 解析器并注册**

在 `crawler/price_sources.py` 末尾追加（并把两者加入 `PARSERS`）：
```python
def _cell_text(cells, idx):
    if idx is None or idx >= len(cells):
        return ""
    return cells[idx]


def _cell_float(cells, idx):
    return _to_float(re.sub(r"[^\d.\-]", "", _cell_text(cells, idx)))


def parse_table(html: str, cfg: dict) -> list:
    t = cfg["table"]
    soup = BeautifulSoup(html, "lxml")
    rows = []
    for tr in soup.select(t["row"]):
        cells = [c.get_text(" ", strip=True) for c in tr.select(t.get("cell", "td"))]
        cols = t.get("columns", {})
        if "name" not in cols or "price" not in cols:
            raise ValueError("表格价格源缺少 columns.name/price")
        if len(cells) <= max(cols[k] for k in ("name", "price")):
            continue
        label = cells[cols["name"]]
        commodity = _match_commodity(label, cfg.get("commodity_map", {}))
        if not commodity:
            continue
        value = _to_float(re.sub(r"[^\d.\-]", "", cells[cols["price"]]))
        if value is None or value <= 0:
            continue
        rows.append(_make_row(
            commodity, cfg.get("price_type", "现货"), value, cfg, label,
            change=_cell_float(cells, cols.get("change")),
            change_pct=_cell_float(cells, cols.get("change_pct")),
            price_date=parse_date(_cell_text(cells, cols.get("date"))) or None,
        ))
    return rows


def parse_regex(html: str, cfg: dict) -> list:
    r = cfg["regex"]
    soup = BeautifulSoup(html, "lxml")
    text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))
    rows = []
    for m in re.finditer(r["pattern"], text):
        label = (m.group(r.get("name_group", "name")) or "").strip()
        commodity = _match_commodity(label, cfg.get("commodity_map", {}))
        if not commodity:
            continue
        value = _to_float(m.group(r.get("price_group", "price")))
        if value is None or value <= 0:
            continue
        rows.append(_make_row(commodity, cfg.get("price_type", "指数"), value, cfg, label))
    return rows


PARSERS["table"] = parse_table
PARSERS["regex"] = parse_regex
```

- [ ] **Step 4: 抓 5 个源的真实样本并填写配置**

Run: `python -m tools.snapshot pp100`（对 `ccmn`、`sxcoal`、`cctd`、`mysteel` 同理）
然后对每个源：用 `Select-String` 或浏览器查看样本里价格表格/文字的 HTML 结构，修正对应 YAML 的 `table.row/columns` 或 `regex.pattern`，直到 `python -m pytest tests/test_price_html_sources.py -v` 全绿。
若某源首页确实没有可抓价格（纯 JS/登录墙），把该 YAML 的 `enabled: false` 并在 README"已知限制"记录，测试用 `pytest.mark.skipif` 按 `enabled` 状态跳过——其余源必须过，至少保住 `pp100` 与 `ccmn`。

各源初始配置（按实测样本修正）：

`config/sources/pp100.yaml`:
```yaml
key: pp100
name: 生意社现货报价
board: price
parser: table
url: https://www.100ppi.com/mprice/
price_type: 现货
unit: 元/吨
table:
  row: "table tr"
  cell: "td"
  columns: {name: 0, price: 1}
commodity_map:
  磷矿石: [磷矿石]
  萤石: [萤石]
  石英砂: [石英砂]
  锰: [锰矿, 电解锰]
  钨: [钨精矿, 黑钨, 白钨]
  钼: [钼精矿, 钼铁]
  锑: [锑锭, 锑]
  焦炭: [焦炭]
  动力煤: [动力煤]
```

`config/sources/ccmn.yaml`:
```yaml
key: ccmn
name: 长江有色金属网
board: price
parser: table
urls:
  - https://www.ccmn.cn/copperprice/
  - https://www.ccmn.cn/leadzincprice/
price_type: 现货
unit: 元/吨
table:
  row: "table tr"
  cell: "td"
  columns: {name: 0, price: 1, change: 2}
commodity_map:
  铜: [铜]
  铅锌: [铅, 锌]
  铝: [铝]
  锡: [锡]
```

`config/sources/sxcoal.yaml`:
```yaml
key: sxcoal
name: 中国煤炭资源网
board: price
parser: regex
url: https://www.sxcoal.com/
price_type: 指数
unit: 元/吨
regex:
  pattern: "(?P<name>CCI[^0-9]{1,14})(?P<price>\\d{3,6})"
commodity_map:
  焦煤: [主焦煤, 柳林, 气煤, 肥煤, 焦煤]
  焦炭: [焦炭]
  动力煤: [5500, 5000, 4500, 动力煤]
```

`config/sources/cctd.yaml`:
```yaml
key: cctd
name: 中国煤炭市场网
board: price
parser: regex
url: https://www.cctd.com.cn/
encoding: gb18030
price_type: 现货
unit: 元/吨
regex:
  pattern: "(?P<name>秦皇岛(?:5500|5000|4500)[^0-9]{0,8})(?P<price>\\d{3,4})"
commodity_map:
  动力煤: [5500, 5000, 4500]
```

`config/sources/mysteel.yaml`:
```yaml
key: mysteel
name: 我的钢铁网指数
board: price
parser: regex
url: https://www.mysteel.com/
price_type: 指数
unit: 元/吨
regex:
  pattern: "(?P<name>(?:Mysteel|我的钢铁)[^0-9]{2,16}指数[^0-9]{0,6})(?P<price>\\d{3,4}(?:\\.\\d+)?)"
commodity_map:
  铁矿石: [62%, 澳粉, 铁矿石, 铁矿]
  焦煤: [焦煤, 主焦]
  焦炭: [焦炭]
  锰硅: [锰硅, 硅锰]
```

- [ ] **Step 5: 运行测试确认通过并提交**

Run: `python -m pytest tests/test_price_sources.py tests/test_price_html_sources.py -v`
Expected: 全部 passed（跳过项仅限明确 `enabled: false` 的源）
```bash
git add -A
git commit -m "feat: 表格/正则价格解析器与现货指数源接入"
```

---

## Task 7: 抓取编排 main.py

**Files:**
- Create: `crawler/main.py`
- Test: `tests/test_main.py`

**Interfaces:**
- Consumes: Tasks 1-6 全部
- Produces:
  - `crawler.main.run_once(settings=None, fetcher=None, sources_dir=None, tags=None) -> dict`；返回 `{"sources_total","sources_ok","sources_error","articles_found","articles_new","prices","errors"}`
  - CLI：`python -m crawler.main --once`
  - 源 YAML 支持 `urls` 列表（多列表页）与 `detail: {enabled: true, content: CSS, limit: 10}`

- [ ] **Step 1: 写失败测试**

`tests/test_main.py`:
```python
import dataclasses
from pathlib import Path

from crawler import main, store
from crawler.config import load_settings
from crawler.fetch import FetchResult

LIST_HTML = """
<ul class="list">
  <li><a href="/a/1.html">河北开展磷矿安全生产整治</a><span>2026-09-15</span></li>
  <li><a href="/a/2.html">云南铜矿项目投产</a><span>2026-09-15</span></li>
  <li><a href="/a/3.html">普通新闻一条</a><span>2026-09-15</span></li>
</ul>
"""

PRICE_TEXT = "秦皇岛5500K动力煤现货价 650 元/吨"


def _write_sources(d: Path):
    (d / "news_a.yaml").write_text(
        "name: 测试新闻站\nboard: news\nurl: https://news.example.com/list\n"
        "list:\n  item: ul.list li\n  title: a\n  date: span\n",
        encoding="utf-8")
    (d / "price_a.yaml").write_text(
        "name: 测试价格源\nboard: price\nparser: regex\nurl: https://price.example.com/\n"
        "price_type: 现货\nunit: 元/吨\nregex:\n"
        "  pattern: \"(?P<name>秦皇岛(?:5500|5000))(?:K)(?:动力煤现货价)[^0-9]{0,6}(?P<price>\\\\d{3,4})\"\n"
        "commodity_map:\n  动力煤: [5500, 5000]\n",
        encoding="utf-8")
    (d / "bad.yaml").write_text(
        "name: 坏掉的源\nboard: news\nurl: https://bad.example.com/\n"
        "list:\n  item: ul li\n  title: a\n",
        encoding="utf-8")


def _fetcher(url, **kwargs):
    if "bad" in url:
        return FetchResult(ok=False, status=500, error="HTTP 500", text="<html>错误页</html>")
    if "price" in url:
        return FetchResult(ok=True, status=200, text=PRICE_TEXT, final_url=url)
    return FetchResult(ok=True, status=200, text=LIST_HTML, final_url=url)


def test_run_once_end_to_end(tmp_path, monkeypatch):
    sources_dir = tmp_path / "sources"
    sources_dir.mkdir()
    _write_sources(sources_dir)
    settings = dataclasses.replace(
        load_settings(), request_interval=0.0, db_path=tmp_path / "t.db")
    monkeypatch.setattr(main.report, "snapshots_dir", lambda: tmp_path / "snaps")
    monkeypatch.setattr(main.report, "logs_dir", lambda: tmp_path / "logs")
    summary = main.run_once(settings=settings, fetcher=_fetcher, sources_dir=sources_dir)

    assert summary["sources_total"] == 3
    assert summary["sources_ok"] == 2
    assert summary["sources_error"] == 1
    assert summary["articles_new"] == 3
    assert summary["prices"] == 1

    conn = store.connect(settings.db_path)
    runs = conn.execute("SELECT source_key,status FROM crawl_runs ORDER BY id").fetchall()
    assert [(r["source_key"], r["status"]) for r in runs] == [
        ("bad", "error"), ("news_a", "ok"), ("price_a", "ok")]
    titles = [r["title"] for r in conn.execute("SELECT title FROM articles"].fetchall())]
    assert "河北开展磷矿安全生产整治" in titles
    assert len(list((tmp_path / "snaps").glob("bad_*.html"))) == 1
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_main.py -v`
Expected: FAIL（`No module named 'crawler.main'`）

- [ ] **Step 3: 实现 main.py**

`crawler/main.py`:
```python
import argparse
import time

from crawler import classify, dedup, parse, price_sources, report, store
from crawler.config import load_settings, load_sources, load_tags
from crawler.fetch import fetch


def _iter_urls(src: dict) -> list:
    return src.get("urls") or [src["url"]]


def _process_articles(conn, src, html, base_url, settings, tags, fetcher):
    items = parse.parse_list(html, src, base_url)
    detail = src.get("detail") or {}
    if detail.get("enabled"):
        limit = int(detail.get("limit", 10))
        fetched = 0
        for item in items:
            if fetched >= limit:
                break
            if item.summary:
                continue
            result = fetcher(item.url, referer=src.get("referer", ""), encoding=src.get("encoding"),
                             timeout=settings.request_timeout, retries=settings.request_retries)
            if result.ok:
                item.summary = parse.extract_summary(result.text, src, settings.summary_max_chars)
            fetched += 1
            time.sleep(settings.request_interval)
    new = merged = skipped = 0
    for item in items:
        article = {
            "url": item.url,
            "title": item.title,
            "summary": item.summary,
            "source_key": src["key"],
            "published_at": item.published_at,
            "classification": classify.classify(item.title, item.summary, src["board"], tags),
        }
        status = dedup.submit_item(conn, article, threshold=settings.dedup_threshold)
        if status == "new":
            new += 1
        elif status == "merged":
            merged += 1
        else:
            skipped += 1
    report.log(f"[{src['key']}] 解析 {len(items)} 条（新增 {new}，转载合并 {merged}，重复 {skipped}）")
    return len(items), new


def _process_prices(conn, src, text):
    rows = price_sources.parse(src["parser"], text, src)
    return store.upsert_prices(conn, rows)


def run_once(settings=None, fetcher=None, sources_dir=None, tags=None) -> dict:
    settings = settings or load_settings()
    tags = tags or load_tags()
    sources = [s for s in load_sources(sources_dir) if s.get("enabled", True)]
    fetcher = fetcher or fetch
    conn = store.connect(settings.db_path)
    store.init_db(conn)
    summary = {"sources_total": len(sources), "sources_ok": 0, "sources_error": 0,
               "articles_found": 0, "articles_new": 0, "prices": 0, "errors": []}
    for src in sources:
        store.upsert_source(conn, src["key"], src.get("name", src["key"]),
                            src["board"], _iter_urls(src)[0], True)
        run_id = store.start_crawl_run(conn, src["key"])
        found = new = 0
        last_result = None
        try:
            for url in _iter_urls(src):
                result = fetcher(url, referer=src.get("referer", ""), encoding=src.get("encoding"),
                                 timeout=settings.request_timeout, retries=settings.request_retries)
                last_result = result
                if not result.ok:
                    raise RuntimeError(result.error or f"HTTP {result.status}")
                if src["board"] == "price":
                    price_count = _process_prices(conn, src, result.text)
                    found += price_count
                    new += price_count
                    summary["prices"] += price_count
                else:
                    item_count, new_count = _process_articles(
                        conn, src, result.text, result.final_url or url, settings, tags, fetcher)
                    found += item_count
                    new += new_count
                    summary["articles_found"] += item_count
                    summary["articles_new"] += new_count
                time.sleep(settings.request_interval)
            store.finish_crawl_run(conn, run_id, "ok", found, new)
            summary["sources_ok"] += 1
            report.log(f"[{src['key']}] 完成：抓到 {found} 条，新增 {new} 条")
        except Exception as e:
            if last_result is not None and last_result.text:
                snap = report.save_snapshot(src["key"], last_result.text)
                report.prune_snapshots(src["key"], keep=3)
                report.log(f"[{src['key']}] 原始响应已存快照 {snap.name}")
            store.finish_crawl_run(conn, run_id, "error", 0, 0, str(e))
            summary["sources_error"] += 1
            summary["errors"].append(f"{src['key']}: {e}")
            report.log(f"[{src['key']}] 失败: {e}")
    conn.close()
    report.log("本轮完成：源 {}/{} 成功，新增文章 {}，价格 {} 条".format(
        summary["sources_ok"], summary["sources_total"],
        summary["articles_new"], summary["prices"]))
    return summary


def main():
    parser = argparse.ArgumentParser(description="矿news 抓取器")
    parser.add_argument("--once", action="store_true", help="执行一轮抓取后退出")
    parser.parse_args()
    run_once()


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_main.py -v`
Expected: 1 passed

- [ ] **Step 5: 全量回归 + 提交**

Run: `python -m pytest -v`
Expected: 全绿（sina/shfe 若被标记 skip 属预期）
```bash
git add -A
git commit -m "feat: 抓取编排（单源隔离/快照/报告）"
```

---

## Task 8: 接入 7 个政策源 + 4 个新闻源

**Files:**
- Create: `config/sources/mnr.yaml`, `chinamine.yaml`, `ndrc.yaml`, `mee.yaml`, `nea.yaml`, `hebei_zrzy.yaml`, `tangshan_zygh.yaml`, `cwestc.yaml`, `ccoalnews.yaml`, `cnmn.yaml`, `kyb.yaml`
- Create: `tests/fixtures/{上述key}_list.html`（用 tools.snapshot 抓取）
- Test: `tests/test_sources_news.py`

**Interfaces:**
- Consumes: `crawler.parse.parse_list`、`tools.snapshot`
- Produces: 11 份可用的源 YAML（含 `list.item/title/date` 选择器；政策源带 `detail.enabled: true` + `detail.content`）

- [ ] **Step 1: 写失败测试与初始 YAML**

`tests/test_sources_news.py`:
```python
from pathlib import Path

import pytest

from crawler import parse
from crawler.config import load_sources

FIXTURES = Path(__file__).resolve().parent / "fixtures"
ARTICLE_SOURCES = ["mnr", "chinamine", "ndrc", "mee", "nea", "hebei_zrzy", "tangshan_zygh",
                   "cwestc", "ccoalnews", "cnmn", "kyb"]


@pytest.mark.parametrize("key", ARTICLE_SOURCES)
def test_source_parses_from_snapshot(key):
    src = [s for s in load_sources() if s["key"] == key][0]
    html = (FIXTURES / f"{key}_list.html").read_text(encoding="utf-8")
    items = parse.parse_list(html, src, src["url"])
    assert len(items) >= 5, f"{key} 解析条数不足"
    assert all(i.title and i.url.startswith("http") for i in items), f"{key} 标题/链接异常"
    lst = src.get("list") or {}
    if lst.get("date") or lst.get("date_regex"):
        assert sum(1 for i in items if i.published_at) >= 3, f"{key} 日期解析异常"
```

每个源先按下表写初始 YAML（`list` 选择器为初值，Step 2 按样本修正；政策源统一带 `detail: {enabled: true, content: "div.TRS_Editor", limit: 10}`；新闻源 `detail: {enabled: false}`）：

| key | name | board | url |
|---|---|---|---|
| mnr | 自然资源部要闻 | policy | https://www.mnr.gov.cn/dt/ywbb/ |
| chinamine | 国家矿山安全监察局要闻 | policy | https://www.chinamine-safety.gov.cn/xw/mkaqjcxw/ |
| ndrc | 发改委发展改革工作 | policy | https://www.ndrc.gov.cn/xxgk/zcfb/fzggwl/ |
| mee | 生态环境部新闻发布 | policy | https://www.mee.gov.cn/ywdt/xwfb/ |
| nea | 国家能源局新闻中心 | policy | https://www.nea.gov.cn/xwzx/ |
| hebei_zrzy | 河北省自然资源厅厅动态 | policy | http://zrzy.hebei.gov.cn/heb/xinwen/stdt/ |
| tangshan_zygh | 唐山自然资源和规划局公告公示 | policy | https://zygh.tangshan.gov.cn/ts/xxgk/gggs |
| cwestc | 中国煤炭新闻网矿业要闻 | news | http://www.cwestc.com/MroeNews.aspx?gd=13 |
| ccoalnews | 中国煤炭网要闻 | news | http://www.ccoalnews.com/news/yaowen.html |
| cnmn | 中国有色网要闻 | news | https://www.cnmn.com.cn/ShowNewsList.aspx?id=43 |
| kyb | 中国矿业报行业要闻 | news | https://kyb.cgs.gov.cn/zhyw/hyyw/ |

示例（`mnr.yaml`，其余按同结构写）：
```yaml
key: mnr
name: 自然资源部要闻
board: policy
url: https://www.mnr.gov.cn/dt/ywbb/
list:
  item: "li"
  title: "a"
  date: "span"
detail:
  enabled: true
  content: "div.TRS_Editor"
  limit: 10
```

- [ ] **Step 2: 逐个抓样本并修正选择器**

Run（11 次）: `python -m tools.snapshot <key>`
每个源：查看 `tests/fixtures/<key>_list.html`，用 `Select-String -Path tests\fixtures\<key>_list.html -Pattern "2026"` 之类定位标题与日期的容器，修正 YAML 选择器直到该源测试通过。
对于 `cwestc`（GB2312）在 YAML 加 `encoding: gb18030`；对重定向/编码异常的源，样本文件若为乱码，先在 YAML 修正 `encoding` 后重新 snapshot。

Run: `python -m pytest tests/test_sources_news.py -v`
Expected: 11 passed（个别源若无有效列表页则 `enabled: false` + 测试跳过，并在 README"已知限制"记录；**不允许留一个失败用例**）

- [ ] **Step 3: 真实抓取冒烟**

Run: `python -m crawler.main --once`
Expected: 控制台输出各源"完成/失败"日志；策略源应抓到条数；然后：
Run: `python -c "from crawler import store; from crawler.config import load_settings; c=store.connect(load_settings().db_path); print([dict(r) for r in c.execute('SELECT source_key,status,items_found,items_new FROM crawl_runs ORDER BY id DESC LIMIT 15')])"`
Expected: 大多数源 `ok` 且 `items_found > 0`；失败源记录原因，逐个修（多为选择器/编码问题）

- [ ] **Step 4: 提交**

```bash
git add -A
git commit -m "feat: 接入 7 个政策源与 4 个新闻源"
```

---

## Task 9: Web 骨架 + 查询层 + 首页

**Files:**
- Create: `web/__init__.py`, `web/app.py`, `web/queries.py`, `web/templates/base.html`, `web/templates/index.html`, `web/static/style.css`
- Test: `tests/test_web_index.py`

**Interfaces:**
- Consumes: `crawler.store`、`crawler.config`
- Produces:
  - `web.app.create_app(db_path=None) -> FastAPI`；路由 `GET /healthz`、`GET /`
  - `web.queries.today_stats(conn)`、`latest_articles(conn, limit=30, board=None)`、`latest_policies(conn, limit=8)`、`price_latest(conn, limit=20)`、`price_series(conn, commodity, days=30, price_type=None)`、`search_articles(conn, q="", mineral=None, board=None, source=None, date_from=None, date_to=None, limit=100)`、`distinct_commodities(conn)`、`source_health(conn)`、`last_runs(conn)`；文章查询返回的 `minerals/regions/types` 已解码为 list

- [ ] **Step 1: 写失败测试**

`tests/test_web_index.py`:
```python
from datetime import datetime

from fastapi.testclient import TestClient

from crawler import store
from web.app import create_app


def seed(db):
    conn = store.connect(db)
    store.init_db(conn)
    item = {"url": "https://e.com/1", "title": "河北开展磷矿安全生产整治", "summary": "摘要文字",
            "source_key": "mnr", "published_at": "2026-09-15"}
    cls = {"board": "policy", "minerals": ["磷矿"], "regions": ["河北"], "types": ["政策"]}
    store.insert_article(conn, item, cls, "u1", "t1")
    conn.execute(
        "INSERT INTO prices(commodity,price_type,value,unit,change,change_pct,price_date,source_key,raw_label,fetched_at) "
        "VALUES('铜','期货',71000,'元/吨',100,0.14,?,?,'cu',?)",
        (datetime.now().strftime("%Y-%m-%d"), "sina", store.now_iso()))
    store.upsert_source(conn, "mnr", "自然资源部", "policy", "https://www.mnr.gov.cn/", True)
    run = store.start_crawl_run(conn, "mnr")
    store.finish_crawl_run(conn, run, "ok", 10, 3)
    conn.commit()
    conn.close()


def test_healthz(tmp_path):
    client = TestClient(create_app(tmp_path / "t.db"))
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


def test_index_renders(tmp_path):
    db = tmp_path / "t.db"
    seed(db)
    client = TestClient(create_app(db))
    resp = client.get("/")
    assert resp.status_code == 200
    assert "今日新增" in resp.text
    assert "河北开展磷矿安全生产整治" in resp.text
    assert "矿价速览" in resp.text
    assert "铜" in resp.text
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_web_index.py -v`
Expected: FAIL（`No module named 'web'`）

- [ ] **Step 3: 实现 queries.py / app.py / 模板 / 样式**

`web/__init__.py`: 空文件。

`web/queries.py`:
```python
import json
from datetime import datetime, timedelta


def _decode(row) -> dict:
    d = dict(row)
    for key in ("minerals", "regions", "types"):
        if key in d and isinstance(d[key], str):
            try:
                d[key] = json.loads(d[key])
            except ValueError:
                d[key] = []
    return d


def today_stats(conn) -> dict:
    day = datetime.now().strftime("%Y-%m-%d")
    rows = conn.execute(
        "SELECT board, COUNT(*) c FROM articles WHERE fetched_at LIKE ? GROUP BY board",
        (day + "%",)).fetchall()
    by_board = {r["board"]: r["c"] for r in rows}
    return {"total": sum(by_board.values()), "by_board": by_board}


def last_runs(conn) -> list:
    rows = conn.execute(
        "SELECT source_key, status, finished_at, items_found FROM crawl_runs WHERE id IN "
        "(SELECT MAX(id) FROM crawl_runs GROUP BY source_key) ORDER BY source_key").fetchall()
    return [dict(r) for r in rows]


def latest_articles(conn, limit=30, board=None) -> list:
    sql = ("SELECT a.*, (SELECT member_count FROM article_clusters c WHERE c.id=a.cluster_id) AS member_count "
           "FROM articles a WHERE a.is_primary=1")
    params = []
    if board:
        sql += " AND a.board=?"
        params.append(board)
    sql += " ORDER BY a.id DESC LIMIT ?"
    params.append(limit)
    return [_decode(r) for r in conn.execute(sql, params).fetchall()]


def latest_policies(conn, limit=8) -> list:
    return latest_articles(conn, limit=limit, board="policy")


def price_latest(conn, limit=20) -> list:
    rows = conn.execute(
        "SELECT p.* FROM prices p JOIN "
        "(SELECT commodity, price_type, MAX(price_date) d FROM prices GROUP BY commodity, price_type) m "
        "ON p.commodity=m.commodity AND p.price_type=m.price_type AND p.price_date=m.d "
        "ORDER BY p.commodity LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


def price_series(conn, commodity, days=30, price_type=None) -> list:
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    sql = "SELECT price_date, AVG(value) value FROM prices WHERE commodity=? AND price_date>=?"
    params = [commodity, cutoff]
    if price_type:
        sql += " AND price_type=?"
        params.append(price_type)
    sql += " GROUP BY price_date ORDER BY price_date"
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def distinct_commodities(conn) -> list:
    return [r["commodity"] for r in
            conn.execute("SELECT DISTINCT commodity FROM prices ORDER BY commodity").fetchall()]


def search_articles(conn, q="", mineral=None, board=None, source=None,
                    date_from=None, date_to=None, limit=100) -> list:
    where = ["a.is_primary=1"]
    params = []
    sql = ("SELECT a.*, (SELECT member_count FROM article_clusters c WHERE c.id=a.cluster_id) AS member_count "
           "FROM articles a ")
    text = (q or "").strip()
    if len(text) >= 3:
        sql += "JOIN articles_fts f ON f.rowid=a.id "
        where.append("articles_fts MATCH ?")
        params.append('"' + text.replace('"', " ") + '"')
    elif text:
        where.append("(a.title LIKE ? OR a.summary LIKE ?)")
        params.extend([f"%{text}%", f"%{text}%"])
    if board:
        where.append("a.board=?")
        params.append(board)
    if source:
        where.append("a.source_key=?")
        params.append(source)
    if mineral:
        where.append("a.minerals LIKE ?")
        params.append(f'%"{mineral}"%')
    if date_from:
        where.append("a.fetched_at>=?")
        params.append(date_from)
    if date_to:
        where.append("a.fetched_at<=?")
        params.append(date_to + " 23:59:59")
    sql += " WHERE " + " AND ".join(where) + " ORDER BY a.id DESC LIMIT ?"
    params.append(limit)
    return [_decode(r) for r in conn.execute(sql, params).fetchall()]


def source_health(conn) -> list:
    rows = conn.execute(
        "SELECT s.key, s.name, s.board, s.enabled, r.status, r.finished_at, r.items_found, r.items_new, r.error "
        "FROM sources s LEFT JOIN crawl_runs r ON r.id = "
        "(SELECT MAX(id) FROM crawl_runs WHERE source_key=s.key) ORDER BY s.board, s.key").fetchall()
    return [dict(r) for r in rows]
```

`web/app.py`:
```python
import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from crawler import store
from crawler.config import load_settings
from web import queries

WEB = Path(__file__).resolve().parent


def create_app(db_path=None) -> FastAPI:
    settings = load_settings()
    db_file = Path(db_path) if db_path else settings.db_path
    app = FastAPI(title="矿业资讯站")
    app.mount("/static", StaticFiles(directory=str(WEB / "static")), name="static")
    templates = Jinja2Templates(directory=str(WEB / "templates"))

    def get_conn():
        conn = store.connect(db_file)
        store.init_db(conn)
        return conn

    @app.get("/healthz")
    def healthz():
        return {"ok": True}

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request):
        conn = get_conn()
        try:
            ctx = {
                "stats": queries.today_stats(conn),
                "runs": queries.last_runs(conn),
                "articles": queries.latest_articles(conn, limit=40),
                "prices": queries.price_latest(conn, limit=18),
                "policies": queries.latest_policies(conn, limit=6),
            }
        finally:
            conn.close()
        return templates.TemplateResponse(request, "index.html", ctx)

    return app


if __name__ == "__main__":
    import uvicorn
    _settings = load_settings()
    (_settings.data_dir / "web.pid").write_text(str(os.getpid()), encoding="utf-8")
    uvicorn.run(create_app(), host="0.0.0.0", port=_settings.port)
```

`web/templates/base.html`:
```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{% block title %}矿业资讯站{% endblock %}</title>
<link rel="stylesheet" href="/static/style.css">
{% block head %}{% endblock %}
</head>
<body>
<header class="top">
  <div class="brand">矿业资讯站 <span class="sub">像素智能 · 内部</span></div>
  <nav>
    <a href="/">首页</a>
    <a href="/prices">行情</a>
    <a href="/policy">政策</a>
    <a href="/search">搜索</a>
    <a href="/sources">源健康</a>
  </nav>
</header>
<main>{% block content %}{% endblock %}</main>
<footer class="foot">仅存标题与摘要 · 点击标题跳转原文</footer>
</body>
</html>
```

`web/templates/index.html`:
```html
{% extends "base.html" %}
{% block content %}
<div class="statusbar">
  今日新增 <b>{{ stats.total }}</b> 条（新闻 {{ stats.by_board.get('news', 0) }} · 政策 {{ stats.by_board.get('policy', 0) }} · 价格源更新见行情页）
  <span class="runs">{% for r in runs %}<span class="dot {{ 'ok' if r.status == 'ok' else 'err' }}" title="{{ r.source_key }} {{ r.finished_at }} {{ r.status }}"></span>{% endfor %}</span>
</div>
<div class="cols">
  <section class="feed">
    <h2>最新动态</h2>
    {% for a in articles %}
    <article>
      <a class="title" href="{{ a.url }}" target="_blank" rel="noopener">{{ a.title }}</a>
      {% if a.member_count and a.member_count > 1 %}<span class="repost">另有 {{ a.member_count - 1 }} 家转载</span>{% endif %}
      <div class="meta">{{ a.source_key }} · {{ a.published_at or a.fetched_at }} · {{ a.minerals|join('、') }} {{ a.types|join('、') }}</div>
      {% if a.summary %}<p class="summary">{{ a.summary }}</p>{% endif %}
    </article>
    {% else %}
    <p class="muted">暂无数据，请先运行：python -m crawler.main --once</p>
    {% endfor %}
  </section>
  <aside>
    <h2>矿价速览</h2>
    <table class="prices">
      {% for p in prices %}
      <tr><td>{{ p.commodity }}<span class="ptype">{{ p.price_type }}</span></td>
      <td class="num">{{ p.value }}</td>
      <td class="{{ 'up' if (p.change_pct or 0) > 0 else 'down' }}">{{ '%+.2f%%'|format(p.change_pct or 0) }}</td></tr>
      {% endfor %}
    </table>
    <h2>最新政策</h2>
    <ul class="policies">{% for a in policies %}<li><a href="{{ a.url }}" target="_blank" rel="noopener">{{ a.title }}</a></li>{% endfor %}</ul>
  </aside>
</div>
{% endblock %}
```

`web/static/style.css`:
```css
* { box-sizing: border-box; }
body { margin: 0; font-family: "Microsoft YaHei", system-ui, sans-serif; color: #1f2430; background: #f5f6f8; }
.top { display: flex; align-items: center; gap: 24px; padding: 10px 20px; background: #17324d; color: #fff; flex-wrap: wrap; }
.brand { font-size: 18px; font-weight: 700; }
.brand .sub { font-size: 12px; font-weight: 400; opacity: .7; margin-left: 6px; }
nav a { color: #cfe1f5; text-decoration: none; margin-right: 14px; }
nav a:hover { color: #fff; }
main { padding: 14px 20px 40px; max-width: 1200px; margin: 0 auto; }
.statusbar { background: #fff; border: 1px solid #e3e6eb; border-radius: 8px; padding: 10px 14px; margin-bottom: 14px; }
.runs { margin-left: 12px; }
.dot { display: inline-block; width: 10px; height: 10px; border-radius: 50%; margin-right: 4px; }
.dot.ok { background: #2e9e5b; }
.dot.err { background: #d64545; }
.cols { display: grid; grid-template-columns: 1fr 320px; gap: 16px; }
.feed article { background: #fff; border: 1px solid #e3e6eb; border-radius: 8px; padding: 10px 14px; margin-bottom: 10px; }
.title { font-size: 16px; font-weight: 600; color: #17324d; text-decoration: none; }
.title:hover { text-decoration: underline; }
.repost { color: #b07d2b; font-size: 12px; margin-left: 8px; }
.meta { color: #6b7280; font-size: 12px; margin-top: 4px; }
.summary { color: #374151; font-size: 13px; margin: 6px 0 0; }
aside h2, .feed h2 { font-size: 15px; margin: 10px 0 8px; }
.prices { width: 100%; background: #fff; border-collapse: collapse; border: 1px solid #e3e6eb; border-radius: 8px; overflow: hidden; }
.prices td, .prices th { padding: 6px 8px; border-bottom: 1px solid #eef0f3; font-size: 13px; }
.prices .num { text-align: right; font-variant-numeric: tabular-nums; }
.ptype { font-size: 11px; color: #9aa1ad; margin-left: 4px; }
.up { color: #c0322b; }
.down { color: #1f7a45; }
.policies { list-style: none; padding: 0; }
.policies li { margin-bottom: 6px; font-size: 13px; }
.muted { color: #9aa1ad; }
.foot { text-align: center; color: #9aa1ad; font-size: 12px; padding: 16px; }
@media (max-width: 760px) { .cols { grid-template-columns: 1fr; } }
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_web_index.py -v`
Expected: 2 passed

- [ ] **Step 5: 提交**

```bash
git add -A
git commit -m "feat: Web 骨架/查询层/首页今日速览"
```

---

## Task 10: 行情页 + 走势图 API + 本地 ECharts

**Files:**
- Modify: `web/app.py`（新增 `/prices`、`/api/prices/{commodity}`）
- Create: `web/templates/prices.html`, `web/static/vendor/echarts.min.js`（下载后入库提交）
- Test: `tests/test_web_prices.py`

**Interfaces:**
- Consumes: `web.queries.price_latest / price_series / distinct_commodities`
- Produces: `GET /prices` 页面；`GET /api/prices/{commodity}?days=30&price_type=` → `{"commodity","days","points":[{"price_date","value"}]}`

- [ ] **Step 1: 写失败测试**

`tests/test_web_prices.py`:
```python
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


def test_prices_page(tmp_path):
    db = tmp_path / "t.db"
    seed(db)
    client = TestClient(create_app(db))
    resp = client.get("/prices")
    assert resp.status_code == 200
    assert "矿价行情" in resp.text
    assert "铜" in resp.text


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
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_web_prices.py -v`
Expected: FAIL（404 Not Found）

- [ ] **Step 3: 实现页面与接口**

在 `web/app.py` 的 `create_app` 内追加：
```python
    @app.get("/prices", response_class=HTMLResponse)
    def prices_page(request: Request):
        conn = get_conn()
        try:
            ctx = {"commodities": queries.distinct_commodities(conn),
                   "prices": queries.price_latest(conn, limit=80)}
        finally:
            conn.close()
        return templates.TemplateResponse(request, "prices.html", ctx)

    @app.get("/api/prices/{commodity}")
    def price_api(commodity: str, days: int = 30, price_type: str = ""):
        conn = get_conn()
        try:
            points = queries.price_series(conn, commodity, days=days,
                                          price_type=price_type or None)
        finally:
            conn.close()
        return {"commodity": commodity, "days": days, "points": points}
```

`web/templates/prices.html`:
```html
{% extends "base.html" %}
{% block head %}<script src="/static/vendor/echarts.min.js"></script>{% endblock %}
{% block content %}
<h2>矿价行情</h2>
<div class="chart-controls">
  <select id="commodity">{% for c in commodities %}<option>{{ c }}</option>{% endfor %}</select>
  <select id="days"><option value="7">近7天</option><option value="30" selected>近30天</option><option value="90">近90天</option></select>
</div>
<div id="chart" style="width:100%;height:360px;background:#fff;border:1px solid #e3e6eb;border-radius:8px"></div>
<h2>最新报价</h2>
<table class="prices wide">
  <tr><th>品种</th><th>类型</th><th>最新价</th><th>涨跌</th><th>涨跌幅</th><th>日期</th><th>来源</th></tr>
  {% for p in prices %}
  <tr>
    <td>{{ p.commodity }}</td><td>{{ p.price_type }}</td>
    <td class="num">{{ p.value }} {{ p.unit }}</td>
    <td class="{{ 'up' if (p.change or 0) > 0 else 'down' }}">{{ p.change if p.change is not none else '-' }}</td>
    <td class="{{ 'up' if (p.change_pct or 0) > 0 else 'down' }}">{{ p.change_pct if p.change_pct is not none else '-' }}</td>
    <td>{{ p.price_date }}</td><td>{{ p.source_key }}</td>
  </tr>
  {% endfor %}
</table>
<script>
const chart = echarts.init(document.getElementById('chart'));
async function load() {
  const c = document.getElementById('commodity').value;
  const d = document.getElementById('days').value;
  const resp = await fetch('/api/prices/' + encodeURIComponent(c) + '?days=' + d);
  const data = await resp.json();
  chart.setOption({
    title: { text: c + ' 近' + d + '天走势' },
    tooltip: { trigger: 'axis' },
    grid: { left: 60, right: 20, top: 50, bottom: 40 },
    xAxis: { type: 'category', data: data.points.map(p => p.price_date) },
    yAxis: { type: 'value', scale: true },
    series: [{ type: 'line', smooth: true, data: data.points.map(p => p.value) }]
  });
}
document.getElementById('commodity').addEventListener('change', load);
document.getElementById('days').addEventListener('change', load);
load();
</script>
{% endblock %}
```

下载 ECharts 到本地（提交入库，运行时零外网依赖）：
```bash
curl -L -o web/static/vendor/echarts.min.js https://registry.npmmirror.com/echarts/latest/files/dist/echarts.min.js
```
若 1 失败改：`curl -L -o web/static/vendor/echarts.min.js https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js`
验证文件 >500KB 且开头含 `ECharts`。

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_web_prices.py -v`
Expected: 2 passed

- [ ] **Step 5: 提交**

```bash
git add -A
git commit -m "feat: 行情页/走势图接口/本地 ECharts"
```

---

## Task 11: 政策页 + 搜索页

**Files:**
- Modify: `web/app.py`（新增 `/policy`、`/search`）
- Create: `web/templates/policy.html`, `web/templates/search.html`
- Test: `tests/test_web_policy_search.py`

**Interfaces:**
- Consumes: `web.queries.search_articles / source_health / distinct_commodities`
- Produces: `GET /policy?region=&source=`；`GET /search?q=&mineral=&board=&source=`；中文 ≥3 字走 FTS5、2 字走 LIKE

- [ ] **Step 1: 写失败测试**

`tests/test_web_policy_search.py`:
```python
from fastapi.testclient import TestClient

from crawler import store
from web.app import create_app


def seed(db):
    conn = store.connect(db)
    store.init_db(conn)
    rows = [
        ("河北开展磷矿安全生产整治", "policy", ["磷矿"], ["河北"], ["政策"]),
        ("云南铜矿项目投产", "news", ["铜"], ["云南"], ["企业"]),
        ("今日铜价小幅上涨", "news", ["铜"], [], ["价格"]),
    ]
    for i, (title, board, minerals, regions, types) in enumerate(rows):
        item = {"url": f"https://e.com/{i}", "title": title, "summary": title + "的摘要",
                "source_key": "mnr", "published_at": "2026-09-15"}
        cls = {"board": board, "minerals": minerals, "regions": regions, "types": types}
        store.insert_article(conn, item, cls, f"u{i}", f"t{i}")
    conn.commit()
    conn.close()


def test_policy_page_filters_region(tmp_path):
    db = tmp_path / "t.db"
    seed(db)
    client = TestClient(create_app(db))
    resp = client.get("/policy?region=河北")
    assert resp.status_code == 200
    assert "河北开展磷矿安全生产整治" in resp.text
    assert "云南铜矿项目投产" not in resp.text


def test_search_fts_and_like(tmp_path):
    db = tmp_path / "t.db"
    seed(db)
    client = TestClient(create_app(db))
    r1 = client.get("/search?q=磷矿")
    assert "河北开展磷矿安全生产整治" in r1.text
    assert "云南铜矿项目投产" not in r1.text
    r2 = client.get("/search?q=铜价")
    assert "今日铜价小幅上涨" in r2.text
    r4 = client.get("/search?q=磷矿安全")
    assert "河北开展磷矿安全生产整治" in r4.text
    r3 = client.get("/search?mineral=铜")
    assert "云南铜矿项目投产" in r3.text
    assert "河北开展磷矿安全生产整治" not in r3.text
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_web_policy_search.py -v`
Expected: FAIL（404）

- [ ] **Step 3: 实现页面与接口**

在 `web/app.py` 内追加：
```python
    @app.get("/policy", response_class=HTMLResponse)
    def policy_page(request: Request, region: str = "", source: str = ""):
        conn = get_conn()
        try:
            articles = queries.search_articles(conn, board="policy",
                                               source=source or None, limit=200)
            if region:
                articles = [a for a in articles if region in (a.get("regions") or [])]
            health = queries.source_health(conn)
            sources = [h for h in health if h["board"] == "policy"]
        finally:
            conn.close()
        return templates.TemplateResponse(request, "policy.html", {
            "articles": articles, "region": region, "source": source, "sources": sources})

    @app.get("/search", response_class=HTMLResponse)
    def search_page(request: Request, q: str = "", mineral: str = "",
                    board: str = "", source: str = ""):
        conn = get_conn()
        try:
            results = queries.search_articles(conn, q=q, mineral=mineral or None,
                                              board=board or None, source=source or None,
                                              limit=100)
            ctx = {"results": results, "q": q, "mineral": mineral, "board": board,
                   "source": source, "commodities": queries.distinct_commodities(conn),
                   "sources": queries.source_health(conn)}
        finally:
            conn.close()
        return templates.TemplateResponse(request, "search.html", ctx)
```

`web/templates/policy.html`:
```html
{% extends "base.html" %}
{% block content %}
<h2>政策法规</h2>
<form method="get" class="filterbar">
  <select name="source">
    <option value="">全部机关</option>
    {% for s in sources %}<option value="{{ s.key }}" {{ 'selected' if s.key == source else '' }}>{{ s.name }}</option>{% endfor %}
  </select>
  <input name="region" value="{{ region }}" placeholder="地区（如 河北）">
  <button type="submit">筛选</button>
</form>
{% for a in articles %}
<article class="card">
  <a class="title" href="{{ a.url }}" target="_blank" rel="noopener">{{ a.title }}</a>
  {% if a.member_count and a.member_count > 1 %}<span class="repost">另有 {{ a.member_count - 1 }} 家转载</span>{% endif %}
  <div class="meta">{{ a.source_key }} · {{ a.published_at or a.fetched_at }} · {{ a.regions|join('、') }} {{ a.types|join('、') }}</div>
  {% if a.summary %}<p class="summary">{{ a.summary }}</p>{% endif %}
</article>
{% else %}
<p class="muted">没有符合条件的政策。</p>
{% endfor %}
{% endblock %}
```

`web/templates/search.html`:
```html
{% extends "base.html" %}
{% block content %}
<h2>全站搜索</h2>
<form method="get" class="filterbar">
  <input name="q" value="{{ q }}" placeholder="关键词（如：磷矿 政策）">
  <select name="mineral">
    <option value="">全部矿种</option>
    {% for c in commodities %}<option value="{{ c }}" {{ 'selected' if c == mineral else '' }}>{{ c }}</option>{% endfor %}
  </select>
  <select name="board">
    <option value="">全部板块</option>
    <option value="news" {{ 'selected' if board == 'news' else '' }}>新闻</option>
    <option value="policy" {{ 'selected' if board == 'policy' else '' }}>政策</option>
  </select>
  <button type="submit">搜索</button>
</form>
<p class="muted">共 {{ results|length }} 条结果</p>
{% for a in results %}
<article class="card">
  <a class="title" href="{{ a.url }}" target="_blank" rel="noopener">{{ a.title }}</a>
  <div class="meta">{{ a.source_key }} · {{ a.published_at or a.fetched_at }} · {{ a.minerals|join('、') }}</div>
  {% if a.summary %}<p class="summary">{{ a.summary }}</p>{% endif %}
</article>
{% endfor %}
{% endblock %}
```

在 `web/static/style.css` 末尾追加：
```css
.filterbar { margin-bottom: 12px; display: flex; gap: 8px; flex-wrap: wrap; }
.filterbar input, .filterbar select, .filterbar button { padding: 6px 10px; border: 1px solid #cfd4dc; border-radius: 6px; background: #fff; }
.filterbar button { background: #17324d; color: #fff; cursor: pointer; }
.card { background: #fff; border: 1px solid #e3e6eb; border-radius: 8px; padding: 10px 14px; margin-bottom: 10px; }
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_web_policy_search.py -v`
Expected: 2 passed

- [ ] **Step 5: 提交**

```bash
git add -A
git commit -m "feat: 政策页与全站搜索（FTS5 + LIKE 兜底）"
```

---

## Task 12: 源健康页 + 管理操作

**Files:**
- Modify: `web/app.py`（新增 `/sources`、`POST /admin/run_crawl`、`GET /admin/logs/{name}`、`GET /admin/backup/now`）
- Modify: `crawler/main.py`（`run_once` 结束时清理 `data/crawl.lock`）
- Create: `web/templates/sources.html`
- Test: `tests/test_web_sources.py`

**Interfaces:**
- Consumes: `web.queries.source_health`、`scripts.backup.run_backup`（Task 13 实现；本任务先按签名 `run_backup(db_path, backup_dir, keep_days=30) -> Path` 调用并在测试中 monkeypatch）
- Produces: 源健康页 + 三个管理端点；`data/crawl.lock` 机制（存在即"抓取中"，超过 3600 秒视为陈旧锁）

- [ ] **Step 1: 写失败测试**

`tests/test_web_sources.py`:
```python
from pathlib import Path

from fastapi.testclient import TestClient

from crawler import store
from web.app import create_app


def seed(db):
    conn = store.connect(db)
    store.init_db(conn)
    store.upsert_source(conn, "mnr", "自然资源部要闻", "policy", "https://www.mnr.gov.cn/", True)
    run = store.start_crawl_run(conn, "mnr")
    store.finish_crawl_run(conn, run, "ok", 20, 5)
    conn.commit()
    conn.close()


def test_sources_page(tmp_path):
    db = tmp_path / "t.db"
    seed(db)
    client = TestClient(create_app(db))
    resp = client.get("/sources")
    assert resp.status_code == 200
    assert "自然资源部要闻" in resp.text
    assert "ok" in resp.text


def test_run_crawl_lock(tmp_path, monkeypatch):
    db = tmp_path / "t.db"
    seed(db)
    started = []
    monkeypatch.setattr("subprocess.Popen", lambda *a, **k: started.append(a) or None)
    client = TestClient(create_app(db))
    resp = client.post("/admin/run_crawl")
    assert resp.status_code == 200
    assert started, "应启动抓取子进程"
    assert (db.parent / "crawl.lock").exists()
    resp2 = client.post("/admin/run_crawl")
    assert resp2.status_code == 409
    (db.parent / "crawl.lock").unlink()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_web_sources.py -v`
Expected: FAIL（404）

- [ ] **Step 3: 实现路由与页面**

在 `web/app.py` 顶部追加导入：
```python
import subprocess
import sys
import time

from fastapi.responses import FileResponse

ROOT = WEB.parent
```

在 `create_app` 内追加：
```python
    @app.get("/sources", response_class=HTMLResponse)
    def sources_page(request: Request):
        conn = get_conn()
        try:
            health = queries.source_health(conn)
        finally:
            conn.close()
        logs = sorted(settings.logs_dir.glob("crawler_*.log"), reverse=True)[:7]
        return templates.TemplateResponse(request, "sources.html", {
            "health": health, "logs": [p.name for p in logs]})

    @app.post("/admin/run_crawl")
    def run_crawl():
        lock = db_file.parent / "crawl.lock"
        if lock.exists() and time.time() - lock.stat().st_mtime < 3600:
            return JSONResponse({"ok": False, "message": "已有抓取任务在运行"}, status_code=409)
        lock.write_text(str(os.getpid()), encoding="utf-8")
        try:
            subprocess.Popen([sys.executable, "-m", "crawler.main", "--once"], cwd=str(ROOT))
        except Exception as exc:
            lock.unlink(missing_ok=True)
            return JSONResponse({"ok": False, "message": f"启动失败: {exc}"}, status_code=500)
        return {"ok": True, "message": "已开始抓取，稍后刷新查看源健康"}

    @app.get("/admin/logs/{name}")
    def download_log(name: str):
        path = settings.logs_dir / name
        if not path.exists() or path.parent != settings.logs_dir or not name.startswith("crawler_"):
            return JSONResponse({"ok": False, "message": "日志文件不存在"}, status_code=404)
        return FileResponse(path, filename=name)

    @app.get("/admin/backup/now")
    def backup_now():
        from scripts.backup import run_backup
        path = run_backup(db_file, settings.data_dir / "backup")
        return {"ok": True, "path": str(path)}
```
（`JSONResponse` 需加入 `from fastapi.responses import ...` 导入行。）

`crawler/main.py` 的 `run_once` 末尾（`return summary` 之前）追加：
```python
    (settings.data_dir / "crawl.lock").unlink(missing_ok=True)
```

`web/templates/sources.html`:
```html
{% extends "base.html" %}
{% block content %}
<h2>源健康</h2>
<p>
  <button onclick="runCrawl()">立即抓取一次</button>
  <a href="/admin/backup/now">立即备份数据库</a>
  <span class="muted" id="msg"></span>
</p>
<table class="prices wide">
  <tr><th>源</th><th>板块</th><th>最近状态</th><th>完成时间</th><th>抓到</th><th>新增</th><th>错误</th></tr>
  {% for h in health %}
  <tr>
    <td>{{ h.name }}<span class="ptype">{{ h.key }}</span></td>
    <td>{{ h.board }}</td>
    <td class="{{ 'oktext' if h.status == 'ok' else 'errtext' }}">{{ h.status or '未跑过' }}</td>
    <td>{{ h.finished_at }}</td><td>{{ h.items_found }}</td><td>{{ h.items_new }}</td>
    <td class="errtext">{{ h.error }}</td>
  </tr>
  {% endfor %}
</table>
<h2>最近日志</h2>
<ul class="policies">{% for name in logs %}<li><a href="/admin/logs/{{ name }}">{{ name }}</a></li>{% endfor %}</ul>
<script>
async function runCrawl() {
  const resp = await fetch('/admin/run_crawl', {method: 'POST'});
  const data = await resp.json();
  document.getElementById('msg').textContent = data.message;
}
</script>
{% endblock %}
```

在 `web/static/style.css` 末尾追加：
```css
.oktext { color: #1f7a45; }
.errtext { color: #c0322b; }
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_web_sources.py -v`
Expected: 2 passed

- [ ] **Step 5: 提交**

```bash
git add -A
git commit -m "feat: 源健康页与管理操作（手动抓取/日志/备份）"
```

---

## Task 13: 运维脚本（备份/看门狗/一键安装）

**Files:**
- Create: `scripts/__init__.py`, `scripts/backup.py`, `scripts/watchdog.py`, `scripts/install.py`, `安装.bat`
- Test: `tests/test_scripts.py`

**Interfaces:**
- Consumes: `crawler.config.load_settings`、`crawler.store.init_db`
- Produces:
  - `scripts.backup.run_backup(db_path, backup_dir, keep_days=30) -> Path`
  - `scripts.watchdog.http_ok(url, timeout=3) -> bool`、`read_pid(pid_file) -> int|None`、`check_and_restart(base_url, pid_file, python_exe=None, workdir=None) -> str`（"ok"/"restarted"/"started"）
  - `scripts.install.ps_task_script(name, python_exe, arguments, workdir, at_logon=False, daily_at=None, repeat_minutes=None, start_when_available=True) -> str`、`register_task(script)`、`firewall_rule(port) -> list`、`disable_sleep() -> list`、`ensure_venv(requirements, python_exe=None)`、`lan_ip() -> str`
  - 计划任务名：`矿news抓取07` / `矿news抓取12` / `矿news抓取18` / `矿news备份` / `矿news网站` / `矿news看门狗`

- [ ] **Step 1: 写失败测试**

`tests/test_scripts.py`:
```python
from datetime import datetime
from pathlib import Path

from scripts import backup, install, watchdog


def test_ps_task_script_contents():
    script = install.ps_task_script("矿news抓取07", r"C:\py\python.exe", "-m crawler.main --once",
                                    r"E:\矿_news", daily_at="07:30")
    assert "Register-ScheduledTask" in script
    assert "矿news抓取07" in script
    assert "-m crawler.main --once" in script
    assert "07:30" in script
    assert "StartWhenAvailable" in script


def test_ps_task_script_logon_and_repeat():
    s1 = install.ps_task_script("矿news网站", "py.exe", "-m web.app", "d", at_logon=True)
    assert "-AtLogOn" in s1
    s2 = install.ps_task_script("矿news看门狗", "py.exe", "-m scripts.watchdog", "d", repeat_minutes=5)
    assert "RepetitionInterval" in s2


def test_netsh_and_powercfg():
    assert install.firewall_rule(8080)[:4] == ["netsh", "advfirewall", "firewall", "add"]
    assert "localport=8080" in install.firewall_rule(8080)
    assert install.disable_sleep() == ["powercfg", "/change", "standby-timeout-ac", "0"]


def test_backup_creates_and_prunes(tmp_path):
    db = tmp_path / "news.db"
    db.write_text("x", encoding="utf-8")
    bdir = tmp_path / "backup"
    bdir.mkdir()
    old = bdir / "news_20200101.db"
    old.write_text("old", encoding="utf-8")
    target = backup.run_backup(db, bdir, keep_days=30)
    assert target.exists()
    assert target.name == f"news_{datetime.now().strftime('%Y%m%d')}.db"
    assert not old.exists()


def test_watchdog_ok_and_restart(tmp_path, monkeypatch):
    pid_file = tmp_path / "web.pid"
    pid_file.write_text("12345", encoding="utf-8")
    monkeypatch.setattr(watchdog, "http_ok", lambda url, timeout=3: True)
    assert watchdog.check_and_restart("http://x", pid_file) == "ok"

    monkeypatch.setattr(watchdog, "http_ok", lambda url, timeout=3: False)
    killed, started = [], []
    monkeypatch.setattr(watchdog, "kill_pid", lambda pid: killed.append(pid))
    monkeypatch.setattr(watchdog, "start_web", lambda py, wd: started.append((py, wd)))
    assert watchdog.check_and_restart("http://x", pid_file) == "restarted"
    assert killed == [12345]
    assert started
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_scripts.py -v`
Expected: FAIL（`No module named 'scripts'`）

- [ ] **Step 3: 实现三个脚本与 安装.bat**

`scripts/__init__.py`: 空文件。

`scripts/backup.py`:
```python
import shutil
from datetime import datetime, timedelta
from pathlib import Path


def run_backup(db_path, backup_dir, keep_days=30) -> Path:
    db_path = Path(db_path)
    backup_dir = Path(backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)
    target = backup_dir / f"news_{datetime.now().strftime('%Y%m%d')}.db"
    shutil.copy2(db_path, target)
    cutoff = datetime.now() - timedelta(days=keep_days)
    for f in backup_dir.glob("news_*.db"):
        try:
            day = datetime.strptime(f.stem.split("_")[1], "%Y%m%d")
        except (IndexError, ValueError):
            continue
        if day < cutoff:
            f.unlink()
    return target


if __name__ == "__main__":
    from crawler.config import load_settings
    s = load_settings()
    print(run_backup(s.db_path, s.data_dir / "backup"))
```

`scripts/watchdog.py`:
```python
import subprocess
import sys
from pathlib import Path

import requests


def http_ok(url, timeout=3) -> bool:
    try:
        return requests.get(url, timeout=timeout).status_code == 200
    except requests.RequestException:
        return False


def read_pid(pid_file):
    try:
        return int(Path(pid_file).read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def kill_pid(pid) -> None:
    subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True)


def start_web(python_exe, workdir) -> None:
    subprocess.Popen(
        [python_exe, "-m", "web.app"],
        cwd=str(workdir),
        creationflags=getattr(subprocess, "DETACHED_PROCESS", 0),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def check_and_restart(base_url, pid_file, python_exe=None, workdir=None) -> str:
    python_exe = python_exe or sys.executable
    workdir = Path(workdir) if workdir else Path(__file__).resolve().parent.parent
    if http_ok(base_url + "/healthz"):
        return "ok"
    pid = read_pid(pid_file)
    if pid:
        kill_pid(pid)
    start_web(python_exe, workdir)
    return "restarted" if pid else "started"


if __name__ == "__main__":
    from crawler.config import load_settings
    s = load_settings()
    print(check_and_restart(f"http://127.0.0.1:{s.port}", s.data_dir / "web.pid"))
```

`scripts/install.py`:
```python
import socket
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

CRAWL_TASKS = [("矿news抓取07", "07:30"), ("矿news抓取12", "12:30"), ("矿news抓取18", "18:30")]
BACKUP_TASK = ("矿news备份", "19:00")


def sh_quote(value) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def ps_task_script(name, python_exe, arguments, workdir, *,
                   at_logon=False, daily_at=None, repeat_minutes=None,
                   start_when_available=True) -> str:
    parts = [
        f"$action = New-ScheduledTaskAction -Execute {sh_quote(python_exe)} "
        f"-Argument {sh_quote(arguments)} -WorkingDirectory {sh_quote(workdir)}",
    ]
    if at_logon:
        parts.append("$trigger = New-ScheduledTaskTrigger -AtLogOn")
    elif daily_at:
        parts.append(f"$trigger = New-ScheduledTaskTrigger -Daily -At {sh_quote(daily_at)}")
    else:
        parts.append(
            "$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) "
            f"-RepetitionInterval (New-TimeSpan -Minutes {int(repeat_minutes or 5)}) "
            "-RepetitionDuration ([TimeSpan]::MaxValue)")
    flags = []
    if start_when_available:
        flags.append("-StartWhenAvailable")
    flags += ["-RestartCount 3", "-RestartInterval (New-TimeSpan -Minutes 1)"]
    parts.append("$settings = New-ScheduledTaskSettingsSet " + " ".join(flags))
    parts.append(f"Register-ScheduledTask -TaskName {sh_quote(name)} "
                 f"-Action $action -Trigger $trigger -Settings $settings -Force")
    return "; ".join(parts)


def register_task(script: str) -> None:
    subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
                   check=True)


def firewall_rule(port) -> list:
    return ["netsh", "advfirewall", "firewall", "add", "rule", "name=矿news网站",
            "dir=in", "action=allow", "protocol=TCP", f"localport={int(port)}"]


def disable_sleep() -> list:
    return ["powercfg", "/change", "standby-timeout-ac", "0"]


def ensure_venv(requirements, python_exe=None) -> Path:
    python_exe = python_exe or sys.executable
    venv_dir = ROOT / ".venv"
    vpy = venv_dir / "Scripts" / "python.exe"
    if not vpy.exists():
        subprocess.run([python_exe, "-m", "venv", str(venv_dir)], check=True)
    for index_url in ("https://pypi.tuna.tsinghua.edu.cn/simple", "https://pypi.org/simple"):
        result = subprocess.run([str(vpy), "-m", "pip", "install", "-r", str(requirements), "-i", index_url],
                                capture_output=True, text=True)
        if result.returncode == 0:
            return vpy
    raise RuntimeError("依赖安装失败，请检查网络后重试")


def lan_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def main():
    if sys.version_info < (3, 11):
        raise SystemExit("需要 Python 3.11 及以上版本")
    requirements = ROOT / "requirements.txt"
    vpy = ensure_venv(requirements)
    subprocess.run([str(vpy), "-c", "from crawler import store; from crawler.config import load_settings; s=load_settings(); store.init_db(store.connect(s.db_path))"], cwd=str(ROOT), check=True)
    for name, when in CRAWL_TASKS:
        register_task(ps_task_script(name, vpy, "-m crawler.main --once", ROOT, daily_at=when))
    register_task(ps_task_script("矿news网站", vpy, "-m web.app", ROOT, at_logon=True))
    register_task(ps_task_script(BACKUP_TASK[0], vpy, "-m scripts.backup", ROOT, daily_at=BACKUP_TASK[1]))
    register_task(ps_task_script("矿news看门狗", vpy, "-m scripts.watchdog", ROOT, repeat_minutes=5))
    subprocess.run(firewall_rule(load_settings_port()), check=False)
    subprocess.run(disable_sleep(), check=False)
    print(f"安装完成，网站地址：http://{lan_ip()}:{load_settings_port()}")


def load_settings_port():
    sys.path.insert(0, str(ROOT))
    from crawler.config import load_settings
    return load_settings().port


if __name__ == "__main__":
    main()
```

`安装.bat`（仅 ASCII，避免编码坑）:
```
@echo off
python "%~dp0scripts\install.py" %*
pause
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_scripts.py -v`
Expected: 5 passed

- [ ] **Step 5: 提交**

```bash
git add -A
git commit -m "feat: 备份/看门狗/一键安装脚本"
```

---

## Task 14: README 运维文档 + 端到端验收

**Files:**
- Create: `README.md`, `scripts/acceptance.py`
- Test: `tests/test_acceptance.py`

**Interfaces:**
- Consumes: 全部模块
- Produces: `scripts.acceptance.run_checks(settings=None) -> list[(名称, 是否通过, 详情)]`；CLI `python -m scripts.acceptance`（全部通过退出码 0）

- [ ] **Step 1: 写失败测试 + 实现验收脚本**

`tests/test_acceptance.py`:
```python
import dataclasses

from crawler import store
from crawler.config import load_settings
from scripts import acceptance


def test_acceptance_reports_checks(tmp_path):
    settings = dataclasses.replace(load_settings(), db_path=tmp_path / "t.db")
    conn = store.connect(settings.db_path)
    store.init_db(conn)
    item = {"url": "https://e.com/1", "title": "磷矿政策", "summary": "",
            "source_key": "mnr", "published_at": ""}
    cls = {"board": "policy", "minerals": ["磷矿"], "regions": [], "types": []}
    store.insert_article(conn, item, cls, "u1", "t1")
    store.upsert_source(conn, "mnr", "自然资源部", "policy", "https://www.mnr.gov.cn/", True)
    run = store.start_crawl_run(conn, "mnr")
    store.finish_crawl_run(conn, run, "ok", 1, 1)
    conn.commit()
    conn.close()
    checks = acceptance.run_checks(settings)
    names = [c[0] for c in checks]
    assert "今日文章数 ≥ 1" in names
    assert "最近一轮源成功率 ≥ 80%" in names
    assert any(name.startswith("搜索响应") for name in names)
```

`scripts/acceptance.py`:
```python
import time

from crawler import store
from crawler.config import load_settings
from web import queries


def run_checks(settings=None) -> list:
    settings = settings or load_settings()
    conn = store.connect(settings.db_path)
    try:
        checks = []
        stats = queries.today_stats(conn)
        checks.append(("今日文章数 ≥ 1", stats["total"] >= 1, str(stats["total"])))
        health = queries.source_health(conn)
        ok = [h for h in health if h["status"] == "ok"]
        ratio = (len(ok) / len(health)) if health else 0.0
        checks.append(("最近一轮源成功率 ≥ 80%", ratio >= 0.8, f"{len(ok)}/{len(health)}"))
        commodities = queries.distinct_commodities(conn)
        checks.append(("价格品种 ≥ 12", len(commodities) >= 12, str(len(commodities))))
        start = time.time()
        queries.search_articles(conn, q="磷矿", limit=10)
        cost_ms = (time.time() - start) * 1000
        checks.append(("搜索响应 < 1000ms", cost_ms < 1000, f"{cost_ms:.0f}ms"))
    finally:
        conn.close()
    return checks


def main():
    checks = run_checks()
    failed = 0
    for name, ok, detail in checks:
        print(f"[{'通过' if ok else '未通过'}] {name}：{detail}")
        failed += 0 if ok else 1
    print(f"结论：{'全部通过' if failed == 0 else f'{failed} 项未通过'}")
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 运行测试确认通过**

Run: `python -m pytest tests/test_acceptance.py -v`
Expected: 1 passed

- [ ] **Step 3: 写 README.md（中文运维文档）**

README 必须包含以下小节，全部使用真实命令与路径：
1. **项目简介**：三大板块、抓取节奏、只存标题+摘要+链接的限制
2. **文件结构**：与计划"文件结构"一节一致
3. **首次安装**：装 Python 3.11+（勾 Add to PATH）→ 双击 `安装.bat`（或 `python scripts\install.py`）→ 浏览器打开 `http://<IP>:8080`
4. **日常操作**：查看首页/行情/政策/搜索；源健康页"立即抓取一次"；备份文件位置 `data/backup/`
5. **加新源/改源教程**：YAML 字段逐项说明（key/name/board/url/urls/referer/encoding/list/detail/parser/table/regex/commodity_map）；标准流程 = 写 YAML → `python -m tools.snapshot <key>` → 看样本填选择器 → 在 `tests/` 对应测试文件加该 key → `python -m pytest tests/test_sources_news.py -v` → 跑 `python -m crawler.main --once` 验证
6. **故障排查**：源失败看 `logs/snapshots/` 快照 → 改选择器 → 跑测试；网站打不开检查看门狗任务与 `data/web.pid`；端口冲突改 `config/settings.yaml`
7. **已知限制**：公众号不抓；被排除源清单（大商所/郑商所/中国矿业网/矿道网/SMM/工信部/百度新闻/金投网）；被 `enabled: false` 的源及原因
8. **备份与恢复**：备份在 `data/backup/news_YYYYMMDD.db`，恢复 = 停网站服务 → 用备份覆盖 `data/news.db` → 重启
9. **二期规划**：推送、AI 摘要、浏览器抓取、竞品监控、云部署

- [ ] **Step 4: 真实环境端到端验收**

依次执行：
```bash
python -m pytest -v
python -m crawler.main --once
python -m scripts.acceptance
```
再启动网站验证（另开一个终端，或直接双击网站计划任务）：
```bash
python -m web.app
```
浏览器/curl 验证：`http://127.0.0.1:8080/`、`/prices`、`/policy`、`/search?q=磷矿`、`/sources` 均可打开且首页显示"今日新增"。
`python -m scripts.acceptance` 输出的"未通过"项：分析原因逐项修复（源失败→按第 6 节流程修；价格品种不足 12→补源或核对品种映射）。**验收标准见 spec 第 11 节**，正式交付前需连续 3 天由计划任务自动运行后复查源健康页。

- [ ] **Step 5: 提交**

```bash
git add -A
git commit -m "docs: README 运维文档 + 端到端验收脚本"
```

---

## 执行说明

- 任务按 1→14 顺序执行，每个任务以测试全绿 + git 提交收尾
- 每个任务开始前先跑 `python -m pytest`（或相关子集）确认当前基线是绿的
- 涉及真实网络的步骤（snapshot、真实抓取、ECharts 下载）若因网络/反爬暂时失败：先用离线样本与手工 JSON 样本保住测试，把该源标记 `enabled: false` 并在 README"已知限制"记录，**不得跳过测试或降低断言**
- 全局约束（spec 红线）适用于每个任务，尤其是"只存标题+摘要+链接"


