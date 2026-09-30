"""每日数据健康告警：把"没人会去看"的巡检结论主动发邮件给管理员。

背景（两个真实事故）：
1. 源站改版后抓取"成功"但 0 行（静默），连续多天没人发现——因为结论只写在
   logs/ai_check_*.md 里。本脚本把同一口径的结果用邮件推出去。
2. 某个品种的报价停在几天前，页面照常显示旧价、抓取状态却是 ok——抓取"成功"
   不等于"数据是新的"，所以单列"报价陈旧"一类。

三类问题（collect_issues）：
- failed：启用源最近一轮 status='error'（只看 MAX(id) 那轮，历史失败已恢复的不报）
- silent：复用 ai_check.silent_sources（跑成功了但 3 天零产出）
- stale ：按"品种+价格类型"判陈旧（不按源判，见 _stale_prices 里的原因）

用法：
    python -m scripts.alert_health            # 有问题才发邮件，24 小时内同一问题只发一次
    python -m scripts.alert_health --dry-run  # 只打印，不发信不写状态
    python -m scripts.alert_health --force    # 忽略去重，强制发送
"""
import argparse
import json
from datetime import date, datetime
from pathlib import Path

from crawler import store
from crawler.config import load_settings, load_sources
from crawler.rules_version import compute_rules_version
# 静默检测的口径只在 ai_check 里实现一份，这里直接复用，避免两处规则漂移
from scripts.ai_check import SILENT_DAYS, silent_sources
# 邮件通道直接复用 web.notify，不另写 SMTP；默认配置路径是 <仓库根>/config/notify.local.yaml，
# 服务器上仓库在 /opt/news，即 /opt/news/config/notify.local.yaml，无需额外适配
from web.notify import load_notify_config, send_mail

STALE_DAYS = 2          # 报价陈旧阈值：实测 29 个品种里 28 个当天更新，1#锡 昨天更新过
DEDUP_HOURS = 24        # 一天 3 次 cron，同一个问题 24 小时内只提醒一次，避免刷屏
STATE_FILENAME = ".alert_state.json"
UNKNOWN = "未知"


def _clean_error(exc) -> str:
    """把异常压成一行可安全打印的文本。

    与 ai_check 同样的理由：YAML 报错会带多行定位并回显文件内容（如 Notepad 存的
    BOM \\ufeff），直接 print 会让 cp936 控制台二次崩溃。这里独立实现而不去动 ai_check，
    以免动到那份已在用的报告行为。
    """
    text = "".join(c for c in " ".join(str(exc).split()) if c.isprintable())
    return text[:200] + "…" if len(text) > 200 else text


def _source_config(settings):
    """读源配置，返回 (名称表, 启用 key 列表, 配置错误)。

    配置读坏时不能整封告警哑掉：failed 退化为按 DB 的 sources.enabled 判断，
    silent 因为拿不到启用清单而跳过，并在邮件正文里说明。
    """
    try:
        if settings is None:
            raw = load_sources()
        else:
            sources_dir = Path(settings.config_dir) / "sources"
            if not sources_dir.is_dir():
                # 目录不在时 glob 会安静地返回空清单 → 三类检测里两类被悄悄关掉，
                # 那正是这套告警要消灭的假阴性，所以当作配置错误报出来
                return {}, [], f"源配置目录不存在：{sources_dir}"
            raw = load_sources(sources_dir)
    except Exception as exc:
        return {}, [], _clean_error(exc)
    names = {s["key"]: s.get("name", s["key"]) for s in raw}
    enabled = [s["key"] for s in raw if s.get("enabled", True)]
    return names, enabled, ""


LATEST_RUN_SQL = (
    "SELECT r.source_key, r.status, r.error FROM crawl_runs r"
    " JOIN (SELECT source_key, MAX(id) id FROM crawl_runs GROUP BY source_key) t"
    " ON t.id = r.id ORDER BY r.source_key"
)


def _db_names(conn) -> dict:
    return {r["key"]: r["name"] for r in conn.execute("SELECT key, name FROM sources")}


def _failed_sources(conn, names, enabled_keys) -> list:
    """最近一轮就失败的启用源。

    口径只认每个源的 MAX(id) 那一轮：历史上失败过、之后已跑成功的源不再报，
    否则一次网络抖动会在告警里赖上好几天。enabled_keys 为 None 表示配置读坏了，
    这时退化为 DB 里的 enabled 标志（宁可多报一个，也不要因为配置问题收不到失败告警）。
    """
    if enabled_keys is None:
        enabled_keys = [r["key"] for r in conn.execute(
            "SELECT key FROM sources WHERE enabled=1 ORDER BY key")]
    enabled = set(enabled_keys)
    db_names = _db_names(conn)
    out = []
    for row in conn.execute(LATEST_RUN_SQL):
        if row["status"] != "error" or row["source_key"] not in enabled:
            continue
        key = row["source_key"]
        out.append({"key": key,
                    "name": names.get(key) or db_names.get(key) or key,
                    "error": row["error"] or "未知错误"})
    return out


def _silent_sources(conn, names, enabled_keys, now) -> list:
    """把 ai_check.silent_sources 的结果补上可读名称（那边只给 key/reason）。"""
    if enabled_keys is None:
        return []  # 拿不到启用清单就不猜，静默检测跳过（邮件正文会说明）
    return [{"key": s["key"], "name": names.get(s["key"], s["key"]),
             "reason": s["reason"], "last_nonzero": s.get("last_nonzero") or ""}
            for s in silent_sources(conn, enabled_keys, days=SILENT_DAYS, now=now)]


def _stale_prices(conn, stale_days, now) -> list:
    """按"品种 + 价格类型"找报价陈旧的项。

    为什么按品种判而不是按源判：备用源天生低频（eastmoney_futures 十个交易日只有五天
    有数据），按源判它每天都在报警，报警多了就等于没报警。只要品种层面（任意源）有今天的
    价，这个品种就是新鲜的；只有整个品种都停在几天前，才是页面显示旧价的那个事故。

    阈值 2 天：上游当天没出价属正常（实测 1#锡 现货就常是昨天），
    连续 2 天没更新才说明上游或解析真出问题了。
    """
    rows = conn.execute(
        "SELECT commodity, price_type, MAX(price_date) latest FROM prices"
        " GROUP BY commodity, price_type").fetchall()
    out = []
    for row in rows:
        try:
            latest = date.fromisoformat(row["latest"])
        except (TypeError, ValueError):
            continue  # 脏日期（历史上有人塞过"9/21"）：跳过这一行，别让整封告警炸掉
        age_days = (now.date() - latest).days
        if age_days < stale_days:
            continue
        # 来源取"提供最新那条价"的行：管理员照着 source_key 去修那个源
        src = conn.execute(
            "SELECT source_key FROM prices WHERE commodity=? AND price_type=? AND price_date=?"
            " ORDER BY id DESC LIMIT 1",
            (row["commodity"], row["price_type"], row["latest"])).fetchone()
        out.append({"commodity": row["commodity"], "price_type": row["price_type"],
                    "latest": row["latest"], "age_days": age_days,
                    "source": (src["source_key"] if src else "")})
    out.sort(key=lambda s: (-s["age_days"], s["commodity"], s["price_type"]))
    return out


def collect_issues(conn, settings=None, stale_days=STALE_DAYS, now=None) -> dict:
    """三类问题清单；没有就是空列表/空字典。"""
    now = now or datetime.now()
    names, enabled, config_error = _source_config(settings)
    # 配置错误时 enabled 传 None：failed 退化为按 DB 判断，silent 直接跳过
    usable = None if config_error else enabled
    return {
        "failed": _failed_sources(conn, names, usable),
        "silent": _silent_sources(conn, names, usable, now),
        "stale": _stale_prices(conn, stale_days, now),
        "config_error": config_error,
    }


def has_issues(issues) -> bool:
    """是否有东西要说。

    config_error 也算：源配置读不了时静默检测根本没做，报"一切正常"就是把
    检测能力悄悄关掉还告诉管理员没问题。
    """
    return bool(issues.get("config_error")) or any(
        issues.get(k) for k in ("failed", "silent", "stale"))


def signature_of(issues) -> str:
    """问题集合的稳定指纹：只认"哪些 key / 哪些品种有问题"，不认名称与天数。

    这样一轮里反复出现同一批问题（cron 每 3 小时一次）指纹不变，才谈得上 24 小时去重；
    问题增减（多了个源、某个品种恢复）指纹就变，会再提醒一次。
    """
    failed = sorted(f["key"] for f in issues.get("failed") or [])
    silent = sorted(s["key"] for s in issues.get("silent") or [])
    stale = sorted(f"{s['commodity']}/{s['price_type']}" for s in issues.get("stale") or [])
    return f"{len(failed)}|{','.join(failed)}|{','.join(silent)}|{','.join(stale)}"


def state_path(settings) -> Path:
    return Path(settings.data_dir) / STATE_FILENAME


def should_send(state_path, signature, within_hours=DEDUP_HOURS, now=None) -> bool:
    """同一个指纹在窗口内已发过就跳过。状态读不了/坏了就当没发过。

    宁可可多发一次，也不要因为状态文件损坏就永久静默——静默正是这个脚本要消灭的故障。
    """
    now = now or datetime.now()
    try:
        state = json.loads(Path(state_path).read_text(encoding="utf-8"))
        if state.get("last_signature") != signature:
            return True
        sent_at = datetime.fromisoformat(state.get("last_sent_at", ""))
        return (now - sent_at).total_seconds() >= within_hours * 3600
    except Exception:
        return True


def mark_sent(state_path, signature, now=None) -> None:
    path = Path(state_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(
        {"last_signature": signature,
         "last_sent_at": (now or datetime.now()).isoformat(timespec="seconds")},
        ensure_ascii=False), encoding="utf-8")


def build_email(issues, rules_version, stale_days=STALE_DAYS) -> tuple:
    """拼主题与正文。只列有问题的类别与段落——空的不写。"""
    failed = issues.get("failed") or []
    silent = issues.get("silent") or []
    stale = issues.get("stale") or []

    labels = []
    if failed:
        labels.append(f"失败 {len(failed)} 个")
    if silent:
        labels.append(f"静默 {len(silent)} 个")
    if stale:
        labels.append(f"报价陈旧 {len(stale)} 个")
    if issues.get("config_error"):
        labels.append("检测受限 1 项")
    subject = "【矿业资讯站】数据异常提醒：" + " / ".join(labels)

    lines = [f"检测时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", ""]
    if issues.get("config_error"):
        lines.append(f"（本次未做静默检测：源配置读取失败 {issues['config_error']}）")
        lines.append("")

    if failed:
        lines.append("## 抓取失败")
        lines.append("")
        for item in failed:
            lines.append(f"- {item['name']}（{item['key']}）：{item['error']}")
        lines.append("")

    if silent:
        lines.append(f"## 疑似静默（{SILENT_DAYS} 天零产出）")
        lines.append("")
        for item in silent:
            detail = f"；最后有产出：{item['last_nonzero']}" if item["last_nonzero"] else ""
            lines.append(f"- {item['name']}（{item['key']}）：{item['reason']}{detail}")
        lines.append("")

    if stale:
        lines.append(f"## 报价陈旧（≥{stale_days} 天未更新）")
        lines.append("")
        for item in stale:
            lines.append("- {} {} 停在 {}（{} 天） 来源 {}".format(
                item["commodity"], item["price_type"], item["latest"],
                item["age_days"], item["source"] or "未知"))
        lines.append("")

    lines.append("排查入口：logs/ai_check_*.md（各源最近一轮与快照）、logs/crawler_*.log（抓取日志）")
    lines.append(f"指纹：{signature_of(issues)}")
    lines.append(f"本邮件由服务器每日抓取后自动发送，规则版本 {rules_version}")
    # 注意：正文只放问题清单，绝不回显 SMTP 密码或任何配置内容
    return subject, "\n".join(lines)


def rules_version(settings) -> str:
    """规则版本号：让人能对齐"这批数据是哪版规则产出的"。读坏就降级，不让告警邮件本身炸掉。"""
    try:
        return compute_rules_version(settings.config_dir)
    except Exception:
        return UNKNOWN


def _parse_args(argv):
    parser = argparse.ArgumentParser(
        description="每日数据健康检查：失败/静默/报价陈旧时发邮件（全好则静默退出）")
    parser.add_argument("--dry-run", action="store_true",
                        help="只打印将要发送的内容，不发信、不写状态")
    parser.add_argument("--force", action="store_true",
                        help="忽略 24 小时去重，强制发送")
    return parser.parse_args(argv)


def run(argv=None, settings=None, sender=None, config_loader=None) -> int:
    """CLI 主体，返回进程退出码。sender/config_loader 可注入（测试用假实现，不发真邮件）。"""
    args = _parse_args(argv)
    settings = settings or load_settings()
    sender = sender or send_mail
    config_loader = config_loader or load_notify_config

    try:
        conn = store.connect(settings.db_path)
    except Exception as exc:
        # DB 读不了必须报错退出：悄悄当成"一切正常"就是这套告警最要命的假阴性
        print(f"数据库打开失败：{_clean_error(exc)}")
        return 1
    try:
        store.init_db(conn)
        issues = collect_issues(conn, settings=settings)
    except Exception as exc:
        print(f"数据健康检测失败：{_clean_error(exc)}")
        return 1
    finally:
        conn.close()

    if not has_issues(issues):
        print("一切正常，无需告警" + ("（--dry-run：未发信、未写状态）" if args.dry_run else ""))
        return 0

    subject, body = build_email(issues, rules_version(settings))
    if args.dry_run:
        print("【dry-run】以下内容不会发送邮件，也不写状态文件：")
        print(f"主题：{subject}")
        print("-" * 40)
        print(body)
        return 0

    signature = signature_of(issues)
    state = state_path(settings)
    if not args.force and not should_send(state, signature):
        print(f"同样的问题（指纹 {signature}）在 24 小时内已发过邮件，本次跳过")
        return 0

    if not sender(subject, body, config=config_loader()):
        # 不写状态：发失败时不能记成"已发"，否则这一轮的问题会被 24 小时去重吃掉
        print("邮件未发送（通知配置未启用或 SMTP 报错），状态未记录，下次 cron 会重试")
        return 1
    mark_sent(state, signature)
    print(f"告警邮件已发送：{subject}")
    return 0


def main() -> int:
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
