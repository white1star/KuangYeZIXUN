# Stitch 前端设计提示词（矿_news）

> 用法：Stitch 新建 Web 项目 → 先贴【总提示词】出首页 → 按顺序贴【续作提示词】逐个出页面 → 最后贴【手机版提示词】。
> 全部界面文案必须是简体中文；导航为 首页 · 新闻 · 矿价 · 政策（"数据源状态"是维护页，不在导航；搜索在首页原地进行）。

---

## 一、总提示词（设计系统 + 首页）

```
Design a modern, clean internal web app called "矿业资讯站" (Mining Intelligence Station) for a Chinese mining-technology company. It aggregates daily mineral news, mineral prices, and government policies for employees.

STYLE: modern SaaS aesthetic like Stripe and Linear — light theme, generous whitespace, calm and professional, ONE accent color, hairline borders, rounded cards, no gradients, no photos or illustrations anywhere (the data has no images); use small colored dots, type color-bars and pill chips as visual accents.

DESIGN SYSTEM:
- Accent color: industrial green #289048. Neutrals: page background #F6F8F7, cards #FFFFFF, primary ink #111418, secondary text #6C7784, hairline borders #DFE6EA.
- Price colors (Chinese convention, red = up): up #D23F31, down #1A8F4C.
- Typography: clean sans-serif (system-ui, Microsoft YaHei for Chinese). Base 14-15px with 1.7 line-height. Big stat numbers 28-32px bold. Labels 12-13px gray.
- Components: cards with 12px radius and a very light shadow; hairline dividers instead of heavy boxes; pill-shaped chips (11-12px) for tags; minimal sticky top navigation with the active item marked by a green underline.
- Desktop-first, content max-width 1200px. ALL UI copy in Simplified Chinese.

GLOBAL HEADER (top navigation, sticky, white background, hairline bottom border):
- Left: small green square logo mark + brand two lines: "像素智能" (bold) / "矿业资讯站" (small, gray).
- Right nav (4 items): 首页 · 新闻 · 矿价 · 政策，current page highlighted with green underline.
- Footer: small gray text on the right with a subtle text link "数据源状态" (maintenance page).

PAGE 1 — 首页 (Home), top to bottom:
1) Slim status strip (small gray text): "上次抓取 12:30 · 今日新增 170 条 · 数据每日自动备份"; on the right a row of 17 tiny source-health dots (green = ok, red = error, gray = not run). If one or more sources failed, also show a small red text link inline: "1 个源异常，点这里查看".
2) A prominent large search box (search-first hero): wide rounded input, max-width 720px, placeholder "搜索新闻、政策、矿种，如：磷矿 政策", with a green search button and airy whitespace around it. Design TWO states for this page:
   - Default state: no results, page shows the sections below.
   - Results state: after submitting a search, results appear INLINE below the search box: a small gray line "共 23 条结果 · 关键词：磷矿" with a "清除" text link, then results in the standard feed item style (bold title max 2 lines, one gray summary line with ellipsis, meta row with source · date · mineral chips and type chips, hairline dividers). Also include an empty state variant: centered gray text "没有找到匹配内容，试试其他关键词".
3) Row of 4 stat cards: 今日新增 170 / 新闻 59 / 政策 111 / 信息源 16/17 正常. Big bold number + small gray label.
4) Row of 6 compact price cards: 动力煤 / 焦煤 / 铁矿石 / 铜 / 黄金 / 磷矿石 — each shows mineral name, latest price + unit, percent change in red or green with a small triangle arrow, source name in tiny gray (e.g. "生意社"). Cards are clickable-feeling, same visual weight.
5) A row of 3 large entrance cards (clickable, generous padding): "新闻资讯 — 每日行业动态与政策早知道 · 今日 170 条", "矿价行情 — 全品种价格与走势 · 20 个品种", "政策法规 — 国家与地方矿业政策 · 今日 111 条". Each has a thin green top bar or a small green arrow, minimal text, lots of whitespace.
The page feels calm, spacious, and search-first at the top.
```

---

## 二、续作提示词（依次贴，保持同一设计系统）

### 页面 2：新闻

```
Now design Page 2 "新闻" in the exact same design system and header. Top: a single row of mineral filter pills: 全部 · 煤炭 · 焦煤 · 铁矿石 · 铜 · 铅锌 · 金 · 锰 · 磷矿 · 萤石 · 石英砂 (pill chips; the active one "全部" filled with accent green, others light gray outline). Below: a clean single-column vertical feed (no card boxes, just hairline dividers): bold title (max 2 lines), one gray summary line with ellipsis, meta row with source name · date · small mineral chips and type chips (类型：政策/技术/安全/市场/企业). About 20 items with realistic Chinese mining headlines like "河北开展磷矿安全生产专项整治", "焦煤主力合约上涨 2.3%", "自然资源部发布绿色矿山建设通知", "紫金矿业某铜矿扩建项目投产". Keep it calm and scannable, single column.
```

### 页面 3：矿价

```
Now design Page 3 "矿价" in the exact same design system and header. Top: a compact toolbar card with three dropdowns: 品种 / 类型（期货·现货·指数）/ 周期（近7天·近30天·近90天）. Below: one large chart card titled "焦煤 价格走势 · 指数 · 近30天" with a simple line chart drawn in accent green #289048 (light horizontal gridlines, minimal axes). Below the chart: a compact table card "最新报价" with columns 品种 / 类型 / 最新价 / 涨跌 / 涨跌幅 / 日期 / 来源; zebra rows, right-aligned numbers, red/green changes, hairline borders; about 15 rows with realistic Chinese mock data (动力煤、焦煤、焦炭、铁矿石、铜、铝、铅、锌、黄金、白银、锰、钨、磷矿石、萤石、石英砂).
```

### 页面 4：政策

```
Now design Page 4 "政策" in the same design system. Top: a light filter card: agency dropdown (自然资源部 / 国家矿山安全监察局 / 国家能源局 / 河北省自然资源厅 / 唐山市自然资源和规划局), a region text input with placeholder "地区，如 河北", and a green primary button "筛选". Below: a clean vertical list (same item style as the news page: bold title, meta row with publisher · date · region chip · type chip, one-line gray summary). About 15 realistic Chinese mining-policy titles.
```

### 页面 5：数据源状态（维护页，不在导航里）

```
Now design a maintenance page titled "数据源状态" with a small gray subtitle "仅维护使用" — it is NOT in the top navigation; users reach it from the red alert on the home page or the footer link. In the same design system. Top: an action card with a green primary button "立即抓取一次", a secondary text-link button "立即备份数据库", and small gray helper text "抓取进行中时不可重复触发". Below: a summary line "17 个信息源 · 16 正常 · 1 异常". Then a data table: 源名称 / 板块 / 最近状态 (colored pill badges: 成功=green, 失败=red, 未跑过=gray) / 完成时间 / 抓到 / 新增 / 错误信息 (gray, truncated with ellipsis). About 12 rows with realistic source names (自然资源部要闻、国家矿山安全监察局、河北省自然资源厅、唐山市自然资源和规划局、生意社现货报价、长江有色金属网、中国煤炭资源网、新浪期货行情…). At the bottom: a small card "最近日志" listing log file names as green text links.
```

---

## 三、手机版提示词

```
Finally, generate mobile phone versions (390px width) of ALL pages in the same design system: single column; the home search box spans full width; stat cards in a 2x2 grid; price cards horizontally scrollable; entrance cards stacked; filter pills horizontally scrollable; feed items stacked; tables horizontally scrollable; sticky top bar with a compact scrollable tab row (首页 · 新闻 · 矿价 · 政策); the maintenance page "数据源状态" is reached only from the home alert.
```

---

## 四、使用说明

1. Stitch 新建项目（Web / Desktop），先贴【总提示词】——它会先出首页（记得让它把搜索的"默认/结果/空态"都画出来）。
2. 如果它问主题：选浅色（Light / Material），配色以上面的色值为准（可以直接把 #289048 / #F6F8F7 / #DFE6EA 贴给它）。
3. 逐条贴【续作提示词】，每出一页检查：头部、卡片圆角、绿色点缀、字级是否一致；不一致就补一句 "continue with the exact same design system as the previous screens"。
4. 最后贴【手机版提示词】。
5. 出图后：把每页的**截图或分享链接**发回来，我照着把 4 个主页面 + 维护页（含手机自适应）实现进现有系统。
