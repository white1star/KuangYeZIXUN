# 公网部署（GitHub Pages）

静态站与内网动态版并存：`web/` 动态版继续在本机使用，本方案额外生成一份纯静态站点，由 GitHub Actions 每天三次自动抓取、构建并发布到 GitHub Pages。

- 抓取：Actions 里运行 `python -m crawler.main --once`（与内网同一套爬虫，公开源，无需任何 Secrets）
- 数据：`data/news.db` 保存在仓库的 **孤儿分支 `data`**，每次更新都强推为**单条提交**，仓库体积≈当前数据库大小
- 构建：`python -m scripts.build_site` 输出 `dist/`（纯静态、相对路径、无外网依赖）
- 发布：`actions/upload-pages-artifact` + `actions/deploy-pages`
- 节奏：北京时间每天 **07:30 / 12:30 / 18:30**（UTC 23:30 / 04:30 / 10:30），也可手动 Run

## 一、前置条件

1. 有 GitHub 账号，本地 `git` 可用
2. 站点仓库必须**公开**（Free 套餐 Pages 不支持私有仓库；数据只有标题+摘要+链接，符合存储红线）

## 二、逐条操作步骤

**1. 在 GitHub 建一个空的公开仓库**

- 打开 https://github.com/new
- Repository name 例如 `mine-news`，选择 **Public**
- 不要勾选 README / .gitignore / License（保持空库），点 Create repository

**2. 本地关联远程并推送代码**（在 `E:\矿_news` 执行，把 `<用户名>` `<仓库>` 换成实际值）

```powershell
git remote add origin https://github.com/<用户名>/<仓库>.git
git push -u origin master
```

**3. 打开 Pages 开关**

- 仓库页 → **Settings → Pages**
- **Build and deployment → Source** 选择 **GitHub Actions**（不要选 Deploy from a branch）

**4. 本地跑一次数据分支初始化**（把当前含回填数据的 `data/news.db` 推到 `data` 分支）

```powershell
python -m scripts.publish_data_branch
```

- 成功输出类似：`已强推到 origin/data（该分支只保留这一条提交）`
- 该脚本用 git 底层对象写入，不会切换分支、不会改动你的工作区
- 想先看效果可加 `--dry-run`（只生成提交对象不推送）

**5. 手动跑一次工作流验证**

- 仓库页 → **Actions** → 左侧「抓取并部署静态站」→ **Run workflow** → 选 `master` → Run
- 等待 3~6 分钟（首次要装依赖 + 抓一轮），绿色对勾即成功
- 首次部署成功后 Pages 可能有 1~2 分钟生效时间

**6. 访问站点**

```
https://<用户名>.github.io/<仓库>/
```

之后无需任何操作：每天 07:30 / 12:30 / 18:30 自动抓取并发布；想立刻更新就在 Actions 页手动 Run。

## 三、日常维护与排障

| 场景 | 做法 |
|---|---|
| 想立刻更新 | Actions → Run workflow |
| 看抓取结果 | Actions 日志里每源一行「解析 N 条」；个别源失败不影响整站 |
| 页面样式/文案改动 | 改 `site_build/` 后提交推送，等下一次 Run（或手动 Run） |
| 本地预览 | `python -m scripts.build_site` 后 `python -m http.server 8090 -d dist`，浏览器开 http://127.0.0.1:8090/ |
| 构建失败 | 打开 Actions 失败步骤日志；常见原因是源站改版导致抓取报错，按内网手册第 6 节修源 |
| 数据库多久没更新 | 看站点首页状态条的「构建时间」与「今日新增」 |
| 仓库会不会越来越大 | 不会：`data` 分支每次都是强推的单提交，旧数据自动被丢弃 |

## 四、国内访问提示与迁移到国内对象存储

`*.github.io` 在国内网络下时快时慢、偶尔打不开，内部同事日常使用建议迁到国内对象存储/CDN。迁移成本很低，因为 `dist/` 就是完整站点，不依赖任何服务端：

1. 开通阿里云 OSS / 腾讯云 COS / 七牛任一 bucket，权限设为**公共读**
2. 开启**静态网站托管**，默认首页设为 `index.html`
3. 绑定自定义域名（可选，建议开 CDN + HTTPS）
4. 把 `dist/` 目录整个上传到 bucket（`index.html`、`news.html`、`search.json`、`vendor/` 等按原目录结构）

数据持续更新有三种方式，任选其一：

- **仍用 GitHub Actions 抓取**：在工作流里把「部署 Pages」两步换成上传 OSS/COS 的命令（用 `ossutil`/`coscli` + 仓库 Secrets 保存 AccessKey），`dist/` 产物完全相同
- **本机定时**：沿用本机计划任务，在 `python -m crawler.main --once` 后追加 `python -m scripts.build_site`，再用对象存储客户端同步 `dist/`
- **换国内 CI**：把仓库镜像到 Gitee 等平台，用同样的构建命令跑流水线

## 五、安全与隐私说明

- 工作流不需要任何 Secrets（爬虫全部是公开源；反馈按钮走 `mailto:` 邮件，不经过服务器）
- 公开仓库里会公开 `data` 分支的 `news.db`：只含标题、≤200 字摘要、原文链接与元数据，不含正文全文
- 静态站没有管理页（源健康页仅内网动态版提供）
