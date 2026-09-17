# 公网部署（GitHub Pages）

静态站与内网动态版并存：`web/` 动态版继续在本机使用，本方案额外生成一份纯静态站点，发布到 GitHub Pages。

**数据流：办公电脑（国内网络，27 个信息源全部可达）每天 07:30 / 12:30 / 18:30 抓取 → 自动把 `data/news.db` 强推到仓库的 `data` 分支 → GitHub Actions 检测到 `data` 分支更新，自动构建并部署 Pages。**

这样分工的原因：Actions 机器在美国，8 个中国源（省厅/协会/交易所等）抓不到；办公电脑在国内网络可以全部抓到，Actions 只做构建部署。

- 抓取与发布：办公电脑计划任务执行 `python -m scripts.crawl_publish`（抓一轮 + 单提交强推 `data` 分支）
- 数据：`data` 是孤儿分支，只含 `data/news.db`（外加工作流文件），每次强推为**单条提交**，仓库体积≈当前数据库大小
- 构建：Actions 里运行 `python -m scripts.build_site` 输出 `dist/`（纯静态、相对路径、无外网依赖）
- 发布：`actions/upload-pages-artifact` + `actions/deploy-pages`
- 触发：`push` 到 `data` 分支自动触发；也可在 Actions 页手动 Run（用于「只更新站点不抓取」）

## 一、前置条件

1. 有 GitHub 账号，本地 `git` 可用，办公电脑装好 **Python 3.11 及以上**
2. 站点仓库必须**公开**（Free 套餐 Pages 不支持私有仓库；数据只有标题+摘要+链接，符合存储红线）
3. 一个 GitHub **PAT**（Personal Access Token）：classic 勾选 `repo` 即可；fine-grained 需对本仓库授予 `Contents: Read and write`
4. 仓库 Settings → Pages → Build and deployment → Source 选择 **GitHub Actions**（只需设置一次）

## 二、办公电脑一次性设置（逐条执行）

**1. 安装 Python 3.11+**

- 官网 python.org 下载安装包，安装时务必勾选 **Add Python to PATH**
- 装完在 PowerShell 输入 `python --version` 能显示版本号即可

**2. 克隆仓库**（把 `<用户名>` 换成实际值；`E:\矿_news` 可换成任意目录）

```powershell
git clone https://github.com/<用户名>/<仓库>.git E:\矿_news
Set-Location E:\矿_news
```

**3. 安装依赖**

```powershell
pip install -r requirements.txt
```

**4. 配置 git 凭据（PAT，只需要做一次）**

```powershell
git config --global credential.helper store
git config --global user.name "你的名字"
git config --global user.email "你的邮箱"
git push -u origin master
```

- `git push` 时会提示输入用户名与密码：**用户名填 GitHub 用户名，密码处粘贴 PAT**（不是 GitHub 登录密码）
- 首次 push 成功后，凭据会被 `credential.helper store` 明文保存在 `%USERPROFILE%\.git-credentials`（只在本机，不会提交）
- 之后 `scripts.crawl_publish` 推 `data` 分支会自动复用这份凭据，不再提示

**5. 注册定时任务（以管理员身份运行）**

```powershell
python scripts\install.py
```

会自动创建 `.venv`、安装依赖并注册 4 类计划任务：

- **矿news抓取07 / 12 / 18**：北京时间 07:30 / 12:30 / 18:30 执行 `python -m scripts.crawl_publish`（抓取并推送 `data` 分支）
- **矿news网站**：登录自启内网动态站
- **矿news看门狗**：每 5 分钟检查网站并自动拉起
- **矿news备份**：每天 19:00 备份数据库（保留 30 天）

**6. 手动验证一次抓取+发布**（首次务必执行，确认凭据与网络正常）

```powershell
python -m scripts.crawl_publish
```

- 正常输出：各源摘要（形如 `源 27/27 成功，文章新增 N 条，价格 M 条`）→ `已生成数据提交 xxxxxxxx` → `已强推到 origin/data`
- 抓取约 5~8 分钟；退出码 0 表示抓取全成功且发布成功，1 表示有源失败（数据仍会尽量发布，按 `docs/ai-maintenance.md` 修源）
- 打开仓库 Commits 页确认 `data` 分支出现新提交；Actions 页会自动出现一次「构建并部署静态站」运行

**7. 访问站点**

```
https://<用户名>.github.io/<仓库>/
```

## 三、GitHub Actions 说明（构建部署）

- 触发条件：`push` 到 `data` 分支；或手动 `workflow_dispatch`
- 步骤：checkout `master` → setup-python → `pip install -r requirements.txt` → 从 `data` 分支恢复 `data/news.db` → `python -m scripts.build_site` → configure-pages → upload-pages-artifact → deploy-pages
- 权限：`contents: write`、`pages: write`、`id-token: write`；并发组 `crawl-deploy`（同一时刻只跑一个部署）
- 全程不需要任何 Secrets

## 四、常见问题

| 场景 | 做法 |
|---|---|
| **PAT 过期** | 在 GitHub → Settings → Developer settings → Personal access tokens 重新生成，然后在办公电脑重新执行一次 `git push`（或 `python -m scripts.crawl_publish`），提示输入密码时粘贴新 PAT；也可手动编辑 `%USERPROFILE%\.git-credentials` 里对应行的密码段。下次推送报 `403`/`Authentication failed` 就是过期信号 |
| **Actions 手动重跑** | 仓库 Actions → 左侧「构建并部署静态站」→ **Run workflow** → 选 `master` → Run；或打开任意一次历史运行点 **Re-run jobs** |
| **只更新站点不抓取** | Actions → Run workflow 一次即可（直接用 `data` 分支现有数据库重新构建）；本地调试用 `python -m scripts.build_site` + `python -m http.server 8090 -d dist` |
| data 分支没更新 | 在办公电脑看 `logs\crawler_YYYYMMDD.log`，并手动复跑 `python -m scripts.crawl_publish` |
| 个别源失败 | 退出码为 1 但数据仍会发布；按 [`docs/ai-maintenance.md`](ai-maintenance.md) 修源后复跑 |
| 页面样式/文案改动 | 改 `site_build/` 后提交推 `master`，再手动 Run 一次工作流（或等下一次 `data` 更新） |
| 数据库多久没更新 | 看站点首页状态条的「构建时间」与「今日新增」 |
| 仓库会不会越来越大 | 不会：`data` 分支每次都是强推的单提交，旧数据自动被丢弃 |

## 五、国内访问提示与迁移到国内对象存储

`*.github.io` 在国内网络下时快时慢、偶尔打不开，内部同事日常使用建议迁到国内对象存储/CDN。迁移成本很低，因为 `dist/` 就是完整站点，不依赖任何服务端：

1. 开通阿里云 OSS / 腾讯云 COS / 七牛任一 bucket，权限设为**公共读**
2. 开启**静态网站托管**，默认首页设为 `index.html`
3. 绑定自定义域名（可选，建议开 CDN + HTTPS）
4. 把 `dist/` 目录整个上传到 bucket（`index.html`、`news.html`、`search.json`、`vendor/` 等按原目录结构）

数据持续更新有三种方式，任选其一：

- **本机定时（推荐）**：办公电脑沿用 `python -m scripts.crawl_publish`，在其后追加 `python -m scripts.build_site`，再用对象存储客户端（`ossutil`/`coscli`）同步 `dist/`
- **Actions 换部署目标**：保持「办公电脑推 `data` 分支 → Actions 构建」，把工作流里部署 Pages 的两步换成上传 OSS/COS 的命令（用仓库 Secrets 保存 AccessKey），`dist/` 产物完全相同
- **换国内 CI**：把仓库镜像到 Gitee 等平台，用同样的构建命令跑流水线

## 六、安全与隐私说明

- 工作流不需要任何 Secrets；抓取凭据（PAT）只存在办公电脑本机
- 公开仓库里会公开 `data` 分支的 `news.db`：只含标题、≤200 字摘要、原文链接与元数据，不含正文全文
- 静态站没有管理页（源健康页仅内网动态版提供），反馈按钮走 `mailto:` 邮件，不经过服务器
