from datetime import datetime
from pathlib import Path

from crawler import store
from crawler.config import load_settings

ROOT = Path(__file__).resolve().parent.parent
BOARD_NAMES = {"news": "新闻", "policy": "政策", "price": "价格"}
STATUS_NAMES = {"ok": "成功", "error": "失败", "running": "进行中"}

HEALTH_SQL = (
    "SELECT s.key, s.name, s.board, r.status, r.finished_at, r.items_found, r.items_new, r.error "
    "FROM sources s LEFT JOIN crawl_runs r ON r.id = "
    "(SELECT MAX(id) FROM crawl_runs WHERE source_key=s.key) ORDER BY s.board, s.key"
)


def _display(path) -> str:
    path = Path(path)
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return str(path).replace("\\", "/")


def _latest_snapshot(settings, key):
    files = sorted((settings.logs_dir / "snapshots").glob(f"{key}_*.html"))
    return files[-1] if files else None


def _overview(conn) -> dict:
    day = datetime.now().strftime("%Y-%m-%d")
    today = conn.execute(
        "SELECT COUNT(*) c FROM articles WHERE fetched_at LIKE ?", (day + "%",)).fetchone()["c"]
    commodities = conn.execute("SELECT COUNT(DISTINCT commodity) c FROM prices").fetchone()["c"]
    last = conn.execute(
        "SELECT MAX(finished_at) t FROM crawl_runs WHERE id IN "
        "(SELECT MAX(id) FROM crawl_runs GROUP BY source_key)").fetchone()["t"]
    new_mine = conn.execute(
        "SELECT COUNT(*) c FROM articles WHERE is_primary=1 AND types LIKE ?",
        ('%"新矿"%',)).fetchone()["c"]
    return {"today_new": today, "commodities": commodities,
            "last_fetch": last or "", "new_mine": new_mine}


def _status_text(row) -> str:
    if not row.get("finished_at"):
        return "未跑过"
    return STATUS_NAMES.get(row.get("status"), row.get("status") or "未知")


def generate_report(settings=None) -> tuple:
    settings = settings or load_settings()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    issues = []
    lines = [f"# AI 巡检报告（{now}）", ""]
    try:
        conn = store.connect(settings.db_path)
        try:
            store.init_db(conn)
            health = [dict(r) for r in conn.execute(HEALTH_SQL).fetchall()]
            overview = _overview(conn)
        finally:
            conn.close()
    except Exception as exc:
        lines.append(f"数据库读取失败：{exc}")
        lines.append("")
        lines.append("## 建议动作")
        lines.append("1. 检查 data/news.db 是否存在、是否被占用；必要时按 docs/ai-maintenance.md 的备份恢复步骤处理")
        return "\n".join(lines), [f"数据库读取失败：{exc}"], 1

    failures = [h for h in health if h.get("status") == "error" and h.get("finished_at")]

    lines.append("## 一、各源最近一轮")
    lines.append("")
    if health:
        lines.append("| 源 | 板块 | 状态 | 完成时间 | 抓到 | 新增 | 错误 |")
        lines.append("|---|---|---|---|---|---|---|")
        for h in health:
            lines.append("| {}（{}） | {} | {} | {} | {} | {} | {} |".format(
                h["name"], h["key"], BOARD_NAMES.get(h["board"], h["board"] or ""),
                _status_text(h), h.get("finished_at") or "—",
                h.get("items_found") if h.get("finished_at") else "—",
                h.get("items_new") if h.get("finished_at") else "—",
                (h.get("error") or "—").replace("|", "／")))
        for h in health:
            if h.get("status") == "error" and h.get("finished_at"):
                issues.append(f"源「{h['name']}」({h['key']}) 抓取失败：{h.get('error') or '未知错误'}")
    else:
        lines.append("（数据库暂无信息源记录，请先跑一轮抓取）")
        issues.append("数据库暂无信息源记录，未执行过抓取")

    lines.append("")
    lines.append("## 二、失败源与快照")
    lines.append("")
    if failures:
        for h in failures:
            snap = _latest_snapshot(settings, h["key"])
            if snap:
                lines.append(f"- {h['name']}（{h['key']}）：最新快照 `{_display(snap)}`")
            else:
                lines.append(f"- {h['name']}（{h['key']}）：未留下快照（连接级失败），先看 logs/crawler_*.log")
    else:
        lines.append("全部源最近一轮正常。")

    lines.append("")
    lines.append("## 三、数据概览")
    lines.append("")
    lines.append(f"- 今日新增文章：{overview['today_new']} 条")
    lines.append(f"- 价格品种数：{overview['commodities']} 个")
    lines.append(f"- 最近抓取时间：{overview['last_fetch'] or '—'}")
    lines.append(f"- 「新矿」标签条数：{overview['new_mine']} 条")

    actions = []
    for h in failures:
        snap = _latest_snapshot(settings, h["key"])
        if snap:
            actions.append(
                f"修复 {h['key']}（修源四步法）：python -m tools.snapshot {h['key']} → 对照快照改 "
                f"config/sources/{h['key']}.yaml → python -m pytest tests/test_sources_news.py → "
                f"python -m crawler.main --once 复跑验证")
        else:
            actions.append(
                f"{h['key']} 无快照：先 python -m crawler.main --once 复现，查看 logs/crawler_*.log，"
                f"确认是网络/DNS 还是站点改版")
    if not failures and not health:
        actions.append("先运行 python -m crawler.main --once 完成首次抓取")
    if overview["today_new"] == 0 and health:
        actions.append("今日新增为 0：确认 07:30/12:30/18:30 抓取计划任务是否执行，看 logs/crawler_*.log")
    if overview["commodities"] and overview["commodities"] < 12:
        actions.append("价格品种数不足 12：核对价格源配置与 commodity_map（见 README 6.4 与 5.1）")
    if not actions:
        actions.append("本轮巡检未发现问题，保持每日巡检即可")

    lines.append("")
    lines.append("## 四、建议动作")
    lines.append("")
    for i, action in enumerate(actions, 1):
        lines.append(f"{i}. {action}")
    if failures:
        lines.append("")
        lines.append("详细步骤见 docs/ai-maintenance.md（修源四步法 / 重打标 / 备份恢复）。")

    return "\n".join(lines), issues, (1 if issues else 0)


def write_report(text, settings=None) -> Path:
    settings = settings or load_settings()
    path = settings.logs_dir / f"ai_check_{datetime.now().strftime('%Y%m%d')}.md"
    path.write_text(text, encoding="utf-8")
    return path


def main():
    settings = load_settings()
    text, issues, code = generate_report(settings)
    print(text)
    path = write_report(text, settings)
    print(f"报告已写入：{path}")
    if issues:
        print(f"发现 {len(issues)} 个问题：")
        for issue in issues:
            print(f"- {issue}")
    raise SystemExit(code)


if __name__ == "__main__":
    main()
