# AI 巡检维护手册

本手册面向"AI 巡检"：**巡检 = 先启动爬虫抓一轮，再体检，发现问题按本手册修复**。
触发词：巡检、体检、AI 巡检、ai_run、ai_check。

## 1. 一键巡检

```powershell
python -m scripts.ai_run
```

执行顺序：

1. **启动爬虫**：调用 `crawler.main.run_once()` 跑一轮真实抓取（等待完成，约 2~4 分钟），打印各源摘要
2. **体检**：调用体检模块 `scripts.ai_check`，对数据库和快照做全面检查，报告写入 `logs\ai_check_YYYYMMDD.md`
3. **给建议**：打印"下一步建议"；有失败源时提示按本手册修复

退出码：`0` 一切正常；`1` 有源失败或体检异常。

只体检、不抓取（快速看现状）：

```powershell
python -m scripts.ai_check
```

报告固定输出四节：各源最近一轮、失败源与快照、数据概览、建议动作。

## 2. 巡检流程（固定三步）

1. **抓**：`python -m scripts.ai_run`（内部先跑 `python -m crawler.main --once`）
2. **看**：读 `logs\ai_check_YYYYMMDD.md`，重点看「二、失败源与快照」和「四、建议动作」
3. **修**：按第 3 节修源四步法处理失败源；修完复跑 `python -m scripts.ai_run` 验证，直到退出码为 0

## 3. 修源四步法（某个源抓取失败）

1. **抓样本**：`python -m tools.snapshot <key>`（失败时用 `--url 覆盖地址` 重试），样本落到 `tests\fixtures\<key>_list.html`
2. **改 YAML**：先打开 `logs\snapshots\` 里该源最新快照对照真实页面，再改 `config\sources\<key>.yaml` 的选择器
3. **跑测试**：新闻/政策源 `python -m pytest tests/test_sources_news.py`；价格 HTML 源 `python -m pytest tests/test_price_html_sources.py`
4. **复跑验证**：`python -m crawler.main --once`，再打开 `http://127.0.0.1:8080/sources` 看该源状态是否恢复 `成功`

注意：

- 失败且已拿到响应体时，每源自动保留最近 3 份原始响应快照（`logs\snapshots\<key>_YYYYMMDD_HHMMSS.html`）；连接级失败（DNS/超时）没有快照，先查 `logs\crawler_YYYYMMDD.log`
- 源站长期不可用时，在 `config\sources\<key>.yaml` 设 `enabled: false`，并到 README「已知限制」登记

## 4. 重打标（改了关键词词典之后）

改过 `config\tags.yaml`（矿种/类型/地区词典）后，历史文章需要按新词典重新打标：

```powershell
python -m crawler.retag
```

按标题+摘要重算全部文章的矿种/地区/类型标签，不会改动标题、链接与正文摘要。

## 5. 备份与恢复

- 自动备份：计划任务"矿news备份"每天 19:00，生成 `data\backup\news_YYYYMMDD.db`，清理 30 天前的旧备份
- 手动备份：`python -m scripts.backup`，或源健康页 `/sources` → 点"立即备份数据库"
- 恢复：停网站（并暂停看门狗与抓取任务，避免占用/写入）→ 把备份改名覆盖 `data\news.db` → 重启网站 → 跑 `python -m scripts.acceptance` 验证

## 6. 定时巡检建议

让巡检每天自动跑一轮，失败时留报告给人工/AI 处理：

- Windows 计划任务（管理员 PowerShell）：

```powershell
schtasks /create /tn "矿news巡检" /tr "python -m scripts.ai_run" /sc daily /st 08:00 /rl highest /f
```

  或在项目目录运行 `python scripts\install.py` 里已有的任务注册逻辑后，手动加一条指向 `python -m scripts.ai_run` 的每日任务。

- Linux/cron（如迁移到服务器）：

```cron
0 8 * * * cd /path/to/news && python -m scripts.ai_run >> logs/ai_run_cron.log 2>&1
```

巡检建议安排在每日最后一次抓取（18:30）之后，或直接每天 08:00 巡检前再抓一轮。

## 7. 给 AI 的巡检提示词模板

```
跑 python -m scripts.ai_run，读 logs/ai_check_*.md，按 docs/ai-maintenance.md 修失败源，
跑全量 python -m pytest，全部通过后提交（commit 信息写清楚修了哪个源/什么问题）。
```

更细的分工版本：

```
1. 运行 python -m scripts.ai_run，记录退出码
2. 打开最新 logs/ai_check_*.md，逐条处理「二、失败源与快照」：
   - 有快照：对照 logs/snapshots/ 下的 HTML，按修源四步法改 config/sources/<key>.yaml
   - 无快照：先看 logs/crawler_*.log 判断网络/DNS 还是改版
3. python -m pytest tests/test_sources_news.py 通过后，再跑 python -m crawler.main --once 验证
4. python -m pytest 全量必须全绿；最后按仓库规范提交
```

## 8. 巡检异常处置速查

| 现象 | 处置 |
|---|---|
| 报告提示"数据库读取失败" | 检查 `data\news.db` 是否被占用/损坏；按第 5 节恢复 |
| 报告提示"未留下快照" | 连接级失败，先重试 `python -m crawler.main --once`，再查网络/DNS |
| 今日新增为 0 | 确认计划任务是否执行；跑 `python -m crawler.main --once` 手动补 |
| 价格品种数不足 12 | 按 README 5.1 核对价格源 `commodity_map`；生意社 `pp100` 重点核对 Referer |
| 单源失败但整轮正常 | 属单源隔离，按修源四步法单独修复即可，不影响其他源 |
