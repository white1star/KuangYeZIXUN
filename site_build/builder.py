import argparse
import json
import shutil
from datetime import datetime
from pathlib import Path

import jinja2
import yaml

from crawler import store
from site_build import data

ROOT = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
STATIC_DIR = Path(__file__).resolve().parent / "static"
SETTINGS_FILE = Path(__file__).resolve().parent / "settings.yaml"
DEFAULT_DB = ROOT / "data" / "news.db"
DEFAULT_OUT = ROOT / "dist"
DEFAULT_VENDOR = ROOT / "web" / "static" / "vendor" / "echarts.min.js"


def load_feedback_key() -> str:
    if not SETTINGS_FILE.exists():
        return ""
    try:
        raw = yaml.safe_load(SETTINGS_FILE.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return ""
    return str((raw.get("feedback") or {}).get("web3forms_key") or "").strip()

NEWS_TABS = {"全部": [], "新矿山": ["新矿"], "市场": ["价格", "市场"],
             "技术": ["技术"], "企业": ["企业"], "安全": ["安全"]}
NEWS_INITIAL = 60
POLICY_INITIAL = 100
HOT_WORDS = ["探矿权", "磷矿", "绿色矿山", "焦煤", "萤石", "尾矿库"]


def _fmt_num(value) -> str:
    if value is None:
        return "—"
    try:
        num = float(value)
    except (TypeError, ValueError):
        return str(value)
    if num.is_integer():
        return f"{int(num):,}"
    return f"{num:,.2f}".rstrip("0").rstrip(".")


def _fmt_pct(value) -> str:
    if value is None:
        return ""
    return f"{float(value):+.2f}%"


def _fmt_size(size) -> str:
    num = float(size)
    for unit in ("B", "KB", "MB"):
        if num < 1024 or unit == "MB":
            return f"{num:.1f} {unit}" if unit != "B" else f"{int(num)} B"
        num /= 1024
    return f"{num:.1f} MB"


def _write(path: Path, text: str) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    return path.stat().st_size


def _json_text(payload) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def build(db_path=None, out_dir=None, vendor_path=None, feedback_key=None) -> dict:
    db_file = Path(db_path) if db_path else DEFAULT_DB
    out = Path(out_dir) if out_dir else DEFAULT_OUT
    vendor = Path(vendor_path) if vendor_path else DEFAULT_VENDOR
    if feedback_key is None:
        feedback_key = load_feedback_key()
    if not db_file.exists():
        raise FileNotFoundError(f"数据库不存在：{db_file}，请先运行 python -m crawler.main --once")
    if not vendor.exists():
        raise FileNotFoundError(f"ECharts 本地文件不存在：{vendor}")
    conn = store.connect(db_file)
    try:
        store.init_db(conn)
        articles = data.load_articles(conn)
        stats = data.today_stats(conn)
        sources_ok, sources_total = data.source_health(conn)
        last_fetch = data.last_fetch_time(conn)
        prices = data.prices_payload(conn)
        policy_meta = data.policy_meta(articles)
    finally:
        conn.close()
    build_time = datetime.now().strftime("%Y-%m-%d %H:%M")
    env = jinja2.Environment(loader=jinja2.FileSystemLoader(str(TEMPLATES_DIR)),
                             autoescape=True, trim_blocks=True, lstrip_blocks=True)
    env.filters["num"] = _fmt_num
    env.filters["pct"] = _fmt_pct
    env.filters["hhmm"] = lambda v: (v or "")[11:16]
    news_articles = [a for a in articles if a["board"] == "news"]
    policy_articles = [a for a in articles if a["board"] == "policy"]
    base = {"build_time": build_time, "feedback_key": feedback_key}
    pages = {
        "index.html": env.get_template("index.html").render(
            **base, page="index", stats=stats, sources_ok=sources_ok, sources_total=sources_total,
            last_fetch=last_fetch, commodity_count=len(prices["commodities"]), hot_words=HOT_WORDS),
        "news.html": env.get_template("news.html").render(
            **base, page="news", articles=news_articles[:NEWS_INITIAL],
            tabs=list(NEWS_TABS.keys())),
        "policy.html": env.get_template("policy.html").render(
            **base, page="policy", articles=policy_articles[:POLICY_INITIAL],
            sources=policy_meta["sources"], regions=policy_meta["regions"]),
        "prices.html": env.get_template("prices.html").render(
            **base, page="prices", prices=prices["latest"],
            commodities=prices["commodities"],
            commodity=prices["commodities"][0] if prices["commodities"] else "",
            type_map=prices["type_map"]),
        "search.html": env.get_template("search.html").render(**base, page="search"),
    }
    sizes = {}
    for name, html in pages.items():
        sizes[name] = _write(out / name, html)
    search_payload = {"generated_at": build_time, "count": len(articles),
                      "items": data.search_items(articles)}
    sizes["search.json"] = _write(out / "search.json", _json_text(search_payload))
    sizes["prices.json"] = _write(out / "prices.json", _json_text(prices))
    for name in ("style.css", "app.js"):
        target = out / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(STATIC_DIR / name, target)
        sizes[name] = target.stat().st_size
    vendor_target = out / "vendor" / "echarts.min.js"
    vendor_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(vendor, vendor_target)
    sizes["vendor/echarts.min.js"] = vendor_target.stat().st_size
    return {
        "out_dir": str(out),
        "built_at": build_time,
        "files": sizes,
        "total_bytes": sum(sizes.values()),
        "counts": {"articles": len(articles), "news": len(news_articles),
                   "policy": len(policy_articles),
                   "prices": len(prices["latest"]),
                   "commodities": len(prices["commodities"])},
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="矿业资讯站静态化构建")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="SQLite 数据库路径")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="静态站点输出目录")
    args = parser.parse_args(argv)
    result = build(db_path=args.db, out_dir=args.out)
    print(f"静态站构建完成：{result['out_dir']}（{result['built_at']}）")
    print("文章 {} 篇（新闻 {}，政策 {}），品种 {} 个，报价行 {} 条".format(
        result["counts"]["articles"], result["counts"]["news"], result["counts"]["policy"],
        result["counts"]["commodities"], result["counts"]["prices"]))
    for name, size in sorted(result["files"].items()):
        print(f"  {name:<24} {_fmt_size(size):>10}")
    print(f"  {'合计':<24} {_fmt_size(result['total_bytes']):>10}")
    return result
