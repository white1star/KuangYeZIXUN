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

另有第四类结果 degraded：**冗余降级**。价格源失败不一定是事故——备用源（eastmoney_futures）
挂了而主源把它的覆盖品种全都供上了，价格一条不少，天天发邮件只会把真告警淹掉。
这种源不进 failed、不进邮件、不进指纹，只在 logs/alert_health.log 与 --dry-run 输出里
留一行痕（判据见 _redundant_covered_by：只要有一个覆盖品种没有别的源供数，照报）。

用法：
    python -m scripts.alert_health            # 有问题才发邮件，24 小时内同一问题只发一次
    python -m scripts.alert_health --dry-run  # 只打印，不发信不写状态
    python -m scripts.alert_health --force    # 忽略去重，强制发送
"""
import argparse
import json
from datetime import date, datetime, timedelta
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
DEGRADE_LOG_NAME = "alert_health.log"   # 冗余降级的留痕文件（服务器上即 /opt/news/logs/）
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
    """读源配置，返回 (名称表, 启用 key 列表, 按 key 的完整配置, 配置错误)。

    配置读坏时不能整封告警哑掉：failed 退化为按 DB 的 sources.enabled 判断，
    silent 因为拿不到启用清单而跳过，并在邮件正文里说明。

    完整配置（configs）是为了降级判定能读到 board 与 commodity_map：load_sources
    已经把每个源的 YAML 整份返回了，这里只是留个引用，不再去读第二遍配置。
    """
    try:
        if settings is None:
            raw = load_sources()
        else:
            sources_dir = Path(settings.config_dir) / "sources"
            if not sources_dir.is_dir():
                # 目录不在时 glob 会安静地返回空清单 → 三类检测里两类被悄悄关掉，
                # 那正是这套告警要消灭的假阴性，所以当作配置错误报出来
                return {}, [], {}, f"源配置目录不存在：{sources_dir}"
            raw = load_sources(sources_dir)
    except Exception as exc:
        return {}, [], {}, _clean_error(exc)
    names = {s["key"]: s.get("name", s["key"]) for s in raw}
    enabled = [s["key"] for s in raw if s.get("enabled", True)]
    configs = {s["key"]: s for s in raw}
    return names, enabled, configs, ""


LATEST_RUN_SQL = (
    "SELECT r.source_key, r.status, r.error FROM crawl_runs r"
    " JOIN (SELECT source_key, MAX(id) id FROM crawl_runs GROUP BY source_key) t"
    " ON t.id = r.id ORDER BY r.source_key"
)


def _db_names(conn) -> dict:
    return {r["key"]: r["name"] for r in conn.execute("SELECT key, name FROM sources")}


def _covered_commodities(src) -> set:
    """这个源按配置"应该覆盖"哪些品种——commodity_map 的值。

    值的写法有两种，都拍平成品种名集合：字符串（sina_futures 的 `JM0: 焦煤`）与
    列表（ccmn 的 `铅锌: [铅, 锌]`）。返回空集合表示配置没写 commodity_map，
    也就是"判不出它该覆盖什么"，调用方要按判不了处理（保守报）。
    """
    mapping = src.get("commodity_map")
    if not isinstance(mapping, dict):
        return set()
    out = set()
    for value in mapping.values():
        items = value if isinstance(value, (list, tuple, set)) else [value]
        out.update(str(v).strip() for v in items if str(v).strip())
    return out


FRESH_SOURCE_SQL = (
    "SELECT source_key, price_date FROM prices WHERE commodity=? AND source_key<>?"
)


def _other_fresh_source(conn, commodity, failed_key, stale_days, today) -> str:
    """这个品种现在还有哪个"别的源"在供数；没有就返回空串。

    为什么必须排除失败源自己（source_key<>?）：源昨天成功、今天失败时，它自己昨天
    写下的行还在库里而且日期很新。拿自己的数据给自己背书，单点源失败就被永久掩盖了。

    新鲜窗口与"报价陈旧"同一把尺（price_date >= today - stale_days）：别的源三天没
    报价时，"还有别的源供数"就是假的，这时失败源仍是唯一的数据来源，必须报。
    日期在 Python 里严格解析，与 _stale_prices 一样跳过历史脏数据（"9/21"）。
    """
    for row in conn.execute(FRESH_SOURCE_SQL, (commodity, failed_key)):
        try:
            latest = date.fromisoformat(row["price_date"])
        except (TypeError, ValueError):
            continue
        if (today - latest).days <= stale_days:   # price_date >= today - stale_days
            return row["source_key"]
    return ""


def _redundant_covered_by(conn, configs, key, stale_days, today):
    """判断失败的价格源是不是"冗余降级"，是则返回 {品种: 供数源}，否则返回 None。

    只有 board=='price' 的源可能降级：新闻/政策源没有冗余这回事，它挂了就是少了一条
    资讯，别的源再多也补不上这条内容，所以一律照报。

    None（照报）的三种情形，任一成立都不降级——判不出覆盖范围时宁可多报一次：
    1. 不是价格源；
    2. 配置里没有（或写空了）commodity_map，不知道它该覆盖哪些品种；
    3. 覆盖品种里只要有一个没有别的源在供数 —— 单点源失败是真风险，哪怕今天的报价
       还新鲜，主源一挂就彻底没数据了。
    """
    src = configs.get(key) or {}
    if src.get("board") != "price":
        return None
    commodities = _covered_commodities(src)
    if not commodities:
        return None
    covered = {c: _other_fresh_source(conn, c, key, stale_days, today) for c in commodities}
    # 全部覆盖品种都还有别的源在供数才是冗余；少一个就是真缺口
    return covered if all(covered.values()) else None


def _failed_sources(conn, names, enabled_keys, configs, stale_days, now) -> tuple:
    """最近一轮就失败的启用源，分成"要告警"与"冗余降级"两拨。

    口径只认每个源的 MAX(id) 那一轮：历史上失败过、之后已跑成功的源不再报，
    否则一次网络抖动会在告警里赖上好几天。enabled_keys 为 None 表示配置读坏了，
    这时退化为 DB 里的 enabled 标志（宁可多报一个，也不要因为配置问题收不到失败告警）。
    顺带配置读坏时 configs 为空 → 一个源都判不出冗余 → 全部照报（保守方向）。
    """
    if enabled_keys is None:
        enabled_keys = [r["key"] for r in conn.execute(
            "SELECT key FROM sources WHERE enabled=1 ORDER BY key")]
    enabled = set(enabled_keys)
    db_names = _db_names(conn)
    failed, degraded = [], []
    for row in conn.execute(LATEST_RUN_SQL):
        if row["status"] != "error" or row["source_key"] not in enabled:
            continue
        key = row["source_key"]
        item = {"key": key,
                "name": names.get(key) or db_names.get(key) or key,
                "error": row["error"] or "未知错误"}
        covered = _redundant_covered_by(conn, configs, key, stale_days, now.date())
        if covered is None:
            failed.append(item)
        else:
            degraded.append(dict(item, covered_by=covered))
    return failed, degraded


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
    """三类问题清单 + 冗余降级清单（后者只留痕，不进邮件）；没有就是空列表/空字典。"""
    now = now or datetime.now()
    names, enabled, configs, config_error = _source_config(settings)
    # 配置错误时 enabled 传 None：failed 退化为按 DB 判断，silent 直接跳过
    usable = None if config_error else enabled
    failed, degraded = _failed_sources(conn, names, usable, configs, stale_days, now)
    return {
        "failed": failed,
        "degraded": degraded,
        "silent": _silent_sources(conn, names, usable, now),
        "stale": _stale_prices(conn, stale_days, now),
        "config_error": config_error,
    }


def report_degraded(settings, degraded) -> None:
    """把降级掉的源说清楚：打印一行 + 写一行日志。

    为什么降级也要留痕：告警邮件只保留"真缺口"，如果降级完全静默，管理员看到
    "期货备用源一个月没报错"会以为它一直在正常抓——实际上它早就死了，只是主源兜住了。
    日志落 logs/alert_health.log（服务器上即 /opt/news/logs/alert_health.log），
    追加写、永不覆盖。日志写不了（磁盘满/无权限）只打印不让整个检查失败：
    这一行是补充信息，抑制它反而会把真告警一起弄丢。
    """
    if not degraded:
        return
    lines = []
    for item in degraded:
        covered = "、".join(f"{c}←{s}" for c, s in item["covered_by"].items())
        # 错误文本走 _clean_error：这一行要 print 到控制台，原始异常文本可能带不可打印
        # 字符（本仓库踩过 cp936 二次崩溃，见 68cf056），且常常是几百字的整条链
        lines.append(f"已降级（冗余）：{item['name']}（{item['key']}）："
                     f"{_clean_error(item['error'])}；"
                     f"覆盖情况 {covered}（别的源仍在供数，未造成数据缺口）")
    try:
        path = Path(settings.logs_dir) / DEGRADE_LOG_NAME
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            for line in lines:
                f.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {line}\n")
    except Exception as exc:
        print(f"（降级日志写入失败，仅打印：{_clean_error(exc)}）")
    for line in lines:
        print(line)


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
    冗余降级（degraded）刻意不算进来：它不影响数据，也不该因为每天都有备用源挂着
    而把指纹一变一变，害得真问题被 24 小时去重吃掉。
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

    # 冗余降级只留痕、不进邮件；无论后面走不发信还是发信路径都先说清楚，
    # 这样"没收到告警"与"源确实挂了但被兜住了"不会混为一谈
    report_degraded(settings, issues.get("degraded"))

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
