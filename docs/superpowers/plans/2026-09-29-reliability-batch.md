# 可靠性第一批（静默源/规则版本/备份验证/进展展示）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** 让两个站能自己发现"悄悄停更的源"、能回答"这批数据由哪版规则产出"、备份必须验证过才算数、台账列表能直接看到项目进展。

**Architecture:** 四项改动都在既有链路上增量落地，不引入新服务、新依赖。矿_news（Python/SQLite）改 `crawler/`+`scripts/`；竞品站（Node）改 `scripts/weekly-run.mjs` 与 `src/App.jsx`。

**Tech Stack:** Python 3.12 + SQLite（矿_news）；Node 24 + React（竞品站）。测试：pytest / node:test。

## Global Constraints

- **不引入新依赖**（两边都不加 npm/pip 包）
- **不改变已发布数据的语义**：静默检测、规则版本号都是"只增信息"，不得改动既有字段含义
- 静默阈值统一 **3 天**；必须排除"本来就低频"的误报（配置里停用的源 / 从未跑过的源分开表述）
- 规则版本号 = 规则文件**内容哈希**（不是时间戳），同内容必须同版本、改一个字必须变
- 备份验证失败时**必须删除坏备份并以非零码退出**（宁可没有备份，也不要一个坏备份被当成好备份）
- 台账列表新增「进展」列是**只读展示**，不得改动分组结果（`group_projects.mjs` 本次不动）
- 中文注释与文案；提交信息中文
- 矿_news 测试基线 **299 passed / 1 skipped**，竞品站 `node --test tests/*.test.mjs` 基线 **35 passed**，两边都不许减少

---

## Task 1：矿_news 静默源检测

**Files:**
- Modify: `E:\矿_news\scripts\ai_check.py`
- Test: `E:\矿_news\tests\test_ai_check.py`

**Interfaces:**
- Produces: `silent_sources(conn, enabled_keys, days=3, now=None) -> list[dict]`，每项 `{"key","name","last_nonzero","runs","reason"}`；`reason ∈ {"3 天零产出","从未成功抓取"}`
- Consumes: 既有 `crawler.config.load_sources()`、`crawler.store`、`crawler.report`

- [ ] **Step 1: 写失败测试**（追加到 `tests/test_ai_check.py`，复用文件里已有的 `make_settings`）

```python
def _add_run(conn, key, started_at, status="ok", items_found=0):
    """直接插轮次记录：既有 store.start_crawl_run 只能写"现在"，测不了 3 天前。"""
    conn.execute(
        "INSERT INTO crawl_runs(source_key,started_at,finished_at,status,items_found,items_new)"
        " VALUES(?,?,?,?,?,0)", (key, started_at, started_at, status, items_found))
    conn.commit()


def _run_days_ago(conn, key, days_ago, **kw):
    ts = (datetime.now() - timedelta(days=days_ago)).strftime("%Y-%m-%d %H:%M:%S")
    _add_run(conn, key, ts, **kw)


def test_silent_sources_flags_three_day_zero(tmp_path):
    """近 3 天有成功轮次但一条都没抓到 → 疑似静默。"""
    settings = make_settings(tmp_path)
    conn = store.connect(settings.db_path)
    store.init_db(conn)
    _run_days_ago(conn, "dead_source", 2, items_found=0)
    _run_days_ago(conn, "dead_source", 1, items_found=0)
    rows = ai_check.silent_sources(conn, ["dead_source"], days=3)
    assert [r["key"] for r in rows] == ["dead_source"]
    assert rows[0]["reason"] == "3 天零产出"
    conn.close()


def test_silent_sources_ignores_sources_with_recent_output(tmp_path):
    settings = make_settings(tmp_path)
    conn = store.connect(settings.db_path)
    store.init_db(conn)
    _run_days_ago(conn, "ok_source", 2, items_found=0)
    _run_days_ago(conn, "ok_source", 1, items_found=7)
    assert ai_check.silent_sources(conn, ["ok_source"], days=3) == []
    conn.close()


def test_silent_sources_separates_never_run(tmp_path):
    """从未成功抓过的启用源单独表述，不和'零产出'混为一谈。"""
    settings = make_settings(tmp_path)
    conn = store.connect(settings.db_path)
    store.init_db(conn)
    rows = ai_check.silent_sources(conn, ["never_run"], days=3)
    assert rows[0]["reason"] == "从未成功抓取"
    conn.close()


def test_silent_sources_ignores_disabled_sources(tmp_path):
    """传入的 enabled_keys 之外（已停用/已删除）的源不报。"""
    settings = make_settings(tmp_path)
    conn = store.connect(settings.db_path)
    store.init_db(conn)
    _run_days_ago(conn, "old_source", 1, items_found=0)
    assert ai_check.silent_sources(conn, [], days=3) == []
    conn.close()


def test_silent_sources_ignores_failed_runs(tmp_path):
    """失败轮次不算'零产出'（那种由既有的失败源段落负责报）。"""
    settings = make_settings(tmp_path)
    conn = store.connect(settings.db_path)
    store.init_db(conn)
    _run_days_ago(conn, "err_source", 1, status="error", items_found=0)
    assert ai_check.silent_sources(conn, ["err_source"], days=3) == []
    conn.close()
```

（顶部 import 补 `from datetime import datetime, timedelta`。）

- [ ] **Step 2: 跑测试确认失败**：`.venv\Scripts\python.exe -m pytest tests\test_ai_check.py -v` → `AttributeError: module 'scripts.ai_check' has no attribute 'silent_sources'`

- [ ] **Step 3: 实现**

在 `scripts/ai_check.py` 加入（并接入 `generate_report`）：

```python
SILENT_DAYS = 3


def silent_sources(conn, enabled_keys, days=SILENT_DAYS, now=None) -> list:
    """近 N 天有成功轮次、却一条都没抓到的启用源；从未成功抓取的单独表述。

    与"失败源"互补：失败源报的是 status=error，这里报的是"跑成功了但颗粒无收"，
    源站改版/被反爬最常表现为后者（静默 0 行，不报错）。
    """
    now = now or datetime.now()
    cutoff = (now - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    enabled = {k for k in (enabled_keys or [])}
    rows = conn.execute(
        "SELECT source_key, COUNT(*) runs, SUM(items_found) found,"
        " MAX(CASE WHEN items_found > 0 THEN started_at END) last_nonzero"
        " FROM crawl_runs WHERE status='ok' AND started_at >= ?"
        " GROUP BY source_key", (cutoff,)).fetchall()
    by_key = {r["source_key"]: r for r in rows}
    out = []
    for key in sorted(enabled):
        r = by_key.get(key)
        if r is None:
            out.append({"key": key, "runs": 0, "last_nonzero": "",
                        "reason": "从未成功抓取"})
        elif not r["found"]:
            out.append({"key": key, "runs": r["runs"],
                        "last_nonzero": r["last_nonzero"] or "",
                        "reason": "%d 天零产出" % days})
    return out
```

`generate_report()` 里：用 `load_sources()` 取启用源 key，调用后追加一段：

```
### 疑似静默源（近 3 天零产出）
- 某某源（最后有产出：2026-09-20 12:30）
- 某某源（从未成功抓取）
```

**不改变退出码**（静默是警告不是失败——有些厅局源本来就低频），但必须在报告里显眼。

- [ ] **Step 4: 跑测试**：`pytest tests\test_ai_check.py -v` → 全绿；`pytest -q` → 无回归
- [ ] **Step 5: 实测**：`.venv\Scripts\python.exe -m scripts.ai_check` 看真实库输出（应能看到真实源的产出情况）
- [ ] **Step 6: 提交**：`git add scripts/ai_check.py tests/test_ai_check.py && git commit -m "feat(check): 静默源检测（近3天零产出单独告警，不改变退出码）"`

---

## Task 2：矿_news 规则版本号

**Files:**
- Create: `E:\矿_news\crawler\rules_version.py`
- Modify: `E:\矿_news\db\schema.sql`、`E:\矿_news\crawler\store.py`、`E:\矿_news\crawler\main.py`、`E:\矿_news\scripts\ai_check.py`
- Test: `E:\矿_news\tests\test_rules_version.py`

**Interfaces:**
- Produces: `compute_rules_version(config_dir: Path) -> str`（形如 `rv-1a2b3c4d5e`）
- Produces: `store.start_crawl_run(conn, source_key, rules_version="")`（新增可选参数，向后兼容）
- Consumes: Task 1 的 `ai_check.generate_report`

- [ ] **Step 1: 写失败测试**（新建 `tests/test_rules_version.py`）

```python
from pathlib import Path

from crawler.rules_version import compute_rules_version


def _cfg(tmp_path: Path) -> Path:
    (tmp_path / "sources").mkdir()
    (tmp_path / "sources" / "a.yaml").write_text("key: a\n", encoding="utf-8")
    (tmp_path / "tags.yaml").write_text("矿种: []\n", encoding="utf-8")
    return tmp_path


def test_same_content_same_version(tmp_path):
    d = _cfg(tmp_path)
    assert compute_rules_version(d) == compute_rules_version(d)


def test_changed_content_changes_version(tmp_path):
    d = _cfg(tmp_path)
    before = compute_rules_version(d)
    (d / "sources" / "a.yaml").write_text("key: a\nurl: x\n", encoding="utf-8")
    assert compute_rules_version(d) != before


def test_new_file_changes_version(tmp_path):
    d = _cfg(tmp_path)
    before = compute_rules_version(d)
    (d / "sources" / "b.yaml").write_text("key: b\n", encoding="utf-8")
    assert compute_rules_version(d) != before


def test_version_is_stable_and_prefixed(tmp_path):
    v = compute_rules_version(_cfg(tmp_path))
    assert v.startswith("rv-") and len(v) == 13  # rv- + 10 位十六进制


def test_missing_dir_returns_unknown(tmp_path):
    assert compute_rules_version(tmp_path / "nope") == "rv-unknown"
```

- [ ] **Step 2: 确认失败** → `ModuleNotFoundError: crawler.rules_version`
- [ ] **Step 3: 实现**

`crawler/rules_version.py`：

```python
"""规则版本号：把 config/ 下决定"抓什么、怎么分类"的文件内容哈希成版本号。

用途：回答"这批数据是哪版规则产出的"——排查数据异常时先对齐版本，
避免拿现在的规则去解释几天前规则抓出来的数据。
"""
import hashlib
from pathlib import Path

PREFIX = "rv-"
GLOBS = ("sources/*.yaml", "tags.yaml", "settings.yaml")


def compute_rules_version(config_dir) -> str:
    config_dir = Path(config_dir)
    if not config_dir.exists():
        return PREFIX + "unknown"
    h = hashlib.sha256()
    files = []
    for pattern in GLOBS:
        files.extend(sorted(config_dir.glob(pattern)))
    for path in sorted(files, key=lambda p: str(p.relative_to(config_dir))):
        h.update(str(path.relative_to(config_dir)).replace("\\", "/").encode("utf-8"))
        h.update(b"\0")
        h.update(path.read_bytes())
        h.update(b"\0")
    return PREFIX + h.hexdigest()[:10]
```

`store.py`：复用**已有的** `_ensure_column`，在 `init_db` 里加一行（老库自动补列）：

```python
    _ensure_column(conn, "crawl_runs", "rules_version", "rules_version TEXT NOT NULL DEFAULT ''")
```

`schema.sql` 的 `crawl_runs` 建表语句同步加 `rules_version TEXT NOT NULL DEFAULT ''`；
`start_crawl_run(conn, source_key, rules_version="")` 写进 INSERT（新增可选参数，老调用方不受影响）。

`main.py`：轮次开始时 `rv = compute_rules_version(settings.config_dir)`，日志打一行
`[规则版本] rv-xxxxxxxxxx`，并把它传给每次 `start_crawl_run`。

`ai_check.py` 报告头部加一行 `规则版本：rv-xxxxxxxxxx`。

- [ ] **Step 4: 跑测试** → 新测全绿 + `pytest -q` 无回归（重点确认老库迁移不炸：`test_config_store.py` 相关用例）
- [ ] **Step 5: 实测** → `python -m crawler.main --once` 日志里能看到规则版本；改一个 yaml 字再跑，版本必变
- [ ] **Step 6: 提交** → `feat(rules): 规则版本号（内容哈希）+ 随轮次入库与报告`

---

## Task 3：矿_news 备份验证

**Files:**
- Modify: `E:\矿_news\scripts\backup.py`
- Test: `E:\矿_news\tests\test_backup.py`（新建）

**Interfaces:**
- Produces: `verify_backup(src_path, backup_path) -> tuple[bool, str]`（通过/不通过 + 中文原因）
- Produces: `run_backup(...)` 校验失败时删除坏备份并 `raise RuntimeError`

- [ ] **Step 1: 写失败测试**

```python
import sqlite3

import pytest

from scripts.backup import run_backup, verify_backup


def _mkdb(path, rows=3):
    conn = sqlite3.connect(path)
    conn.executescript("CREATE TABLE articles(id INTEGER PRIMARY KEY, title TEXT);")
    conn.executemany("INSERT INTO articles(title) VALUES(?)", [("t%d" % i,) for i in range(rows)])
    conn.commit()
    conn.close()
    return path


def test_verify_ok(tmp_path):
    src = _mkdb(tmp_path / "news.db", rows=5)
    target = run_backup(src, tmp_path / "backup")
    ok, why = verify_backup(src, target)
    assert ok, why


def test_verify_detects_row_mismatch(tmp_path):
    src = _mkdb(tmp_path / "news.db", rows=5)
    target = run_backup(src, tmp_path / "backup")
    conn = sqlite3.connect(target)
    conn.execute("DELETE FROM articles WHERE id > 2")   # 模拟备份不完整
    conn.commit()
    conn.close()
    ok, why = verify_backup(src, target)
    assert not ok and "条数" in why


def test_backup_deleted_when_verify_fails(tmp_path, monkeypatch):
    src = _mkdb(tmp_path / "news.db", rows=5)
    monkeypatch.setattr("scripts.backup.verify_backup", lambda s, b: (False, "模拟校验失败"))
    with pytest.raises(RuntimeError, match="备份校验失败"):
        run_backup(src, tmp_path / "backup")
    assert list((tmp_path / "backup").glob("news_*.db")) == []   # 坏备份必须删掉
```

- [ ] **Step 2: 确认失败** → `ImportError: cannot import name 'verify_backup'`
- [ ] **Step 3: 实现**

`scripts/backup.py` 加：

```python
TABLES = ("articles", "prices", "feedback", "crawl_runs", "marketing_copy")


def verify_backup(src_path, backup_path) -> tuple:
    """校验备份可读且条数与源库一致。

    只对比行数就够：integrity_check 负责结构完整，行数负责"确实是这一版的完整拷贝"。
    """
    backup_path = Path(backup_path)
    if not backup_path.exists() or backup_path.stat().st_size == 0:
        return False, "备份文件不存在或为空"
    try:
        b = sqlite3.connect("file:%s?mode=ro" % backup_path.as_posix(), uri=True)
        try:
            if b.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                return False, "完整性检查未通过（文件损坏）"
            s = sqlite3.connect("file:%s?mode=ro" % Path(src_path).as_posix(), uri=True)
            try:
                for table in TABLES:
                    try:
                        n_src = s.execute("SELECT count(*) FROM %s" % table).fetchone()[0]
                        n_bak = b.execute("SELECT count(*) FROM %s" % table).fetchone()[0]
                    except sqlite3.OperationalError:
                        continue          # 该表在旧库里可能不存在
                    if n_src != n_bak:
                        return False, "%s 条数不一致（源 %d / 备份 %d）" % (table, n_src, n_bak)
            finally:
                s.close()
        finally:
            b.close()
    except sqlite3.DatabaseError as exc:
        return False, "备份无法读取：%s" % exc
    return True, "校验通过"
```

`run_backup` 末尾（清理旧备份之前）插入：

```python
    ok, why = verify_backup(db_path, target)
    if not ok:
        target.unlink(missing_ok=True)
        raise RuntimeError("备份校验失败（已删除坏备份）：%s" % why)
```

`__main__` 里打印目标路径与校验结果。

- [ ] **Step 4: 跑测试** → 全绿 + `pytest -q` 无回归
- [ ] **Step 5: 实测** → `.venv\Scripts\python.exe -m scripts.backup`，确认输出含"校验通过"
- [ ] **Step 6: 提交** → `feat(backup): 备份后校验完整性与条数，失败即删除并报错`

---

## Task 4：竞品站 静默平台检测 + 规则版本号

**Files:**
- Modify: `E:\竞品情报信息抓取\prototype\scripts\weekly-run.mjs`
- Test: `E:\竞品情报信息抓取\prototype\tests\weekly-run.test.mjs`

**Interfaces:**
- Produces: `silentPlatforms(scanState, days=3, now=new Date()) -> string[]`（返回平台 id 列表）
- Produces: `rulesVersion(configDir) -> string`（`rv-` + 10 位十六进制）
- Consumes: 既有 scan-state 结构（`{id: {name,lastScanAt,lastStatus,discovered,...}}`）

- [ ] **Step 1: 写失败测试**（追加到 `tests/weekly-run.test.mjs`）

```js
import { silentPlatforms, rulesVersion } from '../scripts/weekly-run.mjs';

test('silentPlatforms 报出 3 天零产出的平台', () => {
  const now = new Date('2026-09-29T06:00:00Z');
  const state = {
    a: { lastStatus: 'ok', discovered: 0, firstSeenAt: '2026-09-01T00:00:00Z', lastNonZeroAt: '2026-09-25T06:00:00Z' },
    b: { lastStatus: 'ok', discovered: 3, firstSeenAt: '2026-09-01T00:00:00Z', lastNonZeroAt: '2026-09-29T06:00:00Z' },
  };
  assert.deepEqual(silentPlatforms(state, 3, now), ['a']);
});

test('silentPlatforms 不报从未见过的平台（未扫描不等于静默）', () => {
  const state = { c: { lastStatus: 'failed', firstSeenAt: '2026-09-01T00:00:00Z' } };
  assert.deepEqual(silentPlatforms(state, 3, new Date('2026-09-29T06:00:00Z')), []);
});

test('silentPlatforms 从 firstSeenAt 起算（新加入的平台不立刻报警）', () => {
  const state = { d: { lastStatus: 'ok', discovered: 0, firstSeenAt: '2026-09-28T00:00:00Z' } };
  assert.deepEqual(silentPlatforms(state, 3, new Date('2026-09-29T06:00:00Z')), []);
});

test('rulesVersion 同内容同版本、改内容即变', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'rv-'));
  fs.writeFileSync(path.join(dir, 'scan-rules.json'), '[]');
  const v1 = rulesVersion(dir);
  assert.match(v1, /^rv-[0-9a-f]{10}$/);
  assert.strictEqual(v1, rulesVersion(dir));            // 同内容稳定
  fs.writeFileSync(path.join(dir, 'scan-rules.json'), '[{}]');
  assert.notStrictEqual(v1, rulesVersion(dir));         // 改内容即变
});
```

（测试文件顶部补 `import fs from 'node:fs'`、`import os from 'node:os'`、`import path from 'node:path'`。）

- [ ] **Step 2: 确认失败** → `does not provide an export named 'silentPlatforms'`
- [ ] **Step 3: 实现**

`weekly-run.mjs`：

```js
// 静默平台：抓取成功但连续 3 天零发现（源站改版/被反爬的典型表现：不报错、只是没数据）
export function silentPlatforms(scanState, days = 3, now = new Date()) {
  const limitMs = days * 86400_000;
  const out = [];
  for (const [id, st] of Object.entries(scanState || {})) {
    if (!st || st.lastStatus !== 'ok') continue;          // 失败由覆盖率门禁负责报
    const since = st.lastNonZeroAt || st.firstSeenAt;
    if (!since) continue;                                  // 没有起点信息就不猜
    if (now.getTime() - new Date(since).getTime() >= limitMs) out.push(id);
  }
  return out.sort();
}

// 规则版本号：回答"这批数据是哪版规则抓的"（dir 可传入，便于测试）
export function rulesVersion(dir = path.join(root, 'config')) {
  const files = ['scan-rules.json', 'platform-library.json']
    .map(f => path.join(dir, f)).filter(existsSync).sort();
  const h = createHash('sha256');
  for (const f of files) { h.update(path.basename(f)); h.update(readFileSync(f)); }
  return 'rv-' + h.digest('hex').slice(0, 10);
}
```

每次扫描后更新 scan-state 条目：`firstSeenAt`（首次创建时写一次）、`lastNonZeroAt`（`discovered > 0` 时更新为当前 ISO 时间）。
`latest-run.json` 增字段：`rulesVersion`、`coverage.silent`（`silentPlatforms()` 结果）。
日志里打印 `规则版本 rv-xxxxxxxxxx` 与静默平台告警行（有则打印）。

- [ ] **Step 4: 跑测试** → `node --test tests/weekly-run.test.mjs` 全绿，全套 `node --test tests/*.test.mjs` 35+ 无回归
- [ ] **Step 5: 提交** → `feat(weekly): 静默平台检测（3天零发现）+ 规则版本号入报告`

---

## Task 5：竞品站 进展展示（列表列 + 审计摘要 + 详情陈旧提示）

**Files:**
- Modify: `E:\竞品情报信息抓取\prototype\src\App.jsx`、`E:\竞品情报信息抓取\prototype\src\styles.css`（或既有 css 文件）
- 参考：`src/App.jsx` 里 `SourcePage` 读取 `public/data/*.json` 的既有写法

**Interfaces:**
- Consumes: `src/data/intelligence.json` 每条的 `openStatus` / `bidOpenDate` / `resultGap` / `date`；`public/data/latest-run.json` 的 `bidOpenAudit.summary`
- Produces: 列表新增「进展」列；表格上方审计摘要条；详情页「距今 N 天」提示

- [ ] **Step 1: 先看现状**（读 `App.jsx` 的 `LEDGER_COLUMNS`、列表渲染行、`Detail` 组件、`SourcePage` 的 JSON 读取方式），确认：
  - 列表当前 9 列：客户/矿种/产品线/竞品/金额/成交方式/发布日期/来源/置信度
  - `Detail` 已有「开标日期」与 `resultGap` 提示
  - `SourcePage` 如何 fetch `public/data/*.json`（照它的方式读 `latest-run.json`）

- [ ] **Step 2: 实现「进展」列**

在 `LEDGER_COLUMNS` 的「成交方式」之后插入 `'进展'`，单元格渲染：

```jsx
// 进展 = 开标状态 + 结果缺口；让"已开标却迟迟没结果"的项目在列表就能看见
const progressCell = item => {
  const st = item.openStatus || '未披露';
  return <span className={`prog prog-${st}`}>{st}{item.resultGap ? <i className="prog-gap">待结果</i> : null}</span>;
};
```

- [ ] **Step 3: 实现审计摘要条**

在筛选器下方、表格上方加一行（数据来自 `latest-run.json` 的 `bidOpenAudit.summary`）：`开标审计：共 44 个项目 · 已开标 19 · 待开标 3 · 未披露 22 · 已开标但无结果 14`；点击"已开标但无结果"等价于筛选 `resultGap`。读取失败时整条**静默隐藏**（不影响主表）。

- [ ] **Step 4: 详情页「距今 N 天」**

在 `Detail` 的「发布日期」指标旁补一个小字：`距今 N 天`（N ≥ 30 时标红提示可能已陈旧）。

- [ ] **Step 5: 样式**：`.prog` 三态配色沿用既有 `wx-via-*` 的浅底深字风格；`.prog-gap` 用警示色小标签

- [ ] **Step 6: 构建与视觉核验**
  - `npm run build` 必须成功
  - 用 Playwright 打开 `dist/client/index.html`（本地静态服务），确认：进展列有值、待结果标记出现、摘要条数字与 `latest-run.json` 一致、详情页显示「距今 N 天」；**截一张图**存 `.superpowers/sdd/progress-column.png` 供人工核验
  - 控制台必须无 JS 错误

- [ ] **Step 7: 提交** → `feat(ui): 台账列表加「进展」列与开标审计摘要，详情补陈旧天数`

---

## Task 6：发布与核验（控制者执行）

- [ ] **竞品站**：`git pull --rebase` → push `main` → 等 Pages 部署 → 抓 `https://white1star.github.io/Xiangsu/` 确认新 bundle 含「进展」文案 → 触发服务器镜像同步 → 抓 `http://39.96.27.206/Xiangsu/` 确认
- [ ] **竞品站服务器**：确认 `/opt/xiangsu` 能拿到新 `weekly-run.mjs`（每日 05:30 cron 会 `git pull`；如需要可手动触发一次并检查日志里有规则版本号与静默告警）
- [ ] **矿_news 服务器**：`/opt/news` 是代码副本不是 git 仓库 → 上传改动的 `scripts/ai_check.py`、`crawler/rules_version.py`、`crawler/store.py`、`crawler/main.py`、`db/schema.sql`，跑一次 `crawler.main --once` 确认迁移与日志正常，再跑 `scripts.ai_check` 看静默段与规则版本
- [ ] **矿_news 本机**：`python -m scripts.backup` 确认输出"校验通过"
- [ ] 更新 `.superpowers/sdd/server_deploy.md` 与两个仓的 AGENTS.md（新增的检测项与版本号说明）

## 回滚

- 矿_news：`git revert`；DB 新列无害（旧代码忽略它）
- 竞品站：`git revert` + 重新 push（Pages 自动回退）+ 服务器镜像同步
