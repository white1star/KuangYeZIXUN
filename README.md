# 矿业资讯内部站（矿_news）运维手册

## 1. 项目简介

唐山像素智能科技有限公司内网资讯站：每天自动抓取**价格行情 / 政策法规 / 行业新闻**三大板块，全员浏览器访问，支持标签筛选、自动去重与历史搜索（FTS5 全文检索）。

- 抓取节奏：每天 **07:30 / 12:30 / 18:30** 三次（Windows 计划任务，错过自动补跑）
- 访问地址：`http://<本机IP>:8080`（本机也可用 `http://127.0.0.1:8080`，端口 8080 可在 `config/settings.yaml` 修改）
- 存储红线：**只存标题 + ≤200 字摘要 + 原文链接 + 元数据**，不存正文全文；请求间隔 ≥1 秒，不绕过登录墙/验证码
- 技术栈：Python 3.11+、requests + BeautifulSoup、FastAPI + Jinja2、SQLite(FTS5)、ECharts 本地静态文件
- 维护原则：加源/改源/改词典只改 YAML 配置，不改代码

---

## 2. 文件结构

```
E:\矿_news\
├── config\
│   ├── settings.yaml            全局参数（端口/阈值/超时）
│   ├── tags.yaml                矿种/类型/地区关键词词典
│   ├── notify.example.yaml      反馈邮件通知示例（真实配置 notify.local.yaml 不入库）
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
│   ├── notify.py                反馈邮件通知（QQ 邮箱 SMTP）
│   ├── queries.py               页面查询
│   ├── templates\*.html         Jinja2 模板
│   └── static\                  样式/style.css、vendor/echarts.min.js
├── scripts\
│   ├── backup.py                每日备份（保留30天）
│   ├── watchdog.py              健康检查+自动拉起
│   ├── install.py               一键安装（venv/计划任务/防火墙/关睡眠）
│   ├── acceptance.py            端到端自检（python -m scripts.acceptance）
│   ├── ai_run.py                AI 巡检总入口：先抓一轮，再体检，给修复建议
│   └── ai_check.py              巡检体检：源状态/失败快照/数据概览/建议报告
├── tools\snapshot.py            抓源站样本到 tests/fixtures（接入与修源用）
├── docs\ai-maintenance.md       AI 巡检维护手册（修源四步法/重打标/备份恢复）
├── tests\                       pytest 测试 + fixtures 离线样本
├── data\                        运行时生成（gitignore）：news.db、web.pid、backup\
├── logs\                        运行时生成（gitignore）：crawler_YYYYMMDD.log、snapshots\
├── requirements.txt
├── README.md                    中文运维文档（本文件）
└── 安装.bat                     一行转发（调 python scripts\install.py）
```

---

## 3. 首次安装

**前置条件：安装 Python 3.11 或更高版本**（官网 python.org 下载，安装时务必勾选 **Add Python to PATH**）。安装完成后在命令行输入 `python --version` 能显示版本号即可。

**步骤一：以管理员身份运行安装脚本（重要）**

> **`安装.bat` 必须右键"以管理员身份运行"。** 否则注册计划任务、添加防火墙规则会静默失败，脚本仍可能显示"安装完成"。

1. 在项目文件夹 `E:\矿_news` 中找到 `安装.bat`
2. 右键 → **以管理员身份运行**（等同命令：`python scripts\install.py`）
3. 脚本自动完成：创建 `.venv` 虚拟环境 → 安装依赖 → 初始化数据库 → 注册 6 个计划任务 → 开放 8080 防火墙 → 关闭睡眠
4. 窗口最后会打印访问地址，形如：`安装完成，网站地址：http://192.168.1.10:8080`

**步骤二：打开网站**

- 浏览器访问 `http://<本机IP>:8080`（同网段同事用同样的地址访问；本机可先用 `http://127.0.0.1:8080` 验证）
- 网站计划任务为"登录时启动"，安装当天可先手动启动一次（在项目目录运行）：`.venv\Scripts\python.exe -m web.app`；以后开机登录自动启动，看门狗每 5 分钟检查并自动拉起

**安装后检查**

| 检查项 | 方法 |
|---|---|
| 计划任务 | 任务计划程序搜索"矿news"：抓取 07/12/18、网站、备份 19:00、看门狗（每 5 分钟） |
| 网站 | 浏览器打开 `http://127.0.0.1:8080/healthz` 返回 `{"ok":true}` |
| 抓取 | `python -m crawler.main --once` 手动跑一轮，再打开 `/sources` 看结果 |
| 自检 | `python -m scripts.acceptance` 输出"全部通过" |

---

## 4. 日常操作

页面（顶部导航）：

| 页面 | 地址 | 用途 |
|---|---|---|
| 首页 | `/` | 今日新增条数 + 每个源最近一轮的状态点（绿=成功、红=失败，悬停看详情） + 最新动态 + 矿价速览 + 最新政策 |
| 行情 | `/prices` | 按品种最新价/涨跌/涨跌幅/日期/来源，点击品种看 7/30/90 天走势图 |
| 政策 | `/policy` | 按发布机关/地区筛选，时间倒序 |
| 搜索 | `/search` | 关键词 + 矿种/板块/来源组合筛选（FTS5，万级数据 <1 秒） |
| 源健康 | `/sources` | 各源最近成功/失败/条数、错误信息、日志下载、"立即抓取一次"、"立即备份数据库" |

常用命令行（在项目目录执行）：

```powershell
python -m crawler.main --once      # 手动抓取一轮（约 2-4 分钟）
python -m scripts.acceptance       # 端到端自检：今日文章数/源成功率/价格品种数/搜索响应
python -m scripts.backup           # 手动备份数据库
python -m scripts.watchdog         # 手动执行一次看门狗健康检查
python -m pytest                   # 跑全部离线测试（源站改版时先看这里）
```

备份文件位置：`data\backup\`（每日 19:00 自动备份，保留最近 30 天）。

### 4.1 反馈邮件通知（可选）

网站在收到"意见反馈"（悬浮按钮提交）后，可自动给管理员 QQ 邮箱发一封通知邮件，默认仅本机配置、不入库：

1. 复制 `config\notify.example.yaml` 为 `config\notify.local.yaml`
2. 填上收发的 QQ 邮箱地址与 **SMTP 授权码**（QQ 邮箱网页版 → 设置 → 账户 → 开启 SMTP 服务后生成，不是登录密码）
3. 保存后重启网站即生效；单发验证：

```powershell
python -c "from web import notify; print(notify.send_feedback_email('测试邮件：反馈通知链路验证'))"
```

关闭方式：把 `config\notify.local.yaml` 里的 `enabled` 改为 `false`，或直接删除该文件。

说明：`notify.local.yaml` 含授权码，已加入 `.gitignore`，不会提交入库，仓库内只保留占位示例 `config\notify.example.yaml`；发送过程在后台线程执行，不阻塞反馈提交，发送失败只写一行日志到 `logs\notify_YYYYMMDD.log`。

---

## 5. 加新源 / 改源教程

### 5.1 源 YAML 字段说明（`config/sources/<key>.yaml`）

| 字段 | 必填 | 说明 |
|---|---|---|
| `key` | 否 | 源唯一标识，默认取文件名（如 `mnr.yaml` → `mnr`），出现在日志/源健康页/测试中 |
| `name` | 是 | 中文显示名，源健康页展示 |
| `board` | 是 | 板块：`price` 价格 / `policy` 政策 / `news` 新闻 |
| `url` | 单页必填 | 列表页地址；与 `urls` 二选一 |
| `urls` | 否 | 多列表页地址数组（如生意社多个品种列表页），会依次抓取 |
| `referer` | 否 | 请求头 Referer，部分站点（新浪行情、生意社）校验需要 |
| `encoding` | 否 | 网页编码，如 `gb18030`；不填按响应自动识别 |
| `list` | 新闻/政策必填 | 列表页解析（`parser` 不在时使用） |
| `list.item` | 是 | 列表行 CSS 选择器（必填，否则报错"源配置缺少 list.item 选择器"） |
| `list.title` | 否 | 标题选择器（相对行）；不填取整行文本 |
| `list.link` | 否 | 链接选择器（相对行）；不填取标题元素或行内第一个 `<a>` |
| `list.date` | 否 | 日期选择器（相对行）；取出文本自动识别 `2026-09-15 / 09-15` 等格式 |
| `list.date_regex` | 否 | 选择器取不到日期时，用正则从链接/行文本提取 |
| `detail` | 否 | 详情页摘要抓取配置 |
| `detail.enabled` | 否 | 是否进详情页抓摘要（每轮限 `limit` 条，控制请求量） |
| `detail.content` | 否 | 正文容器选择器（如 `div.TRS_Editor`）；摘要截断到 200 字 |
| `detail.limit` | 否 | 每轮最多抓几条详情，默认 10 |
| `parser` | 价格源必填 | 价格解析器：`table` / `regex` / `sina_futures` / `eastmoney_futures` / `shfe_daily` |
| `price_type` | 否 | 价格类型：`期货` / `现货` / `指数`（默认按解析器） |
| `unit` / `unit_map` | 否 | 默认单位 / 按品种覆盖单位（如黄金 `元/克`） |
| `table` | 否 | `parser: table` 时必填：`row` 行选择器、`cell` 单元格选择器（默认 `td`）、`columns` 列号映射 `{name, price, change, change_pct, date}` |
| `regex` | 否 | `parser: regex` 时必填：`pattern` 带 `(?P<name>…)`、`(?P<price>…)` 命名组；可用 `name_group`/`price_group` 指定组名 |
| `commodity_map` | 价格源必填 | 页面标签 → 标准品种名映射；值为字符串精确匹配，值为列表时按子串/数字关键词匹配 |
| `field_map` `scale` `close_field` | 否 | 内置行情解析器（新浪/东财/上期所）的字段位置/缩放配置 |
| `enabled` | 否 | `false` 停用该源，抓取与测试自动跳过 |
| `fixture_ext` | 否 | 快照样本扩展名：`html`（默认）/`json`/`txt` |

### 5.2 标准流程（以新增一个新闻/政策源为例）

```powershell
# 1. 写 YAML：复制一个现有源改名，先填 key/name/board/url/encoding
#    例：config\sources\example.yaml

# 2. 抓一份列表页样本到 tests\fixtures\（存为 example_list.html）
python -m tools.snapshot example          # 失败时用 --url 覆盖地址重试

# 3. 用浏览器或编辑器打开样本，对照页面结构填 list.item / list.title / list.date / detail

# 4. 在测试文件登记该 key：
#    新闻/政策源 → tests\test_sources_news.py 的 ARTICLE_SOURCES 列表加 "example"
#    价格 HTML 源 → tests\test_price_html_sources.py 的 PRICE_HTML_SOURCES 列表加 "example"
#    内置解析器源（sina/东财/上期所）→ tests\test_price_sources.py

# 5. 跑该源测试（测试先红后绿，源改版时第一时间报警）
python -m pytest tests/test_sources_news.py -v

# 6. 真实抓一轮验证
python -m crawler.main --once
```

最后打开 `http://<本机IP>:8080/sources` 看源健康页：状态 `ok`、抓到条数正常即接入成功；失败时按第 6 节排查。

### 5.3 改源（源站改版时）

1. 看 `logs\snapshots\` 里该源的最近快照（自动保留最近 3 份），对照真实页面确认哪一层选择器失效
2. 改 `config\sources\<key>.yaml` 的选择器
3. `python -m tools.snapshot <key>` 更新样本 → 跑对应测试 → `python -m crawler.main --once` 验证
4. 若源站长期不可用，把 `enabled: false` 并在 README"已知限制"登记

---

## 6. 故障排查

### 6.1 某个源抓取失败

1. 打开源健康页 `/sources`，看失败源的错误信息与抓到条数
2. 看 `logs\snapshots\` 下该源的 HTML 快照（抓取失败且已拿到响应体时自动保存原始响应快照，连接级失败无快照，每个源保留最近 3 份），用浏览器打开对照页面结构
3. 改 `config\sources\<key>.yaml` 选择器（参见第 5 节教程）
4. 跑 `python -m pytest tests/test_sources_news.py -v`（价格源跑 `tests/test_price_html_sources.py`）确认离线样本通过
5. `python -m crawler.main --once` 验证真实抓取
6. 排查过程可看 `logs\crawler_YYYYMMDD.log`（中文日志，按轮次记录每源条数/错误）

单源失败不会中断整轮抓取（单源隔离），其余源照常出数。

### 6.2 网站打不开

1. 确认计划任务"矿news网站"和"矿news看门狗"处于运行/已启用状态；看门狗每 5 分钟检查一次，会在服务挂掉时自动拉起
2. 查看 `data\web.pid` 是否存在、里面 PID 对应的进程是否还在；源健康页若打不开就先跑 `python -m scripts.watchdog` 手动恢复
3. 本机验证 `http://127.0.0.1:8080/healthz`；他人电脑访问不了但本机能开 → 检查 8080 防火墙规则（重新以管理员运行 `安装.bat`）
4. 手动启动：在项目目录运行 `.venv\Scripts\python.exe -m web.app`（保持窗口打开）

### 6.3 端口冲突（8080 被占用）

1. 改 `config\settings.yaml` 里的 `port`（例如 `8090`）
2. 重启网站服务（结束旧进程后重新启动）
3. 防火墙规则需按新端口重新添加：以管理员身份重跑 `python scripts\install.py`，或手动执行 `netsh advfirewall firewall add rule name=矿news网站 dir=in action=allow protocol=TCP localport=8090`

### 6.4 全站一键自检

```powershell
python -m scripts.acceptance
```

检查 4 项：今日文章数 ≥ 1、最近一轮源成功率 ≥ 90%、价格品种 ≥ 12、搜索响应 < 1000ms；未通过项会打印明细（退出码非 0）。处理建议：源失败 → 按 6.1；价格品种不足 → 补源或核对 `commodity_map` 品种映射。

### 6.5 其他

- 抓取似乎没跑：错过时点的抓取任务会在电脑可用后尽快自动补跑；网页服务在用户登录时自启；手动排查可跑 `python -m crawler.main --once`
- 重复文章：去重阈值在 `config/settings.yaml` 的 `dedup_threshold`（默认 0.85，标题相似度）
- 全部测试：`python -m pytest`（源站改版时先跑离线测试定位问题）

---

## 7. 已知限制

1. **上期所源 `shfe` 已停用**：官方日行情端点返回 404，`config/sources/shfe.yaml` 已设 `enabled: false`；贵金属/有色期货由新浪与东财行情替代。
2. **生意社 `pp100` 依赖 Referer 通过站点校验**：若站点校验姿态变化，会抓不到行而**静默 0 行**，不会报错；需要人工复核——定期在源健康页 `/sources` 看该源条数，若为 0 或明显偏低，用浏览器打开列表页核对，必要时调整 `referer`/选择器。
3. **东方财富期货源在本机曾不可达**（RemoteDisconnected）：仅作新浪行情的备用冗余；失败会被单源隔离，不影响整轮抓取，源健康页会显示失败。
4. **中国矿业报 `kyb` 子域 DNS 无法解析**：`config/sources/kyb.yaml` 已设 `enabled: false`，待域名恢复后再启用并验证选择器。
5. **中国有色网 `cnmn` 列表页无日期**：`published_at` 为空，页面按抓取时间显示；标题与链接正常。
6. **微信公众号不抓取**：抓取成本高、法律灰区；行业站（煤炭/有色/矿业门户）转载已覆盖大部分内容。
7. **被排除的源（不再尝试）**：大商所、郑商所、中国矿业网、矿道网、SMM 上海有色、工信部、百度新闻搜索、金投网、秦皇岛煤炭网、中国铁合金在线。原因：硬 WAF（412/468）、纯 JS 渲染、登录墙、强制安全验证或占位假数据；替代关系见下表。

| 被排除源 | 原因 | 替代 |
|---|---|---|
| 大商所、郑商所 | 硬 WAF（412） | 新浪/东财期货行情 |
| 中国矿业网 chinamining.org.cn | 全站 WAF（468） | 中国煤炭网/中国有色网等 |
| 矿道网 mining120.com | 纯 JS 渲染，无静态列表 | 行业门户转载 |
| SMM 上海有色 | 瑞数 WAF + 登录墙 | 长江有色/生意社，二期浏览器方案 |
| 工信部 miit.gov.cn | JS 校验壳，列表不可直读 | 部委政策源（发改/能源/生态/矿安） |
| 百度新闻搜索 | 强制安全验证 | 各源站直接抓取 |
| 金投网 cngold.org | 实测为占位假数据 | 生意社/新浪/东财 |
| 秦皇岛煤炭网 cqcoal.com | 登录墙 + 纯 JS 模板 | 中国煤炭市场网（cctd） |
| 中国铁合金在线 cnfeol.com | JS 安全验证 | 我的钢铁网/生意社 |
| 微信公众号 | 成本/合规 | 行业站转载 |

补充说明：

- 生意社站内无"磷矿石""动力煤"的对应列表页，这两个品种靠其他源覆盖；若价格页品种数偏少，按 6.4 处理。
- 源站改版必然发生：离线样本测试会先红，按第 5.3 节修复即可，AI 维护成本低。
- 正式交付前需**连续 3 天**由计划任务自动运行后，复查源健康页（验收标准见设计文档第 11 节）。

---

## 8. 备份与恢复

**自动备份**：计划任务"矿news备份"每天 **19:00** 执行，生成 `data\backup\news_YYYYMMDD.db`，自动清理 30 天前的旧备份。

**手动备份**：

- 浏览器：源健康页 `/sources` → 点"立即备份数据库"
- 命令行：`python -m scripts.backup`

**恢复步骤**（例：误删数据/数据库损坏）：

1. 停止网站服务：结束计划任务"矿news网站"并在任务管理器结束对应 `python.exe`；同时**暂停计划任务"矿news看门狗"**，否则 5 分钟内服务会被自动拉起、数据库被占用
2. 暂停"矿news抓取07/12/18"计划任务，避免恢复期间有写入
3. （可选）把当前 `data\news.db` 改名留档
4. 用备份文件覆盖：`copy data\backup\news_20260915.db data\news.db`
5. 重启网站（登录计划任务自动启动，或手动 `python -m web.app`），跑 `python -m scripts.acceptance` 验证

注意：恢复会丢失备份日期之后的新增数据；`news.db` 是单文件数据库，覆盖前建议确认没有抓取进程在运行。

---

## 9. AI 巡检（巡检 = 启动爬虫 + 体检）

```powershell
python -m scripts.ai_run      # 一键巡检：先抓一轮，再体检，报告+建议，退出码 0/1
python -m scripts.ai_check    # 只体检不抓取，报告写入 logs\ai_check_YYYYMMDD.md
```

- 巡检流程、报告读法、「修源四步法」、重打标、备份恢复、定时任务与 AI 提示词模板：见 [`docs/ai-maintenance.md`](docs/ai-maintenance.md)
- 退出码：`0` 一切正常；`1` 有源失败或体检异常（按手册修复后复跑）
- 建议每天定时调用一次 `python -m scripts.ai_run`，失败源由 AI/人工按手册处理

---

## 10. 二期规划（v1 不做的）

1. **推送**：企业微信/钉钉每日摘要
2. **AI 摘要与每日综述**
3. **浏览器抓取方案**：SMM、工信部等 JS/WAF 站
4. **竞品专项监控**：美腾、泰禾、霍里思特等（上市公司公告走巨潮资讯）
5. **云部署迁移**：出差外网访问
6. **更多信息源**：山西/内蒙古/云南/山东等地方省厅，蒙古、赞比亚等海外矿讯
